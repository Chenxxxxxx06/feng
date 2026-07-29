"""Deterministic read-only Agent answerer for maintenance scheduling."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production import ProductionPlan

__all__ = [
    "DOMAIN_READ_PLAYBOOKS",
    "answer_domain_read_task",
    "override_playbook_for_domain",
]


DOMAIN_READ_PLAYBOOKS = {"production.query_plan": "/workorder"}


def override_playbook_for_domain(
    message: str, playbook_id: Optional[str]
) -> Optional[str]:
    """Keep the shared dispatch hook without overriding unrelated workflows."""
    return playbook_id


def _fmt_money(value: Optional[float]) -> str:
    if not value:
        return "¥0"
    if abs(value) >= 10000:
        return f"¥{value / 10000:.1f}万"
    return f"¥{value:,.0f}"


async def _answer_production_plan(
    db: AsyncSession, message: str
) -> dict[str, Any]:
    plans = (
        await db.execute(
            select(ProductionPlan).order_by(ProductionPlan.created_at.desc()).limit(5)
        )
    ).scalars().all()
    if not plans:
        return {
            "status": "unsupported",
            "task_type": "READ",
            "confidence": 0.3,
            "error_code": "domain_read_unavailable",
            "error_message": "尚无维护方案，可在维修工单页生成。",
        }

    active = (
        next((p for p in plans if p.status == "committed"), None)
        or next((p for p in plans if p.baseline_plan_id), None)
        or plans[0]
    )
    objective = active.objective_json or {}
    schedule = active.schedule_json or []
    lines = [
        f"当前维护排程 {active.plan_no}（{active.status}），"
        f"已安排 {len(schedule)} 项检修任务。"
    ]
    lost = objective.get("total_lost_kwh")
    baseline = objective.get("baseline_lost_kwh")
    improvement = objective.get("improvement_pct")
    if lost is not None:
        text = f"预计检修损失电量 {lost:,.0f} kWh"
        if baseline:
            text += f"（基线 {baseline:,.0f} kWh"
            if improvement:
                text += f"，改善 {improvement:.1f}%"
            text += "）"
        lines.append(text)
    if objective.get("total_revenue_loss"):
        lines.append(f"折合收益损失约 {_fmt_money(objective['total_revenue_loss'])}。")
    for item in schedule[:4]:
        lines.append(
            f"· 工单 #{item.get('work_order_id')} → {str(item.get('slot_start'))[:16]}"
            f"（预计损失 {item.get('est_lost_kwh', 0):,.0f} kWh）"
        )
    lines.append("执行资源与安全条件须在工单审核后确认。")

    return {
        "status": "success",
        "task_type": "READ",
        "workflow": "production.query_plan",
        "confidence": 0.85,
        "answer": "\n".join(lines),
        "data": {
            "plan_no": active.plan_no,
            "status": active.status,
            "objective": objective,
            "task_count": len(schedule),
            "schedule_preview": schedule[:10],
        },
        "display": {"navigate_to": "/workorder"},
    }


async def answer_domain_read_task(
    db: AsyncSession,
    *,
    playbook_id: str,
    message: str,
) -> Optional[dict[str, Any]]:
    if playbook_id != "production.query_plan":
        return None
    try:
        return await _answer_production_plan(db, message)
    except Exception as exc:
        return {
            "status": "unsupported",
            "task_type": "READ",
            "confidence": 0.3,
            "error_code": "domain_read_unavailable",
            "error_message": f"维护排程暂时不可用：{type(exc).__name__}",
        }
