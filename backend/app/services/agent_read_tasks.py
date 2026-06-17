"""Deterministic read-only Agent tasks.

This module is the read-side counterpart of the Agent Action Gateway. It uses
the Agent data tools directly and never calls business page code or performs
database mutations.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Fault, RULPrediction, Turbine, User
from app.services.agent_data_tools import (
    ACTIVE_FAULT_STATUSES,
    query_fleet_overview,
    query_knowledge_context,
    query_maintenance_plan_context,
    query_rul_context,
    query_settings_context,
    query_turbine_detail_context,
    query_vibration_context,
    query_workorder_context,
)
from app.services.agent_entities import extract_turbine_ref, resolve_turbine_by_ref
from app.services.agent_workflows.workorder import extract_fault_keyword


WORKORDER_STATUS_ALIASES = {
    "待处理": "pending",
    "待分配": "pending",
    "已分配": "assigned",
    "处理中": "in_progress",
    "待复核": "review",
    "复核": "review",
    "已完成": "completed",
    "完成": "completed",
    "已关闭": "closed",
    "关闭": "closed",
    "已取消": "cancelled",
    "取消": "cancelled",
}

PRIORITY_ALIASES = {
    "紧急": "urgent",
    "高优先级": "high",
    "高优": "high",
    "中优先级": "medium",
    "中优": "medium",
    "低优先级": "low",
    "低优": "low",
}


def _looks_like_turbine_fault_query(message: str) -> bool:
    if not extract_turbine_ref(message):
        return False
    return any(token in message for token in ("故障", "异常", "预警", "健康", "问题"))


def _looks_like_faulty_turbines_query(message: str) -> bool:
    if extract_turbine_ref(message):
        return False
    return (
        "风机" in message
        and any(token in message for token in ("故障", "异常", "预警", "问题"))
        and any(token in message for token in ("哪些", "哪个", "有", "列表", "列出", "所有", "多少"))
    )


def _extract_workorder_ref(message: str) -> str | None:
    match = re.search(r"(?:WO[-_\s]*)?(\d{1,8})\s*(?:号)?工单", message, flags=re.IGNORECASE)
    if match:
        return f"WO-{int(match.group(1)):04d}"
    match = re.search(r"\bWO[-_\s]*(\d{1,8})\b", message, flags=re.IGNORECASE)
    if match:
        return f"WO-{int(match.group(1)):04d}"
    return None


def _extract_workorder_status(message: str) -> str | None:
    lowered = message.lower()
    for alias, status in WORKORDER_STATUS_ALIASES.items():
        if alias in message:
            return status
    for status in ("pending", "assigned", "in_progress", "review", "completed", "closed", "cancelled"):
        if status in lowered:
            return status
    return None


def _extract_priority(message: str) -> str | None:
    lowered = message.lower()
    for alias, priority in PRIORITY_ALIASES.items():
        if alias in message:
            return priority
    for priority in ("urgent", "high", "medium", "low"):
        if priority in lowered:
            return priority
    return None


def _component_hint(message: str) -> str | None:
    lowered = message.lower()
    mapping = {
        "齿轮箱": "gearbox",
        "发电机": "generator",
        "轴承": "bearing",
        "主轴承": "bearing",
        "叶片": "blade",
        "变桨": "pitch",
        "偏航": "yaw",
        "gearbox": "gearbox",
        "generator": "generator",
        "bearing": "bearing",
        "blade": "blade",
        "pitch": "pitch",
        "yaw": "yaw",
    }
    for token, component in mapping.items():
        if token.lower() in lowered:
            return component
    return None


async def _resolve_optional_turbine(db: AsyncSession, message: str) -> tuple[Turbine | None, dict[str, Any] | None]:
    turbine_ref = extract_turbine_ref(message)
    if not turbine_ref:
        return None, None
    resolution = await resolve_turbine_by_ref(db, turbine_ref)
    if resolution.entity:
        return resolution.entity, None
    if resolution.candidates:
        names = "、".join(item.name for item in resolution.candidates)
        return None, {
            "status": "needs_clarification",
            "task_type": "READ",
            "confidence": 0.66,
            "missing_slots": ["turbine_ref"],
            "clarification_question": f"找到多个相近风机：{names}。请明确风机编号。",
        }
    return None, {
        "status": "error",
        "task_type": "READ",
        "confidence": 0.78,
        "error_code": "turbine_not_found",
        "error_message": f"未找到风机 {turbine_ref}。",
    }


def _min_rul_text(predictions: list[dict[str, Any]]) -> str:
    if not predictions:
        return "-"
    values = [float(item.get("remaining_life_days") or 0) for item in predictions if item.get("remaining_life_days") is not None]
    return f"{round(min(values), 1)}天" if values else "-"


def _format_fault_answer(context: dict[str, Any]) -> str:
    turbine = context.get("turbine") or {}
    fault_context = context.get("fault_context") or {}
    workorders = context.get("workorders") or []
    rul_predictions = context.get("rul_predictions") or []
    latest = fault_context.get("latest") or {}
    active_count = int(fault_context.get("active") or 0)
    total_count = int(fault_context.get("total") or 0)
    name = turbine.get("name") or "-"
    status = turbine.get("status") or "-"
    hi_value = turbine.get("hi_value")
    min_rul = min((float(item.get("remaining_life_days") or 0) for item in rul_predictions), default=None)
    page_level_fault = status == "fault" or (isinstance(hi_value, (int, float)) and float(hi_value) < 60)
    page_level_warning = status == "warning" or (isinstance(min_rul, (int, float)) and min_rul <= 30)

    lines: list[str] = [f"**{name} 故障状态查询**"]
    if active_count > 0:
        confidence = latest.get("confidence")
        confidence_text = f"，置信度 {round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else ""
        lines.append(f"结论：当前存在 {active_count} 条活跃故障。")
        lines.append(f"最新故障：{latest.get('fault_type') or '-'}{confidence_text}。")
    elif page_level_fault:
        lines.append("结论：未查询到人工/数据库登记故障记录，但该风机当前处于故障态。")
        lines.append("说明：故障诊断页会基于 CARE 数据集的风机状态、HI 与运行窗口生成页面级故障记录。")
    elif page_level_warning:
        lines.append("结论：未查询到人工/数据库登记故障记录，但该风机存在预警或短RUL风险。")
    elif total_count > 0:
        lines.append("结论：当前没有活跃故障，但存在历史故障记录。")
    else:
        lines.append("结论：当前未查询到故障记录。")

    lines.append(f"风机状态：{status}；HI健康指数：{hi_value if hi_value is not None else '-'}。")

    active_workorders = [
        item for item in workorders
        if item and item.get("status") not in {"completed", "closed", "cancelled"}
    ]
    if active_workorders:
        labels = "、".join(f"{item.get('ref') or item.get('id')}({item.get('status')})" for item in active_workorders[:5])
        lines.append(f"关联未闭环工单：{labels}。")
    elif workorders:
        lines.append("关联工单：暂无未闭环工单。")

    if rul_predictions:
        lines.append(f"最短RUL预测：{_min_rul_text(rul_predictions)}。")

    return "\n".join(lines)


def _format_fleet_answer(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    turbines = data.get("turbines") or []
    status_counts = summary.get("status_counts") or {}
    region_counts = summary.get("region_counts") or {}
    risky = sorted(
        turbines,
        key=lambda item: (
            0 if item.get("status") == "fault" else 1 if item.get("status") == "warning" else 2,
            float(item.get("hi_value") if item.get("hi_value") is not None else 999),
        ),
    )[:8]
    lines = ["**风场监控总览**"]
    lines.append(
        f"总风机 {summary.get('total', 0)} 台；"
        f"正常 {status_counts.get('normal', 0)} 台，预警 {status_counts.get('warning', 0)} 台，故障 {status_counts.get('fault', 0)} 台。"
    )
    lines.append(
        f"平均HI {summary.get('avg_hi') if summary.get('avg_hi') is not None else '-'}；"
        f"最低HI {summary.get('min_hi') if summary.get('min_hi') is not None else '-'}；"
        f"活跃登记故障 {summary.get('active_fault_count', 0)} 条；活跃工单 {summary.get('active_workorder_count', 0)} 个。"
    )
    if region_counts:
        region_text = "、".join(f"{name}:{count}" for name, count in list(region_counts.items())[:8])
        lines.append(f"分组分布：{region_text}。")
    if risky:
        lines.append("重点关注风机：")
        for item in risky[:5]:
            if item.get("status") == "normal" and len(risky) > 5:
                continue
            lines.append(f"- {item.get('name')} | {item.get('region') or '-'} | {item.get('status')} | HI {item.get('hi_value')}")
    return "\n".join(lines)


def _format_turbine_detail_answer(context: dict[str, Any]) -> str:
    turbine = context.get("turbine") or {}
    if not turbine:
        return "未找到该风机。"
    scada = (context.get("latest_scada") or [None])[0] or {}
    faults = context.get("fault_context") or {}
    workorders = context.get("workorders") or []
    rul_predictions = context.get("rul_predictions") or []
    lines = [f"**{turbine.get('name')} 单机详情**"]
    lines.append(f"区域：{turbine.get('region') or '-'}；状态：{turbine.get('status') or '-'}；HI：{turbine.get('hi_value') if turbine.get('hi_value') is not None else '-'}。")
    if scada:
        lines.append(
            f"最新SCADA：功率 {scada.get('power_kw') if scada.get('power_kw') is not None else '-'}kW，"
            f"风速 {scada.get('wind_speed_ms') if scada.get('wind_speed_ms') is not None else '-'}m/s，"
            f"转速 {scada.get('rotor_rpm') if scada.get('rotor_rpm') is not None else '-'}rpm。"
        )
    lines.append(f"故障记录：总计 {faults.get('total', 0)} 条，活跃 {faults.get('active', 0)} 条。")
    if workorders:
        active_orders = [item for item in workorders if item.get("status") not in {"completed", "closed", "cancelled"}]
        lines.append(f"关联工单：{len(workorders)} 个，其中未闭环 {len(active_orders)} 个。")
    if rul_predictions:
        lines.append(f"最短RUL预测：{_min_rul_text(rul_predictions)}。")
    return "\n".join(lines)


def _format_vibration_answer(data: dict[str, Any], turbine_name: str | None = None) -> str:
    summary = data.get("summary") or {}
    lines = [f"**{turbine_name or '风机'} 振动数据**"]
    lines.append(f"记录数：{data.get('total', 0)}；部件：{data.get('component') or '全部'}。")
    lines.append(
        f"最新RMS：{summary.get('latest_rms') if summary.get('latest_rms') is not None else '-'}；"
        f"最大RMS：{summary.get('max_rms') if summary.get('max_rms') is not None else '-'}；"
        f"最新主频峰值：{summary.get('latest_peak_freq_hz') if summary.get('latest_peak_freq_hz') is not None else '-'}Hz。"
    )
    return "\n".join(lines)


def _format_rul_answer(data: dict[str, Any], plan: dict[str, Any] | None = None) -> str:
    items = data.get("items") or []
    lines = ["**RUL与维护优先级**"]
    lines.append(f"RUL记录 {data.get('total', 0)} 条；30天内 {data.get('urgent_count', 0)} 条；30-90天 {data.get('high_count', 0)} 条。")
    for index, item in enumerate(items[:8], start=1):
        lines.append(
            f"{index}. {item.get('turbine_name') or item.get('turbine_id')} | {item.get('component')} | "
            f"剩余 {round(float(item.get('remaining_life_days') or 0), 1)}天"
        )
    if plan:
        lines.append(f"维护计划：共 {plan.get('total', 0)} 项，紧急 {plan.get('urgent_count', 0)} 项，高优 {plan.get('high_count', 0)} 项，估算成本 {plan.get('total_cost_estimate', 0)}。")
    return "\n".join(lines)


def _format_workorder_answer(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    lines = ["**维修工单查询**"]
    if not items:
        lines.append("当前没有查询到符合条件的工单。")
        return "\n".join(lines)
    lines.append(f"查询到 {data.get('total', len(items))} 个工单。")
    for index, item in enumerate(items[:10], start=1):
        lines.append(
            f"{index}. {item.get('ref') or item.get('id')} | {item.get('title') or '-'} | "
            f"{item.get('status') or '-'} | {item.get('priority') or '-'} | 负责人 {item.get('assignee') or '-'}"
        )
    detail = data.get("detail") or {}
    records = detail.get("records") or []
    if records:
        latest = records[-1]
        lines.append(f"最新维修记录：{latest.get('action_type') or '-'}，{latest.get('content') or '-'}。")
    return "\n".join(lines)


def _format_knowledge_answer(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    lines = ["**故障知识库查询**"]
    if not items:
        lines.append("当前没有查询到匹配知识条目。")
        return "\n".join(lines)
    lines.append(f"查询到 {data.get('total', len(items))} 条知识。")
    for index, item in enumerate(items[:5], start=1):
        solution = (item.get("solutions") or ["-"])[0]
        cause = (item.get("root_causes") or ["-"])[0]
        lines.append(f"{index}. {item.get('fault_type')} | {item.get('category') or '-'} | 根因：{cause} | 处理：{solution}")
    return "\n".join(lines)


def _format_settings_answer(data: dict[str, Any]) -> str:
    providers = data.get("ai_providers") or []
    sources = data.get("data_sources") or []
    pipeline = data.get("pipeline") or {}
    thresholds = data.get("thresholds") or {}
    lines = ["**系统设置与数据源状态**"]
    lines.append(f"AI供应商：{len(providers)} 个；HI阈值：{thresholds.get('hi_threshold') if thresholds else '-'}。")
    if providers:
        lines.append("AI供应商状态：")
        for item in providers[:8]:
            lines.append(f"- {item.get('display_name') or item.get('provider')} | {item.get('default_model') or '-'} | {item.get('last_test_status') or 'untested'}")
    if sources:
        connected = sum(1 for item in sources if item.get("status") in {"connected", "active", "success"})
        lines.append(f"数据源：{len(sources)} 个，连接/可用 {connected} 个。")
    counts = pipeline.get("record_counts") or {}
    if counts:
        lines.append("数据记录量：" + "、".join(f"{key}:{value}" for key, value in counts.items()) + "。")
    return "\n".join(lines)


async def _query_faulty_turbines(db: AsyncSession, *, limit: int = 50) -> dict[str, Any]:
    turbines_by_id: dict[int, dict[str, Any]] = {}

    status_result = await db.execute(
        select(Turbine)
        .where(Turbine.status == "fault")
        .order_by(Turbine.hi_value.asc(), Turbine.name.asc())
        .limit(limit)
    )
    for turbine in status_result.scalars().all():
        turbines_by_id[turbine.id] = {
            "id": turbine.id,
            "name": turbine.name,
            "region": turbine.region,
            "status": turbine.status,
            "hi_value": turbine.hi_value,
            "fault_type": "CARE状态/SCADA异常推导",
            "confidence": None,
            "source": "turbine_status",
            "source_label": "风机状态=故障",
            "rul_predictions": [],
        }

    fault_result = await db.execute(
        select(Fault, Turbine)
        .join(Turbine, Turbine.id == Fault.turbine_id)
        .where(Fault.status.in_(list(ACTIVE_FAULT_STATUSES)))
        .order_by(Fault.detected_at.desc())
        .limit(limit)
    )
    for fault, turbine in fault_result.all():
        item = turbines_by_id.setdefault(
            turbine.id,
            {
                "id": turbine.id,
                "name": turbine.name,
                "region": turbine.region,
                "status": turbine.status,
                "hi_value": turbine.hi_value,
                "fault_type": fault.fault_type,
                "confidence": fault.confidence,
                "source": "fault_record",
                "source_label": "登记故障记录",
                "rul_predictions": [],
            },
        )
        item["fault_type"] = fault.fault_type
        item["confidence"] = fault.confidence
        item["source"] = "fault_record+turbine_status" if item["source"] == "turbine_status" else "fault_record"
        item["source_label"] = "登记故障记录 + 风机状态" if item["source"] == "fault_record+turbine_status" else "登记故障记录"

    if turbines_by_id:
        ids = list(turbines_by_id)
        rul_result = await db.execute(
            select(RULPrediction)
            .where(RULPrediction.turbine_id.in_(ids))
            .order_by(RULPrediction.turbine_id.asc(), RULPrediction.remaining_life_days.asc())
        )
        for row in rul_result.scalars().all():
            item = turbines_by_id.get(row.turbine_id)
            if item is not None:
                item["rul_predictions"].append({
                    "component": row.component,
                    "remaining_life_days": row.remaining_life_days,
                })

    rows = sorted(
        turbines_by_id.values(),
        key=lambda item: (
            float(item.get("hi_value") if item.get("hi_value") is not None else 999),
            min((float(pred.get("remaining_life_days") or 999) for pred in item.get("rul_predictions", [])), default=999),
            str(item.get("name") or ""),
        ),
    )
    return {
        "total": len(rows),
        "items": rows[:limit],
        "truncated": len(rows) > limit,
    }


def _format_faulty_turbines_answer(data: dict[str, Any]) -> str:
    items = data.get("items") or []
    total = int(data.get("total") or 0)
    lines = ["**故障风机查询**"]
    if total == 0:
        lines.append("结论：当前未识别到故障风机。")
        return "\n".join(lines)

    lines.append(f"结论：当前识别出 {total} 台故障风机。")
    lines.append("口径：包含 `faults` 表中的活跃登记故障，以及故障诊断页基于 CARE 数据集状态生成的页面级故障。")
    for index, item in enumerate(items[:20], start=1):
        confidence = item.get("confidence")
        confidence_text = f"，置信度 {round(float(confidence) * 100)}%" if isinstance(confidence, (int, float)) else ""
        lines.append(
            f"{index}. {item.get('name')} | {item.get('region') or '-'} | "
            f"状态 {item.get('status')} | HI {item.get('hi_value')} | "
            f"{item.get('fault_type')}{confidence_text} | "
            f"最短RUL {_min_rul_text(item.get('rul_predictions') or [])} | "
            f"来源：{item.get('source_label')}"
        )
    if len(items) > 20 or data.get("truncated"):
        lines.append("仅显示前20条，请增加筛选条件查看更精确范围。")
    return "\n".join(lines)


async def answer_read_task(
    db: AsyncSession,
    *,
    message: str,
    page_context: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    user: User | None = None,
) -> dict[str, Any]:
    """Answer supported read-only Agent questions deterministically."""
    page_context = page_context or {}

    async def require_turbine() -> tuple[Turbine | None, dict[str, Any] | None]:
        turbine, problem = await _resolve_optional_turbine(db, message)
        if turbine or problem:
            return turbine, problem
        context_id = page_context.get("turbine_id") or page_context.get("selectedTurbineId")
        if context_id:
            found = await db.get(Turbine, int(context_id))
            if found:
                return found, None
        return None, {
            "status": "needs_clarification",
            "task_type": "READ",
            "confidence": 0.58,
            "missing_slots": ["turbine_ref"],
            "clarification_question": "请说明要查询哪台风机，例如 YD-B-007。",
        }

    if playbook_id == "monitoring.view_fleet_status":
        data = await query_fleet_overview(db)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.82,
            "answer": _format_fleet_answer(data),
            "data": data,
            "display": {"navigate_to": "/dashboard"},
        }

    if playbook_id == "monitoring.view_turbine_detail":
        turbine, problem = await require_turbine()
        if problem:
            return problem
        context = await query_turbine_detail_context(db, turbine.id)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.84,
            "answer": _format_turbine_detail_answer(context),
            "data": context,
            "display": {"navigate_to": f"/turbine/{turbine.id}", "open_entity": {"type": "turbine", "id": turbine.id}},
        }

    if playbook_id == "diagnosis.view_vibration":
        turbine, problem = await require_turbine()
        if problem:
            return problem
        data = await query_vibration_context(db, turbine_id=turbine.id, component=_component_hint(message))
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.84,
            "answer": _format_vibration_answer(data, turbine.name),
            "data": data,
            "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "turbine", "id": turbine.id}},
        }

    if playbook_id == "prediction.view_rul_and_plan":
        turbine, problem = await _resolve_optional_turbine(db, message)
        if problem:
            return problem
        data = await query_rul_context(db, turbine_id=turbine.id if turbine else None, component=_component_hint(message), limit=20)
        plan = await query_maintenance_plan_context(db, top_n=10)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.82,
            "answer": _format_rul_answer(data, plan),
            "data": {"rul": data, "maintenance_plan": plan},
            "display": {"navigate_to": "/prediction"},
        }

    if playbook_id == "workorder.query_workorders":
        turbine, problem = await _resolve_optional_turbine(db, message)
        if problem:
            return problem
        data = await query_workorder_context(
            db,
            workorder_ref=_extract_workorder_ref(message),
            turbine_id=turbine.id if turbine else None,
            status=_extract_workorder_status(message),
            priority=_extract_priority(message),
        )
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.82,
            "answer": _format_workorder_answer(data),
            "data": data,
            "display": {"navigate_to": "/workorder"},
        }

    if playbook_id == "knowledge.search_fault_knowledge":
        fault_keyword = extract_fault_keyword(message)
        data = await query_knowledge_context(db, query=fault_keyword, fault_type=fault_keyword)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.78,
            "answer": _format_knowledge_answer(data),
            "data": data,
            "display": {"navigate_to": "/knowledge"},
        }

    if playbook_id == "settings.view_system_configuration":
        if not user:
            return {
                "status": "error",
                "task_type": "READ",
                "confidence": 0.0,
                "error_code": "current_user_required",
                "error_message": "查询系统设置需要当前登录用户上下文。",
            }
        data = await query_settings_context(db, user=user)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": playbook_id,
            "confidence": 0.82,
            "answer": _format_settings_answer(data),
            "data": data,
            "display": {"navigate_to": "/settings"},
        }

    if playbook_id == "diagnosis.inspect_turbine_faults":
        turbine, problem = await _resolve_optional_turbine(db, message)
        if problem:
            return problem
        if turbine:
            context = await query_turbine_detail_context(db, turbine.id)
            return {
                "status": "success",
                "task_type": "READ",
                "workflow": playbook_id,
                "confidence": 0.88,
                "answer": _format_fault_answer(context),
                "data": context,
                "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "turbine", "id": turbine.id}},
            }
        data = await _query_faulty_turbines(db)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": "diagnosis.list_faulty_turbines",
            "confidence": 0.78,
            "answer": _format_faulty_turbines_answer(data),
            "data": data,
            "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "faulty_turbines"}},
        }

    if _looks_like_faulty_turbines_query(message):
        data = await _query_faulty_turbines(db)
        return {
            "status": "success",
            "task_type": "READ",
            "workflow": "diagnosis.list_faulty_turbines",
            "confidence": 0.9,
            "answer": _format_faulty_turbines_answer(data),
            "data": data,
            "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "faulty_turbines"}},
        }

    if not _looks_like_turbine_fault_query(message):
        return {
            "status": "unsupported",
            "task_type": "READ",
            "confidence": 0.35,
            "error_code": "read_task_not_supported",
            "error_message": "该只读问题尚未进入确定性Agent查询白名单。",
        }

    turbine_ref = extract_turbine_ref(message)
    resolution = await resolve_turbine_by_ref(db, turbine_ref)
    turbine = resolution.entity
    if not turbine:
        if resolution.candidates:
            names = "、".join(item.name for item in resolution.candidates)
            return {
                "status": "needs_clarification",
                "task_type": "READ",
                "confidence": 0.66,
                "missing_slots": ["turbine_ref"],
                "clarification_question": f"找到多个相近风机：{names}。请明确风机编号。",
            }
        return {
            "status": "error",
            "task_type": "READ",
            "confidence": 0.78,
            "error_code": "turbine_not_found",
            "error_message": f"未找到风机 {turbine_ref}。",
        }

    context = await query_turbine_detail_context(db, turbine.id)
    return {
        "status": "success",
        "task_type": "READ",
        "workflow": "diagnosis.inspect_turbine_faults",
        "confidence": 0.88,
        "answer": _format_fault_answer(context),
        "data": context,
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "turbine", "id": turbine.id}},
    }
