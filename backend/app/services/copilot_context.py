"""Structured context orchestration for Copilot conversations.

The Copilot should not query arbitrary data. This module exposes a small
allowlist of read-only context tools and builds a compact context bundle for
the current session turn. User-selected contexts are the hard boundary; the
LLM planner can only choose tools inside that boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentTrace,
    DecisionPlan,
    EvidenceNode,
    Fault,
    FaultKnowledgeNode,
    Incident,
    RULPrediction,
    SCADARecord,
    Turbine,
    VibrationData,
    WorkOrder,
)

DEFAULT_CONTEXT = "dashboard"
MAX_TOOL_CALLS = 6


@dataclass(frozen=True)
class ContextSpec:
    id: str
    label: str
    description: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    label: str
    description: str
    contexts: tuple[str, ...]


CONTEXT_CATALOG: dict[str, ContextSpec] = {
    "dashboard": ContextSpec("dashboard", "风场监控", "风机总览、区域状态、风机运行概况"),
    "diagnosis": ContextSpec("diagnosis", "故障诊断", "活跃故障、疑似故障、振动与SCADA异常"),
    "incident": ContextSpec("incident", "事件指挥", "当前事件阶段、证据、决策方案与执行闭环"),
    "prediction": ContextSpec("prediction", "预测决策", "RUL预测、维护优先级、预测性维修计划"),
    "workorder": ContextSpec("workorder", "维修工单", "工单状态、派工、维修闭环进展"),
    "knowledge": ContextSpec("knowledge", "知识库", "故障根因、处理方案、备件与案例知识"),
    "current_turbine": ContextSpec("current_turbine", "当前风机", "页面当前选中风机的运行、故障和预测数据"),
}

TOOL_CATALOG: dict[str, ToolSpec] = {
    "fleet_overview": ToolSpec("fleet_overview", "风场总览", "读取全场风机、预警、故障和待处理工单统计", ("dashboard", "diagnosis")),
    "region_status_summary": ToolSpec("region_status_summary", "区域状态", "按区域汇总风机状态分布", ("dashboard",)),
    "turbine_status_list": ToolSpec("turbine_status_list", "风机状态列表", "读取风机名称、区域、状态和健康指数", ("dashboard", "diagnosis", "prediction", "workorder")),
    "current_turbine_status": ToolSpec("current_turbine_status", "当前风机状态", "读取当前风机基础信息和健康指数", ("current_turbine", "diagnosis", "prediction", "workorder")),
    "incident_summary": ToolSpec("incident_summary", "当前事件摘要", "读取当前事件阶段、验证状态、证据和决策数量", ("incident",)),
    "recent_faults": ToolSpec("recent_faults", "故障记录", "读取近期故障、置信度、状态和详情", ("diagnosis", "current_turbine")),
    "latest_scada": ToolSpec("latest_scada", "SCADA快照", "读取当前风机最新SCADA运行参数", ("dashboard", "diagnosis", "current_turbine")),
    "vibration_summary": ToolSpec("vibration_summary", "振动摘要", "读取当前风机近期振动RMS和主频峰值", ("diagnosis", "current_turbine")),
    "rul_summary": ToolSpec("rul_summary", "RUL摘要", "读取剩余寿命预测和置信区间", ("prediction", "current_turbine")),
    "maintenance_plan": ToolSpec("maintenance_plan", "维护优先级", "读取按RUL排序的维护风险项", ("prediction", "workorder")),
    "work_orders": ToolSpec("work_orders", "工单摘要", "读取工单状态、优先级和近期工单", ("workorder", "diagnosis", "current_turbine")),
    "knowledge_lookup": ToolSpec("knowledge_lookup", "知识库匹配", "按问题和故障类型检索根因、方案和备件知识", ("knowledge", "diagnosis")),
}


def _dt(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _last_user_text(messages: list[dict]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def _wants(text: str, *keywords: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _normalize_contexts(selected_contexts: Optional[list[str]], page_context: dict) -> tuple[list[str], bool]:
    valid = [item for item in (selected_contexts or []) if item in CONTEXT_CATALOG]
    return list(dict.fromkeys(valid)), False


def get_allowed_tool_specs(selected_contexts: Optional[list[str]], page_context: Optional[dict] = None) -> list[dict]:
    """Return planner-safe tool metadata for the selected context boundary."""
    contexts, _ = _normalize_contexts(selected_contexts, page_context or {})
    selected = set(contexts)
    specs = []
    for tool in TOOL_CATALOG.values():
        if selected.intersection(tool.contexts):
            specs.append({
                "name": tool.name,
                "label": tool.label,
                "description": tool.description,
                "contexts": [CONTEXT_CATALOG[c].label for c in tool.contexts if c in selected],
            })
    return specs


def _source_labels_for_tool(tool_name: str, selected_contexts: list[str]) -> list[str]:
    tool = TOOL_CATALOG.get(tool_name)
    if not tool:
        return []
    selected = set(selected_contexts)
    return [CONTEXT_CATALOG[c].label for c in tool.contexts if c in selected and c in CONTEXT_CATALOG]


def _context_sources(selected_contexts: list[str], tool_names: list[str]) -> list[dict]:
    used_contexts: dict[str, set[str]] = {context_id: set() for context_id in selected_contexts}
    for tool_name in tool_names:
        tool = TOOL_CATALOG.get(tool_name)
        if not tool:
            continue
        for context_id in tool.contexts:
            if context_id in used_contexts:
                used_contexts[context_id].add(tool.label)
    return [
        {
            "context": context_id,
            "label": CONTEXT_CATALOG[context_id].label,
            "tools": sorted(labels),
        }
        for context_id, labels in used_contexts.items()
        if labels
    ]


async def _resolve_turbine(db: AsyncSession, page_context: dict, question: str) -> Optional[Turbine]:
    raw_id = (
        page_context.get("turbine_id")
        or page_context.get("selected_turbine_id")
        or page_context.get("selectedTurbineId")
    )
    if raw_id:
        result = await db.execute(select(Turbine).where(Turbine.id == int(raw_id)))
        found = result.scalar_one_or_none()
        if found:
            return found

    raw_name = page_context.get("turbine_name") or page_context.get("selected_turbine_name")
    if raw_name:
        result = await db.execute(select(Turbine).where(Turbine.name == str(raw_name)))
        found = result.scalar_one_or_none()
        if found:
            return found

    if question:
        result = await db.execute(select(Turbine).where(Turbine.name.is_not(None)))
        for turbine in result.scalars().all():
            if turbine.name and turbine.name in question:
                return turbine
    return None


async def _overview(db: AsyncSession) -> dict:
    total = (await db.execute(select(func.count(Turbine.id)))).scalar() or 0
    warning = (await db.execute(select(func.count(Turbine.id)).where(Turbine.status == "warning"))).scalar() or 0
    fault = (await db.execute(select(func.count(Turbine.id)).where(Turbine.status == "fault"))).scalar() or 0
    active_faults = (await db.execute(select(func.count(Fault.id)).where(Fault.status != "closed"))).scalar() or 0
    open_work_orders = (await db.execute(select(func.count(WorkOrder.id)).where(~WorkOrder.status.in_(["completed", "closed", "cancelled"])))).scalar() or 0
    return {
        "total_turbines": total,
        "warning_turbines": warning,
        "fault_turbines": fault,
        "active_faults": active_faults,
        "open_work_orders": open_work_orders,
    }


async def _incident_summary(db: AsyncSession, page_context: dict) -> Optional[dict]:
    incident = None
    raw_id = page_context.get("incident_id")
    raw_ref = page_context.get("incident_ref")
    if raw_id:
        incident = (
            await db.execute(select(Incident).where(Incident.id == int(raw_id)))
        ).scalar_one_or_none()
    if incident is None and raw_ref:
        incident = (
            await db.execute(select(Incident).where(Incident.incident_id == str(raw_ref)))
        ).scalar_one_or_none()
    if incident is None:
        turbine_id = page_context.get("turbine_id")
        stmt = select(Incident).order_by(Incident.opened_at.desc()).limit(1)
        if turbine_id:
            stmt = stmt.where(Incident.turbine_id == int(turbine_id))
        incident = (await db.execute(stmt)).scalar_one_or_none()
    if incident is None:
        return None

    evidence_count = (
        await db.execute(
            select(func.count(EvidenceNode.id)).where(EvidenceNode.incident_id == incident.id)
        )
    ).scalar() or 0
    decision_plan_count = (
        await db.execute(
            select(func.count(DecisionPlan.id)).where(DecisionPlan.incident_id == incident.id)
        )
    ).scalar() or 0
    trace_count = (
        await db.execute(
            select(func.count(AgentTrace.id)).where(AgentTrace.incident_id == incident.id)
        )
    ).scalar() or 0
    return {
        "id": incident.id,
        "incident_id": incident.incident_id,
        "turbine_id": incident.turbine_id,
        "title": incident.title,
        "severity": incident.severity,
        "stage": incident.stage,
        "status": incident.status,
        "verification_status": incident.verification_status,
        "summary": incident.summary,
        "resolution": incident.resolution,
        "evidence_count": evidence_count,
        "decision_plan_count": decision_plan_count,
        "agent_trace_count": trace_count,
        "opened_at": _dt(incident.opened_at),
        "updated_at": _dt(incident.updated_at),
    }


async def _region_status_summary(db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(
            select(Turbine.region, Turbine.status, func.count(Turbine.id))
            .group_by(Turbine.region, Turbine.status)
            .order_by(Turbine.region, Turbine.status)
        )
    ).all()
    by_region: dict[str, dict[str, Any]] = {}
    for region, status, count in rows:
        key = region or "未分组"
        item = by_region.setdefault(key, {"region": key, "total": 0, "statuses": {}})
        item["total"] += int(count or 0)
        item["statuses"][status or "unknown"] = int(count or 0)
    return list(by_region.values())


def _turbine_status(turbine: Turbine) -> dict:
    return {
        "id": turbine.id,
        "name": turbine.name,
        "region": turbine.region,
        "status": turbine.status,
        "hi_value": turbine.hi_value,
        "model": turbine.model,
        "power_mw": turbine.power_mw,
        "last_maintenance": _dt(turbine.last_maintenance),
    }


async def _turbine_status_list(db: AsyncSession, limit: int = 24) -> list[dict]:
    rows = (
        await db.execute(
            select(Turbine)
            .order_by(Turbine.region.asc(), Turbine.status.desc(), Turbine.hi_value.asc())
            .limit(limit)
        )
    ).scalars().all()
    return [_turbine_status(row) for row in rows]


async def _recent_faults(db: AsyncSession, turbine_id: Optional[int] = None, limit: int = 8) -> list[dict]:
    stmt = select(Fault, Turbine.name, Turbine.region).join(Turbine, Turbine.id == Fault.turbine_id)
    if turbine_id:
        stmt = stmt.where(Fault.turbine_id == turbine_id)
    stmt = stmt.order_by(Fault.detected_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).all()
    return [
        {
            "id": fault.id,
            "turbine_id": fault.turbine_id,
            "turbine_name": turbine_name,
            "turbine_region": turbine_region,
            "fault_type": fault.fault_type,
            "confidence": fault.confidence,
            "status": fault.status,
            "detected_at": _dt(fault.detected_at),
            "details": fault.details,
        }
        for fault, turbine_name, turbine_region in rows
    ]


async def _work_orders(db: AsyncSession, turbine_id: Optional[int] = None, limit: int = 8) -> dict:
    count_stmt = select(WorkOrder.status, WorkOrder.priority, func.count(WorkOrder.id)).group_by(WorkOrder.status, WorkOrder.priority)
    recent_stmt = select(WorkOrder, Turbine.name).join(Turbine, Turbine.id == WorkOrder.turbine_id)
    if turbine_id:
        count_stmt = count_stmt.where(WorkOrder.turbine_id == turbine_id)
        recent_stmt = recent_stmt.where(WorkOrder.turbine_id == turbine_id)
    count_rows = (await db.execute(count_stmt)).all()
    recent_rows = (await db.execute(recent_stmt.order_by(WorkOrder.created_at.desc()).limit(limit))).all()
    return {
        "summary": [
            {"status": status, "priority": priority, "count": int(count or 0)}
            for status, priority, count in count_rows
        ],
        "recent": [
            {
                "id": order.id,
                "turbine_id": order.turbine_id,
                "turbine_name": turbine_name,
                "title": order.title,
                "status": order.status,
                "priority": order.priority,
                "fault_type": order.fault_type,
                "assignee": order.assignee,
                "due_date": _dt(order.due_date),
                "created_at": _dt(order.created_at),
            }
            for order, turbine_name in recent_rows
        ],
    }


async def _latest_scada(db: AsyncSession, turbine_id: int) -> Optional[dict]:
    record = (
        await db.execute(
            select(SCADARecord)
            .where(SCADARecord.turbine_id == turbine_id)
            .order_by(SCADARecord.timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not record:
        return None
    return {
        "timestamp": _dt(record.timestamp),
        "power_kw": record.power_kw,
        "wind_speed_ms": record.wind_speed_ms,
        "rotor_rpm": record.rotor_rpm,
        "gen_temperature_c": record.gen_temperature_c,
        "gearbox_temperature_c": record.gearbox_temperature_c,
        "bearing_temperature_c": record.bearing_temperature_c,
        "pitch_angle_deg": record.pitch_angle_deg,
        "grid_frequency_hz": record.grid_frequency_hz,
    }


async def _vibration_summary(db: AsyncSession, turbine_id: int) -> list[dict]:
    rows = (
        await db.execute(
            select(VibrationData)
            .where(VibrationData.turbine_id == turbine_id)
            .order_by(VibrationData.timestamp.desc())
            .limit(8)
        )
    ).scalars().all()
    return [
        {
            "timestamp": _dt(row.timestamp),
            "component": row.component,
            "rms": row.rms,
            "peak_freq_hz": row.peak_freq_hz,
        }
        for row in rows
    ]


async def _rul_summary(db: AsyncSession, turbine_id: Optional[int] = None, limit: int = 8) -> list[dict]:
    stmt = select(RULPrediction, Turbine.name).join(Turbine, Turbine.id == RULPrediction.turbine_id)
    if turbine_id:
        stmt = stmt.where(RULPrediction.turbine_id == turbine_id)
    rows = (
        await db.execute(
            stmt.order_by(RULPrediction.remaining_life_days.asc(), RULPrediction.predicted_at.desc()).limit(limit)
        )
    ).all()
    return [
        {
            "turbine_id": row.turbine_id,
            "turbine_name": turbine_name,
            "component": row.component,
            "remaining_life_days": row.remaining_life_days,
            "confidence_lower": row.confidence_lower,
            "confidence_upper": row.confidence_upper,
            "predicted_at": _dt(row.predicted_at),
        }
        for row, turbine_name in rows
    ]


async def _maintenance_plan_summary(db: AsyncSession, limit: int = 8) -> dict:
    rows = (
        await db.execute(
            select(RULPrediction, Turbine)
            .join(Turbine, Turbine.id == RULPrediction.turbine_id)
            .order_by(RULPrediction.remaining_life_days.asc(), Turbine.hi_value.asc())
            .limit(limit)
        )
    ).all()
    items = []
    for prediction, turbine in rows:
        priority = "urgent" if prediction.remaining_life_days <= 30 else "high" if prediction.remaining_life_days <= 90 else "medium"
        items.append({
            "turbine_id": turbine.id,
            "turbine_name": turbine.name,
            "region": turbine.region,
            "status": turbine.status,
            "hi_value": turbine.hi_value,
            "component": prediction.component,
            "remaining_life_days": prediction.remaining_life_days,
            "priority": priority,
        })
    return {
        "items": items,
        "urgent_count": sum(1 for item in items if item["priority"] == "urgent"),
        "high_count": sum(1 for item in items if item["priority"] == "high"),
    }


def _knowledge_terms(question: str, faults: list[dict]) -> list[str]:
    terms = [fault.get("fault_type") for fault in faults if fault.get("fault_type")]
    for token in ("轴承", "齿轮箱", "发电机", "叶片", "变桨", "偏航", "温度", "振动", "unbalance", "erosion"):
        if token.lower() in question.lower():
            terms.append(token)
    return list(dict.fromkeys(str(term) for term in terms if term))


async def _knowledge_lookup(db: AsyncSession, question: str, faults: list[dict], limit: int = 5) -> list[dict]:
    terms = _knowledge_terms(question, faults)
    stmt = select(FaultKnowledgeNode)
    if terms:
        predicates = []
        for term in terms[:5]:
            pattern = f"%{term}%"
            predicates.extend([
                FaultKnowledgeNode.fault_type.ilike(pattern),
                FaultKnowledgeNode.category.ilike(pattern),
            ])
        stmt = stmt.where(or_(*predicates))
    rows = (await db.execute(stmt.order_by(FaultKnowledgeNode.id.desc()).limit(limit))).scalars().all()
    return [
        {
            "fault_type": row.fault_type,
            "category": row.category,
            "severity": row.severity,
            "symptoms": row.symptoms or [],
            "root_causes": row.root_causes or [],
            "solutions": row.solutions or [],
            "spare_parts": row.spare_parts or [],
            "verified": row.verified,
        }
        for row in rows
    ]


def plan_tool_names_rule_based(
    question: str,
    page_context: dict,
    selected_contexts: Optional[list[str]],
) -> list[str]:
    """Rule fallback used when the LLM planner is unavailable."""
    contexts, _ = _normalize_contexts(selected_contexts, page_context)
    selected = set(contexts)
    planned: list[str] = []

    def add(name: str) -> None:
        if name in planned:
            return
        tool = TOOL_CATALOG.get(name)
        if tool and selected.intersection(tool.contexts):
            planned.append(name)

    if "dashboard" in selected:
        add("fleet_overview")
        add("region_status_summary")
        if _wants(question, "风机", "状态", "健康", "hi", "列表", "整体"):
            add("turbine_status_list")
    if "diagnosis" in selected:
        add("fleet_overview")
        add("recent_faults")
        if _wants(question, "振动", "rms", "主频", "波形", "vibration"):
            add("vibration_summary")
        if _wants(question, "scada", "功率", "风速", "温度", "转速", "状态"):
            add("latest_scada")
    if "incident" in selected:
        add("incident_summary")
    if "prediction" in selected:
        add("rul_summary")
        add("maintenance_plan")
    if "workorder" in selected:
        add("work_orders")
    if "knowledge" in selected:
        add("knowledge_lookup")
    if "current_turbine" in selected:
        add("current_turbine_status")
        if _wants(question, "scada", "功率", "风速", "温度", "转速", "状态"):
            add("latest_scada")
        if _wants(question, "故障", "异常", "告警", "诊断", "fault"):
            add("recent_faults")
        if _wants(question, "rul", "寿命", "剩余", "预测"):
            add("rul_summary")

    if not planned:
        allowed = get_allowed_tool_specs(contexts, page_context)
        planned = [tool["name"] for tool in allowed[:2]]
    return planned[:MAX_TOOL_CALLS]


async def _execute_tool(
    db: AsyncSession,
    tool_name: str,
    *,
    turbine: Optional[Turbine],
    question: str,
    recent_faults_cache: list[dict],
    page_context: dict,
) -> Any:
    if tool_name == "fleet_overview":
        return await _overview(db)
    if tool_name == "region_status_summary":
        return await _region_status_summary(db)
    if tool_name == "turbine_status_list":
        return await _turbine_status_list(db)
    if tool_name == "current_turbine_status":
        return _turbine_status(turbine) if turbine else None
    if tool_name == "incident_summary":
        return await _incident_summary(db, page_context)
    if tool_name == "recent_faults":
        return recent_faults_cache or await _recent_faults(db, turbine.id if turbine else None)
    if tool_name == "latest_scada":
        return await _latest_scada(db, turbine.id) if turbine else None
    if tool_name == "vibration_summary":
        return await _vibration_summary(db, turbine.id) if turbine else []
    if tool_name == "rul_summary":
        return await _rul_summary(db, turbine.id if turbine else None)
    if tool_name == "maintenance_plan":
        return await _maintenance_plan_summary(db)
    if tool_name == "work_orders":
        return await _work_orders(db, turbine.id if turbine else None)
    if tool_name == "knowledge_lookup":
        return await _knowledge_lookup(db, question, recent_faults_cache)
    return None


async def build_copilot_context_bundle(
    db: AsyncSession,
    *,
    session_id: Optional[str],
    messages: list[dict],
    page_context: dict,
    selected_contexts: Optional[list[str]] = None,
    requested_tools: Optional[list[str]] = None,
) -> dict:
    question = _last_user_text(messages)
    page_type = str(page_context.get("page_type") or "unknown")
    contexts, defaulted = _normalize_contexts(selected_contexts, page_context)
    selected = set(contexts)
    turbine = await _resolve_turbine(db, page_context, question)

    if requested_tools:
        candidate_tools = []
        for name in requested_tools:
            tool = TOOL_CATALOG.get(name)
            if tool and selected.intersection(tool.contexts) and name not in candidate_tools:
                candidate_tools.append(name)
    else:
        candidate_tools = plan_tool_names_rule_based(question, page_context, contexts)
    candidate_tools = candidate_tools[:MAX_TOOL_CALLS]

    recent_faults_cache: list[dict] = []
    if "recent_faults" in candidate_tools or "knowledge_lookup" in candidate_tools:
        recent_faults_cache = await _recent_faults(db, turbine.id if turbine else None)

    tools: list[dict] = []
    for tool_name in candidate_tools:
        spec = TOOL_CATALOG[tool_name]
        result = await _execute_tool(
            db,
            tool_name,
            turbine=turbine,
            question=question,
            recent_faults_cache=recent_faults_cache,
            page_context=page_context,
        )
        tools.append({
            "name": tool_name,
            "label": spec.label,
            "sources": _source_labels_for_tool(tool_name, contexts),
            "result": result,
        })

    return {
        "version": "context-v2",
        "session_id": session_id,
        "selected_contexts": contexts,
        "selected_contexts_defaulted": defaulted,
        "context_sources": _context_sources(contexts, [tool["name"] for tool in tools]),
        "page": {
            "page_type": page_type,
            "url": page_context.get("url"),
            "selected_turbine_id": turbine.id if turbine else None,
            "selected_turbine_name": turbine.name if turbine else None,
        },
        "question": question[:500],
        "tool_policy": {
            "mode": "user_scoped_allowlist",
            "allowed_contexts": [CONTEXT_CATALOG[context_id].label for context_id in contexts],
            "allowed_tools": [tool["name"] for tool in tools],
            "note": "AI工具选择只能发生在用户已选择的数据范围内。",
        },
        "tools": tools,
    }
