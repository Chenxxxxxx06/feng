from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.database import get_db
from app.models import SCADARecord, Turbine
from app.schemas import TurbineResponse, TurbineListResponse
from app.services.care_monitoring_metrics import (
    CARE_DATASET_ID,
    calculate_care_reliability_metrics,
    refresh_care_hi_snapshots,
)
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


def _source_dataset_filter(source_dataset) -> str | None:
    if not isinstance(source_dataset, str):
        return CARE_DATASET_ID
    value = source_dataset.strip()
    if not value or value.lower() in {"all", "*"}:
        return None
    return value


@router.get("/monitoring-metrics")
async def get_monitoring_metrics(
    source_dataset: str = Query(CARE_DATASET_ID, description="数据集ID"),
    db: AsyncSession = Depends(get_db),
):
    """Return dataset-derived dashboard reliability metrics."""
    if source_dataset != CARE_DATASET_ID:
        return {
            "source_dataset": source_dataset,
            "mtbf_hours": None,
            "mttr_hours": None,
            "mttr_available": False,
            "mttr_note": "Only CARE SCADA monitoring metrics are implemented.",
            "by_region": {},
        }
    return await calculate_care_reliability_metrics(db, source_dataset)


@router.post("/refresh-health")
async def refresh_health_snapshots(
    source_dataset: str = Query(CARE_DATASET_ID, description="数据集ID"),
    db: AsyncSession = Depends(get_db),
):
    """Recalculate persisted turbine HI snapshots from imported dataset rows."""
    if source_dataset != CARE_DATASET_ID:
        raise HTTPException(status_code=400, detail="Only CARE SCADA HI refresh is implemented.")
    updates = await refresh_care_hi_snapshots(db, source_dataset)
    return {
        "source_dataset": source_dataset,
        "updated": len(updates),
        "items": updates,
    }


@router.get("/", response_model=TurbineListResponse)
async def list_turbines(
    model: str | None = Query(None, description="风机型号"),
    region: str | None = Query(None, description="区域"),
    hi_min: float | None = Query(None, description="HI最小值"),
    hi_max: float | None = Query(None, description="HI最大值"),
    status: str | None = Query(None, description="状态"),
    source_dataset: str | None = Query(CARE_DATASET_ID, description="数据集ID；传 all 返回全部"),
    db: AsyncSession = Depends(get_db),
):
    q = select(Turbine)
    dataset_filter = _source_dataset_filter(source_dataset)
    if dataset_filter:
        q = q.where(Turbine.source_dataset == dataset_filter)
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
async def get_turbines_geojson(
    source_dataset: str | None = Query(CARE_DATASET_ID, description="数据集ID；传 all 返回全部"),
    db: AsyncSession = Depends(get_db),
):
    """Return all turbines as GeoJSON FeatureCollection for map display."""
    q = select(Turbine)
    dataset_filter = _source_dataset_filter(source_dataset)
    if dataset_filter:
        q = q.where(Turbine.source_dataset == dataset_filter)
    result = await db.execute(q)
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


@router.get("/dashboard-aggregate")
async def get_dashboard_aggregate(
    source_dataset: str = Query(CARE_DATASET_ID, description="数据集ID"),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate dashboard data: component temps, SCADA trends, total power, energy.

    Returns data derived from real SCADA records — no hardcoded values.
    """
    # ── Turbines ──
    turbine_result = await db.execute(
        select(Turbine).where(Turbine.source_dataset == source_dataset)
    )
    turbines = turbine_result.scalars().all()
    turbine_ids = [t.id for t in turbines]
    total_count = len(turbines)

    if not turbine_ids:
        return {
            "source_dataset": source_dataset,
            "total_turbines": 0,
            "component_temps": [],
            "scada_trends": {"wind_speed_ms": [], "power_kw": [], "gearbox_temp_c": []},
            "total_power_kw": 0,
            "today_energy_kwh": 0,
            "data_available": False,
            "note": "No turbine data found for this dataset.",
        }

    # ── Latest SCADA per turbine for component temps & current power ──
    # SQLite-compatible subquery: get latest timestamp per turbine, then join back
    placeholders = ",".join(f":tid_{i}" for i in range(len(turbine_ids)))
    params = {f"tid_{i}": tid for i, tid in enumerate(turbine_ids)}
    latest_sql = text(f"""
        SELECT s.turbine_id, s.power_kw, s.wind_speed_ms,
            s.bearing_temperature_c, s.gearbox_temperature_c,
            s.gen_temperature_c, s.pitch_angle_deg
        FROM scada_records s
        INNER JOIN (
            SELECT turbine_id, MAX(timestamp) AS max_ts
            FROM scada_records
            WHERE turbine_id IN ({placeholders})
            GROUP BY turbine_id
        ) latest ON s.turbine_id = latest.turbine_id AND s.timestamp = latest.max_ts
    """)
    latest_result = await db.execute(latest_sql, params)
    latest_rows = latest_result.mappings().all()

    # Aggregate component temps (all temperatures from SCADA)
    bearing_temps = [r["bearing_temperature_c"] for r in latest_rows if r["bearing_temperature_c"] is not None]
    gearbox_temps = [r["gearbox_temperature_c"] for r in latest_rows if r["gearbox_temperature_c"] is not None]
    gen_temps = [r["gen_temperature_c"] for r in latest_rows if r["gen_temperature_c"] is not None]
    pitch_angles = [r["pitch_angle_deg"] for r in latest_rows if r["pitch_angle_deg"] is not None]
    power_values = [r["power_kw"] for r in latest_rows if r["power_kw"] is not None]

    # Avg rated power for p.u. → kW conversion (CARE data uses per-unit power)
    avg_rated_kw = sum((t.power_mw or 3.2) * 1000 for t in turbines) / max(len(turbines), 1)

    def _avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    def _status(temp: float, max_temp: float) -> str:
        if temp >= max_temp * 0.95:
            return "fault"
        if temp >= max_temp * 0.85:
            return "warning"
        return "normal"

    component_temps = [
        {
            "label": "主轴承",
            "temperature": _avg(bearing_temps),
            "maxTemp": 85.0,
            "unit": "°C",
            "status": _status(_avg(bearing_temps), 85.0),
        },
        {
            "label": "齿轮箱",
            "temperature": _avg(gearbox_temps),
            "maxTemp": 90.0,
            "unit": "°C",
            "status": _status(_avg(gearbox_temps), 90.0),
        },
        {
            "label": "发电机",
            "temperature": _avg(gen_temps),
            "maxTemp": 80.0,
            "unit": "°C",
            "status": _status(_avg(gen_temps), 80.0),
        },
        {
            "label": "变桨角度",
            "temperature": _avg(pitch_angles),
            "maxTemp": 90.0,
            "unit": "°",
            "status": _status(abs(_avg(pitch_angles)), 45.0),
        },
    ]

    # Convert p.u. power to approximate kW using avg rated power
    raw_total = sum(power_values)
    # CARE power values are p.u. (0-1 range) — scale to kW if needed
    is_per_unit = all(abs(p) <= 1.5 for p in power_values) if power_values else False
    if is_per_unit and power_values:
        total_power_kw = round(raw_total * avg_rated_kw, 1)
        power_multiplier = avg_rated_kw
    else:
        total_power_kw = round(raw_total, 1)
        power_multiplier = 1.0

    # ── 24h SCADA trends (latest data window, not wall-clock) ──
    # Find the latest timestamp in the dataset for these turbines
    max_ts_result = await db.execute(
        text(f"""
            SELECT MAX(timestamp) AS max_ts
            FROM scada_records
            WHERE turbine_id IN ({placeholders})
        """),
        params,
    )
    max_ts_row = max_ts_result.mappings().first()
    latest_ts = max_ts_row["max_ts"] if max_ts_row else None

    if latest_ts:
        window_start = latest_ts - timedelta(hours=24)
    else:
        window_start = datetime.now(timezone.utc) - timedelta(hours=24)

    trends_sql = text(f"""
        SELECT
            strftime('%Y-%m-%d %H:00:00', timestamp) AS hour_bucket,
            AVG(wind_speed_ms) AS avg_wind,
            AVG(power_kw) AS avg_power,
            AVG(gearbox_temperature_c) AS avg_gearbox_temp
        FROM scada_records
        WHERE turbine_id IN ({placeholders})
          AND timestamp >= :window_start
        GROUP BY hour_bucket
        ORDER BY hour_bucket
    """)
    trends_params = dict(params)
    trends_params["window_start"] = window_start
    trends_result = await db.execute(trends_sql, trends_params)
    trends_rows = trends_result.mappings().all()

    wind_trend: list[dict] = []
    power_trend: list[dict] = []
    temp_trend: list[dict] = []
    total_power_for_energy = 0.0
    for row in trends_rows:
        hour_str = str(row["hour_bucket"]) if row["hour_bucket"] else ""
        # Extract HH:MM from 'YYYY-MM-DD HH:00:00'
        if len(hour_str) >= 16:
            hour_str = hour_str[11:16]
        w = round(row["avg_wind"] or 0, 1)
        raw_p = row["avg_power"] or 0
        p = round(raw_p * power_multiplier, 1)  # p.u. → kW
        t = round(row["avg_gearbox_temp"] or 0, 1)
        wind_trend.append({"time": hour_str, "value": w})
        power_trend.append({"time": hour_str, "value": p})
        temp_trend.append({"time": hour_str, "value": t})
        total_power_for_energy += p

    # If no hourly trends found, sample individual records
    if not trends_rows:
        fallback_sql = text(f"""
            SELECT turbine_id, timestamp, wind_speed_ms, power_kw, gearbox_temperature_c
            FROM scada_records
            WHERE turbine_id IN ({placeholders})
            ORDER BY timestamp DESC
            LIMIT 48
        """)
        fallback_result = await db.execute(fallback_sql, params)
        fallback_rows = fallback_result.mappings().all()
        for r in fallback_rows:
            ts = r["timestamp"]
            if ts:
                hour_str = f"{ts.strftime('%m/%d %H:%M')}" if hasattr(ts, 'strftime') else str(ts)[:16]
            else:
                hour_str = f"T{r['turbine_id']}"
            raw_p = r["power_kw"] or 0
            wind_trend.append({"time": hour_str, "value": round(r["wind_speed_ms"] or 0, 1)})
            power_trend.append({"time": hour_str, "value": round(raw_p * power_multiplier, 1)})
            temp_trend.append({"time": hour_str, "value": round(r["gearbox_temperature_c"] or 0, 1)})
            total_power_for_energy += raw_p * power_multiplier

    # Energy: avg hourly power × 24h → kWh
    trend_count = max(len(trends_rows), len(wind_trend), 1)
    today_energy_kwh = round(total_power_for_energy / trend_count * 24, 0) if total_power_for_energy > 0 else 0

    data_window = "recent_24h" if trends_rows else "fallback_samples"
    return {
        "source_dataset": source_dataset,
        "total_turbines": total_count,
        "component_temps": component_temps,
        "scada_trends": {
            "wind_speed_ms": wind_trend,
            "power_kw": power_trend,
            "gearbox_temp_c": temp_trend,
        },
        "total_power_kw": total_power_kw,
        "today_energy_kwh": today_energy_kwh,
        "power_is_per_unit": is_per_unit,
        "power_multiplier": power_multiplier,
        "avg_rated_power_kw": avg_rated_kw,
        "data_available": bool(component_temps or wind_trend or power_trend or temp_trend),
        "data_window": data_window,
        "latest_data_ts": latest_ts.isoformat() if latest_ts else None,
        "note": f"数据集最新时间: {latest_ts.isoformat() if latest_ts else 'N/A'}; 窗口模式: {data_window}; 功率因数: ×{power_multiplier:.0f}",
    }
