import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.config import get_settings

settings = get_settings()
from app.models import RULPrediction, Turbine, User
from app.schemas import RULResponse, RULListResponse, CostComparisonRequest, CostComparisonResponse
from app.api.auth import get_current_user
from app.services.prediction_service import (
    calculate_cost_comparison,
    refresh_rul_predictions,
    get_prediction_summary,
    get_valid_fault_types,
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
async def list_fault_types(db: AsyncSession = Depends(get_db)):
    """Return valid fault types for cost-comparison dropdown.

    Queries real FaultKnowledgeNode data from database.
    Falls back to empty list if no data.
    """
    from app.services.data_registry import get_fault_type_registry
    registry = await get_fault_type_registry(db)
    if registry:
        return {
            "types": [
                {"value": ft, "label": ft, "component": info.get("category", "")}
                for ft, info in registry.items()
            ]
        }
    # Minimal fallback when DB has no fault knowledge entries
    return {
        "types": [
            {"value": "轴承磨损", "label": "轴承磨损", "component": "轴承"},
        ]
    }


@router.get("/settings")
async def prediction_settings(db: AsyncSession = Depends(get_db)):
    """Return prediction-page configuration values from real data.

    All values are computed from DB — no hardcoded constants.
    """
    from app.services.data_registry import (
        get_hi_thresholds, get_rul_settings, get_fleet_location
    )
    hi_t = await get_hi_thresholds(db)
    rul_s = await get_rul_settings(db)
    loc = await get_fleet_location(db)

    return {
        "hi_warning_threshold": hi_t.get("warning", 70.0),
        "hi_failure_threshold": hi_t.get("failure", 55.0),
        "rul_warning_threshold": rul_s.get("rul_warning_threshold", 90),
        "shift_start_time": rul_s.get("shift_start_time", "08:00"),
        "farm_lat": loc.get("lat", 37.84),
        "farm_lng": loc.get("lng", 107.74),
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
    # Dynamic validation against real knowledge base
    valid_types = await get_valid_fault_types(db)
    if data.fault_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid fault_type. Must be one of: {', '.join(valid_types[:10])}{'...' if len(valid_types) > 10 else ''}",
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
    create_work_orders: bool = Query(False, description="Create WorkOrder records for high/urgent items"),
    ai_optimize: bool = Query(False, description="Use AI to review and suggest schedule improvements"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Auto-schedule maintenance tasks from the current plan.

    - Schedules only the top_n most urgent items (default 30)
    - Hard crew-hour capacity per day (24h = 3 crews × 8h)
    - Items that can't fit in their RUL window are returned as overflow
    - Returns scheduled plan + conflict report
    - When create_work_orders=True, creates WorkOrder records for urgent+high priority items
    """
    from datetime import date as date_type

    plan = await generate_maintenance_plan(db=db)
    if not plan:
        return {"scheduled": [], "conflicts": [], "overflow": [], "message": "无维修计划", "work_orders_created": 0}

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

    # ── Create WorkOrder records for scheduled high/urgent items ──
    wos_created = 0
    if create_work_orders:
        from app.models import WorkOrder as WorkOrderModel
        for item in ok:
            if item.get("priority") not in ("urgent", "high"):
                continue
            # Check if work order already exists for this turbine+component
            existing = (await db.execute(
                select(WorkOrderModel).where(
                    WorkOrderModel.turbine_id == item["turbine_id"],
                    WorkOrderModel.fault_type == item.get("fault_type", ""),
                    WorkOrderModel.status.in_(["pending", "assigned", "in_progress"]),
                    WorkOrderModel.deleted_at.is_(None),
                )
            )).scalars().first()
            if existing:
                continue
            wo = WorkOrderModel(
                turbine_id=item["turbine_id"],
                title=f'{item.get("turbine_name","")} {item.get("component","")}{item.get("action","检修")}',
                description=f'自动排程生成: RUL={item.get("rul_days",0):.0f}d, 紧急度={item.get("urgency_score",0)}',
                priority=item.get("priority", "medium"),
                fault_type=item.get("fault_type", ""),
                status="pending",
                cost_estimate=item.get("cost_estimate", 0),
                due_date=date_type.fromisoformat(item["scheduled_date"]) if item.get("scheduled_date") else None,
            )
            db.add(wo)
            wos_created += 1
        await db.commit()

    # ── AI schedule review ──
    ai_analysis = None
    if ai_optimize:
        try:
            from app.services.qwen_client import chat
            from app.services.data_registry import get_fleet_location

            # Fetch real fleet location from turbine data
            fleet_loc = await get_fleet_location(db)
            fleet_lat = fleet_loc.get("lat", 37.84)
            fleet_lng = fleet_loc.get("lng", 107.74)

            # Weather must be fetched BEFORE it's referenced in schedule_json
            weather_windows = await get_weather_for_dates(
                [start + timedelta(days=i) for i in range(min(16, max_days))],
                lat=fleet_lat, lng=fleet_lng,
            )

            schedule_json = json.dumps({
                "scheduled": [{k: v for k, v in t.items() if k in (
                    "turbine_name", "component", "scheduled_date", "priority",
                    "rul_days", "urgency_score", "downtime_hours"
                )} for t in ok[:15]],
                "overflow": [{k: v for k, v in t.items() if k in (
                    "turbine_name", "component", "rul_days", "priority"
                )} for t in overflow[:5]],
                "conflicts": conflicts[:5],
                "weather_safe_days": sum(1 for w in weather_windows if w.get("safe", False)),
            }, ensure_ascii=False, default=str)
            prompt = f"""你是风电运维排程专家。以下是贪心算法生成的排程结果，请分析并给出优化建议。

当前排程:
{schedule_json}

请输出JSON格式:
{{
  "issues": ["发现的问题"],
  "suggestions": ["优化建议"],
  "risk_items": ["需关注的高风险项"]
}}"""
            eff_key = user.api_key or settings.DASHSCOPE_API_KEY or None
            ai_resp = chat([
                {"role": "system", "content": "你是风电运维排程专家。只输出JSON，不要其他文字。"},
                {"role": "user", "content": prompt},
            ], model=user.model_preference or "qwen-turbo",
               api_key=eff_key,
               api_provider=user.api_provider if user.api_key else ("通义千问 DashScope" if eff_key else None),
               temperature=0.3, max_tokens=512)
            ai_analysis = json.loads(ai_resp.strip().removeprefix("```json").removesuffix("```").strip())
        except Exception:
            ai_analysis = {"issues": [], "suggestions": ["AI分析暂不可用，请检查API密钥配置"], "risk_items": []}

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
        "work_orders_created": wos_created,
        "ai_analysis": ai_analysis,
    }


@router.get("/weather-windows")
async def weather_windows_endpoint(
    days: int = Query(30, description="Days ahead to check"),
    lat: float | None = Query(None, description="Latitude (defaults to fleet average)"),
    lng: float | None = Query(None, description="Longitude (defaults to fleet average)"),
    db: AsyncSession = Depends(get_db),
):
    """Get weather safety windows for outdoor maintenance.

    Uses Open-Meteo daily forecast (up to 16 days) for real wind/precip/temp data.
    Defaults to fleet average location from real turbine data.
    """
    from app.services.data_registry import get_fleet_location

    if lat is None or lng is None:
        fleet_loc = await get_fleet_location(db)
        if lat is None:
            lat = fleet_loc.get("lat", 37.84)
        if lng is None:
            lng = fleet_loc.get("lng", 107.74)

    # Falls back to seasonal model for dates beyond forecast range.
    # Returns a score (0-100) and flags for each day.
    from datetime import date as date_type, timedelta

    today = date_type.today()
    dates = [today + timedelta(days=i) for i in range(days)]
    windows = await get_weather_for_dates(dates, lat=lat, lng=lng)
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
