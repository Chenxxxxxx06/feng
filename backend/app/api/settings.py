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
