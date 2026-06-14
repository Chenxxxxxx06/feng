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


@router.post("/cost-comparison", response_model=CostComparisonResponse)
async def compare_cost(
    data: CostComparisonRequest,
    db: AsyncSession = Depends(get_db),
):
    """Compare immediate repair cost with delayed maintenance risk cost."""
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

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
    Currently uses a seasonal model; real API integration planned.
    """
    from datetime import date as date_type, timedelta

    today = date_type.today()
    dates = [today + timedelta(days=i) for i in range(days)]
    windows = get_weather_for_dates(dates, lat=lat, lng=lng)
    return {
        "location": {"lat": lat, "lng": lng},
        "windows": windows,
        "safe_days": sum(1 for w in windows if w["safe"]),
        "total_days": len(windows),
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
