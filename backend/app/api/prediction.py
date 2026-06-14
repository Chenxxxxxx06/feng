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
