from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Turbine
from app.schemas import TurbineResponse, TurbineListResponse
from app.services.data_pipeline.scada_loader import scada_loader
from app.services.data_pipeline.era5_loader import era5_loader
from app.services.data_pipeline.geo_loader import geo_loader
from app.api.auth import get_current_user
from app.models import User as UserModel

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=TurbineListResponse)
async def list_turbines(
    model: str | None = Query(None, description="风机型号"),
    region: str | None = Query(None, description="区域"),
    hi_min: float | None = Query(None, description="HI最小值"),
    hi_max: float | None = Query(None, description="HI最大值"),
    status: str | None = Query(None, description="状态"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Turbine)
    if model:
        q = q.where(Turbine.model == model)
    if region:
        q = q.where(Turbine.region == region)
    if hi_min is not None:
        q = q.where(Turbine.hi_value >= hi_min)
    if hi_max is not None:
        q = q.where(Turbine.hi_value <= hi_max)
    if status:
        q = q.where(Turbine.status == status)

    result = await db.execute(q)
    turbines = result.scalars().all()

    return TurbineListResponse(
        turbines=[TurbineResponse.model_validate(t) for t in turbines],
        total=len(turbines),
        healthy=sum(1 for t in turbines if t.status == "normal"),
        warning=sum(1 for t in turbines if t.status == "warning"),
        faulty=sum(1 for t in turbines if t.status == "fault"),
    )


@router.get("/geojson")
async def get_turbines_geojson(db: AsyncSession = Depends(get_db)):
    """Return all turbines as GeoJSON FeatureCollection for map display."""
    result = await db.execute(select(Turbine))
    turbines = result.scalars().all()
    turbine_dicts = [
        {
            "id": t.id, "name": t.name, "model": t.model,
            "power_mw": t.power_mw, "lat": t.lat, "lng": t.lng,
            "region": t.region, "status": t.status, "hi_value": t.hi_value,
        }
        for t in turbines
    ]
    return geo_loader.build_turbines_geojson(turbine_dicts)


@router.get("/shaanxi-boundary")
async def get_shaanxi_boundary():
    """Return Shaanxi province boundary GeoJSON."""
    return geo_loader.load_shaanxi_boundary()


@router.get("/{turbine_id}", response_model=TurbineResponse)
async def get_turbine(turbine_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")
    return TurbineResponse.model_validate(turbine)


@router.get("/{turbine_id}/scada")
async def get_scada_data(
    turbine_id: int,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    """Get SCADA data — uses DB first, falls back to physics simulation."""
    from datetime import datetime, timedelta, timezone
    from app.models import SCADARecord

    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    # Try DB first
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    db_result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == turbine_id, SCADARecord.timestamp >= since)
        .order_by(SCADARecord.timestamp.desc())
        .limit(hours * 6)
    )
    db_records = db_result.scalars().all()

    if db_records:
        return [
            {
                "timestamp": r.timestamp.isoformat(),
                "power_kw": r.power_kw,
                "wind_speed_ms": r.wind_speed_ms,
                "rotor_rpm": r.rotor_rpm,
                "gen_temperature_c": r.gen_temperature_c,
                "gearbox_temperature_c": r.gearbox_temperature_c,
                "bearing_temperature_c": r.bearing_temperature_c,
                "pitch_angle_deg": r.pitch_angle_deg,
                "nacelle_direction_deg": r.nacelle_direction_deg,
                "grid_frequency_hz": r.grid_frequency_hz,
                "ambient_temp_c": r.ambient_temp_c,
                "data_source": "database",
            }
            for r in db_records
        ]

    # Fall back to simulation
    return scada_loader.generate_turbine_scada(
        turbine_id=turbine.id,
        turbine_mw=turbine.power_mw,
        hours=hours,
        resolution_min=10,
    )


@router.get("/{turbine_id}/health")
async def get_turbine_health(
    turbine_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get dynamically calculated Health Index for a turbine."""
    from app.services.health_index import calculate_turbine_hi
    from app.models import SCADARecord
    from datetime import datetime, timedelta, timezone

    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    # Get recent SCADA data
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    scada_result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == turbine_id, SCADARecord.timestamp >= since)
        .limit(144)
    )
    scada = scada_result.scalars().all()
    scada_dicts = [
        {"power_kw": r.power_kw, "wind_speed_ms": r.wind_speed_ms,
         "gen_temperature_c": r.gen_temperature_c, "rotor_rpm": r.rotor_rpm}
        for r in scada
    ]

    # Days since last maintenance
    last_maint_days = None
    if turbine.last_maintenance:
        last_maint_days = (datetime.now(timezone.utc) - turbine.last_maintenance).days

    hi_result = calculate_turbine_hi(
        scada_data=scada_dicts if scada_dicts else None,
        last_maintenance_days=last_maint_days,
        current_hi=turbine.hi_value,
    )

    # Update turbine HI in DB
    turbine.hi_value = hi_result["hi_value"]
    turbine.status = hi_result["status"]
    await db.commit()

    hi_result["turbine_id"] = turbine_id
    hi_result["turbine_name"] = turbine.name
    return hi_result


@router.get("/{turbine_id}/wind")
async def get_turbine_wind(
    turbine_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get real-time wind data for a turbine's location."""
    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    wind = era5_loader.get_wind_at(turbine.lat, turbine.lng)
    return wind
