from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import SCADARecord, Turbine
from app.schemas import TurbineResponse, TurbineListResponse
from app.services.data_pipeline.era5_loader import era5_loader
from app.services.data_pipeline.open_meteo_loader import (
    OpenMeteoWeatherError,
    open_meteo_loader,
)
from app.services.data_pipeline.geo_loader import geo_loader
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

CARE_POWER_SOURCE_FIELDS = {
    "Wind Farm A": "power_30_avg",
    "Wind Farm B": "power_62_avg",
    "Wind Farm C": "power_6_avg",
}


@router.get("/", response_model=TurbineListResponse)
async def list_turbines(
    model: str | None = Query(None, description="风机型号"),
    region: str | None = Query(None, description="区域"),
    hi_min: float | None = Query(None, description="HI最小值"),
    hi_max: float | None = Query(None, description="HI最大值"),
    status: str | None = Query(None, description="状态"),
    source_dataset: str | None = Query("care_to_compare_v6", description="数据集ID"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Turbine)
    if source_dataset:
        q = q.where(Turbine.source_dataset == source_dataset)
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
    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    db_records, dataset_window = await _load_scada_window_records(db, turbine_id, hours)

    if db_records:
        return [
            _scada_response(r, dataset_window)
            for r in reversed(db_records)
        ]

    return []


async def _load_scada_window_records(
    db: AsyncSession,
    turbine_id: int,
    hours: int,
) -> tuple[list[SCADARecord], str]:
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

    return db_records, dataset_window


def _scada_response(record, dataset_window: str) -> dict:
    extra = dict(record.extra or {})
    power_meta = _power_display_metadata(record.power_kw, extra)
    return {
        "timestamp": record.timestamp.isoformat(),
        "power_kw": record.power_kw,
        **power_meta,
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
        "source_wind_farm": extra.get("source_wind_farm"),
        "event_label": extra.get("event_label"),
        "event_component_category": extra.get("event_component_category"),
        "status_type_id": extra.get("status_type_id"),
    }


def _power_display_metadata(power_value: float | None, extra: dict) -> dict:
    source_dataset = extra.get("source_dataset")
    source_wind_farm = extra.get("source_wind_farm")
    if source_dataset == "care_to_compare_v6" and power_value is not None and abs(power_value) <= 1.5:
        return {
            "power_unit": "p.u.",
            "power_label": "有功功率",
            "power_source_field": CARE_POWER_SOURCE_FIELDS.get(source_wind_farm),
        }
    return {
        "power_unit": "kW",
        "power_label": "有功功率",
        "power_source_field": CARE_POWER_SOURCE_FIELDS.get(source_wind_farm),
    }


def _wind_history_response(record: SCADARecord, dataset_window: str, slot_start_minute: int) -> dict:
    extra = dict(record.extra or {})
    return {
        "timestamp": record.timestamp.isoformat(),
        "replay_slot_start_minute": slot_start_minute,
        "wind_speed_ms": record.wind_speed_ms,
        "wind_gust_ms": None,
        "wind_direction_deg": None,
        "nacelle_direction_deg": record.nacelle_direction_deg,
        "air_temperature_c": record.ambient_temp_c,
        "air_pressure_hpa": None,
        "turbulence_intensity": None,
        "data_source": "real_dataset",
        "source_dataset": extra.get("source_dataset"),
        "dataset_window": dataset_window,
        "quality": {"display_mode": "wall_clock_24h_loop"},
    }


@router.get("/{turbine_id}/wind-history")
async def get_turbine_wind_history(
    turbine_id: int,
    hours: int = Query(24, ge=1, le=720),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Turbine).where(Turbine.id == turbine_id))
    turbine = result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    db_records, dataset_window = await _load_scada_window_records(db, turbine_id, hours)
    if not db_records:
        return []

    ordered = list(reversed(db_records))
    slots = min(hours, 24)
    history: list[dict] = []
    for slot_index in range(slots):
        if len(ordered) == 1:
            record = ordered[0]
        else:
            source_index = round(slot_index * (len(ordered) - 1) / max(slots - 1, 1))
            record = ordered[source_index]
        history.append(
            _wind_history_response(
                record,
                dataset_window=dataset_window,
                slot_start_minute=round(slot_index * 1440 / slots),
            )
        )
    return history


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
    if turbine.lat is None or turbine.lng is None:
        raise HTTPException(
            status_code=404,
            detail="This asset has no real geographic coordinates; weather lookup is unavailable.",
        )

    try:
        return await open_meteo_loader.get_current_weather(turbine.lat, turbine.lng)
    except OpenMeteoWeatherError:
        try:
            return era5_loader.get_wind_at(turbine.lat, turbine.lng)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=502,
                detail="Open-Meteo weather lookup failed and no local weather dataset is available.",
            ) from exc
