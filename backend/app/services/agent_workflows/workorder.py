"""Work-order workflow helpers for Agent actions."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Fault, Turbine

FAULT_KEYWORDS = (
    "齿轮箱点蚀",
    "齿轮箱过热",
    "齿轮箱漏油",
    "齿轮断齿",
    "轴承磨损",
    "轴承异常",
    "轴承保持架故障",
    "轴承电蚀",
    "发电机过热",
    "发电机绝缘老化",
    "变频器故障",
    "变压器过热",
    "转子不平衡",
    "叶片前缘侵蚀",
    "叶片裂纹",
    "叶片结冰",
    "偏航系统故障",
    "风向传感器故障",
    "振动异常",
    "SCADA异常",
)


def extract_fault_keyword(message: str) -> Optional[str]:
    for keyword in FAULT_KEYWORDS:
        if keyword in message:
            return keyword
    return None


def extract_priority_hint(message: str) -> Optional[str]:
    if any(token in message for token in ("紧急", "urgent", "立即", "马上")):
        return "urgent"
    if any(token in message for token in ("高优先级", "高优", "严重", "high")):
        return "high"
    if any(token in message for token in ("低优先级", "低优", "low")):
        return "low"
    if any(token in message for token in ("中优先级", "中优", "medium")):
        return "medium"
    return None


async def query_turbine_fault_context(db: AsyncSession, turbine_id: int, *, limit: int = 5) -> list[Fault]:
    result = await db.execute(
        select(Fault)
        .where(Fault.turbine_id == turbine_id)
        .order_by(Fault.detected_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _priority_from_context(turbine: Turbine, faults: list[Fault]) -> str:
    active_faults = [item for item in faults if item.status in ("open", "active", "pending")]
    max_confidence = max((float(item.confidence or 0) for item in active_faults), default=0.0)
    if turbine.status == "fault" or max_confidence >= 0.9:
        return "urgent"
    if turbine.status == "warning" or max_confidence >= 0.8:
        return "high"
    if max_confidence >= 0.6 or float(turbine.hi_value or 100) < 80:
        return "medium"
    return "medium"


def _primary_fault(message: str, faults: list[Fault]) -> Optional[Fault]:
    keyword = extract_fault_keyword(message)
    if keyword:
        for fault in faults:
            if keyword in (fault.fault_type or ""):
                return fault
    active = [item for item in faults if item.status in ("open", "active", "pending")]
    if active:
        return max(active, key=lambda item: float(item.confidence or 0))
    return faults[0] if faults else None


def fault_context_state(faults: list[Fault]) -> dict[str, Any]:
    items = [
        {
            "id": fault.id,
            "fault_type": fault.fault_type,
            "confidence": fault.confidence,
            "status": fault.status,
            "detected_at": fault.detected_at.isoformat() if fault.detected_at else None,
        }
        for fault in faults
    ]
    return {
        "total": len(items),
        "active": sum(1 for item in items if item["status"] in ("open", "active", "pending")),
        "latest": items[0] if items else None,
        "items": items,
    }


def draft_create_workorder_fields(
    *,
    turbine: Turbine,
    faults: list[Fault],
    message: str,
    assignee_name: str | None,
    assignee_id: int | None,
    assignee_email: str | None,
) -> dict[str, Any]:
    primary_fault = _primary_fault(message, faults)
    fault_keyword = extract_fault_keyword(message)
    fault_type = fault_keyword or (primary_fault.fault_type if primary_fault else "待诊断")
    priority = extract_priority_hint(message) or _priority_from_context(turbine, faults)
    title = f"{turbine.name} {fault_type}维修工单" if fault_type != "待诊断" else f"{turbine.name} 维修工单"

    context_lines = [
        f"用户指令：{message}",
        f"风机：{turbine.name}，区域：{turbine.region or '-'}，状态：{turbine.status}，HI健康指数：{float(turbine.hi_value or 0):.1f}",
    ]
    if primary_fault:
        context_lines.append(
            f"参考故障：{primary_fault.fault_type}，置信度：{float(primary_fault.confidence or 0):.0%}，状态：{primary_fault.status}"
        )
    else:
        context_lines.append("参考故障：当前未查到明确活跃故障，先按待诊断维修任务记录。")

    return {
        "turbine_id": turbine.id,
        "turbine_name": turbine.name,
        "title": title,
        "description": "\n".join(context_lines),
        "status": "assigned" if assignee_id else "pending",
        "priority": priority,
        "fault_type": fault_type,
        "fault_id": primary_fault.id if primary_fault else None,
        "assignee": assignee_name,
        "assignee_id": assignee_id,
        "assignee_email": assignee_email,
    }
