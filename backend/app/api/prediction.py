from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import RULPrediction, Turbine
from app.schemas import RULResponse, RULListResponse, CostComparisonRequest, CostComparisonResponse
from app.api.auth import get_current_user
from app.services.prediction_service import (
    calculate_cost_comparison,
    refresh_rul_predictions,
    get_prediction_summary,
    VALID_FAULT_TYPES,
)
from app.services.maintenance_planner import (
    generate_maintenance_plan,
    build_plan_summary_for_llm,
)
from app.services.maintenance_scheduler import (
    auto_schedule,
    detect_conflicts,
    get_weather_for_dates,
    generate_ics,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/rul", response_model=RULListResponse)
async def get_rul_predictions(
    turbine_id: int | None = Query(None),
    component: str | None = Query(None, description="Filter by component name"),
    max_remaining_days: int | None = Query(None, description="Max remaining days (for risk filtering)"),
    db: AsyncSession = Depends(get_db),
):
    if turbine_id is not None:
        turbine = await db.get(Turbine, turbine_id)
        if not turbine:
            raise HTTPException(status_code=404, detail="Turbine not found")

    q = (
        select(RULPrediction, Turbine.name)
        .join(Turbine, Turbine.id == RULPrediction.turbine_id)
        .order_by(RULPrediction.remaining_life_days.asc(), RULPrediction.predicted_at.desc())
    )
    if turbine_id:
        q = q.where(RULPrediction.turbine_id == turbine_id)
    if component:
        q = q.where(RULPrediction.component == component)
    if max_remaining_days is not None:
        q = q.where(RULPrediction.remaining_life_days <= max_remaining_days)

    result = await db.execute(q)

    items = []
    for p, turbine_name in result.all():
        items.append(RULResponse(
            turbine_id=p.turbine_id,
            turbine_name=turbine_name,
            component=p.component,
            remaining_life_days=p.remaining_life_days,
            confidence_lower=p.confidence_lower,
            confidence_upper=p.confidence_upper,
            predicted_at=p.predicted_at,
        ))
    return RULListResponse(predictions=items)


@router.post("/rul/refresh")
async def refresh_rul(
    turbine_id: int | None = Query(None, description="Turbine ID; omit to refresh all"),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate RUL predictions using current health index data.

    Replaces ALL existing RUL predictions for the specified turbine(s).
    Uses the health-index engine to project remaining life per component.
    """
    try:
        summary = await refresh_rul_predictions(turbine_id=turbine_id, db=db)
        return {"success": True, **summary}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"RUL refresh failed: {exc}")


@router.get("/summary")
async def prediction_summary(db: AsyncSession = Depends(get_db)):
    """Aggregated prediction statistics for dashboards."""
    return await get_prediction_summary(db)


@router.get("/fault-types")
async def list_fault_types():
    """Return valid fault types for cost-comparison dropdown."""
    return {
        "types": [
            {"value": k, "label": v["label"], "component": v["component"]}
            for k, v in {
                "bearing_wear": {"label": "轴承磨损", "component": "主轴承"},
                "gearbox_failure": {"label": "齿轮箱故障", "component": "齿轮箱"},
                "blade_damage": {"label": "叶片损伤", "component": "叶片"},
                "generator_failure": {"label": "发电机故障", "component": "发电机"},
                "pitch_system_fault": {"label": "变桨系统故障", "component": "变桨系统"},
                "main_shaft_misalignment": {"label": "主轴不对中", "component": "主轴承"},
                "cooling_system_fault": {"label": "冷却系统故障", "component": "发电机"},
                "electrical_connection": {"label": "电气连接松动", "component": "发电机"},
            }.items()
        ]
    }


@router.post("/cost-comparison", response_model=CostComparisonResponse)
async def compare_cost(
    data: CostComparisonRequest,
    db: AsyncSession = Depends(get_db),
):
    """Compare immediate repair cost with delayed maintenance risk cost.

    Uses real turbine data (power rating, health index) and fault-type specifics
    to compute failure probability, cost estimates, and recommendations.
    """
    if data.fault_type not in VALID_FAULT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid fault_type. Must be one of: {', '.join(VALID_FAULT_TYPES)}",
        )

    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail=f"Turbine {data.turbine_id} not found")

    return await calculate_cost_comparison(data=data, turbine=turbine, db=db)


@router.get("/maintenance-plan")
async def get_maintenance_plan(
    top_n: int | None = Query(None, description="Limit to top N most urgent items"),
    region: str | None = Query(None, description="Filter by region"),
    format: str | None = Query(None, description="'summary' returns LLM-ready text"),
    db: AsyncSession = Depends(get_db),
):
    """Generate prioritized maintenance action plan.

    Each item is scored across four dimensions:
    - RUL urgency (40%): shorter remaining life = higher score
    - Health index (25%): lower HI = higher score
    - Active faults (20%): fault presence adds urgency
    - Maintenance gap (15%): time since last service

    Returns sorted list with priority, action, cost, downtime, parts.
    """
    plan = await generate_maintenance_plan(db=db, top_n=top_n, region=region)

    if format == "summary":
        return {
            "plan": plan,
            "summary": build_plan_summary_for_llm(plan),
        }

    return {
        "plan": plan,
        "total": len(plan),
        "urgent_count": sum(1 for t in plan if t["priority"] == "urgent"),
        "high_count": sum(1 for t in plan if t["priority"] == "high"),
        "total_cost_estimate": round(sum(t["cost_estimate"] for t in plan), 2),
    }


@router.post("/schedule")
async def schedule_maintenance(
    start_date: str | None = Query(None, description="Start date YYYY-MM-DD, defaults to today"),
    max_days: int = Query(90, description="Max days to schedule ahead"),
    top_n: int = Query(30, description="Number of most urgent items to schedule"),
    db: AsyncSession = Depends(get_db),
):
    """Auto-schedule maintenance tasks from the current plan.

    - Schedules only the top_n most urgent items (default 30)
    - Hard crew-hour capacity per day (24h = 3 crews × 8h)
    - Items that can't fit in their RUL window are returned as overflow
    - Returns scheduled plan + conflict report
    """
    from datetime import date as date_type

    plan = await generate_maintenance_plan(db=db)
    if not plan:
        return {"scheduled": [], "conflicts": [], "overflow": [], "message": "无维修计划"}

    start = date_type.today()
    if start_date:
        try:
            start = date_type.fromisoformat(start_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid start_date format, use YYYY-MM-DD")

    scheduled = auto_schedule(plan, start_date=start, max_days=max_days, top_n=top_n)
    conflicts = detect_conflicts(scheduled)
    overflow = [t for t in scheduled if t.get("overflow")]
    ok = [t for t in scheduled if not t.get("overflow")]

    return {
        "scheduled": ok,
        "overflow": overflow,
        "conflicts": conflicts,
        "start_date": start.isoformat(),
        "max_days": max_days,
        "top_n": top_n,
        "total_scheduled": len(ok),
        "total_overflow": len(overflow),
        "conflict_count": len(conflicts),
    }


@router.get("/weather-windows")
async def weather_windows_endpoint(
    days: int = Query(30, description="Days ahead to check"),
    lat: float = Query(37.3, description="Latitude"),
    lng: float = Query(107.6, description="Longitude"),
):
    """Get weather safety windows for outdoor maintenance.

    Returns a score (0-100) and flags for each day in the forecast window.
    Uses Open-Meteo forecast API for days 1–16, seasonal model for days 17+.
    Each window includes a `source` field: "open_meteo" or "seasonal_model".
    """
    from datetime import date as date_type, timedelta

    today = date_type.today()
    dates = [today + timedelta(days=i) for i in range(days)]
    windows = await get_weather_for_dates(dates, lat=lat, lng=lng)
    return {
        "location": {"lat": lat, "lng": lng},
        "windows": windows,
        "safe_days": sum(1 for w in windows if w["safe"]),
        "total_days": len(windows),
        "forecast_source": {
            "near_term": "open_meteo",
            "near_term_days": min(16, days),
            "long_range": "seasonal_model",
        },
    }


@router.get("/schedule/export-ics")
async def export_schedule_ics(
    start_date: str | None = Query(None),
    max_days: int = Query(90),
    db: AsyncSession = Depends(get_db),
):
    """Export scheduled maintenance plan as .ics calendar file."""
    from datetime import date as date_type

    plan = await generate_maintenance_plan(db=db)
    if not plan:
        raise HTTPException(status_code=404, detail="No maintenance plan to export")

    start = date_type.today()
    if start_date:
        start = date_type.fromisoformat(start_date)

    scheduled = auto_schedule(plan, start_date=start, max_days=max_days)
    ics_content = generate_ics(scheduled, title="风调预顺 运维计划")

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": "attachment; filename=fengdiao_schedule.ics"},
    )
