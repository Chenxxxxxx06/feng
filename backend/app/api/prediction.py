from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import RULPrediction, Turbine
from app.schemas import RULResponse, RULListResponse, CostComparisonRequest, CostComparisonResponse
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/rul", response_model=RULListResponse)
async def get_rul_predictions(
    turbine_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(RULPrediction)
    if turbine_id:
        q = q.where(RULPrediction.turbine_id == turbine_id)
    q = q.order_by(RULPrediction.predicted_at.desc())
    result = await db.execute(q)
    predictions = result.scalars().all()

    items = []
    for p in predictions:
        t_result = await db.execute(select(Turbine).where(Turbine.id == p.turbine_id))
        t = t_result.scalar_one_or_none()
        items.append(RULResponse(
            turbine_id=p.turbine_id,
            turbine_name=t.name if t else "",
            component=p.component,
            remaining_life_days=p.remaining_life_days,
            confidence_lower=p.confidence_lower,
            confidence_upper=p.confidence_upper,
            predicted_at=p.predicted_at,
        ))
    return RULListResponse(predictions=items)


@router.post("/cost-comparison", response_model=CostComparisonResponse)
async def compare_cost(data: CostComparisonRequest):
    """Placeholder - will integrate cost model in Stage 6"""
    return CostComparisonResponse(
        immediate_repair_cost=85000.0,
        delayed_repair_cost=135000.0,
        downtime_loss_per_day=12000.0,
        failure_probability=0.35,
        recommendation="建议在7天内安排检修，预期可节省维修成本约5万元",
        optimal_window_days=7,
    )
