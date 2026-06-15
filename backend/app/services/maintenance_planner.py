"""Maintenance Planner — ranking algorithm for predictive maintenance scheduling.

Generates a prioritized maintenance action plan by scoring each turbine component
across four dimensions: RUL urgency, health index, fault presence, and maintenance
history. The output is consumable by both the frontend table and the LLM copilot.

Algorithm:
    urgency = 0.40 * rul_score + 0.25 * hi_score + 0.20 * fault_score + 0.15 * maint_score
    Each sub-score is normalized to 0–100 (higher = more urgent).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RULPrediction, Turbine, Fault, WorkOrder

logger = logging.getLogger(__name__)

# ── Urgency scoring weights (configurable) ──
URGENCY_WEIGHTS = {
    "rul": 0.40,       # RUL remaining life
    "hi": 0.25,        # Health index
    "fault": 0.20,     # Active faults
    "maintenance": 0.15,  # Maintenance gap
}
URGENCY_THRESHOLDS = {
    "urgent": 70,   # >= 70 → urgent priority
    "high": 45,     # >= 45 → high priority
    "medium": 25,   # >= 25 → medium priority
}

# ── Component maintenance config ──
COMPONENT_CONFIG = {
    "齿轮箱": {
        "actions": {30: "立即停机更换齿轮箱", 90: "安排齿轮箱大修", 180: "齿轮箱专项检查", 999: "纳入常规巡检"},
        "downtime_hours": 8, "crew_size": 3,
        "parts": ["齿轮箱总成", "润滑油", "密封件"],
    },
    "发电机": {
        "actions": {30: "立即更换发电机轴承", 90: "安排发电机检修", 180: "发电机温度监测加强", 999: "常规巡检"},
        "downtime_hours": 6, "crew_size": 2,
        "parts": ["发电机轴承", "冷却风扇", "绝缘材料"],
    },
    "主轴承": {
        "actions": {30: "立即更换主轴承", 90: "安排主轴对中校正", 180: "加强振动监测", 999: "常规巡检"},
        "downtime_hours": 8, "crew_size": 2,
        "parts": ["主轴承", "润滑脂", "密封圈"],
    },
    "叶片": {
        "actions": {30: "立即停机修复叶片", 90: "安排叶片检修", 180: "叶片无人机巡检", 999: "常规巡检"},
        "downtime_hours": 8, "crew_size": 3,
        "parts": ["修复材料", "涂层", "平衡配重"],
    },
    "变桨系统": {
        "actions": {30: "立即修复变桨系统", 90: "安排变桨校准", 180: "变桨角度检查", 999: "常规巡检"},
        "downtime_hours": 4, "crew_size": 2,
        "parts": ["变桨电机", "控制器", "传感器"],
    },
}

# ── Fault-type → urgency boost ──
FAULT_URGENCY_BOOST = {
    "bearing_inner_race_wear": 25,
    "gearbox_tooth_pitting": 30,
    "generator_overheat": 20,
    "blade_leading_edge_erosion": 18,
    "pitch_system_fault": 22,
    "main_shaft_misalignment": 28,
    "cooling_system_fault": 15,
    "electrical_connection": 12,
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

    # ── Score every component ──
    tasks: list[dict] = []
    for r in rul_items:
        turbine = turbines.get(r.turbine_id)
        if not turbine:
            continue

        # Compute urgency sub-scores
        rul_score = _score_rul(r.remaining_life_days)
        hi_score = _score_hi(turbine.hi_value or 85)
        fault_score = _score_faults(faults_by_turbine.get(r.turbine_id, []), r.component)
        maint_score = _score_maintenance_gap(turbine, now)

        w = URGENCY_WEIGHTS
        urgency = round(
            w["rul"] * rul_score + w["hi"] * hi_score + w["fault"] * fault_score + w["maintenance"] * maint_score,
            1,
        )

        # Determine action tier
        action = _determine_action(r.component, r.remaining_life_days)
        config = COMPONENT_CONFIG.get(r.component, COMPONENT_CONFIG["齿轮箱"])

        # Check for existing work orders
        existing_wos = [
            wo for wo in wos_by_turbine.get(r.turbine_id, [])
            if _wo_matches_component(wo, r.component)
        ]

        # Priority label
        ut = URGENCY_THRESHOLDS
        if urgency >= ut["urgent"]:
            priority = "urgent"
        elif urgency >= ut["high"]:
            priority = "high"
        elif urgency >= ut["medium"]:
            priority = "medium"
        else:
            priority = "low"

        # Cost estimate
        cost_estimate = _estimate_maintenance_cost(
            r.component, r.remaining_life_days, turbine.power_mw or 2.0, turbine.hi_value or 85.0
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
            "downtime_hours": config["downtime_hours"],
            "crew_size": config["crew_size"],
            "parts_needed": config["parts"],
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

def _score_rul(days: float) -> float:
    """Score RUL urgency. Shorter RUL → higher score."""
    if days < 30:
        return 90 + (30 - days) / 30 * 10   # 90 → 100
    elif days < 90:
        return 60 + (90 - days) / 60 * 30   # 60 → 90
    elif days < 180:
        return 30 + (180 - days) / 90 * 30  # 30 → 60
    elif days < 365:
        return 10 + (365 - days) / 185 * 20 # 10 → 30
    else:
        return max(0, 10 - (days - 365) / 365 * 10)


def _score_hi(hi: float) -> float:
    """Score health index urgency. Lower HI → higher score."""
    if hi < 50:
        return 90
    elif hi < 60:
        return 70 + (60 - hi) / 10 * 20
    elif hi < 75:
        return 40 + (75 - hi) / 15 * 30
    elif hi < 85:
        return 15 + (85 - hi) / 10 * 25
    else:
        return max(0, 15 - (hi - 85) / 15 * 15)


def _score_faults(faults: list[Fault], component: str) -> float:
    """Score based on active faults. Component-specific faults add more."""
    if not faults:
        return 0
    score = 0
    for f in faults:
        boost = FAULT_URGENCY_BOOST.get(f.fault_type, 10)
        score += boost * f.confidence
    return min(100, score)


def _score_maintenance_gap(turbine: Turbine, now: datetime) -> float:
    """Score based on time since last maintenance. Longer gap → higher score."""
    if not turbine.last_maintenance:
        return 30  # unknown → moderate urgency
    lm = turbine.last_maintenance
    if lm.tzinfo is None:
        lm = lm.replace(tzinfo=timezone.utc)
    days = (now - lm).days
    if days < 90:
        return 0
    elif days < 180:
        return 10 + (days - 90) / 90 * 15
    elif days < 365:
        return 25 + (days - 180) / 185 * 25
    else:
        return min(100, 50 + (days - 365) / 365 * 50)


def _determine_action(component: str, rul_days: float) -> str:
    """Map RUL to a concrete maintenance action."""
    config = COMPONENT_CONFIG.get(component, COMPONENT_CONFIG["齿轮箱"])
    for threshold in sorted(config["actions"]):
        if rul_days < threshold:
            return config["actions"][threshold]
    return "常规巡检"


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
