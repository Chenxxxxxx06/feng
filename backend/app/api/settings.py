from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import (
    AIProviderConfig,
    DataSource,
    NotificationConfig,
    NotificationLog,
    OperationLog,
    Turbine,
    User,
)
from app.schemas import (
    ThresholdConfigRequest, ThresholdConfigResponse,
    DataSourceResponse, DataSourceTestRequest,
    ProfileUpdateRequest, UserResponse,
    AIProviderConfigCreate, AIProviderConfigResponse, AIProviderTestRequest,
    OperationLogCreate, OperationLogResponse,
    ThresholdAlertStatus, ThresholdAlertTurbine,
)
from app.services.data_pipeline import get_pipeline_state, set_source_status, SourceStatus
from app.services.data_pipeline.era5_loader import era5_loader
from app.services.data_pipeline.scada_loader import scada_loader
from app.services.qwen_client import get_client
from app.services.email_service import EmailConfigError, send_email
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

AI_PROVIDER_TEMPLATES: dict[str, dict] = {
    "dashscope": {
        "display_name": "通义千问 DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "model_options": ["qwen-plus", "qwen-turbo", "qwen3.6-flash"],
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "model_options": ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"],
    },
    "glm": {
        "display_name": "智谱GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5-flash",
        "model_options": ["glm-5-flash"],
    },
    "kimi": {
        "display_name": "Kimi Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2.6",
        "model_options": ["kimi-k2.6"],
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "model_options": ["gpt-4o-mini", "gpt-4.1", "gpt-4", "gpt-3.5-turbo"],
    },
    "gemini": {
        "display_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "model_options": ["gemini-2.5-flash", "gemini-3.5-flash"],
    },
    "ollama": {
        "display_name": "Ollama本地模型",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5",
        "model_options": ["qwen2.5", "llama3.1", "deepseek-r1"],
    },
}


def _provider_template_key(provider: str | None) -> str:
    key = (provider or "").strip().lower()
    aliases = {
        "qwen": "dashscope",
        "tongyi": "dashscope",
        "aliyun": "dashscope",
    }
    return aliases.get(key, key)


def _provider_template(provider: str | None) -> dict:
    return AI_PROVIDER_TEMPLATES.get(_provider_template_key(provider), {})


def _serialize_ai_provider(config: AIProviderConfig) -> AIProviderConfigResponse:
    return AIProviderConfigResponse(
        id=config.id,
        provider=config.provider,
        display_name=config.display_name,
        base_url=config.base_url,
        api_style=config.api_style or "openai",
        default_model=config.default_model,
        model_options=config.model_options or _provider_template(config.provider).get("model_options", []),
        enabled=bool(config.enabled),
        has_api_key=bool(config.api_key),
        last_test_status=config.last_test_status,
        last_test_message=config.last_test_message,
        last_test_at=config.last_test_at,
    )


def _provider_key_from_legacy(user: User) -> str:
    text = f"{user.api_provider or ''} {user.model_preference or ''}".lower()
    if "deepseek" in text:
        return "deepseek"
    if "glm" in text or "智谱" in text:
        return "glm"
    if "kimi" in text or "moonshot" in text:
        return "kimi"
    if "gpt" in text or "openai" in text:
        return "openai"
    if "gemini" in text:
        return "gemini"
    if "ollama" in text:
        return "ollama"
    return "dashscope"


def _format_ai_provider_error(config: AIProviderConfig, exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if config.provider == "kimi" and ("401" in raw or "invalid authentication" in lowered):
        return (
            "Kimi认证失败：请确认使用的是 Kimi 开放平台控制台创建的 API Key，"
            "Base URL 为 https://api.moonshot.cn/v1，且密钥未过期、未禁用、未误用 Kimi 网页端登录凭证。"
            f"原始错误：{raw}"
        )
    return raw


async def _ensure_legacy_ai_provider(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.user_id == user.id).limit(1))
    if result.scalar_one_or_none():
        return
    if not (user.api_key or user.api_base_url or user.api_provider or user.model_preference):
        return
    provider = _provider_key_from_legacy(user)
    template = _provider_template(provider) or AI_PROVIDER_TEMPLATES["dashscope"]
    config = AIProviderConfig(
        user_id=user.id,
        provider=provider,
        display_name=user.api_provider or template["display_name"],
        api_key=user.api_key,
        base_url=user.api_base_url or template["base_url"],
        api_style="openai",
        default_model=user.model_preference or template["default_model"],
        model_options=template["model_options"],
        enabled=True,
    )
    db.add(config)
    await db.commit()


@router.get("/ai-provider-templates")
async def list_ai_provider_templates():
    return [
        {"provider": provider, **template, "api_style": "openai", "requires_api_key": provider != "ollama"}
        for provider, template in AI_PROVIDER_TEMPLATES.items()
    ]


@router.get("/ai-providers", response_model=list[AIProviderConfigResponse])
async def list_ai_providers(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _ensure_legacy_ai_provider(db, user)
    result = await db.execute(
        select(AIProviderConfig)
        .where(AIProviderConfig.user_id == user.id)
        .order_by(AIProviderConfig.created_at.asc(), AIProviderConfig.id.asc())
    )
    return [_serialize_ai_provider(config) for config in result.scalars().all()]


@router.post("/ai-providers", response_model=AIProviderConfigResponse)
async def create_ai_provider(
    data: AIProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    provider = data.provider.strip().lower()
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user.id,
            AIProviderConfig.provider == provider,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        config = AIProviderConfig(user_id=user.id, provider=provider)
        db.add(config)
    template = _provider_template(provider)
    config.display_name = data.display_name or template.get("display_name") or provider
    if data.api_key and data.api_key.strip():
        config.api_key = data.api_key.strip()
        config.last_test_status = "untested"
        config.last_test_message = None
        config.last_test_at = None
    config.base_url = data.base_url.strip()
    config.api_style = data.api_style or "openai"
    config.default_model = data.default_model.strip() if data.default_model else None
    raw_options = data.model_options or template.get("model_options", [])
    clean_options = []
    for option in raw_options:
        value = option.strip()
        if value and value not in clean_options:
            clean_options.append(value)
    if config.default_model and config.default_model not in clean_options:
        clean_options.insert(0, config.default_model)
    config.model_options = clean_options
    config.enabled = data.enabled
    config.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(config)
    return _serialize_ai_provider(config)


@router.post("/ai-providers/{provider_id}/test")
async def test_ai_provider(
    provider_id: int,
    data: AIProviderTestRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="AI供应商配置不存在")

    model = data.model or config.default_model or _provider_template(config.provider).get("default_model") or "qwen-plus"
    if not config.api_key and config.provider != "ollama":
        config.last_test_status = "error"
        config.last_test_message = "未配置API Key"
        config.last_test_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "error", "message": config.last_test_message, "model": model}

    try:
        client = get_client(config.api_key, config.base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
            temperature=0,
        )
        config.last_test_status = "success"
        config.last_test_message = "连接正常"
        config.last_test_at = datetime.now(timezone.utc)
        await db.commit()
        return {
            "status": "success",
            "message": "连接正常",
            "model": model,
            "sample": response.choices[0].message.content,
        }
    except Exception as exc:
        config.last_test_status = "error"
        config.last_test_message = _format_ai_provider_error(config, exc)
        config.last_test_at = datetime.now(timezone.utc)
        await db.commit()
        return {"status": "error", "message": config.last_test_message, "model": model}


@router.delete("/ai-providers/{provider_id}")
async def delete_ai_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="AI供应商配置不存在")

    label = config.display_name or config.provider
    await db.delete(config)
    await db.commit()
    return {"success": True, "deleted_id": provider_id, "message": f"{label} 已删除"}


@router.get("/thresholds", response_model=list[ThresholdConfigResponse])
async def get_thresholds(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = await _get_or_create_notification_config(db, user)
    return [ThresholdConfigResponse.model_validate(config)]


@router.put("/thresholds", response_model=ThresholdConfigResponse)
async def save_threshold(
    data: ThresholdConfigRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = await _get_or_create_notification_config(db, user)
    update_data = data.model_dump()
    for k, v in update_data.items():
        setattr(config, k, v)
    await db.commit()
    await db.refresh(config)
    return ThresholdConfigResponse.model_validate(config)


async def _get_or_create_notification_config(db: AsyncSession, user: User) -> NotificationConfig:
    result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    config = result.scalar_one_or_none()
    if config:
        return config
    config = NotificationConfig(
        user_id=user.id,
        hi_threshold=70.0,
        email_enabled=True,
        email_address=user.email,
    )
    db.add(config)
    await db.commit()
    await db.refresh(config)
    return config


async def _threshold_alert_turbines(db: AsyncSession, threshold: float) -> list[Turbine]:
    result = await db.execute(
        select(Turbine)
        .where(Turbine.hi_value < threshold)
        .order_by(Turbine.hi_value.asc(), Turbine.name.asc())
    )
    return list(result.scalars().all())


def _serialize_threshold_alerts(
    config: NotificationConfig,
    turbines: list[Turbine],
) -> ThresholdAlertStatus:
    return ThresholdAlertStatus(
        threshold=config.hi_threshold,
        low_count=len(turbines),
        turbines=[
            ThresholdAlertTurbine(
                id=t.id,
                name=t.name,
                region=t.region,
                status=t.status,
                hi_value=t.hi_value,
                model=t.model,
            )
            for t in turbines
        ],
        email_enabled=bool(config.email_enabled),
        email_address=config.email_address,
        checked_at=datetime.now(timezone.utc),
    )


@router.get("/threshold-alerts", response_model=ThresholdAlertStatus)
async def get_threshold_alerts(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = await _get_or_create_notification_config(db, user)
    turbines = await _threshold_alert_turbines(db, config.hi_threshold)
    return _serialize_threshold_alerts(config, turbines)


def _threshold_email_body(config: NotificationConfig, turbines: list[Turbine]) -> str:
    lines = [
        "风调预顺 PHM - HI阈值告警",
        "",
        f"当前阈值: HI < {config.hi_threshold:.0f}",
        f"低于阈值风机: {len(turbines)} 台",
        "",
    ]
    for turbine in turbines:
        lines.append(
            f"- {turbine.name} | 区域: {turbine.region or '-'} | HI: {turbine.hi_value:.1f} | 状态: {turbine.status}"
        )
    lines.extend(["", "请及时在风场监控和故障诊断页面核查，并安排巡检或工单闭环。"])
    return "\n".join(lines)


@router.post("/threshold-alerts/send-email")
async def send_threshold_alert_email(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    config = await _get_or_create_notification_config(db, user)
    if not config.email_enabled:
        raise HTTPException(status_code=400, detail="Email notification is disabled in settings")
    recipient = config.email_address or user.email
    if not recipient:
        raise HTTPException(status_code=400, detail="No alert recipient email configured")

    turbines = await _threshold_alert_turbines(db, config.hi_threshold)
    if not turbines:
        raise HTTPException(status_code=400, detail="No turbines are below the current HI threshold")

    subject = f"[Fengdiao PHM] HI阈值告警: {len(turbines)}台风机低于{config.hi_threshold:.0f}"
    body = _threshold_email_body(config, turbines)
    try:
        await send_email(recipient, subject, body)
        db.add(
            NotificationLog(
                work_order_id=None,
                recipient_email=recipient,
                subject=subject,
                status="sent",
                sent_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return {"sent": 1, "recipient_email": recipient, "low_count": len(turbines)}
    except EmailConfigError as exc:
        db.add(
            NotificationLog(
                work_order_id=None,
                recipient_email=recipient,
                subject=subject,
                status="failed",
                error_message=str(exc),
            )
        )
        await db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.add(
            NotificationLog(
                work_order_id=None,
                recipient_email=recipient,
                subject=subject,
                status="failed",
                error_message=str(exc),
            )
        )
        await db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/operation-logs", response_model=list[OperationLogResponse])
async def list_operation_logs(
    page: str | None = Query(None, max_length=64),
    limit: int | None = Query(None, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    query = select(OperationLog).where(OperationLog.user_id == user.id)
    if page:
        query = query.where(OperationLog.page == page)
    query = query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
    if limit is not None:
        query = query.limit(limit)
    result = await db.execute(query)
    return [OperationLogResponse.model_validate(log) for log in result.scalars().all()]


@router.post("/operation-logs", response_model=OperationLogResponse)
async def create_operation_log(
    data: OperationLogCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    level = data.level if data.level in {"success", "info", "error"} else "info"
    log = OperationLog(
        user_id=user.id,
        page=data.page,
        action=data.action,
        result=data.result,
        level=level,
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)
    return OperationLogResponse.model_validate(log)


@router.get("/data-sources", response_model=list[DataSourceResponse])
async def list_data_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DataSource))
    return [DataSourceResponse.model_validate(ds) for ds in result.scalars().all()]


@router.post("/data-sources/test")
async def test_data_source(data: DataSourceTestRequest):
    """Test connection to a data source."""
    src = data.source_type.lower()
    try:
        if src == "scada":
            ok = scada_loader.is_real_data_available()
            set_source_status("scada", SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL)
        elif src == "vibration":
            set_source_status("vibration", SourceStatus.PARTIAL)
        elif src == "image":
            set_source_status("image", SourceStatus.PARTIAL)
        elif src == "weather":
            ok = era5_loader.is_real_data_available()
            set_source_status("weather", SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL)
        else:
            return {"status": "error", "message": f"Unknown source type: {src}"}

        return {
            "status": "success",
            "message": f"Connection test to {data.source_type} completed",
            "source_type": data.source_type,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "source_type": data.source_type}


@router.get("/pipeline-status")
async def get_pipeline_status(db: AsyncSession = Depends(get_db)):
    """Get data pipeline status from database sources and actual record counts."""
    from sqlalchemy import func
    from app.models import SCADARecord, VibrationData, BladeImage, DataImportBatch
    from app.services.data_pipeline.open_meteo_loader import open_meteo_loader

    sources: list[dict] = []

    # ── SCADA source ──
    scada_count = (await db.execute(select(func.count(SCADARecord.id)))).scalar() or 0
    scada_batch = (await db.execute(
        select(DataImportBatch).where(DataImportBatch.source_type == "scada")
        .order_by(DataImportBatch.completed_at.desc()).limit(1)
    )).scalars().first()
    sources.append({
        "type": "scada",
        "name": "SCADA运行数据",
        "status": "connected" if scada_count > 0 else "disconnected",
        "last_update": scada_batch.completed_at.isoformat() if scada_batch and scada_batch.completed_at else None,
        "record_count": scada_count,
        "real_data_available": scada_count > 0,
        "note": "CARE数据集已接入" if scada_count > 0 else "SCADA数据未导入",
    })

    # ── Vibration source ──
    vib_count = (await db.execute(select(func.count(VibrationData.id)))).scalar() or 0
    sources.append({
        "type": "vibration",
        "name": "振动监测数据",
        "status": "connected" if vib_count > 0 else "disconnected",
        "last_update": None,
        "record_count": vib_count,
        "real_data_available": vib_count > 0,
        "note": "CARE参考波形已接入" if vib_count > 0 else "振动数据未导入",
    })

    # ── Blade image source ──
    blade_count = (await db.execute(select(func.count(BladeImage.id)))).scalar() or 0
    from pathlib import Path
    dtu_dir = Path(__file__).resolve().parents[2] / "data" / "curated_datasets" / "raw" / "blade_images" / "dtu_drone_inspection"
    dtu_images = len(set(p.name for p in dtu_dir.rglob("*") if p.suffix.lower() in ('.jpg','.jpeg','.png'))) if dtu_dir.exists() else 0
    sources.append({
        "type": "image",
        "name": "叶片图像数据",
        "status": "connected" if (blade_count > 0 or dtu_images > 0) else "disconnected",
        "last_update": None,
        "record_count": max(blade_count, dtu_images),
        "real_data_available": (blade_count > 0 or dtu_images > 0),
        "note": f"DTU巡检{dtu_images}张可用" if dtu_images > 0 else "叶片图像未下载",
    })

    # ── Weather source ──
    weather_ok = False
    try:
        await open_meteo_loader.get_current_weather(37.3, 107.6)
        weather_ok = True
    except Exception:
        weather_ok = False
    sources.append({
        "type": "weather",
        "name": "气象环境数据",
        "status": "connected" if weather_ok else "disconnected",
        "last_update": None,
        "record_count": 0,
        "real_data_available": weather_ok,
        "note": "Open-Meteo实时API可用" if weather_ok else "气象API不可达",
    })

    errors: list[str] = []
    if scada_count == 0:
        errors.append("SCADA数据未导入")
    if vib_count == 0:
        errors.append("振动数据缺失")
    if not weather_ok:
        errors.append("气象API连接失败")

    return {
        "sources": sources,
        "overall_status": "healthy" if len(errors) == 0 else "degraded",
        "errors": errors,
    }


@router.get("/preferences")
async def get_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user preferences (display name, landing page, digest, toggles)."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.preferences or {}


@router.put("/preferences")
async def save_preferences(
    data: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save user preferences."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.preferences = data
    await db.commit()
    return {"success": True}

@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = data.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
