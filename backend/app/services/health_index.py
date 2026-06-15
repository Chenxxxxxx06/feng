"""Health Index (HI) calculation service.

Computes turbine health index from multi-source data:
- SCADA performance metrics (power curve deviation, temperature trends)
- Vibration RMS trends
- Blade image damage severity
- Maintenance history (time since last maintenance)

HI is normalized to 0-100, where:
  100-80: Healthy (green)
  79-60: Warning (yellow)
  59-0:  Fault (red)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Weights for each component
WEIGHTS = {
    "performance": 0.35,
    "vibration": 0.25,
    "blade": 0.15,
    "maintenance": 0.15,
    "trend": 0.10,
}


def calculate_turbine_hi(
    scada_data: Optional[list[dict]] = None,
    vibration_rms: Optional[float] = None,
    blade_damage_severity: Optional[str] = None,
    last_maintenance_days: Optional[float] = None,
    current_hi: Optional[float] = None,
) -> dict:
    """Calculate health index for a single turbine.

    Args:
        scada_data: List of SCADA data records
        vibration_rms: Vibration RMS value in mm/s²
        blade_damage_severity: Blade damage level ("none", "minor", "moderate", "severe")
        last_maintenance_days: Days since last maintenance
        current_hi: Current HI value for trend calculation

    Returns:
        Dict with hi_value, status, component_scores, and calculated_at
    """
    scores = {}

    # 1. Performance score (from SCADA)
    if scada_data:
        scores["performance"] = _performance_score(scada_data)
    else:
        scores["performance"] = {"score": 85, "weight": WEIGHTS["performance"]}

    # 2. Vibration score
    if vibration_rms is not None:
        scores["vibration"] = _vibration_score(vibration_rms)
    else:
        scores["vibration"] = {"score": 80, "weight": WEIGHTS["vibration"]}

    # 3. Blade condition score
    if blade_damage_severity:
        scores["blade"] = _blade_score(blade_damage_severity)
    else:
        scores["blade"] = {"score": 90, "weight": WEIGHTS["blade"]}

    # 4. Maintenance score
    if last_maintenance_days is not None:
        scores["maintenance"] = _maintenance_score(last_maintenance_days)
    else:
        scores["maintenance"] = {"score": 85, "weight": WEIGHTS["maintenance"]}

    # 5. Trend score (based on HI degradation rate)
    if current_hi is not None and last_maintenance_days:
        scores["trend"] = _trend_score(current_hi, last_maintenance_days)
    else:
        scores["trend"] = {"score": 80, "weight": WEIGHTS["trend"]}

    # Weighted average
    total_weight = sum(s["weight"] for s in scores.values())
    hi = sum(s["score"] * s["weight"] for s in scores.values()) / total_weight
    hi = max(0, min(100, round(hi, 1)))

    # Determine status
    if hi >= 80:
        status = "normal"
    elif hi >= 60:
        status = "warning"
    else:
        status = "fault"

    return {
        "hi_value": hi,
        "status": status,
        "component_scores": {
            name: {"score": round(s["score"], 1), "weight": s["weight"]}
            for name, s in scores.items()
        },
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }


def _performance_score(scada: list[dict]) -> dict:
    """Score based on SCADA operational data.

    Checks for:
    - Low power at high wind speeds
    - High generator temperatures
    - Abnormal RPM patterns
    """
    if not scada:
        return {"score": 85, "weight": WEIGHTS["performance"]}

    issues = 0
    total = max(len(scada), 1)
    power_values = [abs(r.get("power_kw", 0) or 0) for r in scada]
    normalized_power = bool(power_values) and max(power_values) <= 1.5

    for r in scada:
        wind = r.get("wind_speed_ms", 0) or 0
        power = r.get("power_kw", 0) or 0

        if normalized_power:
            # CARE imports normalized active power as p.u.
            if wind > 10 and power < 0.35:
                issues += 2
            elif wind > 8 and power < 0.25:
                issues += 1
        else:
            # Low power at rated wind (>10 m/s wind but <500 kW)
            if wind > 10 and power < 500:
                issues += 2

        # High generator temperature
        gen_temp = r.get("gen_temperature_c", 80) or 80
        if gen_temp > 95:
            issues += 1

        # High gearbox temperature
        gearbox_temp = r.get("gearbox_temperature_c", 70) or 70
        if gearbox_temp > 85:
            issues += 1

    issue_ratio = issues / (total * 4)
    score = max(40, 100 - issue_ratio * 60)
    return {"score": round(score, 1), "weight": WEIGHTS["performance"]}


def _vibration_score(rms: float) -> dict:
    """Score based on vibration RMS level.

    Typical thresholds:
    - Healthy: < 2.0 mm/s²
    - Warning: 2.0-4.0 mm/s²
    - Fault: > 4.0 mm/s²
    """
    if rms < 2.0:
        score = 90 + (2.0 - rms) / 2.0 * 10
    elif rms < 4.0:
        score = 80 - (rms - 2.0) / 2.0 * 20
    else:
        score = max(30, 60 - (rms - 4.0) * 10)
    return {"score": round(score, 1), "weight": WEIGHTS["vibration"]}


def _blade_score(severity: str) -> dict:
    """Score based on blade inspection results.

    Severity levels:
    - none: No damage
    - minor: Surface scratches, minor erosion
    - moderate: Cracks, significant erosion
    - severe: Structural damage, lightning strikes
    """
    mapping = {
        "none": 95,
        "minor": 82,
        "moderate": 60,
        "severe": 35,
    }
    return {"score": mapping.get(severity, 85), "weight": WEIGHTS["blade"]}


def _maintenance_score(days_since: float) -> dict:
    """Score based on time since last maintenance.

    More recent maintenance results in higher score.
    """
    if days_since < 90:
        score = 95
    elif days_since < 180:
        score = 85
    elif days_since < 365:
        score = 70
    else:
        score = max(40, 55 - (days_since - 365) / 30)
    return {"score": round(score, 1), "weight": WEIGHTS["maintenance"]}


def _trend_score(current_hi: float, days_observed: float) -> dict:
    """Score based on degradation trend.

    Estimates how fast HI is declining and penalizes rapid degradation.
    """
    if days_observed <= 0:
        return {"score": 80, "weight": WEIGHTS["trend"]}

    # Calculate degradation rate (points per day)
    degradation = (100 - current_hi) / days_observed

    if degradation < 0.02:
        score = 90
    elif degradation < 0.05:
        score = 75
    elif degradation < 0.1:
        score = 55
    else:
        score = 35
    return {"score": round(score, 1), "weight": WEIGHTS["trend"]}
