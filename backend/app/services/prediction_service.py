"""Prediction service for cost comparison and RUL calculations."""

from app.schemas import CostComparisonRequest, CostComparisonResponse
from app.models import Turbine
from sqlalchemy.ext.asyncio import AsyncSession


async def calculate_cost_comparison(
    data: CostComparisonRequest,
    turbine: Turbine,
    db: AsyncSession,
) -> CostComparisonResponse:
    """Calculate cost comparison between immediate and delayed repair.

    Stub implementation — replace with real calculation logic.
    """
    base_cost = _estimate_repair_cost(turbine, data.fault_type)

    return CostComparisonResponse(
        immediate_repair_cost=base_cost,
        delayed_repair_cost=base_cost * 2.5,
        downtime_loss_per_day=turbine.power_mw * 5000 or 5000,
        failure_probability=0.35,
        recommendation="建议在下次计划停机期间安排维修",
        optimal_window_days=14,
        risk_level="medium",
        estimated_saving=base_cost * 1.5,
        cost_drivers=["备件成本", "停机损失", "人工成本"],
    )


def _estimate_repair_cost(turbine: Turbine, fault_type: str) -> float:
    """Estimate base repair cost based on turbine power and fault type."""
    base = (turbine.power_mw or 2.0) * 50000
    multipliers = {
        "gearbox_failure": 2.5,
        "bearing_failure": 1.5,
        "blade_damage": 3.0,
        "generator_failure": 2.0,
    }
    return base * multipliers.get(fault_type, 1.0)
