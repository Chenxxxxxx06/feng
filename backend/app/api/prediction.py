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
