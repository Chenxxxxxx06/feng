"""Structured slot extraction for the unified Agent planner.

This layer is intentionally deterministic. It does not decide whether an
action is allowed; it only exposes what the planner understood from the user
message and current page context so the frontend, audit log, and later LLM
planner can share a stable contract.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.agent_entities import normalize_turbine_ref
from app.services.agent_workflows.workorder import extract_fault_keyword, extract_priority_hint

WORKORDER_STATUS_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("cancelled", ("取消", "作废", "撤销")),
    ("closed", ("关闭工单", "关单", "归档")),
    ("completed", ("完成工单", "已完成", "完成", "修复完成", "处理完成")),
    ("review", ("提交复核", "待复核", "复核")),
    ("in_progress", ("处理中", "开始处理", "开始维修", "正在处理", "已开工")),
    ("assigned", ("已分配", "待执行")),
    ("pending", ("待处理", "挂起")),
]

FAULT_PROCESSING_STATUS_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("failed", ("失败", "未解决", "处理失败", "无法关闭")),
    ("closed", ("关闭故障", "故障已处理", "已处理", "处理完成", "修复完成", "关闭")),
    ("processing", ("开始处理", "处理中")),
]

AI_PROVIDER_ALIASES = {
    "deepseek": "deepseek",
    "deep seek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
    "月之暗面": "kimi",
    "通义千问": "dashscope",
    "通义": "dashscope",
    "千问": "dashscope",
    "阿里云": "dashscope",
    "qwen": "dashscope",
    "dashscope": "dashscope",
    "openai": "openai",
    "chatgpt": "openai",
    "智谱": "glm",
    "zhipu": "glm",
    "glm": "glm",
    "ollama": "ollama",
}

COMPONENT_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("gearbox", ("齿轮箱", "gear box", "gearbox")),
    ("generator", ("发电机", "generator")),
    ("main_bearing", ("主轴承", "主轴", "main bearing")),
    ("bearing", ("轴承", "bearing")),
    ("blade", ("叶片", "blade", "桨叶")),
    ("converter", ("变频器", "converter")),
    ("transformer", ("变压器", "transformer")),
    ("yaw", ("偏航", "yaw")),
    ("pitch", ("变桨", "pitch")),
    ("cooling", ("冷却", "cooling")),
    ("scada", ("scada", "SCADA")),
    ("vibration", ("振动", "vibration")),
]


def _slot(value: Any, source: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    return {"value": value, "source": source}


def _put(slots: dict[str, dict[str, Any]], key: str, value: Any, source: str) -> None:
    item = _slot(value, source)
    if item is not None and key not in slots:
        slots[key] = item


def _extract_workorder_id(message: str) -> int | None:
    patterns = [
        r"WO[-_\s]*(\d{1,8})",
        r"\bWO[-_\s]*(\d{1,8})\b",
        r"工单\s*#?\s*(\d{1,8})",
        r"(\d{1,8})\s*号工单",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_turbine_ref_for_slots(message: str) -> str | None:
    patterns = [
        r"([A-Za-z]{1,4}[-_\s]?[A-Za-z][-_]?\s*\d{1,4})\s*(?:号)?风机",
        r"(?<![A-Za-z0-9])([A-Za-z]{1,4}[-_\s]?[A-Za-z][-_]?\s*\d{1,4})(?![A-Za-z0-9])",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, message):
            raw = match.group(1).strip()
            if re.match(r"^WO[-_\s]*\d+$", raw, flags=re.IGNORECASE):
                continue
            normalized = normalize_turbine_ref(raw)
            if normalized and not normalized.startswith("W-O-"):
                return normalized
    return None


def _extract_fault_id(message: str) -> int | None:
    patterns = [
        r"故障\s*#?\s*(\d{1,8})",
        r"fault\s*#?\s*(\d{1,8})",
        r"(\d{1,8})\s*号故障",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_assignee_name(message: str) -> str | None:
    if any(token in message for token in ("暂不指定", "不指定", "无需指定", "先不指定", "不用指定")):
        return None
    patterns = [
        r"(?:分配给|派给|交给|指派给|安排给|给)\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})(?:师傅|工程师|人员|处理|负责|$)",
        r"让\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})(?:师傅|工程师|人员)?\s*(?:处理|负责|接手)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip()
            for suffix in ("师傅", "工程师", "人员"):
                if value.endswith(suffix):
                    value = value[: -len(suffix)]
            return value.strip() or None
    return None


def _extract_reason(message: str) -> str | None:
    patterns = [
        r"(?:原因|说明|备注|处理结果|理由)[是为:：]?\s*(.+)$",
        r"[，,]\s*(已.+)$",
        r"[，,]\s*(现场.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip()
            return value or None
    return None


def _extract_record_content(message: str) -> str | None:
    patterns = [
        r"(?:追加记录|维修记录|处理说明|记录|备注)[：:]\s*(.+)$",
        r"(?:追加记录|维修记录|处理说明|记录|备注)\s*(.+)$",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip()
            value = re.sub(r"^WO[-_\s]*\d{1,8}\s*", "", value, flags=re.IGNORECASE).strip(" ，,。")
            return value or None
    return None


def _extract_target_workorder_status(message: str) -> str | None:
    lowered = message.lower()
    for status, keywords in WORKORDER_STATUS_ALIASES:
        if any(keyword.lower() in lowered for keyword in keywords):
            return status
    match = re.search(r"标记为\s*([\u4e00-\u9fa5A-Za-z_]+)", message)
    if match:
        label = match.group(1).strip()
        label_map = {
            "待处理": "pending",
            "已分配": "assigned",
            "处理中": "in_progress",
            "待复核": "review",
            "已完成": "completed",
            "已关闭": "closed",
            "已取消": "cancelled",
        }
        return label_map.get(label, label if label in {item[0] for item in WORKORDER_STATUS_ALIASES} else None)
    return None


def _extract_fault_processing_status(message: str) -> str | None:
    for status, keywords in FAULT_PROCESSING_STATUS_ALIASES:
        if any(keyword in message for keyword in keywords):
            return status
    return None


def _extract_provider_key(message: str) -> str | None:
    lowered = message.lower()
    for alias, provider in sorted(AI_PROVIDER_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias.lower() in lowered:
            return provider
    return None


def _extract_component(message: str) -> str | None:
    lowered = message.lower()
    for component, aliases in COMPONENT_ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            return component
    return None


def _extract_scope(message: str) -> str | None:
    lowered = message.lower()
    if any(token in message for token in ("全部", "全场", "所有", "所有风机")):
        return "fleet"
    if any(token in message for token in ("这台", "当前风机", "当前机组")):
        return "current_turbine"
    if any(token in lowered for token in ("a组", "风场a", "区域a")):
        return "group_a"
    if any(token in lowered for token in ("b组", "风场b", "区域b")):
        return "group_b"
    if any(token in lowered for token in ("c组", "风场c", "区域c")):
        return "group_c"
    return None


def _extract_float_after(message: str, keywords: tuple[str, ...]) -> float | None:
    for keyword in keywords:
        match = re.search(rf"{re.escape(keyword)}\s*(\d+(?:\.\d+)?)", message, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _context_value(page_context: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = page_context.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def extract_agent_slots(
    message: str,
    *,
    page_context: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Extract best-effort structured slots from message and page context."""
    page_context = page_context or {}
    slots: dict[str, dict[str, Any]] = {}

    playbook_id = str((playbook or {}).get("id") or "").strip()
    _put(slots, "playbook_id", playbook_id, "planner")

    turbine_ref = _extract_turbine_ref_for_slots(message)
    _put(slots, "turbine_ref", turbine_ref, "message")

    context_turbine_ref = normalize_turbine_ref(
        _context_value(page_context, "turbine_name", "selected_turbine_name", "selectedTurbineName")
    )
    _put(slots, "turbine_ref", context_turbine_ref, "page_context")
    _put(slots, "turbine_id", _context_value(page_context, "turbine_id", "selected_turbine_id", "selectedTurbineId"), "page_context")

    workorder_id = _extract_workorder_id(message)
    if workorder_id is not None:
        _put(slots, "workorder_id", workorder_id, "message")
        _put(slots, "workorder_ref", f"WO-{workorder_id:04d}", "message")
    _put(slots, "workorder_id", _context_value(page_context, "workorder_id", "workOrderId"), "page_context")

    fault_id = _extract_fault_id(message)
    _put(slots, "fault_id", fault_id, "message")
    _put(slots, "fault_id", _context_value(page_context, "fault_id", "selected_fault_id", "selectedFaultId"), "page_context")

    _put(slots, "fault_keyword", extract_fault_keyword(message), "message")
    _put(slots, "fault_type", _context_value(page_context, "fault_type", "selected_fault_type", "selectedFaultType"), "page_context")
    _put(slots, "component", _extract_component(message), "message")
    _put(slots, "assignee_name", _extract_assignee_name(message), "message")
    _put(slots, "priority", extract_priority_hint(message), "message")
    _put(slots, "target_workorder_status", _extract_target_workorder_status(message), "message")
    fault_processing_status = _extract_fault_processing_status(message)
    if fault_processing_status and ("故障" in message or "fault" in message.lower() or fault_id is not None):
        _put(slots, "target_processing_status", fault_processing_status, "message")
    _put(slots, "record_content", _extract_record_content(message), "message")
    _put(slots, "reason", _extract_reason(message), "message")
    _put(slots, "provider", _extract_provider_key(message), "message")
    _put(slots, "scope", _extract_scope(message), "message")
    _put(slots, "cost_actual", _extract_float_after(message, ("成本", "费用", "花费")), "message")
    _put(slots, "downtime_hours", _extract_float_after(message, ("停机", "耗时")), "message")

    return slots
