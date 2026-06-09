from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import DataSource, Turbine
from app.schemas import TurbineResponse, TurbineListResponse
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
    """Get SCADA data from imported database records."""
    from datetime import datetime, timedelta, timezone
    from app.models import SCADARecord

    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    source_result = await db.execute(select(DataSource).where(DataSource.source_type == "scada"))
    source = source_result.scalar_one_or_none()
    if not source or source.status != "connected":
        return []

    # Try recent records first. Imported public datasets are often historical,
    # so if no recent records exist, return the latest real dataset window and
    # mark it explicitly in the response.
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    db_result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == turbine_id, SCADARecord.timestamp >= since)
        .order_by(SCADARecord.timestamp.desc())
        .limit(hours * 6)
    )
    db_records = db_result.scalars().all()
    dataset_window = "recent"

    if not db_records:
        latest_result = await db.execute(
            select(SCADARecord)
            .where(SCADARecord.turbine_id == turbine_id)
            .order_by(SCADARecord.timestamp.desc())
            .limit(hours * 6)
        )
        db_records = latest_result.scalars().all()
        dataset_window = "historical_latest"

    if db_records:
        return [
            _scada_response(r, dataset_window)
            for r in reversed(db_records)
        ]

    return []


def _scada_response(record, dataset_window: str) -> dict:
    extra = dict(record.extra or {})
    return {
        "timestamp": record.timestamp.isoformat(),
        "power_kw": record.power_kw,
        "wind_speed_ms": record.wind_speed_ms,
        "rotor_rpm": record.rotor_rpm,
        "gen_temperature_c": record.gen_temperature_c,
        "gearbox_temperature_c": record.gearbox_temperature_c,
        "bearing_temperature_c": record.bearing_temperature_c,
        "pitch_angle_deg": record.pitch_angle_deg,
        "nacelle_direction_deg": record.nacelle_direction_deg,
        "grid_frequency_hz": record.grid_frequency_hz,
        "ambient_temp_c": record.ambient_temp_c,
        "data_source": "real_dataset",
        "dataset_window": dataset_window,
        "source_dataset": extra.get("source_dataset"),
        "source_file": extra.get("source_file"),
        "source_row": extra.get("source_row"),
        "source_turbine_id": extra.get("source_turbine_id"),
    }


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

    try:
        return era5_loader.get_wind_at(turbine.lat, turbine.lng)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
