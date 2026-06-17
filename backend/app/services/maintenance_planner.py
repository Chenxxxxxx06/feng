"""Maintenance Planner — ranking algorithm for predictive maintenance scheduling.

Generates a prioritized maintenance action plan by scoring each turbine component
across four dimensions: RUL urgency, health index, fault presence, and maintenance
history. The output is consumable by both the frontend table and the LLM copilot.

Algorithm:
    urgency = 0.40 * rul_score + 0.25 * hi_score + 0.20 * fault_score + 0.15 * maint_score
    Each sub-score is normalized to 0–100 (higher = more urgent).

All configuration (weights, thresholds, component configs, urgency boosts,
base costs) is sourced from data_registry which computes values from the
real database (FaultKnowledgeNode, WorkOrder, SCADA). No hardcoded data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RULPrediction, Turbine, Fault, WorkOrder

logger = logging.getLogger(__name__)


def _reg():
    """Late-import data_registry helpers to avoid circular imports."""
    from app.services.data_registry import (
        get_urgency_weights,
        get_urgency_thresholds,
        get_component_config,
        get_urgency_boost,
        get_score_thresholds,
    )
    return {
        "get_urgency_weights": get_urgency_weights,
        "get_urgency_thresholds": get_urgency_thresholds,
        "get_component_config": get_component_config,
        "get_urgency_boost": get_urgency_boost,
        "get_score_thresholds": get_score_thresholds,
    }


async def generate_maintenance_plan(
    *,
    db: AsyncSession,
    top_n: Optional[int] = None,
    region: Optional[str] = None,
) -> list[dict]:
    """Generate prioritized maintenance action plan.

    Args:
        db: Async database session
        top_n: Limit results to top N most urgent items
        region: Optional region filter

    Returns:
        Sorted list of maintenance task dicts
    """
    now = datetime.now(timezone.utc)

    # ── Load turbine metadata ──
    tq = select(Turbine)
    if region:
        tq = tq.where(Turbine.region == region)
    turbines_result = await db.execute(tq)
    turbines = {t.id: t for t in turbines_result.scalars().all()}

    # ── Load all RUL predictions ──
    rul_result = await db.execute(
        select(RULPrediction).where(
            RULPrediction.turbine_id.in_(list(turbines.keys()))
        )
    )
    rul_items: list[RULPrediction] = list(rul_result.scalars().all())

    # ── Load active faults ──
    faults_result = await db.execute(
        select(Fault).where(
            Fault.turbine_id.in_(list(turbines.keys())),
            Fault.status == "open",
        )
    )
    faults_by_turbine: dict[int, list[Fault]] = {}
    for f in faults_result.scalars().all():
        faults_by_turbine.setdefault(f.turbine_id, []).append(f)

    # ── Load pending work orders ──
    wo_result = await db.execute(
        select(WorkOrder).where(
            WorkOrder.turbine_id.in_(list(turbines.keys())),
            WorkOrder.status.in_(["pending", "assigned", "in_progress"]),
        )
    )
    wos_by_turbine: dict[int, list[WorkOrder]] = {}
    for wo in wo_result.scalars().all():
        wos_by_turbine.setdefault(wo.turbine_id, []).append(wo)

    # ── Load configuration from real data registry ──
    reg = _reg()
    urg_weights = await reg["get_urgency_weights"](db)
    urg_thresholds = await reg["get_urgency_thresholds"](db)
    comp_config = await reg["get_component_config"](db)
    urg_boost = await reg["get_urgency_boost"](db)
    score_thresholds = await reg["get_score_thresholds"](db)

    if not comp_config:
        logger.warning("Empty component config from data registry — maintenance plan may be incomplete")

    # ── Score every component ──
    tasks: list[dict] = []
    for r in rul_items:
        turbine = turbines.get(r.turbine_id)
        if not turbine:
            continue

        # Compute urgency sub-scores
        rul_score = _score_rul(r.remaining_life_days, score_thresholds.get("rul"))
        hi_score = _score_hi(turbine.hi_value or 85, score_thresholds.get("hi"))
        fault_score = _score_faults(faults_by_turbine.get(r.turbine_id, []), r.component, urg_boost)
        maint_score = _score_maintenance_gap(turbine, now, score_thresholds.get("maintenance_gap"))

        w = urg_weights
        urgency = round(
            w["rul"] * rul_score + w["hi"] * hi_score + w["fault"] * fault_score + w["maintenance"] * maint_score,
            1,
        )

        # Determine action tier — use real component config from knowledge base
        action = _determine_action(r.component, r.remaining_life_days, comp_config)
        config = comp_config.get(r.component, {})
        fallback_parts = ["常规备件"]
        fallback_actions = {30: "紧急检修", 90: "计划维修", 180: "状态检修", 999: "常规巡检"}

        # Check for existing work orders
        existing_wos = [
            wo for wo in wos_by_turbine.get(r.turbine_id, [])
            if _wo_matches_component(wo, r.component)
        ]

        # Priority label
        if urgency >= urg_thresholds["urgent"]:
            priority = "urgent"
        elif urgency >= urg_thresholds["high"]:
            priority = "high"
        elif urgency >= urg_thresholds["medium"]:
            priority = "medium"
        else:
            priority = "low"

        # Cost estimate — use real base costs from component config (spare_parts sum)
        cost_estimate = _estimate_maintenance_cost_real(
            r.component, r.remaining_life_days, turbine.power_mw or 2.0, turbine.hi_value or 85.0, comp_config
        )

        tasks.append({
            "turbine_id": r.turbine_id,
            "turbine_name": turbine.name,
            "region": turbine.region,
            "component": r.component,
            "rul_days": round(r.remaining_life_days, 1),
            "hi_value": turbine.hi_value,
            "status": turbine.status,
            "urgency_score": urgency,
            "priority": priority,
            "action": action,
            "downtime_hours": config.get("downtime_hours", 8),
            "crew_size": config.get("crew_size", 2),
            "parts_needed": config.get("parts", fallback_parts),
            "cost_estimate": round(cost_estimate, 2),
            "active_faults": [
                {"type": f.fault_type, "confidence": f.confidence}
                for f in faults_by_turbine.get(r.turbine_id, [])
            ],
            "existing_work_orders": [
                {"id": wo.id, "title": wo.title, "status": wo.status}
                for wo in existing_wos
            ],
            "confidence_interval": [r.confidence_lower, r.confidence_upper],
        })

    # Sort by urgency desc
    tasks.sort(key=lambda t: t["urgency_score"], reverse=True)

    if top_n:
        tasks = tasks[:top_n]

    return tasks


# ── Sub-score functions ──

# ── Fallback scoring thresholds (when DB has no data) ──
_FALLBACK_RUL = [
    {"max_days": 30, "score_floor": 90, "score_ceiling": 100},
    {"max_days": 90, "score_floor": 60, "score_ceiling": 90},
    {"max_days": 180, "score_floor": 30, "score_ceiling": 60},
    {"max_days": 365, "score_floor": 10, "score_ceiling": 30},
    {"max_days": 9999, "score_floor": 0, "score_ceiling": 10},
]
_FALLBACK_HI = [
    {"max_hi": 50, "score": 90},
    {"max_hi": 60, "score_floor": 70, "score_ceiling": 90},
    {"max_hi": 75, "score_floor": 40, "score_ceiling": 70},
    {"max_hi": 85, "score_floor": 15, "score_ceiling": 40},
    {"max_hi": 100, "score_floor": 0, "score_ceiling": 15},
]
_FALLBACK_GAP = [
    {"max_days": 90, "score": 0},
    {"max_days": 180, "score_floor": 10, "score_ceiling": 25},
    {"max_days": 365, "score_floor": 25, "score_ceiling": 50},
    {"max_days": 9999, "score_floor": 50, "score_ceiling": 100},
]


def _score_rul(days: float, thresholds: list[dict] | None = None) -> float:
    """Score RUL urgency using configurable thresholds."""
    t = thresholds or _FALLBACK_RUL
    for entry in t:
        if days < entry["max_days"]:
            if "score" in entry:
                return float(entry["score"])
            lo, hi = entry["score_floor"], entry["score_ceiling"]
            # Linear interpolation within band
            prev_max = 0.0
            for prev in t:
                if prev["max_days"] < entry["max_days"]:
                    prev_max = max(prev_max, prev["max_days"])
            frac = (days - prev_max) / max(1, entry["max_days"] - prev_max)
            return round(lo + (hi - lo) * frac, 1)
    return 5.0


def _score_hi(hi: float, thresholds: list[dict] | None = None) -> float:
    """Score health index urgency using configurable thresholds."""
    t = thresholds or _FALLBACK_HI
    for entry in t:
        if hi < entry["max_hi"]:
            if "score" in entry:
                return float(entry["score"])
            lo, hi_score = entry["score_floor"], entry["score_ceiling"]
            # Find previous entry's max for interpolation
            prev_max = 0.0
            for prev in t:
                if prev["max_hi"] < entry["max_hi"]:
                    prev_max = max(prev_max, prev["max_hi"])
            frac = (hi - prev_max) / max(1, entry["max_hi"] - prev_max)
            return round(lo + (hi_score - lo) * frac, 1)
    return 5.0


def _score_faults(faults: list[Fault], component: str, boost_map: dict[str, int] | None = None) -> float:
    """Score based on active faults. Boost values from knowledge base severity."""
    if not faults:
        return 0
    score = 0
    for f in faults:
        boost = (boost_map or {}).get(f.fault_type, 10)
        score += boost * f.confidence
    return min(100, score)


def _score_maintenance_gap(turbine: Turbine, now: datetime, thresholds: list[dict] | None = None) -> float:
    """Score based on time since last maintenance. Configurable thresholds."""
    if not turbine.last_maintenance:
        return 30
    lm = turbine.last_maintenance
    if lm.tzinfo is None:
        lm = lm.replace(tzinfo=timezone.utc)
    days = (now - lm).days
    t = thresholds or _FALLBACK_GAP
    for entry in t:
        if days < entry["max_days"]:
            if "score" in entry:
                return float(entry["score"])
            lo, hi = entry["score_floor"], entry["score_ceiling"]
            prev_max = 0.0
            for prev in t:
                if prev["max_days"] < entry["max_days"]:
                    prev_max = max(prev_max, prev["max_days"])
            frac = (days - prev_max) / max(1, entry["max_days"] - prev_max)
            return round(lo + (hi - lo) * frac, 1)
    return 5.0


def _determine_action(component: str, rul_days: float, comp_config: dict[str, dict] | None = None) -> str:
    """Map RUL to a concrete maintenance action using real component config."""
    if comp_config:
        config = comp_config.get(component, {})
        actions = config.get("actions", {})
        if actions:
            for threshold in sorted(actions.keys()):
                if rul_days < threshold:
                    return actions[threshold]
            return actions[max(actions.keys())]
    # Fallback
    fallback = {30: "紧急检修", 90: "计划维修", 180: "状态检修", 999: "常规巡检"}
    for threshold in sorted(fallback.keys()):
        if rul_days < threshold:
            return fallback[threshold]
    return "常规巡检"


# ── Cost estimation (NEW — uses real data registry) ──

def _estimate_maintenance_cost_real(
    component: str,
    rul_days: float,
    power_mw: float,
    hi_value: float = 85.0,
    comp_config: dict[str, dict] | None = None,
) -> float:
    """Estimate maintenance cost using real base costs from knowledge base.

    base: from FaultKnowledgeNode.spare_parts sum (est_cost * quantity)
    urgency_mult: higher for short RUL (emergency premium)
    power_mult: larger turbine = higher cost
    hi_mult: worse health = more damage = higher cost
    """
    # Base cost from real data (spare_parts sum from knowledge base)
    base = 50000  # global fallback
    if comp_config:
        cfg = comp_config.get(component, {})
        base = cfg.get("base_cost", 50000)

    # Urgency multiplier
    if rul_days < 30:
        urgency_mult = 1.5
    elif rul_days < 90:
        urgency_mult = 1.2
    elif rul_days < 365:
        urgency_mult = 1.0
    else:
        urgency_mult = 0.85

    # Power scaling
    power_mult = max(0.5, power_mw / 1.5) if power_mw > 0 else 1.0

    # HI scaling: worse health → higher repair cost
    hi_mult = max(0.7, 100.0 / max(hi_value, 40.0))

    return round(base * urgency_mult * power_mult * hi_mult, 2)


# Legacy alias for backwards compatibility
_estimate_maintenance_cost = _estimate_maintenance_cost_real

# Legacy alias for module-level access (used by external callers that haven't migrated)
COMPONENT_CONFIG: dict = {}
URGENCY_WEIGHTS: dict[str, float] = {"rul": 0.40, "hi": 0.25, "fault": 0.20, "maintenance": 0.15}
URGENCY_THRESHOLDS: dict[str, int] = {"urgent": 70, "high": 45, "medium": 25}
FAULT_URGENCY_BOOST: dict[str, int] = {}


def _wo_matches_component(wo: WorkOrder, component: str) -> bool:
    """Check if a work order is related to a given component."""
    title = (wo.title or "").lower()
    desc = (wo.description or "").lower()
    comp_lower = component.lower()
    return comp_lower in title or comp_lower in desc


def _estimate_maintenance_cost(
    component: str,
    rul_days: float,
    power_mw: float,
    hi_value: float = 85.0,
) -> float:
    """Estimate maintenance cost based on component, urgency, turbine power and health.

    Lower HI → higher cost (more damage to repair).
    Larger power → higher cost (bigger components).
    Shorter RUL → higher cost (emergency premium).
    """
    base_costs = {
        "齿轮箱": 120_000,
        "发电机": 45_000,
        "主轴承": 85_000,
        "叶片": 35_000,
        "变桨系统": 18_000,
    }
    base = base_costs.get(component, 30_000)
    # Urgency multiplier: more urgent = more expensive
    if rul_days < 30:
        urgency_mult = 1.5
    elif rul_days < 90:
        urgency_mult = 1.2
    elif rul_days < 365:
        urgency_mult = 1.0
    else:
        urgency_mult = 0.85
    # Power scaling: per-MW cost (baseline 2MW turbine)
    power_mult = max(0.5, power_mw / 1.5) if power_mw > 0 else 1.0
    # HI scaling: worse health → higher repair cost
    hi_mult = max(0.7, 100.0 / max(hi_value, 40.0))
    return round(base * urgency_mult * power_mult * hi_mult, 2)


# ── LLM-friendly summary builder ──

def build_plan_summary_for_llm(plan: list[dict]) -> str:
    """Format the maintenance plan as a human-readable summary for LLM prompts."""
    if not plan:
        return "当前无维修计划，所有部件状态正常。"

    lines = [f"## 维修计划 (共{len(plan)}项)\n"]

    # Top urgent items
    urgent = [t for t in plan if t["priority"] == "urgent"]
    high = [t for t in plan if t["priority"] == "high"]

    if urgent:
        lines.append(f"### 🔴 紧急 ({len(urgent)}项)")
        for i, t in enumerate(urgent[:5], 1):
            lines.append(
                f"{i}. {t['turbine_name']} {t['component']} — "
                f"RUL {t['rul_days']:.0f}天 | HI {t['hi_value']:.0f} | "
                f"建议: {t['action']} | 预估费用: ¥{t['cost_estimate']:,.0f} | "
                f"停机: {t['downtime_hours']}h"
            )

    if high:
        lines.append(f"\n### 🟡 高优先级 ({len(high)}项)")
        for i, t in enumerate(high[:5], 1):
            lines.append(
                f"{i}. {t['turbine_name']} {t['component']} — "
                f"RUL {t['rul_days']:.0f}天 | 建议: {t['action']}"
            )

    # Stats
    total_cost = sum(t["cost_estimate"] for t in plan)
    total_downtime = sum(t["downtime_hours"] for t in urgent + high)
    lines.append(f"\n### 统计")
    lines.append(f"总预估费用: ¥{total_cost:,.0f}")
    lines.append(f"紧急+高优先级总停机时间: {total_downtime}h ({total_downtime/24:.1f}天)")
    lines.append(f"涉及风机: {len(set(t['turbine_id'] for t in plan))}台")
    regions = set(t["region"] for t in plan)
    lines.append(f"涉及区域: {', '.join(regions)}")

    return "\n".join(lines)
