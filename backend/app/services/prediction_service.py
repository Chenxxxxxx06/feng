"""Prediction service for cost comparison and RUL calculations."""

from app.schemas import CostComparisonRequest, CostComparisonResponse
from app.models import Turbine
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RULPrediction, Turbine, SCADARecord
from app.schemas import CostComparisonRequest, CostComparisonResponse
from app.services.health_index import calculate_turbine_hi, WEIGHTS

logger = logging.getLogger(__name__)

# ── Component-to-HI-weight mapping ──
COMPONENT_WEIGHTS = {
    "齿轮箱": ("gearbox", WEIGHTS["performance"]),
    "发电机": ("generator", WEIGHTS["performance"]),
    "主轴承": ("main_bearing", WEIGHTS["vibration"]),
    "叶片": ("blade", WEIGHTS["blade"]),
    "变桨系统": ("pitch", WEIGHTS["trend"]),
}

# ── Fault-type to base cost and component mapping ──
FAULT_COST_CONFIG = {
    "bearing_wear": {
        "base": 85_000,
        "multiplier": 1.5,
        "downtime_days": 3,
        "component": "主轴承",
        "label": "轴承磨损",
    },
    "gearbox_failure": {
        "base": 120_000,
        "multiplier": 2.5,
        "downtime_days": 7,
        "component": "齿轮箱",
        "label": "齿轮箱故障",
    },
    "blade_damage": {
        "base": 35_000,
        "multiplier": 3.0,
        "downtime_days": 5,
        "component": "叶片",
        "label": "叶片损伤",
    },
    "generator_failure": {
        "base": 45_000,
        "multiplier": 2.0,
        "downtime_days": 4,
        "component": "发电机",
        "label": "发电机故障",
    },
    "pitch_system_fault": {
        "base": 18_000,
        "multiplier": 1.0,
        "downtime_days": 2,
        "component": "变桨系统",
        "label": "变桨系统故障",
    },
    "main_shaft_misalignment": {
        "base": 60_000,
        "multiplier": 1.8,
        "downtime_days": 5,
        "component": "主轴承",
        "label": "主轴不对中",
    },
    "cooling_system_fault": {
        "base": 25_000,
        "multiplier": 1.2,
        "downtime_days": 2,
        "component": "发电机",
        "label": "冷却系统故障",
    },
    "electrical_connection": {
        "base": 15_000,
        "multiplier": 0.8,
        "downtime_days": 1,
        "component": "发电机",
        "label": "电气连接松动",
    },
}

VALID_FAULT_TYPES = list(FAULT_COST_CONFIG.keys())


# ── RUL Refresh ──

async def refresh_rul_predictions(
    turbine_id: Optional[int] = None,
    *,
    db: AsyncSession,
) -> dict:
    """Regenerate RUL predictions for one or all turbines.

    Uses the health-index engine to project remaining life for each major
    component.  Existing predictions for the target turbine(s) are replaced.

    Returns a summary dict with counts.
    """
    # Load target turbines
    q = select(Turbine)
    if turbine_id is not None:
        q = q.where(Turbine.id == turbine_id)
    result = await db.execute(q)
    turbines = result.scalars().all()

    if not turbines:
        return {"refreshed": 0, "predictions": 0, "turbines": 0}

    now = datetime.now(timezone.utc)

    # Delete old predictions for these turbines
    tids = [t.id for t in turbines]
    from sqlalchemy import delete

    await db.execute(delete(RULPrediction).where(RULPrediction.turbine_id.in_(tids)))
    await db.flush()

    total_predictions = 0
    for t in turbines:
        preds = await _predict_turbine_components(t, now, db)
        for p in preds:
            db.add(p)
        total_predictions += len(preds)

    await db.commit()

    logger.info(
        "RUL refresh: %d turbines → %d predictions",
        len(turbines),
        total_predictions,
    )
    return {
        "refreshed": len(turbines),
        "predictions": total_predictions,
        "turbines": len(turbines),
    }


async def _predict_turbine_components(
    turbine: Turbine,
    now: datetime,
    db: AsyncSession,
) -> list[RULPrediction]:
    """Generate RUL predictions for all major components of a single turbine.

    Uses real turbine state directly (HI, maintenance days, status) rather than
    re-running the full HI engine, because demo data lacks per-component SCADA.
    Each component gets a realistic variance so the 5 components of one turbine
    don't all report identical values.
    """
    import random

    hi = turbine.hi_value or 85.0
    status = turbine.status or "normal"

    # Days since last maintenance — strong signal for wear components
    maint_days = 180.0  # default
    if turbine.last_maintenance:
        lm = turbine.last_maintenance
        if lm.tzinfo is None:
            lm = lm.replace(tzinfo=timezone.utc)
        maint_days = max(1.0, (now - lm).days)

    predictions: list[RULPrediction] = []
    for component_name, (comp_key, weight) in COMPONENT_WEIGHTS.items():
        # ── Per-component effective health ──
        # Start from overall turbine HI, then apply component-specific offset
        comp_offset = _component_offset(comp_key, maint_days, hi)
        effective_hi = max(15.0, min(99.0, hi + comp_offset))

        # ── Project RUL ──
        remaining = _project_rul(effective_hi, weight, maint_days)

        # ── Confidence interval ──
        # Wider spread for worse health and longer maintenance gaps
        base_spread = (100 - effective_hi) * 1.5 + (maint_days / 365) * 20
        spread = max(5, base_spread)
        lower = round(max(1, remaining - spread), 1)
        upper = round(remaining + spread, 1)

        predictions.append(
            RULPrediction(
                turbine_id=turbine.id,
                component=component_name,
                predicted_at=now,
                remaining_life_days=round(remaining, 1),
                confidence_lower=lower,
                confidence_upper=upper,
            )
        )

    return predictions


def _component_offset(comp_key: str, maint_days: float, hi: float) -> float:
    """Return a per-component health offset so predictions vary realistically.

    - Bearings & gearbox: degrade with maintenance gaps
    - Generator: sensitive to overall HI
    - Blades: degrade slowly unless damaged
    - Pitch system: moderate degradation
    """
    import hashlib, random

    # Deterministic per-component seed so values are stable across refreshes
    seed_val = int(hashlib.md5(comp_key.encode()).hexdigest()[:8], 16) % 1000
    rng = random.Random(seed_val)

    # Base offsets by component type
    base = {
        "gearbox": -8.0,
        "main_bearing": -5.0,
        "generator": -3.0,
        "blade": +2.0,
        "pitch": -1.0,
    }

    # Maintenance penalty: components wear faster when neglected
    maint_penalty = min(0, -(maint_days / 365) * 4)

    # Random scatter (±4%)
    scatter = rng.uniform(-4, 4)

    return base.get(comp_key, 0.0) + maint_penalty + scatter


def _project_rul(
    effective_hi: float,
    weight: float,
    maint_days: float,
) -> float:
    """Project remaining useful life from effective component health.

    Uses a piecewise model that maps HI ranges to realistic RUL bands:

        HI ≥ 90  →  300–500 days  (healthy, slow degradation)
        HI 75–90 →  120–400 days  (normal aging)
        HI 55–75 →   40–200 days  (warning — needs attention)
        HI < 55  →    5–80 days   (critical — imminent failure)

    Maintenance gap penalizes RUL further (neglected components fail sooner).
    """
    # Base RUL from effective HI (piecewise linear interpolation)
    if effective_hi >= 90:
        base = 300 + (effective_hi - 90) * 20  # 300 → 500
    elif effective_hi >= 75:
        base = 120 + (effective_hi - 75) * 12  # 120 → 300
    elif effective_hi >= 55:
        base = 40 + (effective_hi - 55) * 4  # 40 → 120
    else:
        base = max(5, effective_hi * 0.8)  # 5 → 44

    # Maintenance penalty: mild — each day past 180 costs ~0.15 RUL days
    overdue = max(0, maint_days - 180)
    maint_penalty = overdue * 0.15

    # Component weight tweak: heavier components degrade slightly faster
    weight_factor = 1.0 - (weight - 0.15) * 0.2

    return max(5, (base - maint_penalty) * weight_factor)


# ── Cost Comparison ──

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
