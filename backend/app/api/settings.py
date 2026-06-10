import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.database import get_db
from app.models import BladeImage, NotificationConfig, DataSource, SCADARecord, User, VibrationData, WorkOrder
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
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_INTEGRATION_PLAN = DATA_DIR / "data_integration_plan.json"


@router.get("/thresholds", response_model=list[ThresholdConfigResponse])
async def get_thresholds(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NotificationConfig))
    return [ThresholdConfigResponse.model_validate(c) for c in result.scalars().all()]


@router.put("/thresholds", response_model=ThresholdConfigResponse)
async def save_threshold(data: ThresholdConfigRequest, db: AsyncSession = Depends(get_db)):
    users = await db.execute(select(User).limit(1))
    user = users.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=400, detail="No user found")

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
async def test_data_source(data: DataSourceTestRequest, db: AsyncSession = Depends(get_db)):
    """Test connection to a data source."""
    src = data.source_type.lower()
    try:
        if src == "scada":
            scada_count = await db.scalar(select(func.count()).select_from(SCADARecord))
            ok = bool(scada_count) or scada_loader.is_real_data_available()
            set_source_status("scada", SourceStatus.CONNECTED if ok else SourceStatus.PARTIAL)
        elif src == "vibration":
            set_source_status("vibration", SourceStatus.DISCONNECTED)
        elif src == "image":
            set_source_status("image", SourceStatus.DISCONNECTED)
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
    """Get current data pipeline status for all sources."""
    state = get_pipeline_state()
    scada_count = await db.scalar(select(func.count()).select_from(SCADARecord))
    scada_with_extra = await db.scalar(
        select(func.count()).select_from(SCADARecord).where(SCADARecord.extra.is_not(None))
    )
    vibration_count = await db.scalar(select(func.count()).select_from(VibrationData))
    image_count = await db.scalar(select(func.count()).select_from(BladeImage))
    scada_source_result = await db.execute(
        select(DataSource)
        .where(DataSource.source_type == "scada")
        .order_by(DataSource.last_data_at.desc().nullslast())
        .limit(1)
    )
    scada_source = scada_source_result.scalar_one_or_none()
    scada_ready = bool(scada_count and scada_with_extra == scada_count)

    sources = [
        {
            "type": "scada",
            "name": "SCADA运行数据",
            "status": "connected" if scada_ready else ("partial" if scada_count else "disconnected"),
            "last_update": scada_source.last_data_at.isoformat() if scada_source and scada_source.last_data_at else None,
            "record_count": scada_count,
            "real_data_available": scada_ready,
            "note": (
                f"主时间线数据已导入：{scada_source.name}"
                if scada_ready and scada_source
                else "存在SCADA记录但缺少来源字段，建议清理旧demo数据后重新导入"
                if scada_count
                else "待导入 CARE to Compare 或现场SCADA数据"
            ),
        },
        {
            "type": "vibration",
            "name": "振动监测数据",
            "status": "connected" if vibration_count else "disconnected",
            "last_update": state.last_vibration.isoformat() if state.last_vibration else None,
            "record_count": vibration_count,
            "real_data_available": bool(vibration_count),
            "note": "真实振动数据集已导入" if vibration_count else "待导入真实公开振动数据集",
        },
        {
            "type": "image",
            "name": "叶片图像数据",
            "status": "connected" if image_count else "disconnected",
            "last_update": state.last_image.isoformat() if state.last_image else None,
            "record_count": image_count,
            "real_data_available": bool(image_count),
            "note": "真实叶片图像数据集已导入" if image_count else "待导入真实公开叶片图像数据集",
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


@router.get("/data-integration-plan")
async def get_data_integration_plan(db: AsyncSession = Depends(get_db)):
    """Return the project data integration plan and current layer readiness."""
    if not DATA_INTEGRATION_PLAN.exists():
        raise HTTPException(status_code=404, detail="Data integration plan not found")

    plan = json.loads(DATA_INTEGRATION_PLAN.read_text(encoding="utf-8"))
    scada_count = await db.scalar(select(func.count()).select_from(SCADARecord))
    scada_with_extra = await db.scalar(
        select(func.count()).select_from(SCADARecord).where(SCADARecord.extra.is_not(None))
    )
    vibration_count = await db.scalar(select(func.count()).select_from(VibrationData))
    image_count = await db.scalar(select(func.count()).select_from(BladeImage))
    work_order_count = await db.scalar(select(func.count()).select_from(WorkOrder))
    weather_available = era5_loader.is_real_data_available()

    current_counts = {
        "scada_records": scada_count,
        "scada_records_with_source_metadata": scada_with_extra,
        "vibration_samples": vibration_count,
        "blade_images": image_count,
        "weather_available": weather_available,
        "work_orders": work_order_count,
    }

    layer_status = [
        {
            "id": "operational_core",
            "status": "ready" if scada_count and scada_with_extra == scada_count else ("needs_review" if scada_count else "missing"),
            "record_count": scada_count,
            "note": (
                "SCADA主线已导入且来源字段完整"
                if scada_count and scada_with_extra == scada_count
                else "存在SCADA记录但部分缺少来源字段，建议清理旧demo数据后重新导入"
                if scada_count
                else "待导入CARE或现场SCADA主时间线"
            ),
        },
        {
            "id": "diagnostic_sample_library",
            "status": "ready" if vibration_count and image_count else ("partial" if vibration_count or image_count else "missing"),
            "record_count": vibration_count + image_count,
            "note": "振动和图像样本库均已导入" if vibration_count and image_count else "诊断样本库尚未完整导入",
        },
        {
            "id": "weather_context",
            "status": "ready" if weather_available else "optional",
            "record_count": 1 if weather_available else 0,
            "note": "ERA5或现场气象已可用" if weather_available else "气象层为可选补充，当前未接入",
        },
        {
            "id": "business_records",
            "status": "needs_review" if work_order_count else "empty",
            "record_count": work_order_count,
            "note": "存在工单记录，但当前模型缺少来源审计字段，旧demo库需复核" if work_order_count else "业务数据应由真实系统操作沉淀",
        },
    ]

    return {
        "plan": plan,
        "current_counts": current_counts,
        "layer_status": layer_status,
    }


@router.put("/profile", response_model=UserResponse)
async def update_profile(data: ProfileUpdateRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == "admin"))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    update_data = data.model_dump(exclude_none=True)
    for k, v in update_data.items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
