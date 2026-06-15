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
    """Compare immediate repair cost with delayed maintenance risk cost."""
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail=f"Turbine {data.turbine_id} not found")

    return await calculate_cost_comparison(data=data, turbine=turbine, db=db)
