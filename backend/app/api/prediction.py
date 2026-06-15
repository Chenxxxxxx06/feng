from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import RULPrediction, Turbine
from app.schemas import RULResponse, RULListResponse, CostComparisonRequest, CostComparisonResponse
from app.api.auth import get_current_user
from app.services.prediction_service import calculate_cost_comparison

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
