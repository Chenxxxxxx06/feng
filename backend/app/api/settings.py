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
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/thresholds", response_model=list[ThresholdConfigResponse])
async def get_thresholds(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    config = result.scalar_one_or_none()
    if not config:
        config = NotificationConfig(
            user_id=user.id,
            hi_threshold=70.0,
            email_enabled=True,
            email_address=user.email,
            wechat_enabled=False,
        )
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return [ThresholdConfigResponse.model_validate(config)]


@router.put("/thresholds", response_model=ThresholdConfigResponse)
async def save_threshold(
    data: ThresholdConfigRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    config = result.scalar_one_or_none()
    if config:
        for k, v in data.model_dump().items():
            setattr(config, k, v)
    else:
        config = NotificationConfig(user_id=user.id, **data.model_dump())
        db.add(config)
    await db.commit()
    await db.refresh(config)
    return ThresholdConfigResponse.model_validate(config)


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
    dtu_dir = Path(__file__).resolve().parents[1] / "data" / "curated_datasets" / "raw" / "blade_images" / "dtu_drone_inspection"
    dtu_images = len(list(dtu_dir.rglob("*.JPG"))) + len(list(dtu_dir.rglob("*.jpg"))) if dtu_dir.exists() else 0
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
