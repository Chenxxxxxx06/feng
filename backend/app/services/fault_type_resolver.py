"""Shared fault-name normalization used by decision and task workflows."""

from __future__ import annotations

from typing import Optional


EN_TO_CN_FAULT: dict[str, str] = {
    "bearing_wear": "轴承磨损",
    "bearing_fault": "轴承磨损",
    "bearing_inner_race_wear": "轴承磨损",
    "bearing_outer_race": "轴承磨损",
    "bearing_ball": "轴承磨损",
    "bearing_cage_failure": "轴承保持架故障",
    "bearing_electrical_corrosion": "轴承电蚀",
    "gearbox_pitting": "齿轮箱点蚀",
    "gearbox_tooth_pitting": "齿轮箱点蚀",
    "gearbox_tooth_wear": "齿轮箱点蚀",
    "gearbox_fault": "齿轮箱点蚀",
    "gearbox_tooth_break": "齿轮断齿",
    "gearbox_oil_leak": "齿轮箱漏油",
    "generator_overheat": "发电机过热",
    "generator_fault": "发电机过热",
    "generator_insulation": "发电机绝缘老化",
    "blade_erosion": "叶片前缘侵蚀",
    "leading_edge_erosion": "叶片前缘侵蚀",
    "blade_leading_edge_erosion": "叶片前缘侵蚀",
    "blade_damage": "叶片裂纹",
    "blade_crack": "叶片裂纹",
    "blade_ice": "叶片结冰",
    "blade_imbalance": "转子不平衡",
    "unbalance": "转子不平衡",
    "pitch_system_fault": "变桨系统故障",
    "main_shaft_misalignment": "轴对中不良",
    "shaft_misalignment": "轴对中不良",
    "misalignment": "轴对中不良",
    "coupling_wear": "联轴器磨损",
    "converter_fault": "变频器故障",
    "electrical_fault": "变频器故障",
    "transformer_overheat": "变压器过热",
    "yaw_failure": "偏航系统故障",
    "yaw_sensor_fault": "风向传感器故障",
    "tower_weld_crack": "塔筒焊缝裂纹",
    "tower_foundation": "基础沉降",
}


def resolve_fault_type(raw: Optional[str]) -> Optional[str]:
    """Normalize a fault code or incident title to the knowledge-base label."""
    if not raw:
        return None
    cleaned = str(raw).strip()
    if not cleaned:
        return None
    normalized = cleaned.lower()
    if normalized in EN_TO_CN_FAULT:
        return EN_TO_CN_FAULT[normalized]
    for code in sorted(EN_TO_CN_FAULT, key=len, reverse=True):
        if code in normalized:
            return EN_TO_CN_FAULT[code]
    for label in sorted(set(EN_TO_CN_FAULT.values()), key=len, reverse=True):
        if label in cleaned:
            return label
    return cleaned
