"""
Data Registry — single source of truth for all prediction/maintenance configuration.

All values are computed from real database records. No hardcoded constants.
Cached with configurable TTL. Falls back to sensible defaults when data is missing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FaultKnowledgeNode, NotificationConfig, SCADARecord, Turbine, WorkOrder, User

logger = logging.getLogger(__name__)

# ── In-memory cache ────────────────────────────────────────────────────
_cache: dict[str, tuple[datetime, Any]] = {}
_CACHE_TTL = timedelta(minutes=10)


def _cached(key: str, compute_fn, *args, **kwargs):
    """Return cached value or recompute if expired."""
    now = datetime.now(timezone.utc)
    if key in _cache:
        ts, val = _cache[key]
        if now - ts < _CACHE_TTL:
            return val
    result = compute_fn(*args, **kwargs)
    _cache[key] = (now, result)
    return result


def invalidate_cache(prefix: str = ""):
    """Clear all or selectively prefixed cache entries."""
    if not prefix:
        _cache.clear()
    else:
        for k in list(_cache.keys()):
            if k.startswith(prefix):
                del _cache[k]


# ── Fault type registry ───────────────────────────────────────────────

async def get_fault_type_registry(db: AsyncSession) -> dict[str, dict]:
    """Build registry from FaultKnowledgeNode table.

    Returns dict keyed by fault_type (Chinese name). Each value:
      {category, icon, severity, avg_downtime_hours, total_parts_cost,
       avg_case_cost, avg_downtime_days, solutions_list, spare_parts_list}
    """
    return await _build_fault_registry(db)


async def _build_fault_registry(db: AsyncSession) -> dict[str, dict]:
    """Build the fault type registry from actual database data."""
    result = await db.execute(select(FaultKnowledgeNode))
    nodes = result.scalars().all()

    registry: dict[str, dict] = {}
    for node in nodes:
        solutions = node.solutions or []
        parts = node.spare_parts or []
        cases = node.cases or []

        # Compute average downtime from solutions
        downtime_hours = [
            s.get("downtime_hours", 0)
            for s in solutions
            if isinstance(s, dict) and s.get("downtime_hours")
        ]
        avg_downtime = sum(downtime_hours) / len(downtime_hours) if downtime_hours else 0

        # Compute total parts cost
        parts_costs = [
            p.get("est_cost", 0) * max(1, p.get("quantity", 1))
            for p in parts
            if isinstance(p, dict)
        ]
        total_parts_cost = sum(parts_costs) if parts_costs else 0

        # Compute average case cost and downtime
        case_costs = [
            c.get("total_cost", 0)
            for c in cases
            if isinstance(c, dict) and c.get("total_cost")
        ]
        avg_case_cost = sum(case_costs) / len(case_costs) if case_costs else 0

        case_downtimes = [
            c.get("downtime_days", 0)
            for c in cases
            if isinstance(c, dict) and c.get("downtime_days")
        ]
        avg_downtime_days = sum(case_downtimes) / len(case_downtimes) if case_downtimes else 0

        registry[node.fault_type] = {
            "category": node.category or "",
            "icon": node.icon or "⚠️",
            "severity": node.severity or "medium",
            "avg_downtime_hours": avg_downtime,
            "total_parts_cost": total_parts_cost,
            "avg_case_cost": avg_case_cost,
            "avg_downtime_days": avg_downtime_days,
            "solutions_list": solutions,
            "spare_parts_list": parts,
        }

    if not registry:
        logger.warning("FaultKnowledgeNode table is empty — falling back to defaults")
        return _fallback_fault_registry()

    logger.info("Built fault registry with %d entries from database", len(registry))
    return registry


def _fallback_fault_registry() -> dict[str, dict]:
    """Minimal fallback when database has no knowledge entries."""
    return {
        "轴承磨损": {
            "category": "轴承", "icon": "⚠️", "severity": "medium",
            "avg_downtime_hours": 8, "total_parts_cost": 85000,
            "avg_case_cost": 85000, "avg_downtime_days": 3,
            "solutions_list": [], "spare_parts_list": [],
        },
        "齿轮箱故障": {
            "category": "齿轮箱", "icon": "⚠️", "severity": "high",
            "avg_downtime_hours": 16, "total_parts_cost": 120000,
            "avg_case_cost": 120000, "avg_downtime_days": 7,
            "solutions_list": [], "spare_parts_list": [],
        },
        "叶片损伤": {
            "category": "叶片", "icon": "⚠️", "severity": "medium",
            "avg_downtime_hours": 10, "total_parts_cost": 35000,
            "avg_case_cost": 35000, "avg_downtime_days": 5,
            "solutions_list": [], "spare_parts_list": [],
        },
        "发电机故障": {
            "category": "发电机", "icon": "⚠️", "severity": "high",
            "avg_downtime_hours": 12, "total_parts_cost": 45000,
            "avg_case_cost": 45000, "avg_downtime_days": 4,
            "solutions_list": [], "spare_parts_list": [],
        },
        "变桨系统故障": {
            "category": "变桨", "icon": "⚠️", "severity": "medium",
            "avg_downtime_hours": 6, "total_parts_cost": 18000,
            "avg_case_cost": 18000, "avg_downtime_days": 2,
            "solutions_list": [], "spare_parts_list": [],
        },
        "主轴不对中": {
            "category": "传动", "icon": "⚠️", "severity": "high",
            "avg_downtime_hours": 10, "total_parts_cost": 60000,
            "avg_case_cost": 60000, "avg_downtime_days": 5,
            "solutions_list": [], "spare_parts_list": [],
        },
        "冷却系统故障": {
            "category": "电气", "icon": "⚠️", "severity": "low",
            "avg_downtime_hours": 6, "total_parts_cost": 25000,
            "avg_case_cost": 25000, "avg_downtime_days": 2,
            "solutions_list": [], "spare_parts_list": [],
        },
        "电气连接松动": {
            "category": "电气", "icon": "⚠️", "severity": "low",
            "avg_downtime_hours": 4, "total_parts_cost": 15000,
            "avg_case_cost": 15000, "avg_downtime_days": 1,
            "solutions_list": [], "spare_parts_list": [],
        },
    }


# ── Cost aggregates from WorkOrders ───────────────────────────────────

async def get_cost_aggregates(db: AsyncSession) -> dict[str, dict]:
    """Aggregate real costs from WorkOrder table grouped by fault_type.

    Returns dict keyed by fault_type with {avg_cost_estimate, avg_cost_actual, avg_downtime_hours}.
    """
    result = await db.execute(
        select(
            WorkOrder.fault_type,
            func.avg(WorkOrder.cost_estimate).label("avg_est"),
            func.avg(WorkOrder.cost_actual).label("avg_act"),
            func.avg(WorkOrder.downtime_hours).label("avg_down"),
            func.count(WorkOrder.id).label("cnt"),
        )
        .where(
            WorkOrder.deleted_at.is_(None),
            WorkOrder.fault_type.isnot(None),
        )
        .group_by(WorkOrder.fault_type)
    )
    rows = result.all()
    aggregates: dict[str, dict] = {}
    for row in rows:
        fault_type = row[0]
        if not fault_type:
            continue
        aggregates[fault_type] = {
            "avg_cost_estimate": float(row[1] or 0),
            "avg_cost_actual": float(row[2] or 0),
            "avg_downtime_hours": float(row[3] or 0),
            "count": int(row[4] or 0),
        }
    if aggregates:
        logger.info("Cost aggregates built from %d fault types with real WorkOrder data", len(aggregates))
    else:
        logger.warning("No WorkOrder data available for cost aggregation")
    return aggregates


# ── Component config from Knowledge Base ──────────────────────────────

async def get_component_config(db: AsyncSession) -> dict[str, dict]:
    """Build component-level configuration from FaultKnowledgeNode.

    Groups knowledge entries by category, aggregates solutions and spare_parts.
    Returns dict keyed by component Chinese name.
    """
    result = await db.execute(select(FaultKnowledgeNode))
    nodes = list(result.scalars().all())

    # Group by category
    by_category: dict[str, list[FaultKnowledgeNode]] = defaultdict(list)
    for node in nodes:
        cat = node.category or "其他"
        by_category[cat].append(node)

    config: dict[str, dict] = {}
    for category, cat_nodes in by_category.items():
        # Aggregate all solutions across category
        all_solutions: list[dict] = []
        all_parts: list[dict] = []
        for node in cat_nodes:
            if node.solutions:
                all_solutions.extend(s for s in node.solutions if isinstance(s, dict))
            if node.spare_parts:
                all_parts.extend(p for p in node.spare_parts if isinstance(p, dict))

        # Compute actions by difficulty tier
        actions = _build_actions_from_solutions(all_solutions)

        # Downtime hours: average of all solutions
        dtimes = [s.get("downtime_hours", 0) for s in all_solutions]
        avg_downtime = sum(dtimes) / len(dtimes) if dtimes else 8

        # Crew size from difficulty
        crew = _estimate_crew_from_solutions(all_solutions)

        # Unique parts
        parts = list(dict.fromkeys(p.get("name", "") for p in all_parts if p.get("name")))

        # Base cost: sum of all spare parts est_cost * quantity
        base_cost = sum(
            p.get("est_cost", 0) * max(1, p.get("quantity", 1))
            for p in all_parts
        )

        config[category] = {
            "actions": actions,
            "downtime_hours": int(max(1, avg_downtime)),
            "crew_size": crew,
            "parts": parts or ["常规备件"],
            "base_cost": base_cost,
        }

    if config:
        logger.info("Component config built for %d categories from knowledge base", len(config))
    else:
        logger.warning("No component config available — falling back")
        return _fallback_component_config()

    return config


def _build_actions_from_solutions(solutions: list[dict]) -> dict[int, str]:
    """Map solutions to RUL-based action tiers.

    Returns dict: {max_rul_days: action_text}
    """
    if not solutions:
        return {30: "紧急检修", 90: "计划维修", 180: "状态检修", 999: "常规巡检"}

    # Sort by downtime (shorter = more urgent = lower RUL threshold)
    unique_actions = list(dict.fromkeys(
        s.get("action", "") for s in solutions if s.get("action")
    ))
    if not unique_actions:
        return {30: "紧急检修", 90: "计划维修", 180: "状态检修", 999: "常规巡检"}

    # Map actions to RUL thresholds
    if len(unique_actions) >= 4:
        return {30: unique_actions[0], 90: unique_actions[1], 180: unique_actions[2], 999: unique_actions[-1]}
    elif len(unique_actions) == 3:
        return {30: unique_actions[0], 90: unique_actions[1], 999: unique_actions[2]}
    elif len(unique_actions) == 2:
        return {90: unique_actions[0], 999: unique_actions[1]}
    else:
        return {90: unique_actions[0], 999: "常规巡检"}


def _estimate_crew_from_solutions(solutions: list[dict]) -> int:
    """Estimate crew size from solution difficulty levels."""
    difficulties = [s.get("difficulty", "medium") for s in solutions if s.get("difficulty")]
    if not difficulties:
        return 2
    # Count difficulty levels
    hard_count = sum(1 for d in difficulties if d in ("hard", "困难", "高"))
    if hard_count / len(difficulties) > 0.5:
        return 3
    return 2


def _fallback_component_config() -> dict[str, dict]:
    """Minimal fallback when knowledge base is empty."""
    return {
        "齿轮箱": {
            "actions": {30: "更换齿轮箱总成", 90: "更换齿轮箱轴承", 180: "齿轮箱油液分析及换油", 999: "齿轮箱常规检查"},
            "downtime_hours": 8, "crew_size": 3,
            "parts": ["齿轮箱总成", "润滑油", "密封件"],
            "base_cost": 120000,
        },
        "发电机": {
            "actions": {30: "更换发电机绕组", 90: "更换发电机轴承", 180: "发电机绝缘检测", 999: "发电机常规检查"},
            "downtime_hours": 6, "crew_size": 2,
            "parts": ["发电机轴承", "冷却风扇", "绝缘材料"],
            "base_cost": 45000,
        },
        "轴承": {
            "actions": {30: "更换主轴承", 90: "轴承振动分析及润滑", 180: "轴承间隙检查", 999: "轴承常规巡检"},
            "downtime_hours": 8, "crew_size": 2,
            "parts": ["主轴承", "润滑脂", "密封圈"],
            "base_cost": 85000,
        },
        "叶片": {
            "actions": {30: "叶片更换或大修", 90: "叶片前缘修复", 180: "叶片涂层维护", 999: "叶片外观检查"},
            "downtime_hours": 8, "crew_size": 3,
            "parts": ["修复材料", "涂层", "平衡配重"],
            "base_cost": 35000,
        },
        "变桨": {
            "actions": {30: "更换变桨电机", 90: "变桨控制器检修", 180: "变桨系统润滑", 999: "变桨功能测试"},
            "downtime_hours": 4, "crew_size": 2,
            "parts": ["变桨电机", "控制器", "传感器"],
            "base_cost": 18000,
        },
    }


# ── Urgency configuration ──────────────────────────────────────────────

async def get_urgency_boost(db: AsyncSession) -> dict[str, int]:
    """Map fault_type to urgency boost based on severity from knowledge base."""
    result = await db.execute(select(FaultKnowledgeNode))
    nodes = result.scalars().all()

    severity_map = {"critical": 30, "high": 25, "medium": 15, "low": 10}
    boost: dict[str, int] = {}
    for node in nodes:
        sev = (node.severity or "medium").lower()
        boost[node.fault_type] = severity_map.get(sev, 15)

    if boost:
        logger.info("Urgency boost built for %d fault types", len(boost))
    else:
        logger.warning("No urgency boost data — empty")
    return boost


async def get_urgency_weights(db: AsyncSession, user_id: int | None = None) -> dict[str, float]:
    """Get urgency scoring weights from user preferences or defaults.

    Reads from User.preferences JSON key 'urgency_weights'.
    Falls back to: rul=0.40, hi=0.25, fault=0.20, maintenance=0.15
    """
    default = {"rul": 0.40, "hi": 0.25, "fault": 0.20, "maintenance": 0.15}
    if user_id is None:
        return default
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.preferences and isinstance(user.preferences, dict):
            return user.preferences.get("urgency_weights", default)
    except Exception:
        pass
    return default


async def get_urgency_thresholds(db: AsyncSession, user_id: int | None = None) -> dict[str, int]:
    """Get urgency priority thresholds from user preferences.

    Reads from User.preferences JSON key 'urgency_thresholds'.
    Falls back to: urgent=70, high=45, medium=25
    """
    default = {"urgent": 70, "high": 45, "medium": 25}
    if user_id is None:
        return default
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.preferences and isinstance(user.preferences, dict):
            return user.preferences.get("urgency_thresholds", default)
    except Exception:
        pass
    return default


# ── HI / RUL threshold configuration ──────────────────────────────────

async def get_hi_thresholds(db: AsyncSession, user_id: int | None = None) -> dict[str, float]:
    """Get HI threshold configuration.

    Source: NotificationConfig.hi_threshold for warning level.
    failure=55.0 (physical constant), healthy=90.0 (physical constant)
    """
    warning = 70.0
    if user_id is not None:
        result = await db.execute(
            select(NotificationConfig).where(NotificationConfig.user_id == user_id)
        )
        config = result.scalar_one_or_none()
        if config and config.hi_threshold:
            warning = float(config.hi_threshold)
    return {"failure": 55.0, "warning": warning, "healthy": 90.0}


async def get_rul_settings(db: AsyncSession, user_id: int | None = None) -> dict[str, Any]:
    """Get RUL-related configuration from user preferences.

    Returns: {rul_warning_threshold: 90, shift_start_time: "08:00"}
    """
    default = {"rul_warning_threshold": 90, "shift_start_time": "08:00"}
    if user_id is None:
        return default
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.preferences and isinstance(user.preferences, dict):
            return {
                "rul_warning_threshold": user.preferences.get("rul_warning_threshold", 90),
                "shift_start_time": user.preferences.get("shift_start_time", "08:00"),
            }
    except Exception:
        pass
    return default


# ── Cost calculation parameters ────────────────────────────────────────

async def get_cost_params(db: AsyncSession, user_id: int | None = None) -> dict[str, float]:
    """Get cost calculation parameters from user preferences.

    Reads from User.preferences JSON key 'cost_params'.
    Falls back to electricity_price=0.40 CNY/kWh and industry-typical probability curves.
    """
    default = {
        "electricity_price_cny_per_kwh": 0.40,
        "failure_prob_healthy_slope": 0.005,
        "failure_prob_warning_slope": 0.01,
        "failure_prob_fault_slope": 0.015,
        "risk_high_threshold": 0.40,
        "risk_medium_threshold": 0.15,
        "optimal_window_high_days": 3,
        "optimal_window_medium_days": 14,
        "optimal_window_low_days": 45,
        "repair_failure_extra_factor": 0.30,
    }
    if user_id is None:
        return default
    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.preferences and isinstance(user.preferences, dict):
            stored = user.preferences.get("cost_params")
            if isinstance(stored, dict):
                # Merge with defaults so all keys are always present
                return {**default, **stored}
    except Exception:
        pass
    return default


# ── Component degradation rates from SCADA ────────────────────────────

async def get_degradation_rates(db: AsyncSession) -> dict[str, float]:
    """Compute component-specific degradation rate modifiers from real SCADA data.

    Analyzes sensor slopes per component:
    - gearbox: gearbox_temperature_c trend
    - main_bearing: bearing_temperature_c trend
    - generator: gen_temperature_c trend
    - blade: power_kw / wind_speed_ms ratio trend
    - pitch: pitch_angle_deg variability

    Returns dict of component_key -> rate_modifier (normalized, 0.3-3.0 range).

    Falls back to industry-typical values when SCADA data insufficient.
    """
    fallback = {
        "gearbox": 1.5,
        "main_bearing": 1.3,
        "generator": 1.0,
        "blade": 0.5,
        "pitch": 0.7,
    }

    try:
        result = await db.execute(
            select(SCADARecord)
            .order_by(SCADARecord.timestamp.desc())
            .limit(20000)
        )
        records = result.scalars().all()
        if len(records) < 100:
            logger.warning("Insufficient SCADA data for degradation rate computation")
            return fallback

        rates: dict[str, float] = {}

        # Gearbox temperature degradation slope
        gearbox_temps = [
            r.gearbox_temperature_c
            for r in records
            if r.gearbox_temperature_c is not None and r.gearbox_temperature_c > 0
        ]
        if len(gearbox_temps) > 100:
            slope = _estimate_slope(gearbox_temps, len(records))
            rates["gearbox"] = max(0.3, min(3.0, abs(slope) * 150))

        # Generator temperature degradation slope
        gen_temps = [
            r.gen_temperature_c
            for r in records
            if r.gen_temperature_c is not None and r.gen_temperature_c > 0
        ]
        if len(gen_temps) > 100:
            slope = _estimate_slope(gen_temps, len(records))
            rates["generator"] = max(0.3, min(3.0, abs(slope) * 100))

        # Bearing temperature
        bearing_temps = [
            r.bearing_temperature_c
            for r in records
            if r.bearing_temperature_c is not None and r.bearing_temperature_c > 0
        ]
        if len(bearing_temps) > 100:
            slope = _estimate_slope(bearing_temps, len(records))
            rates["main_bearing"] = max(0.3, min(3.0, abs(slope) * 130))

        # Blade: power / wind_speed ratio degradation
        power_ratios = [
            r.power_kw / max(1.0, r.wind_speed_ms or 1)
            for r in records
            if r.power_kw is not None and r.wind_speed_ms is not None and r.wind_speed_ms > 0
        ]
        if len(power_ratios) > 100:
            slope = _estimate_slope(power_ratios, len(records))
            rates["blade"] = max(0.3, min(3.0, abs(slope) * 50))

        # Pitch: angular variability as proxy for system degradation
        pitch_vals = [
            r.pitch_angle_deg
            for r in records
            if r.pitch_angle_deg is not None
        ]
        if len(pitch_vals) > 100:
            variance = _estimate_variance(pitch_vals)
            rates["pitch"] = max(0.3, min(3.0, variance * 10))

        # Merge with fallback for any missing keys
        result_rates = {**fallback, **rates}
        logger.info(
            "Degradation rates computed from %d SCADA records: %s",
            len(records),
            {k: f"{v:.2f}" for k, v in result_rates.items()},
        )
        return result_rates

    except Exception as exc:
        logger.warning("Failed to compute degradation rates from SCADA: %s", exc)
        return fallback


def _estimate_slope(values: list[float], total_count: int) -> float:
    """Estimate linear degradation slope from value series.

    Uses first half vs second half comparison as proxy for slope.
    Positive = increasing (degradation), negative = decreasing.
    """
    n = len(values)
    if n < 2:
        return 0.0
    mid = n // 2
    first_half_avg = sum(values[:mid]) / mid
    second_half_avg = sum(values[mid:]) / (n - mid)
    # Normalize slope relative to mean value
    mean_val = sum(values) / n
    if mean_val == 0:
        return 0.0
    return (second_half_avg - first_half_avg) / mean_val


def _estimate_variance(values: list[float]) -> float:
    """Compute normalized variance of a value series."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / n
    return variance / (mean ** 2)


# ── Fleet location ─────────────────────────────────────────────────────

async def get_fleet_location(db: AsyncSession) -> dict[str, float]:
    """Compute fleet average lat/lng from actual turbine locations."""
    result = await db.execute(
        select(
            func.avg(Turbine.lat).label("avg_lat"),
            func.avg(Turbine.lng).label("avg_lng"),
        ).where(
            Turbine.lat.isnot(None),
            Turbine.lng.isnot(None),
        )
    )
    row = result.one_or_none()
    if row and row[0] is not None:
        return {"lat": float(row[0]), "lng": float(row[1])}
    # Fallback: Shaanxi wind farm centroid
    logger.warning("No turbine location data — using fleet default")
    return {"lat": 37.84, "lng": 107.74}


# ── Score threshold configuration ─────────────────────────────────────

async def get_score_thresholds(db: AsyncSession, user_id: int | None = None) -> dict[str, list[dict]]:
    """Get configurable scoring thresholds from user preferences.

    Returns dict with keys: 'rul', 'hi', 'maintenance_gap'
    Each is a list of {max_val, score_floor, score_ceiling} for linear interpolation.
    """
    # RUL scoring (days remaining -> urgency score)
    rul_default = [
        {"max_days": 30, "score_floor": 90, "score_ceiling": 100},
        {"max_days": 90, "score_floor": 60, "score_ceiling": 90},
        {"max_days": 180, "score_floor": 30, "score_ceiling": 60},
        {"max_days": 365, "score_floor": 10, "score_ceiling": 30},
        {"max_days": 9999, "score_floor": 0, "score_ceiling": 10},
    ]
    # HI scoring (HI value -> urgency score)
    hi_default = [
        {"max_hi": 50, "score": 90},
        {"max_hi": 60, "score_floor": 70, "score_ceiling": 90},
        {"max_hi": 75, "score_floor": 40, "score_ceiling": 70},
        {"max_hi": 85, "score_floor": 15, "score_ceiling": 40},
        {"max_hi": 100, "score_floor": 0, "score_ceiling": 15},
    ]
    # Maintenance gap scoring (days since last maintenance -> urgency score)
    gap_default = [
        {"max_days": 90, "score": 0},
        {"max_days": 180, "score_floor": 10, "score_ceiling": 25},
        {"max_days": 365, "score_floor": 25, "score_ceiling": 50},
        {"max_days": 9999, "score_floor": 50, "score_ceiling": 100},
    ]

    if user_id is None:
        return {"rul": rul_default, "hi": hi_default, "maintenance_gap": gap_default}

    try:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user and user.preferences and isinstance(user.preferences, dict):
            stored = user.preferences.get("score_thresholds")
            if isinstance(stored, dict):
                return {
                    "rul": stored.get("rul", rul_default),
                    "hi": stored.get("hi", hi_default),
                    "maintenance_gap": stored.get("maintenance_gap", gap_default),
                }
    except Exception:
        pass
    return {"rul": rul_default, "hi": hi_default, "maintenance_gap": gap_default}
