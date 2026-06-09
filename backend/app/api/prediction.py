from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import Fault, RULPrediction, Turbine, WorkOrder
from app.schemas import (
    CostComparisonRequest,
    CostComparisonResponse,
    RULListResponse,
    RULResponse,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


FAULT_COST_PROFILE = {
    "bearing_wear": {"base_cost": 85000.0, "severity": 0.68, "component": "main_bearing"},
    "bearing_inner_race_wear": {"base_cost": 85000.0, "severity": 0.72, "component": "main_bearing"},
    "gearbox_tooth_pitting": {"base_cost": 120000.0, "severity": 0.78, "component": "gearbox"},
    "generator_overheat": {"base_cost": 45000.0, "severity": 0.55, "component": "generator"},
    "blade_leading_edge_erosion": {"base_cost": 35000.0, "severity": 0.42, "component": "blade"},
    "pitch_system_fault": {"base_cost": 18000.0, "severity": 0.35, "component": "pitch_system"},
    "cooling_system_fault": {"base_cost": 28000.0, "severity": 0.45, "component": "cooling_system"},
    "main_shaft_misalignment": {"base_cost": 70000.0, "severity": 0.65, "component": "main_shaft"},
    "electrical_connection": {"base_cost": 22000.0, "severity": 0.32, "component": "electrical"},
}


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _risk_level(probability: float) -> str:
    if probability >= 0.65:
        return "high"
    if probability >= 0.35:
        return "medium"
    return "low"


def _derive_rul_from_hi(hi_value: float) -> float:
    """Conservative fallback when no RUL prediction exists."""
    return round(_clamp((hi_value - 35.0) * 9.0, 14.0, 720.0), 1)


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
    for prediction in predictions:
        turbine_result = await db.execute(select(Turbine).where(Turbine.id == prediction.turbine_id))
        turbine = turbine_result.scalar_one_or_none()
        items.append(
            RULResponse(
                turbine_id=prediction.turbine_id,
                turbine_name=turbine.name if turbine else "",
                component=prediction.component,
                remaining_life_days=prediction.remaining_life_days,
                confidence_lower=prediction.confidence_lower,
                confidence_upper=prediction.confidence_upper,
                predicted_at=prediction.predicted_at,
            )
        )
    return RULListResponse(predictions=items)


@router.post("/cost-comparison", response_model=CostComparisonResponse)
async def compare_cost(
    data: CostComparisonRequest,
    db: AsyncSession = Depends(get_db),
):
    """Compare immediate and delayed maintenance cost.

    The recommendation is based on turbine HI, latest RUL, open faults,
    turbine power, and recent work-order costs. It is designed as a practical
    decision-support baseline for the demo rather than a fixed placeholder.
    """
    turbine_result = await db.execute(select(Turbine).where(Turbine.id == data.turbine_id))
    turbine = turbine_result.scalar_one_or_none()
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    profile = FAULT_COST_PROFILE.get(
        data.fault_type,
        {"base_cost": 50000.0, "severity": 0.5, "component": data.fault_type or "unknown"},
    )

    rul_result = await db.execute(
        select(RULPrediction)
        .where(RULPrediction.turbine_id == turbine.id)
        .order_by(RULPrediction.remaining_life_days.asc(), RULPrediction.predicted_at.desc())
        .limit(1)
    )
    latest_rul = rul_result.scalar_one_or_none()
    remaining_days = latest_rul.remaining_life_days if latest_rul else _derive_rul_from_hi(turbine.hi_value)

    fault_result = await db.execute(
        select(Fault).where(Fault.turbine_id == turbine.id, Fault.status == "open")
    )
    open_faults = fault_result.scalars().all()

    workorder_result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.turbine_id == turbine.id, WorkOrder.cost_actual.is_not(None))
        .order_by(WorkOrder.created_at.desc())
        .limit(5)
    )
    historical_orders = workorder_result.scalars().all()
    historical_actuals = [order.cost_actual for order in historical_orders if order.cost_actual]
    historical_avg = sum(historical_actuals) / len(historical_actuals) if historical_actuals else None
    base_repair_cost = historical_avg if historical_avg else profile["base_cost"]

    capacity_factor = 0.32
    tariff_yuan_per_kwh = 0.38
    downtime_loss_per_day = turbine.power_mw * 1000 * 24 * capacity_factor * tariff_yuan_per_kwh

    hi_risk = (100.0 - turbine.hi_value) / 100.0
    rul_risk = 1.0 - _clamp(remaining_days / 365.0, 0.0, 1.0)
    open_fault_risk = _clamp(len(open_faults) * 0.08, 0.0, 0.24)
    failure_probability = _clamp(
        profile["severity"] * 0.35 + hi_risk * 0.35 + rul_risk * 0.25 + open_fault_risk,
        0.05,
        0.88,
    )

    planned_downtime_days = 0.75 if profile["base_cost"] < 50000 else 1.25
    unplanned_downtime_days = 3.0 + profile["severity"] * 3.0
    escalation_factor = 1.18 + profile["severity"] * 0.55

    immediate_repair_cost = base_repair_cost + downtime_loss_per_day * planned_downtime_days
    delayed_repair_cost = (
        base_repair_cost * escalation_factor
        + failure_probability * (base_repair_cost * 0.45 + downtime_loss_per_day * unplanned_downtime_days)
    )

    immediate_repair_cost = round(immediate_repair_cost, 2)
    delayed_repair_cost = round(delayed_repair_cost, 2)
    downtime_loss_per_day = round(downtime_loss_per_day, 2)
    failure_probability = round(failure_probability, 3)
    estimated_saving = round(delayed_repair_cost - immediate_repair_cost, 2)

    if failure_probability >= 0.65 or remaining_days <= 30:
        optimal_window_days = min(7, max(1, int(remaining_days // 3) or 1))
    elif failure_probability >= 0.35 or remaining_days <= 90:
        optimal_window_days = min(21, max(7, int(remaining_days // 4)))
    else:
        optimal_window_days = min(60, max(21, int(remaining_days // 6)))

    if estimated_saving >= 0:
        recommendation = (
            f"建议在{optimal_window_days}天内安排检修。预计较延迟检修节省"
            f"{estimated_saving:,.0f}元，当前故障概率约{failure_probability:.0%}。"
        )
    else:
        recommendation = (
            f"可纳入{optimal_window_days}天内计划维护。当前立即检修经济优势不明显，"
            "但需持续跟踪HI与RUL变化。"
        )

    cost_drivers = [
        f"健康指数HI={turbine.hi_value:.1f}",
        f"最短RUL={remaining_days:.0f}天",
        f"开放故障={len(open_faults)}条",
        f"单日停机损失约{downtime_loss_per_day:,.0f}元",
    ]
    if historical_avg:
        cost_drivers.append(f"参考近{len(historical_actuals)}次实际工单均值{historical_avg:,.0f}元")
    else:
        cost_drivers.append(f"参考{profile['component']}基准维修成本{profile['base_cost']:,.0f}元")

    return CostComparisonResponse(
        immediate_repair_cost=immediate_repair_cost,
        delayed_repair_cost=delayed_repair_cost,
        downtime_loss_per_day=downtime_loss_per_day,
        failure_probability=failure_probability,
        recommendation=recommendation,
        optimal_window_days=optimal_window_days,
        risk_level=_risk_level(failure_probability),
        estimated_saving=estimated_saving,
        cost_drivers=cost_drivers,
    )
