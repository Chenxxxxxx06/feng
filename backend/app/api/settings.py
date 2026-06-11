from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import NotificationConfig, DataSource, User
from app.schemas import (
    ThresholdConfigRequest, ThresholdConfigResponse,
    DataSourceResponse, DataSourceTestRequest,
    ProfileUpdateRequest, UserResponse,
)
from app.services.data_pipeline import get_pipeline_state, set_source_status, SourceStatus
from app.services.data_pipeline.era5_loader import era5_loader
from app.services.data_pipeline.scada_loader import scada_loader
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.services.qwen_client import normalize_model_preference, resolve_model_config
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

SOURCE_NAMES = {
    "scada": "SCADA运行数据",
    "vibration": "振动监测数据",
    "image": "叶片图像数据",
    "weather": "气象环境数据",
}


@router.get("/thresholds", response_model=list[ThresholdConfigResponse])
async def get_thresholds(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(NotificationConfig).where(NotificationConfig.user_id == current_user.id)
    )
    return [ThresholdConfigResponse.model_validate(c) for c in result.scalars().all()]


@router.put("/thresholds", response_model=ThresholdConfigResponse)
async def save_threshold(
    data: ThresholdConfigRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(NotificationConfig).where(NotificationConfig.user_id == current_user.id)
    )
    config = result.scalar_one_or_none()
    if config:
        for k, v in data.model_dump().items():
            setattr(config, k, v)
    else:
        config = NotificationConfig(user_id=current_user.id, **data.model_dump())
        db.add(config)
    await db.commit()
    await db.refresh(config)
    return ThresholdConfigResponse.model_validate(config)


@router.get("/data-sources", response_model=list[DataSourceResponse])
async def list_data_sources(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DataSource))
    return [DataSourceResponse.model_validate(ds) for ds in result.scalars().all()]


@router.post("/data-sources/test")
async def test_data_source(
    data: DataSourceTestRequest,
    db: AsyncSession = Depends(get_db),
):
    """Test connection to a data source."""
    src = data.source_type.lower()
    if src not in SOURCE_NAMES:
        raise HTTPException(status_code=400, detail=f"Unknown source type: {src}")

    try:
        if src == "scada":
            ok = scada_loader.is_real_data_available()
            set_source_status("scada", SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL)
            status = SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL
        elif src == "vibration":
            set_source_status("vibration", SourceStatus.PARTIAL)
            status = SourceStatus.PARTIAL
        elif src == "image":
            set_source_status("image", SourceStatus.PARTIAL)
            status = SourceStatus.PARTIAL
        elif src == "weather":
            ok = era5_loader.is_real_data_available()
            set_source_status("weather", SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL)
            status = SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL

        result = await db.execute(select(DataSource).where(DataSource.source_type == src))
        source = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if source:
            source.status = status.value
            source.connection_params = data.connection_params
            source.last_connected_at = now
        else:
            source = DataSource(
                source_type=src,
                name=SOURCE_NAMES[src],
                status=status.value,
                connection_params=data.connection_params,
                last_connected_at=now,
            )
            db.add(source)
        await db.commit()

        return {
            "status": "success",
            "message": f"Connection test to {data.source_type} completed",
            "source_type": data.source_type,
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "source_type": data.source_type}


@router.get("/pipeline-status")
async def get_pipeline_status():
    """Get current data pipeline status for all sources."""
    state = get_pipeline_state()

    sources = [
        {
            "type": "scada",
            "name": "SCADA运行数据",
            "status": state.scada.value,
            "last_update": state.last_scada.isoformat() if state.last_scada else None,
            "record_count": state.scada_records,
            "real_data_available": scada_loader.is_real_data_available(),
            "note": "CARE to Compare 数据集" if not scada_loader.is_real_data_available() else "CARE数据集已接入",
        },
        {
            "type": "vibration",
            "name": "振动监测数据",
            "status": state.vibration.value,
            "last_update": state.last_vibration.isoformat() if state.last_vibration else None,
            "record_count": state.vibration_files,
            "real_data_available": False,
            "note": "Fraunhofer LBF数据集待下载",
        },
        {
            "type": "image",
            "name": "叶片图像数据",
            "status": state.image.value,
            "last_update": state.last_image.isoformat() if state.last_image else None,
            "record_count": state.image_files,
            "real_data_available": False,
            "note": "当前使用模拟叶片图像",
        },
        {
            "type": "weather",
            "name": "气象环境数据",
            "status": state.weather.value,
            "last_update": state.last_weather.isoformat() if state.last_weather else None,
            "record_count": state.weather_updates,
            "real_data_available": era5_loader.is_real_data_available(),
            "note": "ERA5再分析数据" if not era5_loader.is_real_data_available() else "ERA5数据已接入",
        },
    ]

    return {
        "sources": sources,
        "overall_status": "healthy" if len(state.errors) == 0 else "degraded",
        "errors": state.errors[-10:],
    }


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    requested_model = data.model_preference or current_user.model_preference
    normalized_model = normalize_model_preference(requested_model)
    model_config = resolve_model_config(normalized_model)
    new_api_key = data.api_key.strip() if data.api_key else None

    if new_api_key:
        if not model_config.requires_api_key:
            raise HTTPException(status_code=400, detail="本地模型不需要配置AI服务密钥")
        if data.api_provider and data.api_provider != model_config.provider:
            raise HTTPException(
                status_code=400,
                detail=f"密钥供应商为 {data.api_provider}，但所选模型属于 {model_config.provider}",
            )
        current_user.api_key = new_api_key
        current_user.api_provider = model_config.provider

    if data.model_preference:
        if current_user.api_key and model_config.requires_api_key:
            if not current_user.api_provider:
                raise HTTPException(status_code=400, detail="已有密钥未绑定供应商，请重新输入密钥并保存")
            if current_user.api_provider != model_config.provider:
                raise HTTPException(
                    status_code=400,
                    detail=f"当前密钥属于 {current_user.api_provider}，不能选择 {model_config.provider} 模型。请重新输入对应供应商的密钥。",
                )
        current_user.model_preference = data.model_preference

    await db.commit()
    await db.refresh(current_user)
    return UserResponse.model_validate(current_user)
