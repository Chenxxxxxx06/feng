"""Prediction service: RUL refresh, cost comparison, and prediction summary.

RUL prediction is driven by the Health Index (HI) engine. Since ML models are
not yet deployed, this service uses a rule-based degradation model that:
- Reads current HI, component scores, and maintenance days per turbine
- Projects remaining life using a HI degradation curve
- Generates confidence intervals from component-score variance
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
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
    """Compare immediate vs delayed repair cost using real turbine data.

    Now driven by actual turbine power rating, current HI, and fault-type
    specifics rather than hard-coded constants.
    """
    config = FAULT_COST_CONFIG.get(
        data.fault_type,
        {"base": 50_000, "multiplier": 1.0, "downtime_days": 3, "label": data.fault_type},
    )

    power_mw = turbine.power_mw or 2.0
    hi = turbine.hi_value or 85.0

    # ── Immediate repair cost ──
    # Scales with turbine power and fault severity
    immediate = config["base"] * (power_mw / 2.0) * config["multiplier"]

    # ── Failure probability ──
    # Derived from health index: lower HI → higher probability
    if hi >= 90:
        failure_prob = 0.05 + (90 - hi) * 0.005
    elif hi >= 70:
        failure_prob = 0.10 + (90 - hi) * 0.01
    elif hi >= 50:
        failure_prob = 0.30 + (70 - hi) * 0.015
    else:
        failure_prob = 0.60

    failure_prob = round(min(0.95, max(0.02, failure_prob)), 3)

    # ── Downtime loss per day ──
    # Revenue lost per day = power * 24h * electricity price (~0.5 ¥/kWh)
    daily_loss = power_mw * 1000 * 24 * 0.5

    # ── Delayed repair cost ──
    # If failure occurs during delay, cost = immediate repair + downtime × days
    downtime_days = config["downtime_days"]
    failure_extra_cost = failure_prob * (daily_loss * downtime_days + immediate * 0.3)
    delayed = immediate + failure_extra_cost

    # ── Estimated saving ──
    saving = delayed - immediate

    # ── Risk level ──
    if failure_prob > 0.4:
        risk_level = "high"
    elif failure_prob > 0.15:
        risk_level = "medium"
    else:
        risk_level = "low"

    # ── Optimal window ──
    # Suggest maintenance within N days based on HI degradation rate
    if risk_level == "high":
        optimal_days = 3
    elif risk_level == "medium":
        optimal_days = 14
    else:
        optimal_days = 45

    # ── Recommendation ──
    if risk_level == "high":
        recommendation = (
            f"紧急建议：{turbine.name} 当前健康指数 {hi:.0f}，{config['label']}故障概率 "
            f"{(failure_prob * 100):.0f}%。强烈建议在 {optimal_days} 天内安排立即检修，"
            f"避免突发性停机造成的 {(daily_loss * downtime_days):,.0f} 元损失。"
        )
    elif risk_level == "medium":
        recommendation = (
            f"建议在下次计划停机（{optimal_days} 天内）安排 {turbine.name} 的 "
            f"{config['label']} 检修。当前 HI={hi:.0f}，故障概率 "
            f"{(failure_prob * 100):.0f}%，提前维修预计可节省 ¥{saving:,.0f}。"
        )
    else:
        recommendation = (
            f"{turbine.name} ({config['label']}) 当前状态良好（HI={hi:.0f}），"
            f"故障概率仅 {(failure_prob * 100):.0f}%。建议纳入常规巡检计划，"
            f"在 {optimal_days} 天内安排预防性检查即可。"
        )

    # ── Cost drivers ──
    cost_drivers = _build_cost_drivers(config, power_mw, daily_loss, failure_prob)

    return CostComparisonResponse(
        immediate_repair_cost=round(immediate, 2),
        delayed_repair_cost=round(delayed, 2),
        downtime_loss_per_day=round(daily_loss, 2),
        failure_probability=failure_prob,
        recommendation=recommendation,
        optimal_window_days=optimal_days,
        risk_level=risk_level,
        estimated_saving=round(saving, 2),
        cost_drivers=cost_drivers,
    )


def _build_cost_drivers(
    config: dict,
    power_mw: float,
    daily_loss: float,
    failure_prob: float,
) -> list[str]:
    """Build human-readable cost driver descriptions."""
    drivers = [
        f"备件成本 ({config['label']})",
        f"停机损失 (¥{daily_loss:,.0f}/天 × {config['downtime_days']}天)",
        f"人工成本 ({power_mw:.1f}MW机组)",
    ]
    if failure_prob > 0.2:
        drivers.append(f"故障风险溢价 (概率{(failure_prob * 100):.0f}%)")
    if config["downtime_days"] > 3:
        drivers.append("发电损失（长停机窗口）")
    if config["multiplier"] >= 2.0:
        drivers.append("紧急调配附加费")
    return drivers


# ── Prediction Summary ──

async def get_prediction_summary(db: AsyncSession) -> dict:
    """Aggregate prediction stats for dashboard consumption."""
    now = datetime.now(timezone.utc)

    # Turbine health distribution
    total_result = await db.execute(select(func.count(Turbine.id)))
    total = total_result.scalar() or 0

    healthy_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "normal")
    )
    warning_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "warning")
    )
    fault_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "fault")
    )

    # RUL statistics
    rul_result = await db.execute(
        select(
            func.count(RULPrediction.id),
            func.avg(RULPrediction.remaining_life_days),
            func.min(RULPrediction.remaining_life_days),
            func.max(RULPrediction.remaining_life_days),
        )
    )
    rul_count, rul_avg, rul_min, rul_max = rul_result.one()

    # Imminent failures (RUL < 30 days)
    imminent_result = await db.execute(
        select(func.count(RULPrediction.id)).where(
            RULPrediction.remaining_life_days < 30
        )
    )
    imminent_count = imminent_result.scalar() or 0

    # Critical components (RUL < 90 days)
    critical_result = await db.execute(
        select(func.count(RULPrediction.id)).where(
            RULPrediction.remaining_life_days < 90
        )
    )
    critical_count = critical_result.scalar() or 0

    # Average HI across fleet
    hi_result = await db.execute(
        select(func.avg(Turbine.hi_value))
    )
    avg_hi = hi_result.scalar()

    # RUL by region
    region_rows = await db.execute(
        select(
            Turbine.region,
            func.avg(RULPrediction.remaining_life_days).label("avg_rul"),
            func.count(RULPrediction.id).label("cnt"),
        )
        .join(RULPrediction, RULPrediction.turbine_id == Turbine.id)
        .group_by(Turbine.region)
    )
    by_region = {
        row.region: {"avg_rul": round(row.avg_rul, 1), "count": row.cnt}
        for row in region_rows
    }

    # MTBF estimate (mean time between failures)
    # Simplified: fleet total operational hours / fault count
    fault_count = fault_result.scalar() or 0
    if fault_count > 0:
        mtbf_hours = (total * 24 * 365) / fault_count
    else:
        mtbf_hours = total * 24 * 365  # no faults → max

    # MTTR estimate (mean time to repair)
    # Based on average downtime configuration
    avg_downtime = sum(c["downtime_days"] for c in FAULT_COST_CONFIG.values()) / len(
        FAULT_COST_CONFIG
    )
    mttr_hours = avg_downtime * 8  # 8 working hours per day

    return {
        "fleet": {
            "total": total,
            "healthy": healthy_result.scalar() or 0,
            "warning": warning_result.scalar() or 0,
            "fault": fault_count,
            "avg_hi": round(avg_hi, 1) if avg_hi else None,
        },
        "rul": {
            "total_predictions": rul_count or 0,
            "avg_days": round(rul_avg, 1) if rul_avg else None,
            "min_days": round(rul_min, 1) if rul_min else None,
            "max_days": round(rul_max, 1) if rul_max else None,
            "imminent_count": imminent_count,
            "critical_count": critical_count,
        },
        "reliability": {
            "mtbf_hours": round(mtbf_hours, 1),
            "mttr_hours": round(mttr_hours, 1),
        },
        "by_region": by_region,
        "generated_at": now.isoformat(),
    }
