"""Work order Agent actions.

This module is the first slice of the new Agent task system:

- READ tasks are reported as unsupported here and can fall back to the old
  page-navigation / read-only data chain.
- WRITE tasks are handled through controlled backend actions.
- COMPOSITE tasks are identified but not executed by this first slice.
- CLARIFY is returned when required slots are missing or ambiguous.

No business page internals are called from here. The module works through
database models and backend validation only.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder
from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import (
    AIProviderConfig,
    AgentActionLog,
    Fault,
    FaultKnowledgeNode,
    FaultSignal,
    MaintenancePersonnel,
    NotificationConfig,
    MaintenanceRecord,
    SCADARecord,
    Turbine,
    User,
    WorkOrder,
)
from app.services.agent_data_tools import resolve_fault_by_context
from app.services.agent_entities import (
    extract_turbine_ref,
    resolve_personnel_by_name,
    resolve_turbine_by_ref,
    resolve_workorder_by_ref,
)
from app.services.agent_workflows.workorder import (
    draft_create_workorder_fields,
    extract_fault_keyword,
    extract_priority_hint,
    fault_context_state,
    query_turbine_fault_context,
)
from app.services.prediction_service import refresh_rul_predictions
from app.services.care_monitoring_metrics import CARE_DATASET_ID, calculate_care_hi_from_scada
from app.services.qwen_client import get_client

FINAL_STATUSES = {"completed", "closed", "cancelled"}
PENDING_ACTION_TTL = timedelta(minutes=10)
AGENT_WRITE_ROLES = {"admin", "technician"}
AGENT_ADMIN_ACTIONS = {
    "delete_ai_provider_config",
    "test_ai_provider_connection",
    "upsert_ai_provider_config",
    "upsert_personnel",
    "delete_personnel",
    "review_knowledge_node",
    "delete_knowledge_node",
    "update_threshold_config",
}
WORKORDER_TRANSITIONS = {
    "pending": {"assigned", "in_progress", "cancelled"},
    "assigned": {"in_progress", "cancelled"},
    "in_progress": {"review", "completed", "cancelled"},
    "review": {"in_progress", "completed", "cancelled"},
    "completed": {"closed"},
    "closed": set(),
    "cancelled": set(),
}
WORKORDER_STATUS_LABELS = {
    "pending": "待处理",
    "assigned": "已分配",
    "in_progress": "处理中",
    "review": "待复核",
    "completed": "已完成",
    "closed": "已关闭",
    "cancelled": "已取消",
}
AI_PROVIDER_ALIASES = {
    "deepseek": "deepseek",
    "deep seek": "deepseek",
    "kimi": "moonshot",
    "moonshot": "moonshot",
    "月之暗面": "moonshot",
    "通义千问": "dashscope",
    "通义": "dashscope",
    "千问": "dashscope",
    "阿里云": "dashscope",
    "qwen": "dashscope",
    "dashscope": "dashscope",
    "openai": "openai",
    "chatgpt": "openai",
    "智谱": "zhipu",
    "glm": "zhipu",
    "ollama": "ollama",
}
AI_PROVIDER_CANONICAL = {
    "moonshot": "kimi",
    "zhipu": "glm",
    "qwen": "dashscope",
}
AI_PROVIDER_TEMPLATES: dict[str, dict[str, Any]] = {
    "dashscope": {
        "display_name": "通义千问 DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "model_options": ["qwen-plus", "qwen-turbo", "qwen3.6-flash"],
    },
    "deepseek": {
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "model_options": ["deepseek-chat", "deepseek-reasoner", "deepseek-v4-flash"],
    },
    "glm": {
        "display_name": "智谱GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5-flash",
        "model_options": ["glm-5-flash"],
    },
    "kimi": {
        "display_name": "Kimi Moonshot",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "kimi-k2.6",
        "model_options": ["kimi-k2.6"],
    },
    "openai": {
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "model_options": ["gpt-4o-mini", "gpt-4.1", "gpt-4", "gpt-3.5-turbo"],
    },
    "gemini": {
        "display_name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.5-flash",
        "model_options": ["gemini-2.5-flash", "gemini-3.5-flash"],
    },
    "ollama": {
        "display_name": "Ollama本地模型",
        "base_url": "http://localhost:11434/v1",
        "default_model": "qwen2.5",
        "model_options": ["qwen2.5", "llama3.1", "deepseek-r1"],
    },
}
DEFAULT_PERSONNEL_REGION = "陕北"
DEFAULT_PERSONNEL_SKILLS = ["风机维护", "电气检修"]
SKILL_KEYWORDS = {
    "齿轮箱": "齿轮箱检修",
    "轴承": "轴承检修",
    "电气": "电气检修",
    "变桨": "变桨系统",
    "偏航": "偏航系统",
    "叶片": "叶片巡检",
    "发电机": "发电机检修",
    "SCADA": "SCADA诊断",
    "振动": "振动分析",
}
DETECTION_COMPONENT_ALIASES: list[tuple[str, tuple[str, ...]]] = [
    ("gearbox_high_speed", ("齿轮箱高速轴", "高速轴", "gearbox_high_speed")),
    ("gearbox", ("齿轮箱", "gear box", "gearbox")),
    ("generator", ("发电机", "generator")),
    ("main_bearing", ("主轴承", "主轴", "main bearing")),
    ("bearing", ("轴承", "bearing")),
    ("blade", ("叶片", "桨叶", "blade")),
    ("converter", ("变频器", "converter")),
    ("transformer", ("变压器", "transformer")),
    ("yaw", ("偏航", "yaw")),
    ("pitch", ("变桨", "pitch")),
    ("cooling", ("冷却", "cooling")),
]


@dataclass
class PendingAction:
    request_id: str
    user_id: int
    raw_message: str
    task_type: str
    action: str
    params: dict[str, Any]
    before: dict[str, Any]
    after: dict[str, Any]
    warnings: list[str]
    created_at: datetime
    expires_at: datetime


_PENDING_ACTIONS: dict[str, PendingAction] = {}


def _audit_safe_params(action: str, params: dict[str, Any]) -> dict[str, Any]:
    safe = dict(params)
    if action == "upsert_ai_provider_config" and "api_key" in safe:
        safe["api_key"] = "__redacted__" if safe.get("api_key") else None
    return safe


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime | None) -> datetime:
    if not value:
        return _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _can_execute_agent_action(user: User, action: str) -> bool:
    if not user.is_active:
        return False
    role = str(user.role or "viewer")
    if action in AGENT_ADMIN_ACTIONS:
        return role == "admin"
    return role in AGENT_WRITE_ROLES


def _permission_denied_response(action: str, *, task_type: str = "WORKFLOW") -> dict[str, Any]:
    return {
        "status": "error",
        "task_type": task_type,
        "confidence": 0.0,
        "error_code": "permission_denied",
        "error_message": f"当前账号没有执行 Agent 动作 `{action}` 的权限。本次不会生成确认卡片，也不会修改数据。",
    }


def _workorder_ref(workorder: WorkOrder) -> str:
    return f"WO-{workorder.id:04d}"


def _workorder_state(workorder: WorkOrder) -> dict[str, Any]:
    return {
        "id": workorder.id,
        "ref": _workorder_ref(workorder),
        "turbine_id": workorder.turbine_id,
        "fault_id": workorder.fault_id,
        "title": workorder.title,
        "description": workorder.description,
        "status": workorder.status,
        "priority": workorder.priority,
        "fault_type": workorder.fault_type,
        "due_date": workorder.due_date.isoformat() if workorder.due_date else None,
        "cost_estimate": workorder.cost_estimate,
        "cost_actual": workorder.cost_actual,
        "downtime_hours": workorder.downtime_hours,
        "assignee": workorder.assignee,
        "assignee_id": workorder.assignee_id,
        "assignee_email": workorder.assignee_email,
        "completed_at": workorder.completed_at.isoformat() if workorder.completed_at else None,
        "cancelled_at": workorder.cancelled_at.isoformat() if workorder.cancelled_at else None,
        "deleted_at": workorder.deleted_at.isoformat() if workorder.deleted_at else None,
    }


def _turbine_state(turbine: Turbine) -> dict[str, Any]:
    return {
        "id": turbine.id,
        "name": turbine.name,
        "region": turbine.region,
        "status": turbine.status,
        "hi_value": turbine.hi_value,
    }


def _fault_state(fault: Fault) -> dict[str, Any]:
    return {
        "id": fault.id,
        "turbine_id": fault.turbine_id,
        "detected_at": fault.detected_at.isoformat() if fault.detected_at else None,
        "fault_type": fault.fault_type,
        "confidence": fault.confidence,
        "status": fault.status,
        "processing_status": getattr(fault, "processing_status", None) or "pending",
        "priority": getattr(fault, "priority", None),
        "handler": getattr(fault, "handler", None),
        "status_note": getattr(fault, "status_note", None),
        "work_order_id": getattr(fault, "work_order_id", None),
        "details": fault.details,
    }


def _ai_provider_state(config: AIProviderConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "provider": config.provider,
        "display_name": config.display_name,
        "base_url": config.base_url,
        "api_style": config.api_style,
        "default_model": config.default_model,
        "model_options": config.model_options or [],
        "enabled": config.enabled,
        "last_test_status": config.last_test_status,
        "last_test_message": config.last_test_message,
        "has_api_key": bool(config.api_key),
    }


def _format_ai_provider_test_error(config: AIProviderConfig, exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()
    if config.provider == "kimi" and ("401" in raw or "invalid authentication" in lowered):
        return (
            "Kimi认证失败：请确认使用的是 Kimi 开放平台控制台创建的 API Key，"
            "Base URL 为 https://api.moonshot.cn/v1，且密钥未过期、未禁用、未误用 Kimi 网页端登录凭证。"
            f"原始错误：{raw}"
        )
    return raw[:1200]


def _threshold_config_state(config: NotificationConfig | None, *, user: User) -> dict[str, Any]:
    return {
        "id": config.id if config else None,
        "hi_threshold": float(config.hi_threshold) if config else 70.0,
        "email_enabled": bool(config.email_enabled) if config else True,
        "email_address": config.email_address if config else user.email,
        "wechat_enabled": bool(config.wechat_enabled) if config else False,
    }


def _knowledge_state(node: FaultKnowledgeNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "fault_type": node.fault_type,
        "category": node.category,
        "icon": node.icon,
        "severity": node.severity,
        "symptoms": node.symptoms or [],
        "root_causes": node.root_causes or [],
        "solutions": node.solutions or [],
        "related_faults": node.related_faults or [],
        "spare_parts": node.spare_parts or [],
        "cases": node.cases or [],
        "source": getattr(node, "source", "manual"),
        "confidence": getattr(node, "confidence", 1.0),
        "verified": bool(getattr(node, "verified", True)),
        "extracted_from": getattr(node, "extracted_from", None),
    }


async def _personnel_profile(db: AsyncSession, user: User) -> MaintenancePersonnel | None:
    result = await db.execute(
        select(MaintenancePersonnel).where(
            or_(MaintenancePersonnel.user_id == user.id, MaintenancePersonnel.name == user.username)
        )
    )
    return result.scalar_one_or_none()


async def _personnel_state(
    db: AsyncSession,
    user: User,
    *,
    profile: MaintenancePersonnel | None = None,
    active_count: int | None = None,
) -> dict[str, Any]:
    profile = profile if profile is not None else await _personnel_profile(db, user)
    return {
        "id": user.id,
        "name": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": bool(user.is_active),
        "skills": (profile.skills if profile and profile.skills else DEFAULT_PERSONNEL_SKILLS),
        "region": (profile.region if profile and profile.region else DEFAULT_PERSONNEL_REGION),
        "is_available": bool(profile.is_available) if profile else bool(user.is_active),
        "active_workorder_count": active_count if active_count is not None else await _active_workorder_count(db, user.username),
    }


def _extract_workorder_ref(message: str) -> Optional[int]:
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


def _extract_turbine_ref(message: str) -> Optional[str]:
    return extract_turbine_ref(message)


def _extract_assignee_name(message: str) -> Optional[str]:
    if any(token in message for token in ("暂不指定", "不指定", "无需指定", "先不指定", "不用指定")):
        return None
    patterns = [
        r"(?:分配给|派给|交给|指派给|安排给|给)\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})(?:师傅|工程师|人员|处理|负责|$)",
        r"让\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})(?:师傅|工程师|人员)?\s*(?:处理|负责|接手)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            name = match.group(1).strip()
            for suffix in ("师傅", "工程师", "人员"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
            return name.strip() or None
    return None


def _extract_fault_id(message: str) -> Optional[int]:
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


def _extract_fault_keyword(message: str) -> Optional[str]:
    for keyword in ("齿轮箱", "轴承", "主轴", "叶片", "发电机", "变桨", "冷却", "偏航", "振动", "过热", "磨损", "不平衡", "erosion", "unbalance"):
        if keyword.lower() in message.lower():
            return keyword
    match = re.search(r"的([\u4e00-\u9fa5A-Za-z0-9_ -]{2,32})故障", message)
    if match:
        return match.group(1).strip()
    return None


def _clean_fault_type_candidate(value: str, turbine_ref: str | None = None) -> str | None:
    cleaned = value.strip(" ，,。；;：:")
    cleaned = re.sub(r"^(给|为|对|将|把)", "", cleaned).strip()
    if turbine_ref:
        compact_ref = turbine_ref.replace("-", "").replace("_", "").replace(" ", "")
        variants = {turbine_ref, compact_ref}
        for variant in variants:
            if variant:
                cleaned = cleaned.replace(variant, "")
    cleaned = re.sub(r"^[A-Za-z]{1,4}[-_\s]?[A-Za-z][-_]?\s*\d{1,4}(?:号)?(?:风机|机组)?", "", cleaned).strip()
    cleaned = re.sub(r"(?:故障记录|故障|异常)$", "", cleaned).strip(" 的")
    if cleaned in {"故障", "异常", "记录", "新增", "创建", "登记"}:
        return None
    return cleaned[:64] if len(cleaned) >= 2 else None


def _extract_create_fault_type(message: str, turbine_ref: str | None = None) -> Optional[str]:
    explicit = _extract_field_after_label(message, ("故障类型", "故障类别", "故障名称"), max_length=64)
    if explicit:
        return _clean_fault_type_candidate(explicit, turbine_ref)

    known = extract_fault_keyword(message)
    if known:
        return known

    patterns = [
        r"(?:登记|新增|创建|记录|录入)\s*(?:一条|一个)?\s*([^，,。；;\n]{2,80}?)(?:故障|异常)",
        r"(?:给|为|对)\s*[^，,。；;\n]{0,32}?\s*(?:登记|新增|创建|记录|录入)\s*([^，,。；;\n]{2,80}?)(?:故障|异常)",
        r"([^\s，,。；;\n]{2,64}?)(?:故障|异常)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        candidate = _clean_fault_type_candidate(match.group(1), turbine_ref)
        if candidate:
            return candidate
    return _extract_fault_keyword(message)


def _extract_fault_confidence(message: str) -> Optional[float]:
    patterns = [
        r"(?:置信度|可信度|confidence)\s*(?:为|是|:|：)?\s*(\d+(?:\.\d+)?)\s*(%)?",
        r"(\d+(?:\.\d+)?)\s*%",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if not match:
            continue
        value = float(match.group(1))
        has_percent = len(match.groups()) >= 2 and match.group(2) == "%"
        if has_percent or value > 1:
            value = value / 100
        return max(0.0, min(1.0, value))
    return None


def _extract_fault_details_text(message: str) -> Optional[str]:
    details = _extract_field_after_label(message, ("详情", "描述", "说明", "备注"), max_length=512)
    if details:
        return details
    return _extract_reason(message)


def _extract_detection_component(message: str) -> str:
    lowered = message.lower()
    for component, aliases in DETECTION_COMPONENT_ALIASES:
        if any(alias.lower() in lowered for alias in aliases):
            return component
    return "gearbox_high_speed"


def _extract_detection_window_hours(message: str) -> int:
    match = re.search(r"(?:最近|近|过去)?\s*(\d{1,3})\s*(小时|h|H|天|日)", message)
    if not match:
        return 24
    value = int(match.group(1))
    unit = match.group(2)
    hours = value * 24 if unit in ("天", "日") else value
    return max(1, min(168, hours))


def _extract_detection_persist_result(message: str) -> bool:
    if any(keyword in message for keyword in ("不保存", "不落库", "不要保存", "只检测", "只看结果", "仅检测")):
        return False
    return any(keyword in message for keyword in ("保存", "落库", "写入故障", "生成故障记录", "创建故障记录", "加入故障列表"))


def _extract_batch_detection_status(message: str) -> Optional[str]:
    if any(keyword in message for keyword in ("预警风机", "预警机组", "warning")):
        return "warning"
    if any(keyword in message for keyword in ("故障风机", "故障机组", "fault")):
        return "fault"
    if any(keyword in message for keyword in ("异常风机", "异常机组")):
        return "abnormal"
    return None


def _extract_batch_detection_region(message: str) -> Optional[str]:
    patterns = [
        r"风场\s*([ABCabc])",
        r"([ABCabc])\s*组",
        r"(?:区域|组别)\s*(?:为|是|:|：)?\s*([\u4e00-\u9fa5A-Za-z0-9_-]{1,12})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        value = match.group(1).strip()
        if re.fullmatch(r"[ABCabc]", value):
            return value.upper()
        return value
    return None


def _region_matches(actual: str | None, requested: str | None) -> bool:
    if not requested:
        return True
    actual_text = str(actual or "")
    requested_text = str(requested or "")
    if not actual_text:
        return False
    if actual_text == requested_text or requested_text in actual_text or actual_text in requested_text:
        return True
    if len(requested_text) == 1 and requested_text.upper() in actual_text.upper():
        return True
    return False


def _extract_schedule_max_days(message: str) -> int:
    if any(keyword in message for keyword in ("下周", "本周", "一周", "7天", "七天")):
        return 7
    if any(keyword in message for keyword in ("下月", "本月", "一个月", "30天", "三十天")):
        return 30
    match = re.search(r"(?:未来|之后|接下来|近)?\s*(\d{1,3})\s*天", message)
    if match:
        return max(1, min(180, int(match.group(1))))
    return 90


def _extract_schedule_top_n(message: str) -> int:
    patterns = [
        r"(?:前|最多|优先)\s*(\d{1,3})\s*(?:项|个|台|条)?",
        r"top\s*(\d{1,3})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return max(1, min(100, int(match.group(1))))
    return 30


def _extract_schedule_create_work_orders(message: str) -> bool:
    if any(keyword in message for keyword in ("不创建工单", "不要创建工单", "只生成排程", "只排程", "不生成工单")):
        return False
    return any(keyword in message for keyword in ("创建工单", "生成工单", "同时建工单", "同时创建工单", "并创建工单", "并生成工单"))


def _extract_health_refresh_scope(message: str) -> dict[str, Any]:
    turbine_ref = _extract_turbine_ref(message)
    region = _extract_batch_detection_region(message) or _extract_region(message)
    fleet = any(keyword in message for keyword in ("全场", "全部风机", "所有风机", "全部机组", "所有机组"))
    status_scope = None
    if any(keyword in message for keyword in ("故障风机", "故障机组")):
        status_scope = "fault"
    elif any(keyword in message for keyword in ("预警风机", "预警机组")):
        status_scope = "warning"
    elif any(keyword in message for keyword in ("正常风机", "正常机组")):
        status_scope = "normal"
    return {
        "turbine_ref": turbine_ref,
        "region": region,
        "fleet": fleet,
        "status": status_scope,
    }


def _context_turbine_id(page_context: dict[str, Any] | None) -> Optional[int]:
    if not page_context:
        return None
    for key in ("turbine_id", "selected_turbine_id", "selectedTurbineId"):
        value = page_context.get(key)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _context_turbine_ref(page_context: dict[str, Any] | None) -> Optional[str]:
    if not page_context:
        return None
    for key in ("turbine_name", "selected_turbine_name", "selectedTurbineName"):
        value = page_context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_reason(message: str) -> Optional[str]:
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


def _extract_target_workorder_status(message: str) -> Optional[str]:
    ordered: list[tuple[str, tuple[str, ...]]] = [
        ("cancelled", ("取消", "作废", "撤销")),
        ("closed", ("关闭工单", "关单", "归档")),
        ("completed", ("完成工单", "已完成", "完成", "修复完成", "处理完成")),
        ("review", ("提交复核", "待复核", "复核")),
        ("in_progress", ("处理中", "开始处理", "开始维修", "正在处理", "已开工")),
        ("assigned", ("已分配", "待执行")),
        ("pending", ("待处理", "挂起")),
    ]
    lowered = message.lower()
    for status, keywords in ordered:
        if any(keyword.lower() in lowered for keyword in keywords):
            return status
    match = re.search(r"标记为\s*([\u4e00-\u9fa5A-Za-z_]+)", message)
    if match:
        label = match.group(1).strip()
        for status, zh in WORKORDER_STATUS_LABELS.items():
            if label in (status, zh):
                return status
    return None


def _extract_record_content(message: str) -> Optional[str]:
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


def _extract_cost_actual(message: str) -> Optional[float]:
    match = re.search(r"(?:成本|费用|花费)\s*(\d+(?:\.\d+)?)", message)
    return float(match.group(1)) if match else None


def _extract_downtime_hours(message: str) -> Optional[float]:
    match = re.search(r"(?:停机|耗时)\s*(\d+(?:\.\d+)?)\s*(小时|h|H|天|日)?", message)
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2) or "小时"
    return value * 24 if unit in ("天", "日") else value


def _extract_due_date(message: str) -> Optional[datetime]:
    match = re.search(r"(?:截止|到期|计划完成|完成时间|due(?: date)?)\s*(?:为|到|在|:|：)?\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})", message, flags=re.IGNORECASE)
    if not match:
        return None
    text = match.group(1).replace("/", "-")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_cost_estimate(message: str) -> Optional[float]:
    match = re.search(r"(?:预计成本|成本估算|预算|预计费用)\s*(?:为|改成|调整为|:|：)?\s*(\d+(?:\.\d+)?)", message)
    return float(match.group(1)) if match else None


def _extract_field_after_label(message: str, labels: tuple[str, ...], *, max_length: int = 128) -> Optional[str]:
    joined = "|".join(re.escape(label) for label in labels)
    patterns = [
        rf"(?:{joined})\s*(?:改成|改为|调整为|设为|为|是|:|：)\s*([^，,。；;\n]{{1,{max_length}}})",
        rf"(?:补充|修改|更新)\s*(?:{joined})\s*(?:为|:|：)?\s*([^，,。；;\n]{{1,{max_length}}})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return match.group(1).strip()
    return None


def _extract_workorder_patch_fields(message: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    priority = extract_priority_hint(message)
    if priority:
        patch["priority"] = priority
    title = _extract_field_after_label(message, ("标题", "工单标题"), max_length=128)
    if title:
        patch["title"] = title
    description = _extract_field_after_label(message, ("描述", "说明", "维修说明", "处理说明"), max_length=512)
    if description:
        patch["description"] = description
    fault_type = _extract_field_after_label(message, ("故障类型", "故障"), max_length=64)
    if fault_type:
        patch["fault_type"] = fault_type
    elif any(keyword in message for keyword in ("故障类型", "故障改成", "故障改为")):
        keyword = _extract_fault_keyword(message)
        if keyword:
            patch["fault_type"] = keyword
    cost_estimate = _extract_cost_estimate(message)
    if cost_estimate is not None:
        patch["cost_estimate"] = cost_estimate
    due_date = _extract_due_date(message)
    if due_date:
        patch["due_date"] = due_date
    return patch


def _extract_fault_patch_fields(message: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    confidence = _extract_fault_confidence(message)
    if confidence is not None:
        patch["confidence"] = confidence
    priority = extract_priority_hint(message)
    if priority:
        patch["priority"] = priority
    fault_type = _extract_field_after_label(message, ("故障类型", "故障类别", "故障名称"), max_length=64)
    if fault_type:
        cleaned = _clean_fault_type_candidate(fault_type, _extract_turbine_ref(message))
        if cleaned:
            patch["fault_type"] = cleaned
    elif any(keyword in message for keyword in ("故障类型", "故障类别", "故障名称")):
        inferred = _extract_create_fault_type(message, _extract_turbine_ref(message))
        if inferred:
            patch["fault_type"] = inferred
    details = _extract_field_after_label(message, ("详情", "描述", "说明"), max_length=512)
    if details:
        patch["details_description"] = details
    handler = _extract_field_after_label(message, ("处理人", "负责人"), max_length=64)
    if handler:
        patch["handler"] = handler
    status_note = _extract_field_after_label(message, ("状态备注", "处理备注", "备注"), max_length=512)
    if status_note:
        patch["status_note"] = status_note
    return patch


def _extract_fault_processing_status(message: str) -> Optional[str]:
    if any(token in message for token in ("失败", "未解决", "处理失败", "无法关闭")):
        return "failed"
    if any(token in message for token in ("关闭故障", "故障已处理", "已处理", "处理完成", "修复完成", "关闭")):
        return "closed"
    if any(token in message for token in ("开始处理", "处理中")):
        return "processing"
    return None


def _extract_provider_key(message: str) -> Optional[str]:
    lowered = message.lower()
    for alias, provider in sorted(AI_PROVIDER_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias.lower() in lowered:
            return AI_PROVIDER_CANONICAL.get(provider, provider)
    return None


def _provider_template(provider: str | None) -> dict[str, Any]:
    key = AI_PROVIDER_CANONICAL.get(str(provider or "").strip().lower(), str(provider or "").strip().lower())
    return AI_PROVIDER_TEMPLATES.get(key, {})


def _extract_url(message: str) -> Optional[str]:
    match = re.search(r"https?://[^\s，,。；;\n]+", message, flags=re.IGNORECASE)
    if match:
        return match.group(0).strip().rstrip("。；;,，")
    return None


def _extract_api_key_value(message: str) -> Optional[str]:
    patterns = [
        r"(?:API\s*KEY|api\s*key|apikey|密钥|key)\s*(?:为|是|:|：|=)?\s*([A-Za-z0-9_\-\.]{8,512})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value.lower() not in {"base", "url", "api"}:
                return value
    return None


def _extract_default_model(message: str, provider: str | None = None) -> Optional[str]:
    labels_value = _extract_field_after_label(message, ("默认模型", "模型名称", "模型"), max_length=128)
    if labels_value:
        value = labels_value.strip().strip("`'\"")
        if value and value not in {"改成", "改为", "设置"}:
            return value
    template = _provider_template(provider)
    known_models = list(template.get("model_options") or [])
    known_models.extend(
        [
            "qwen-plus",
            "qwen-turbo",
            "qwen3.6-flash",
            "deepseek-chat",
            "deepseek-reasoner",
            "kimi-k2.6",
            "glm-5-flash",
            "gpt-4o-mini",
            "gemini-2.5-flash",
            "qwen2.5",
        ]
    )
    lowered = message.lower()
    for model in sorted(set(known_models), key=len, reverse=True):
        if model.lower() in lowered:
            return model
    return None


def _extract_model_options(message: str, provider: str | None = None, default_model: str | None = None) -> list[str]:
    options: list[str] = []
    patterns = [
        r"(?:常用模型|模型列表|可选模型)\s*(?:为|是|:|：)?\s*([^。；;\n]{1,512})",
        r"(?:添加常用模型|新增常用模型)\s*([^。；;\n]{1,256})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if not match:
            continue
        raw = match.group(1)
        for item in re.split(r"[、,，\s]+", raw):
            value = item.strip().strip("`'\"")
            if value and re.search(r"[A-Za-z0-9]", value) and value not in options:
                options.append(value)
    template_options = list(_provider_template(provider).get("model_options") or [])
    for model in template_options:
        if model.lower() in message.lower() and model not in options:
            options.append(model)
    if default_model and default_model not in options:
        options.insert(0, default_model)
    return options


def _extract_ai_provider_payload(message: str) -> dict[str, Any]:
    provider = _extract_provider_key(message)
    template = _provider_template(provider)
    base_url = _extract_url(message) or template.get("base_url")
    default_model = _extract_default_model(message, provider) or template.get("default_model")
    model_options = _extract_model_options(message, provider, default_model)
    if not model_options:
        model_options = list(template.get("model_options") or ([default_model] if default_model else []))
    enabled = True
    if any(keyword in message for keyword in ("禁用", "停用", "关闭")):
        enabled = False
    elif any(keyword in message for keyword in ("启用", "开启", "打开")):
        enabled = True
    return {
        "provider": provider,
        "display_name": template.get("display_name") or provider,
        "api_key": _extract_api_key_value(message),
        "base_url": base_url,
        "api_style": "openai",
        "default_model": default_model,
        "model_options": model_options,
        "enabled": enabled,
    }


def _extract_personnel_name(message: str) -> Optional[str]:
    patterns = [
        r"(?:新增|添加|创建)\s*(?:维护人员|人员|师傅|工程师)?\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})",
        r"(?:删除|禁用|移除)\s*(?:维护人员|人员|师傅|工程师)?\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})",
        r"把\s*([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})\s*(?:的)?(?:区域|邮箱|技能|负责)",
        r"([\u4e00-\u9fa5A-Za-z0-9_·.-]{2,32})(?:师傅|工程师)\s*(?:区域|邮箱|技能|负责|删除|禁用)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip(" ，,。；;：:")
            for suffix in ("师傅", "工程师", "人员"):
                if value.endswith(suffix):
                    value = value[: -len(suffix)]
            return value.strip() or None
    return _extract_assignee_name(message)


def _extract_email(message: str) -> Optional[str]:
    match = re.search(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", message)
    return match.group(0).strip() if match else None


def _extract_hi_threshold(message: str) -> Optional[float]:
    patterns = [
        r"(?:HI|hi|健康指数)?\s*(?:告警)?\s*阈值\s*(?:改成|改为|调整为|设为|设置为|为|是|到|:|：)?\s*(\d+(?:\.\d+)?)",
        r"(?:HI|hi|健康指数)\s*(?:告警)?\s*(?:改成|改为|调整为|设为|设置为|到)\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return float(match.group(1))
    return None


def _extract_threshold_patch(message: str) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    threshold = _extract_hi_threshold(message)
    if threshold is not None:
        patch["hi_threshold"] = threshold

    email = _extract_email(message)
    if email:
        patch["email_address"] = email
        if "邮件" in message or "email" in message.lower():
            patch["email_enabled"] = True

    if any(keyword in message for keyword in ("关闭邮件", "禁用邮件", "停用邮件", "取消邮件")):
        patch["email_enabled"] = False
    elif any(keyword in message for keyword in ("开启邮件", "启用邮件", "打开邮件", "邮件通知")):
        patch["email_enabled"] = True

    if any(keyword in message for keyword in ("关闭企业微信", "禁用企业微信", "停用企业微信", "取消企业微信", "关闭微信")):
        patch["wechat_enabled"] = False
    elif any(keyword in message for keyword in ("开启企业微信", "启用企业微信", "打开企业微信", "企业微信通知", "微信通知")):
        patch["wechat_enabled"] = True
    return patch


def _extract_region(message: str) -> Optional[str]:
    patterns = [
        r"(?:区域|负责区域|组别|风场)(?:改成|改为|调整为|设为|为|是|:|：)?\s*([\u4e00-\u9fa5A-Za-z0-9_-]{1,12})",
        r"([ABCabc])\s*组",
        r"风场\s*([ABCabc])",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip()
            if re.fullmatch(r"[ABCabc]", value):
                return f"{value.upper()}组"
            return value
    return None


def _extract_skills(message: str) -> list[str]:
    skills: list[str] = []
    lowered = message.lower()
    for keyword, skill in SKILL_KEYWORDS.items():
        if keyword.lower() in lowered and skill not in skills:
            skills.append(skill)
    return skills


def _extract_knowledge_node_id(message: str) -> Optional[int]:
    patterns = [
        r"知识(?:节点)?\s*#?\s*(\d{1,8})",
        r"节点\s*#?\s*(\d{1,8})",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            return int(match.group(1))
    return None


def _extract_knowledge_fault_type(message: str) -> Optional[str]:
    patterns = [
        r"新增\s*([\u4e00-\u9fa5A-Za-z0-9_ -]{2,48}?)(?:处理方案|故障知识|知识|方案)",
        r"更新\s*([\u4e00-\u9fa5A-Za-z0-9_ -]{2,48}?)(?:处理方案|故障知识|知识|方案)",
        r"删除(?:重复的)?\s*([\u4e00-\u9fa5A-Za-z0-9_ -]{2,48}?)(?:知识节点|故障知识|知识)",
        r"把\s*([\u4e00-\u9fa5A-Za-z0-9_ -]{2,48}?)(?:知识|故障知识)\s*标记",
        r"([\u4e00-\u9fa5A-Za-z0-9_ -]{2,48}?)(?:知识节点|故障知识|处理方案|知识)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(1).strip(" ，,。；;：:")
            value = re.sub(r"^(重复的|这个|该)", "", value).strip()
            return value or None
    return _extract_fault_keyword(message)


def _extract_knowledge_review_action(message: str) -> Optional[str]:
    if any(keyword in message for keyword in ("拒绝", "驳回", "不通过", "删除这个候选")):
        return "reject"
    if any(keyword in message for keyword in ("已验证", "验证", "标记可信", "通过", "审核通过")):
        return "verify"
    return None


def _knowledge_category_for_fault(fault_type: str) -> str:
    lowered = fault_type.lower()
    if any(token.lower() in lowered for token in ("齿轮箱", "gearbox")):
        return "gearbox"
    if any(token.lower() in lowered for token in ("轴承", "bearing")):
        return "bearing"
    if any(token.lower() in lowered for token in ("叶片", "blade", "erosion")):
        return "blade"
    if any(token.lower() in lowered for token in ("发电机", "generator")):
        return "generator"
    return "general"


def _looks_like_knowledge_upsert_intent(message: str) -> bool:
    return any(keyword in message for keyword in ("新增知识", "更新知识库", "沉淀经验", "故障知识", "处理方案")) and not any(keyword in message for keyword in ("删除", "拒绝", "审核", "验证"))


def _looks_like_knowledge_review_intent(message: str) -> bool:
    return any(keyword in message for keyword in ("审核知识", "验证知识", "拒绝知识", "标记可信", "已验证", "审核通过")) or (
        "知识" in message and any(keyword in message for keyword in ("拒绝", "验证", "通过"))
    )


def _looks_like_knowledge_delete_intent(message: str) -> bool:
    return "知识" in message and any(keyword in message for keyword in ("删除", "移除"))


def _looks_like_advance_workorder_intent(message: str) -> bool:
    return bool(_extract_workorder_ref(message)) and bool(_extract_target_workorder_status(message))


def _looks_like_add_record_intent(message: str) -> bool:
    return bool(_extract_workorder_ref(message)) and any(keyword in message for keyword in ("追加记录", "维修记录", "处理说明", "备件", "成本", "停机", "备注", "记录"))


def _looks_like_update_workorder_fields_intent(message: str) -> bool:
    if not _extract_workorder_ref(message):
        return False
    return any(keyword in message for keyword in ("修改工单", "更新工单", "调整优先级", "优先级改", "补充描述", "修改成本", "预计成本", "成本估算", "截止", "到期", "标题改", "描述改", "故障类型改"))


def _looks_like_cancel_workorder_intent(message: str) -> bool:
    return bool(_extract_workorder_ref(message)) and any(keyword in message for keyword in ("取消工单", "删除工单", "作废工单", "撤销工单", "取消", "删除", "作废", "撤销"))


def _looks_like_fault_status_intent(message: str) -> bool:
    return ("故障" in message) and bool(_extract_fault_processing_status(message)) and (bool(_extract_fault_id(message)) or bool(_extract_turbine_ref(message)))


def _looks_like_create_fault_intent(message: str) -> bool:
    has_create = any(keyword in message for keyword in ("登记", "新增", "创建", "记录", "录入"))
    has_fault = any(keyword in message for keyword in ("故障", "异常", "fault"))
    return has_create and has_fault and "工单" not in message and not _extract_fault_processing_status(message)


def _looks_like_update_fault_intent(message: str) -> bool:
    if "故障" not in message or _extract_fault_processing_status(message):
        return False
    if any(keyword in message for keyword in ("工单", "知识")):
        return False
    has_target = bool(_extract_fault_id(message) or _extract_turbine_ref(message)) or "最新故障" in message or "这个故障" in message
    has_patch = bool(_extract_fault_patch_fields(message)) or any(keyword in message for keyword in ("调整置信度", "修改置信度", "改优先级", "优先级改", "故障类型改"))
    has_update = any(keyword in message for keyword in ("更新", "修改", "调整", "改成", "改为", "设为"))
    return has_target and has_update and has_patch


def _looks_like_delete_fault_intent(message: str) -> bool:
    if any(keyword in message for keyword in ("工单", "知识")):
        return False
    return "故障" in message and any(keyword in message for keyword in ("删除", "移除", "清除", "清理")) and not _extract_fault_processing_status(message)


def _looks_like_rul_refresh_intent(message: str) -> bool:
    lowered = message.lower()
    return any(keyword in lowered for keyword in ("rul", "剩余寿命", "寿命预测")) and any(keyword in message for keyword in ("刷新", "重新计算", "重新预测", "更新"))


def _looks_like_health_refresh_intent(message: str) -> bool:
    lowered = message.lower()
    has_health = any(keyword in lowered for keyword in ("hi", "健康指数", "健康状态", "风机状态"))
    has_refresh = any(keyword in message for keyword in ("刷新", "重新计算", "重新评估", "更新", "重算"))
    return has_health and has_refresh and "rul" not in lowered and "剩余寿命" not in message


def _looks_like_auto_detection_intent(message: str) -> bool:
    return any(keyword in message for keyword in ("自动检测", "自动故障检测", "故障检测", "故障识别", "运行检测", "检测故障", "诊断这台", "诊断该", "做故障识别", "做诊断")) or (
        "诊断" in message and any(keyword in message for keyword in ("风机", "齿轮箱", "轴承", "叶片", "发电机", "主轴"))
    )


def _looks_like_batch_detection_intent(message: str) -> bool:
    has_batch = any(keyword in message for keyword in ("批量", "全场", "所有", "全部", "A组", "B组", "C组", "风场A", "风场B", "风场C", "预警风机", "故障风机", "异常风机"))
    has_detection = any(keyword in message for keyword in ("故障检测", "自动检测", "故障识别", "批量检测", "批量诊断", "检测", "诊断"))
    return has_batch and has_detection


def _looks_like_generate_schedule_intent(message: str) -> bool:
    has_schedule = any(keyword in message for keyword in ("维护排程", "维护计划", "维护日历", "排程", "排班", "检修计划"))
    has_generate = any(keyword in message for keyword in ("生成", "制定", "安排", "规划", "排一下", "排个", "排一份"))
    return has_schedule and has_generate


def _looks_like_delete_ai_provider_intent(message: str) -> bool:
    return any(keyword in message for keyword in ("删除", "移除", "清除")) and any(keyword in message for keyword in ("供应商", "AI配置", "API KEY", "apikey", "api key", "DeepSeek", "Kimi", "通义", "千问", "OpenAI", "智谱", "Ollama"))


def _looks_like_test_ai_provider_intent(message: str) -> bool:
    has_provider = any(keyword.lower() in message.lower() for keyword in ("供应商", "AI配置", "API KEY", "apikey", "api key", "DeepSeek", "Kimi", "通义", "千问", "OpenAI", "智谱", "Ollama", "DashScope"))
    has_test = any(keyword in message for keyword in ("测试", "验证", "检查", "连通", "连接", "是否可用", "能不能用", "可用吗"))
    return has_provider and has_test


def _looks_like_upsert_ai_provider_intent(message: str) -> bool:
    if _looks_like_delete_ai_provider_intent(message) or _looks_like_test_ai_provider_intent(message):
        return False
    has_provider = any(keyword.lower() in message.lower() for keyword in ("供应商", "AI配置", "API KEY", "apikey", "api key", "DeepSeek", "Kimi", "通义", "千问", "OpenAI", "智谱", "Ollama", "DashScope"))
    has_change = any(keyword in message for keyword in ("新增", "添加", "创建", "保存", "配置", "更新", "修改", "改成", "改为", "设置", "设为", "启用", "禁用", "开启", "关闭"))
    return has_provider and has_change


def _looks_like_update_threshold_intent(message: str) -> bool:
    has_target = any(keyword in message for keyword in ("阈值", "告警", "通知渠道", "邮件通知", "企业微信通知", "微信通知")) or bool(_extract_hi_threshold(message))
    has_change = any(keyword in message for keyword in ("改成", "改为", "调整", "设置", "设为", "开启", "启用", "关闭", "禁用", "停用", "取消"))
    return has_target and has_change


def _looks_like_personnel_upsert_intent(message: str) -> bool:
    has_personnel = any(keyword in message for keyword in ("维护人员", "人员", "师傅", "工程师", "王工", "张工", "李工"))
    has_change = any(keyword in message for keyword in ("新增", "添加", "创建", "修改", "更新", "改成", "改为", "区域", "邮箱", "技能", "负责"))
    return has_personnel and has_change


def _looks_like_personnel_delete_intent(message: str) -> bool:
    has_personnel = any(keyword in message for keyword in ("维护人员", "人员", "师傅", "工程师", "王工", "张工", "李工"))
    return has_personnel and any(keyword in message for keyword in ("删除", "禁用", "移除"))


def _looks_like_assign_intent(message: str) -> bool:
    return any(keyword in message for keyword in ("分配", "派给", "派工", "指派", "交给", "安排给", "负责", "处理")) and bool(_extract_workorder_ref(message))


def _looks_like_create_workorder_intent(message: str) -> bool:
    has_create = any(keyword in message for keyword in ("创建", "新建", "发起", "生成", "开一份", "开个", "开", "建立", "建一个", "建个"))
    has_workorder = "工单" in message or "维修任务" in message or ("维修" in message and "风机" in message)
    return has_create and has_workorder


def _classify_task_type(message: str) -> str:
    if _looks_like_create_workorder_intent(message):
        return "WORKFLOW"
    if _looks_like_create_fault_intent(message):
        return "WORKFLOW"
    if _looks_like_update_fault_intent(message) or _looks_like_delete_fault_intent(message):
        return "WRITE"
    if _looks_like_update_workorder_fields_intent(message) or _looks_like_cancel_workorder_intent(message):
        return "WRITE"
    if _looks_like_personnel_upsert_intent(message) or _looks_like_personnel_delete_intent(message):
        return "WORKFLOW"
    if _looks_like_knowledge_upsert_intent(message) or _looks_like_knowledge_review_intent(message) or _looks_like_knowledge_delete_intent(message):
        return "WORKFLOW"
    if _looks_like_advance_workorder_intent(message) or _looks_like_add_record_intent(message):
        return "WRITE"
    if _looks_like_batch_detection_intent(message):
        return "WORKFLOW"
    if _looks_like_auto_detection_intent(message):
        return "WORKFLOW"
    if _looks_like_generate_schedule_intent(message):
        return "WORKFLOW"
    if _looks_like_test_ai_provider_intent(message):
        return "WORKFLOW"
    if _looks_like_upsert_ai_provider_intent(message):
        return "WORKFLOW"
    if _looks_like_update_threshold_intent(message):
        return "WRITE"
    if _looks_like_fault_status_intent(message) or _looks_like_rul_refresh_intent(message) or _looks_like_delete_ai_provider_intent(message):
        return "WRITE"
    if _looks_like_health_refresh_intent(message):
        return "WORKFLOW"
    if _looks_like_assign_intent(message):
        return "WRITE"
    if any(token in message for token in ("如果", "然后", "并且", "同时", "再")):
        return "COMPOSITE"
    if any(token in message for token in ("查看", "打开", "查询", "看看", "总结", "分析", "筛选")):
        return "READ"
    return "READ"


async def _resolve_workorder(db: AsyncSession, workorder_id: int) -> Optional[WorkOrder]:
    resolution = await resolve_workorder_by_ref(db, workorder_id)
    return resolution.entity


async def _active_workorder_count(db: AsyncSession, assignee: str) -> int:
    result = await db.execute(
        select(WorkOrder).where(
            WorkOrder.assignee == assignee,
            WorkOrder.status.notin_(["completed", "closed", "cancelled"]),
        )
    )
    return len(list(result.scalars().all()))


async def _store_pending_action(
    db: AsyncSession,
    *,
    user: User,
    raw_message: str,
    task_type: str,
    action: str,
    params: dict[str, Any],
    before: dict[str, Any],
    after: dict[str, Any],
    warnings: list[str],
    parsed_slots: dict[str, Any],
    confidence: float,
    workflow: str | None = None,
    steps: list[str] | None = None,
) -> str:
    request_id = f"act_{uuid.uuid4().hex[:16]}"
    pending = PendingAction(
        request_id=request_id,
        user_id=user.id,
        raw_message=raw_message,
        task_type=task_type,
        action=action,
        params=params,
        before=before,
        after=after,
        warnings=warnings,
        created_at=_utc_now(),
        expires_at=_utc_now() + PENDING_ACTION_TTL,
    )
    _PENDING_ACTIONS[request_id] = pending
    parsed_action: dict[str, Any] = {
        "task_type": task_type,
        "action": action,
        "slots": parsed_slots,
        "confidence": confidence,
        "warnings": warnings,
    }
    if workflow:
        parsed_action["workflow"] = workflow
    if steps:
        parsed_action["steps"] = steps
    db.add(
        AgentActionLog(
            request_id=request_id,
            user_id=user.id,
            raw_message=raw_message,
            parsed_action=parsed_action,
            action=action,
            params=_audit_safe_params(action, params),
            before_state=before,
            after_state=after,
            status="pending",
        )
    )
    await db.commit()
    return request_id


async def _load_pending_action(db: AsyncSession, *, user: User, request_id: str) -> Optional[PendingAction]:
    pending = _PENDING_ACTIONS.get(request_id)
    if pending and pending.user_id == user.id:
        return pending

    result = await db.execute(
        select(AgentActionLog).where(
            AgentActionLog.request_id == request_id,
            AgentActionLog.user_id == user.id,
            AgentActionLog.status == "pending",
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        return None

    parsed_action = log.parsed_action or {}
    created_at = _as_aware_utc(log.created_at)
    restored = PendingAction(
        request_id=request_id,
        user_id=user.id,
        raw_message=str(log.raw_message or ""),
        task_type=str(parsed_action.get("task_type") or "WRITE"),
        action=log.action,
        params=dict(log.params or {}),
        before=dict(log.before_state or {}),
        after=dict(log.after_state or {}),
        warnings=list(parsed_action.get("warnings") or []),
        created_at=created_at,
        expires_at=created_at + PENDING_ACTION_TTL,
    )
    _PENDING_ACTIONS[request_id] = restored
    return restored


async def _claim_pending_action(
    db: AsyncSession,
    *,
    user: User,
    request_id: str,
) -> Optional[PendingAction]:
    """P0-13: Atomically claim a pending action (status: pending → executing).

    Uses an UPDATE with WHERE status='pending' to ensure only one caller
    can claim the action. Returns the pending action if claimed, None otherwise.
    """
    from sqlalchemy import update

    now = _utc_now()
    result = await db.execute(
        update(AgentActionLog)
        .where(
            AgentActionLog.request_id == request_id,
            AgentActionLog.user_id == user.id,
            AgentActionLog.status == "pending",
        )
        .values(status="executing", executed_at=now)
    )
    if result.rowcount == 0:
        return None  # Already claimed or not found

    await db.commit()

    # Reload the claimed log
    reloaded = await db.execute(
        select(AgentActionLog).where(AgentActionLog.request_id == request_id)
    )
    log = reloaded.scalar_one_or_none()
    if not log:
        return None

    parsed_action = log.parsed_action or {}
    created_at = _as_aware_utc(log.created_at)
    return PendingAction(
        request_id=request_id,
        user_id=user.id,
        raw_message=str(log.raw_message or ""),
        task_type=str(parsed_action.get("task_type") or "WRITE"),
        action=log.action,
        params=dict(log.params or {}),
        before=dict(log.before_state or {}),
        after=dict(log.after_state or {}),
        warnings=list(parsed_action.get("warnings") or []),
        created_at=created_at,
        expires_at=created_at + PENDING_ACTION_TTL,
    )


async def plan_agent_action(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    page_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Plan a supported Agent action and return a confirmation payload."""
    task_type = _classify_task_type(message)
    if task_type == "COMPOSITE":
        return {
            "status": "unsupported",
            "task_type": "COMPOSITE",
            "confidence": 0.5,
            "error_code": "composite_not_supported",
            "error_message": "组合任务已识别，但当前第一版尚未启用组合编排，将回退到原有 Agent 流程。",
        }
    if task_type == "READ":
        return {
            "status": "unsupported",
            "task_type": "READ",
            "confidence": 0.5,
            "error_code": "read_task_fallback",
            "error_message": "查看类任务交由页面操作或只读数据工具处理。",
        }

    if _looks_like_create_workorder_intent(message):
        if not _can_execute_agent_action(user, "create_workorder_record"):
            return _permission_denied_response("create_workorder_record")
        return await _plan_create_workorder(db, user=user, message=message)
    if _looks_like_create_fault_intent(message):
        if not _can_execute_agent_action(user, "create_fault_record"):
            return _permission_denied_response("create_fault_record")
        return await _plan_create_fault_record(db, user=user, message=message)
    if _looks_like_cancel_workorder_intent(message):
        if not _can_execute_agent_action(user, "cancel_workorder_record"):
            return _permission_denied_response("cancel_workorder_record", task_type="WRITE")
        return await _plan_cancel_workorder(db, user=user, message=message)
    if _looks_like_update_workorder_fields_intent(message):
        if not _can_execute_agent_action(user, "update_workorder_record"):
            return _permission_denied_response("update_workorder_record", task_type="WRITE")
        return await _plan_update_workorder_fields(db, user=user, message=message)
    if _looks_like_add_record_intent(message):
        if not _can_execute_agent_action(user, "add_maintenance_record"):
            return _permission_denied_response("add_maintenance_record", task_type="WRITE")
        return await _plan_add_maintenance_record(db, user=user, message=message)
    if _looks_like_advance_workorder_intent(message):
        if not _can_execute_agent_action(user, "advance_workorder_status"):
            return _permission_denied_response("advance_workorder_status", task_type="WRITE")
        return await _plan_advance_workorder_status(db, user=user, message=message)
    if _looks_like_fault_status_intent(message):
        if not _can_execute_agent_action(user, "update_fault_processing_status"):
            return _permission_denied_response("update_fault_processing_status", task_type="WRITE")
        return await _plan_fault_processing_status(db, user=user, message=message)
    if _looks_like_delete_fault_intent(message):
        if not _can_execute_agent_action(user, "delete_fault_record"):
            return _permission_denied_response("delete_fault_record", task_type="WRITE")
        return await _plan_delete_fault_record(db, user=user, message=message)
    if _looks_like_update_fault_intent(message):
        if not _can_execute_agent_action(user, "update_fault_record"):
            return _permission_denied_response("update_fault_record", task_type="WRITE")
        return await _plan_update_fault_record(db, user=user, message=message)
    if _looks_like_batch_detection_intent(message):
        if not _can_execute_agent_action(user, "run_batch_fault_detection"):
            return _permission_denied_response("run_batch_fault_detection")
        return await _plan_batch_fault_detection(db, user=user, message=message)
    if _looks_like_auto_detection_intent(message):
        if not _can_execute_agent_action(user, "run_auto_fault_detection"):
            return _permission_denied_response("run_auto_fault_detection")
        return await _plan_auto_fault_detection(db, user=user, message=message, page_context=page_context)
    if _looks_like_health_refresh_intent(message):
        if not _can_execute_agent_action(user, "refresh_health_indexes"):
            return _permission_denied_response("refresh_health_indexes")
        return await _plan_refresh_health_indexes(db, user=user, message=message)
    if _looks_like_rul_refresh_intent(message):
        if not _can_execute_agent_action(user, "refresh_rul_predictions"):
            return _permission_denied_response("refresh_rul_predictions", task_type="WRITE")
        return await _plan_refresh_rul_predictions(db, user=user, message=message)
    if _looks_like_generate_schedule_intent(message):
        if not _can_execute_agent_action(user, "generate_maintenance_schedule"):
            return _permission_denied_response("generate_maintenance_schedule")
        return await _plan_generate_maintenance_schedule(db, user=user, message=message)
    if _looks_like_update_threshold_intent(message):
        if not _can_execute_agent_action(user, "update_threshold_config"):
            return _permission_denied_response("update_threshold_config", task_type="WRITE")
        return await _plan_update_threshold_config(db, user=user, message=message)
    if _looks_like_test_ai_provider_intent(message):
        if not _can_execute_agent_action(user, "test_ai_provider_connection"):
            return _permission_denied_response("test_ai_provider_connection")
        return await _plan_test_ai_provider(db, user=user, message=message)
    if _looks_like_upsert_ai_provider_intent(message):
        if not _can_execute_agent_action(user, "upsert_ai_provider_config"):
            return _permission_denied_response("upsert_ai_provider_config")
        return await _plan_upsert_ai_provider(db, user=user, message=message)
    if _looks_like_delete_ai_provider_intent(message):
        if not _can_execute_agent_action(user, "delete_ai_provider_config"):
            return _permission_denied_response("delete_ai_provider_config", task_type="WRITE")
        return await _plan_delete_ai_provider(db, user=user, message=message)
    if _looks_like_knowledge_delete_intent(message):
        if not _can_execute_agent_action(user, "delete_knowledge_node"):
            return _permission_denied_response("delete_knowledge_node")
        return await _plan_delete_knowledge_node(db, user=user, message=message)
    if _looks_like_knowledge_review_intent(message):
        if not _can_execute_agent_action(user, "review_knowledge_node"):
            return _permission_denied_response("review_knowledge_node")
        return await _plan_review_knowledge_node(db, user=user, message=message)
    if _looks_like_knowledge_upsert_intent(message):
        if not _can_execute_agent_action(user, "upsert_knowledge_node"):
            return _permission_denied_response("upsert_knowledge_node")
        return await _plan_upsert_knowledge_node(db, user=user, message=message)
    if _looks_like_personnel_delete_intent(message):
        if not _can_execute_agent_action(user, "delete_personnel"):
            return _permission_denied_response("delete_personnel")
        return await _plan_delete_personnel(db, user=user, message=message)
    if _looks_like_personnel_upsert_intent(message):
        if not _can_execute_agent_action(user, "upsert_personnel"):
            return _permission_denied_response("upsert_personnel")
        return await _plan_upsert_personnel(db, user=user, message=message)
    if _looks_like_assign_intent(message):
        if not _can_execute_agent_action(user, "assign_workorder"):
            return _permission_denied_response("assign_workorder", task_type="WRITE")
        return await _plan_assign_workorder(db, user=user, message=message)

    return {
        "status": "unsupported",
        "task_type": task_type,
        "confidence": 0.2,
        "error_code": "action_not_supported",
        "error_message": "该变更类任务尚未进入受控动作白名单。",
    }


async def _plan_assign_workorder(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    assignee_name = _extract_assignee_name(message)
    missing = []
    if not workorder_id:
        missing.append("workorder_ref")
    if not assignee_name:
        missing.append("assignee_name")
    if missing:
        prompts = {
            "workorder_ref": "请说明具体工单编号，例如 WO-0003。",
            "assignee_name": "请说明要分配给哪位师傅。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.55,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    workorder = await _resolve_workorder(db, workorder_id)
    if not workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.8,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}。",
        }
    if workorder.status in FINAL_STATUSES:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.88,
            "error_code": "invalid_status_transition",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许重新派工。",
        }

    assignee_resolution = await resolve_personnel_by_name(db, assignee_name)
    assignee, candidates = assignee_resolution.entity, assignee_resolution.candidates
    if not assignee:
        if candidates:
            candidate_names = "、".join(item.username for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.68,
                "missing_slots": ["assignee_name"],
                "clarification_question": f"找到多个相近人员：{candidate_names}。请明确要分配给谁。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.82,
            "error_code": "assignee_not_found",
            "error_message": f"未找到名为“{assignee_name}”的可派工人员。",
        }

    warnings: list[str] = []
    if workorder.assignee and workorder.assignee != assignee.username:
        warnings.append(f"该工单当前负责人为 {workorder.assignee}，确认后将被覆盖。")
    active_count = await _active_workorder_count(db, assignee.username)
    if active_count >= 5:
        warnings.append(f"{assignee.username} 当前已有 {active_count} 个未完成工单，请确认负载是否可接受。")

    before = _workorder_state(workorder)
    after = {
        **before,
        "status": "assigned" if workorder.status == "pending" else workorder.status,
        "assignee": assignee.username,
        "assignee_id": assignee.id,
        "assignee_email": assignee.email,
    }
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="assign_workorder",
        params={"workorder_id": workorder.id, "assignee_id": assignee.id},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"workorder_ref": _workorder_ref(workorder), "assignee_name": assignee.username},
        confidence=0.9,
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "assign_workorder",
        "confidence": 0.9,
        "confirmation": {
            "title": "确认分配工单",
            "summary": f"将 {_workorder_ref(workorder)} 分配给 {assignee.username}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_update_workorder_fields(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    patch_fields = _extract_workorder_patch_fields(message)
    missing = []
    if not workorder_id:
        missing.append("workorder_ref")
    if not patch_fields:
        missing.append("patch_fields")
    if missing:
        prompts = {
            "workorder_ref": "请说明要修改哪张工单，例如 WO-0003。",
            "patch_fields": "请说明要修改哪些字段，例如优先级、标题、描述、预计成本或截止日期。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    workorder = await _resolve_workorder(db, workorder_id)
    if not workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.8,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}。",
        }
    if workorder.status in {"closed", "cancelled"}:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.84,
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许修改核心字段。",
        }

    params_patch: dict[str, Any] = {}
    for key, value in patch_fields.items():
        if isinstance(value, datetime):
            params_patch[key] = value.isoformat()
        else:
            params_patch[key] = value
    before = _workorder_state(workorder)
    after = {**before, **params_patch, "updated_by_agent": True}
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="update_workorder_record",
        params={"workorder_id": workorder.id, "patch_fields": params_patch},
        before=before,
        after=after,
        warnings=["该动作会修改工单核心字段，请确认执行前后差异。"],
        parsed_slots={"workorder_ref": _workorder_ref(workorder), "patch_fields": params_patch},
        confidence=0.84,
        workflow="workorder.update_fields",
        steps=[
            "resolve_workorder_by_ref",
            "validate_workorder_patch",
            "require_confirmation",
            "update_workorder_record",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "update_workorder_record",
        "workflow": "workorder.update_fields",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认修改工单字段",
            "summary": f"修改 {_workorder_ref(workorder)} 的 {len(params_patch)} 个字段",
            "before": before,
            "after": after,
            "warnings": ["该动作会修改工单核心字段，请确认执行前后差异。"],
        },
    }


async def _plan_cancel_workorder(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    reason = _extract_reason(message)
    missing = []
    if not workorder_id:
        missing.append("workorder_ref")
    if not reason:
        missing.append("reason")
    if missing:
        prompts = {
            "workorder_ref": "请说明要取消或删除的工单编号，例如 WO-0003。",
            "reason": "请说明取消或删除原因，便于审计。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    workorder = await _resolve_workorder(db, workorder_id)
    if not workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.8,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}。",
        }
    if workorder.status in {"closed", "cancelled"}:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.84,
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许重复取消。",
        }

    before = _workorder_state(workorder)
    after = {
        **before,
        "status": "cancelled",
        "cancelled_at": _utc_now().isoformat(),
        "cancel_reason": reason,
    }
    warnings = ["取消工单会将状态置为 cancelled，并写入维护记录；不做物理删除。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="cancel_workorder_record",
        params={"workorder_id": workorder.id, "reason": reason},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"workorder_ref": _workorder_ref(workorder), "reason": reason},
        confidence=0.86,
        workflow="workorder.cancel_or_delete",
        steps=[
            "resolve_workorder_by_ref",
            "validate_workorder_cancel",
            "require_confirmation",
            "cancel_workorder_record",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "cancel_workorder_record",
        "workflow": "workorder.cancel_or_delete",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认取消工单",
            "summary": f"取消 {_workorder_ref(workorder)}，原因：{reason}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


def _validate_workorder_transition(current: str | None, target: str) -> tuple[bool, str | None]:
    current_status = current or "pending"
    if current_status == target:
        return False, f"工单当前已经是 {WORKORDER_STATUS_LABELS.get(target, target)}。"
    allowed = WORKORDER_TRANSITIONS.get(current_status, set())
    if target not in allowed:
        label = WORKORDER_STATUS_LABELS.get(current_status, current_status)
        target_label = WORKORDER_STATUS_LABELS.get(target, target)
        return False, f"工单状态不允许从 {label} 直接变更为 {target_label}。"
    return True, None


async def _plan_advance_workorder_status(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    target_status = _extract_target_workorder_status(message)
    missing = []
    if not workorder_id:
        missing.append("workorder_ref")
    if not target_status:
        missing.append("target_status")
    if missing:
        prompts = {
            "workorder_ref": "请说明具体工单编号，例如 WO-0003。",
            "target_status": "请说明目标状态，例如 处理中、待复核、已完成或已关闭。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    workorder = await _resolve_workorder(db, workorder_id)
    if not workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.82,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}。",
        }

    ok, reason = _validate_workorder_transition(workorder.status, target_status)
    if not ok:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.86,
            "error_code": "invalid_status_transition",
            "error_message": reason,
        }

    note = _extract_record_content(message) or _extract_reason(message)
    before = _workorder_state(workorder)
    after = {
        **before,
        "status": target_status,
        "completed_at": _utc_now().isoformat() if target_status == "completed" else None,
        "cancelled_at": _utc_now().isoformat() if target_status == "cancelled" else None,
        "maintenance_note": note,
    }
    warnings: list[str] = []
    if target_status in FINAL_STATUSES and not note:
        warnings.append("目标状态为终态，但未提供处理说明；建议确认后补充维护记录。")

    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="advance_workorder_status",
        params={"workorder_id": workorder.id, "target_status": target_status, "note": note},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "workorder_ref": _workorder_ref(workorder),
            "target_status": target_status,
            "maintenance_note": note,
        },
        confidence=0.88,
        workflow="workorder.advance_status",
        steps=[
            "resolve_workorder_by_ref",
            "validate_workorder_status_transition",
            "require_confirmation",
            "advance_workorder_status",
            "verify_status_changed",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "advance_workorder_status",
        "workflow": "workorder.advance_status",
        "confidence": 0.88,
        "confirmation": {
            "title": "确认推进工单状态",
            "summary": f"将 {_workorder_ref(workorder)} 从 {WORKORDER_STATUS_LABELS.get(workorder.status, workorder.status)} 变更为 {WORKORDER_STATUS_LABELS.get(target_status, target_status)}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_add_maintenance_record(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    content = _extract_record_content(message)
    missing = []
    if not workorder_id:
        missing.append("workorder_ref")
    if not content:
        missing.append("record_content")
    if missing:
        prompts = {
            "workorder_ref": "请说明具体工单编号，例如 WO-0003。",
            "record_content": "请说明要追加的维修记录内容，例如“已更换主轴承”。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    workorder = await _resolve_workorder(db, workorder_id)
    if not workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.82,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}。",
        }
    if workorder.status in {"closed", "cancelled"}:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.86,
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许追加维修记录。",
        }

    target_status = _extract_target_workorder_status(message)
    if target_status:
        ok, reason = _validate_workorder_transition(workorder.status, target_status)
        if not ok:
            return {
                "status": "error",
                "task_type": "WRITE",
                "confidence": 0.84,
                "error_code": "invalid_status_transition",
                "error_message": reason,
            }
    cost_actual = _extract_cost_actual(message)
    downtime_hours = _extract_downtime_hours(message)
    before = _workorder_state(workorder)
    after = {
        **before,
        "status": target_status or workorder.status,
        "new_record": {
            "action_type": "progress",
            "content": content,
            "cost_actual": cost_actual,
            "downtime_hours": downtime_hours,
        },
        "cost_actual": cost_actual if cost_actual is not None else workorder.cost_actual,
        "downtime_hours": downtime_hours if downtime_hours is not None else workorder.downtime_hours,
    }
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="add_maintenance_record",
        params={
            "workorder_id": workorder.id,
            "content": content,
            "target_status": target_status,
            "cost_actual": cost_actual,
            "downtime_hours": downtime_hours,
        },
        before=before,
        after=after,
        warnings=[],
        parsed_slots={
            "workorder_ref": _workorder_ref(workorder),
            "record_content": content,
            "target_status": target_status,
            "cost_actual": cost_actual,
            "downtime_hours": downtime_hours,
        },
        confidence=0.86,
        workflow="workorder.add_progress_record",
        steps=[
            "resolve_workorder_by_ref",
            "validate_maintenance_record",
            "require_confirmation",
            "add_maintenance_record",
            "verify_record_created",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "add_maintenance_record",
        "workflow": "workorder.add_progress_record",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认追加维修记录",
            "summary": f"向 {_workorder_ref(workorder)} 追加维修记录",
            "before": before,
            "after": after,
            "warnings": [],
        },
    }


async def _plan_create_workorder(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    turbine_ref = _extract_turbine_ref(message)
    if not turbine_ref:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.6,
            "missing_slots": ["turbine_ref"],
            "clarification_question": "请说明要为哪台风机创建维修工单，例如 YD-B-007。",
        }

    turbine_resolution = await resolve_turbine_by_ref(db, turbine_ref)
    turbine, candidates = turbine_resolution.entity, turbine_resolution.candidates
    if not turbine:
        if candidates:
            names = "、".join(item.name for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.68,
                "missing_slots": ["turbine_ref"],
                "clarification_question": f"找到多个相近风机：{names}。请明确风机编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "turbine_not_found",
            "error_message": f"未找到风机 {turbine_ref}。",
        }

    assignee_name = _extract_assignee_name(message)
    assignee: Optional[User] = None
    if assignee_name:
        assignee_resolution = await resolve_personnel_by_name(db, assignee_name)
        assignee, candidates = assignee_resolution.entity, assignee_resolution.candidates
        if not assignee:
            if candidates:
                names = "、".join(item.username for item in candidates)
                return {
                    "status": "needs_clarification",
                    "task_type": "CLARIFY",
                    "confidence": 0.68,
                    "missing_slots": ["assignee_name"],
                    "clarification_question": f"找到多个相近人员：{names}。请明确要分配给谁。",
                }
            return {
                "status": "error",
                "task_type": "WRITE",
                "confidence": 0.78,
                "error_code": "assignee_not_found",
                "error_message": f"未找到名为“{assignee_name}”的可派工人员。",
            }

    faults = await query_turbine_fault_context(db, turbine.id)
    fault_context = fault_context_state(faults)
    after = draft_create_workorder_fields(
        turbine=turbine,
        faults=faults,
        message=message,
        assignee_name=assignee.username if assignee else None,
        assignee_id=assignee.id if assignee else None,
        assignee_email=assignee.email if assignee else None,
    )
    before = {"turbine": _turbine_state(turbine), "fault_context": fault_context, "workorder": None}
    warnings: list[str] = []
    if after.get("fault_type") == "待诊断":
        warnings.append("未查询到明确活跃故障，系统已按待诊断维修任务草拟，确认前请核对标题和描述。")
    workflow_steps = [
        "resolve_turbine_by_ref",
        "query_turbine_fault_context",
        "draft_workorder_fields",
        "resolve_personnel_if_present",
        "validate_workorder_draft",
        "require_confirmation",
        "create_workorder_record",
        "verify_workorder_created",
        "present_result",
    ]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="create_workorder_record",
        params={
            "turbine_id": turbine.id,
            "fault_id": after.get("fault_id"),
            "title": after["title"],
            "description": after["description"],
            "priority": after["priority"],
            "fault_type": after["fault_type"],
            "assignee_id": assignee.id if assignee else None,
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "turbine_ref": turbine.name,
            "assignee_name": assignee.username if assignee else None,
            "priority": after["priority"],
            "fault_type": after["fault_type"],
        },
        confidence=0.86,
        workflow="create_workorder_workflow",
        steps=workflow_steps,
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "create_workorder_record",
        "workflow": "create_workorder_workflow",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认创建维修工单",
            "summary": (
                f"为 {turbine.name} 创建维修工单，系统草拟优先级为 {after['priority']}，"
                + (f"负责人为 {assignee.username}" if assignee else "暂不指定维护人员")
            ),
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_create_fault_record(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    turbine_ref = _extract_turbine_ref(message)
    fault_type = _extract_create_fault_type(message, turbine_ref)
    missing: list[str] = []
    if not turbine_ref:
        missing.append("turbine_ref")
    if not fault_type:
        missing.append("fault_type")
    if missing:
        prompts = {
            "turbine_ref": "请说明故障属于哪台风机，例如 YD-B-007。",
            "fault_type": "请说明故障类型，例如齿轮箱过热、轴承异常或叶片裂纹。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    turbine_resolution = await resolve_turbine_by_ref(db, turbine_ref)
    turbine, candidates = turbine_resolution.entity, turbine_resolution.candidates
    if not turbine:
        if candidates:
            names = "、".join(item.name for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.68,
                "missing_slots": ["turbine_ref"],
                "clarification_question": f"找到多个相近风机：{names}。请明确风机编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "turbine_not_found",
            "error_message": f"未找到风机 {turbine_ref}。",
        }

    provided_confidence = _extract_fault_confidence(message)
    confidence = 0.5 if provided_confidence is None else provided_confidence
    priority = extract_priority_hint(message) or "medium"
    details_text = _extract_fault_details_text(message)
    faults = await query_turbine_fault_context(db, turbine.id)
    duplicate_faults = [
        item for item in faults
        if item.status in ("open", "active", "pending") and str(item.fault_type or "") == fault_type
    ]
    before = {
        "turbine": _turbine_state(turbine),
        "fault_context": fault_context_state(faults),
        "fault": None,
    }
    details = {
        "source": "agent_manual_fault",
        "description": details_text or "Agent人工登记故障记录。",
        "raw_message": message[:500],
    }
    after = {
        "turbine_id": turbine.id,
        "turbine_name": turbine.name,
        "turbine_region": turbine.region,
        "fault_type": fault_type,
        "confidence": confidence,
        "priority": priority,
        "status": "open",
        "processing_status": "pending",
        "details": details,
        "duplicate_active_fault_ids": [item.id for item in duplicate_faults],
    }
    warnings: list[str] = []
    if provided_confidence is None:
        warnings.append("用户未提供置信度，系统按人工录入默认值 0.5 记录；确认前请核对。")
    if duplicate_faults:
        ids = "、".join(f"#{item.id}" for item in duplicate_faults)
        warnings.append(f"该风机已有同类活跃故障 {ids}，确认后会新增一条独立故障记录。")

    workflow_steps = [
        "resolve_turbine_by_ref",
        "query_turbine_fault_context",
        "validate_fault_payload",
        "require_confirmation",
        "create_fault_record",
        "verify_written_entity",
        "present_result",
    ]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="create_fault_record",
        params={
            "turbine_id": turbine.id,
            "fault_type": fault_type,
            "confidence": confidence,
            "priority": priority,
            "details": details,
            "allow_duplicate": bool(duplicate_faults),
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "turbine_ref": turbine.name,
            "fault_type": fault_type,
            "confidence": confidence,
            "priority": priority,
            "details": details_text,
        },
        confidence=0.84,
        workflow="diagnosis.create_fault",
        steps=workflow_steps,
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "create_fault_record",
        "workflow": "diagnosis.create_fault",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认创建故障记录",
            "summary": f"为 {turbine.name} 登记 {fault_type}，置信度 {confidence:.0%}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _resolve_detection_turbine(
    db: AsyncSession,
    *,
    message: str,
    page_context: dict[str, Any] | None,
) -> tuple[Turbine | None, list[Turbine], str | None]:
    turbine_ref = _extract_turbine_ref(message) or _context_turbine_ref(page_context)
    if turbine_ref:
        resolution = await resolve_turbine_by_ref(db, turbine_ref)
        return resolution.entity, resolution.candidates, turbine_ref
    turbine_id = _context_turbine_id(page_context)
    if turbine_id is not None:
        turbine = await db.get(Turbine, turbine_id)
        return turbine, [turbine] if turbine else [], str(turbine_id)
    return None, [], None


async def _plan_auto_fault_detection(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    page_context: dict[str, Any] | None,
) -> dict[str, Any]:
    turbine, candidates, raw_ref = await _resolve_detection_turbine(db, message=message, page_context=page_context)
    if not turbine:
        if candidates:
            names = "、".join(item.name for item in candidates if item)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["turbine_ref"],
                "clarification_question": f"找到多个相近风机：{names}。请明确要检测哪台风机。",
            }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["turbine_ref"],
            "clarification_question": "请说明要检测哪台风机，例如 YD-B-007；如果在故障诊断页，也可以先选中风机后再说“诊断这台风机”。",
        }

    component = _extract_detection_component(message)
    window_hours = _extract_detection_window_hours(message)
    persist_result = _extract_detection_persist_result(message)
    before = {
        "turbine": _turbine_state(turbine),
        "component": component,
        "analysis_window_hours": window_hours,
        "data_source": "vibration",
        "persist_result": persist_result,
    }
    after = {
        **before,
        "operation": "run_auto_fault_detection",
        "result_status": "pending_confirmation",
    }
    warnings = [
        "自动检测结果来自已导入振动/SCADA数据与规则模型，仍需人工核验。",
    ]
    if persist_result:
        warnings.append("确认后若检测到疑似故障且置信度达到阈值，将新增故障记录。")
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="run_auto_fault_detection",
        params={
            "turbine_id": turbine.id,
            "component": component,
            "window_hours": window_hours,
            "data_source": "vibration",
            "persist_result": persist_result,
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "turbine_ref": turbine.name,
            "raw_turbine_ref": raw_ref,
            "component": component,
            "window_hours": window_hours,
            "data_source": "vibration",
            "persist_result": persist_result,
        },
        confidence=0.82,
        workflow="diagnosis.run_auto_detection",
        steps=[
            "resolve_turbine_by_ref",
            "query_vibration_context",
            "validate_detection_input",
            "require_confirmation",
            "run_auto_fault_detection",
            "query_knowledge_context",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "run_auto_fault_detection",
        "workflow": "diagnosis.run_auto_detection",
        "confidence": 0.82,
        "confirmation": {
            "title": "确认执行单机自动故障检测",
            "summary": f"对 {turbine.name} 执行 {component} 自动故障检测，窗口 {window_hours} 小时",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _resolve_batch_detection_turbines(
    db: AsyncSession,
    *,
    message: str,
) -> tuple[list[Turbine], dict[str, Any]]:
    region = _extract_batch_detection_region(message)
    status_scope = _extract_batch_detection_status(message)
    is_fleet = any(keyword in message for keyword in ("全场", "所有风机", "全部风机", "所有机组", "全部机组"))
    scope = {
        "region": region,
        "status": status_scope,
        "fleet": is_fleet,
    }
    result = await db.execute(select(Turbine).order_by(Turbine.region.asc(), Turbine.name.asc()))
    turbines = list(result.scalars().all())
    if region:
        turbines = [item for item in turbines if _region_matches(item.region, region)]
    if status_scope == "warning":
        turbines = [item for item in turbines if item.status == "warning"]
    elif status_scope == "fault":
        turbines = [item for item in turbines if item.status == "fault"]
    elif status_scope == "abnormal":
        turbines = [item for item in turbines if item.status in {"warning", "fault"}]
    if not (region or status_scope or is_fleet):
        return [], scope
    return turbines, scope


async def _plan_batch_fault_detection(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    turbines, scope = await _resolve_batch_detection_turbines(db, message=message)
    if not (scope.get("region") or scope.get("status") or scope.get("fleet")):
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["scope"],
            "clarification_question": "请说明批量检测范围，例如风场A、预警风机、故障风机或全场风机。",
        }
    if not turbines:
        return {
            "status": "error",
            "task_type": "WORKFLOW",
            "confidence": 0.74,
            "error_code": "batch_scope_empty",
            "error_message": "当前范围内没有可检测的风机，本次不会生成确认动作。",
        }

    component = _extract_detection_component(message)
    window_hours = _extract_detection_window_hours(message)
    persist_result = _extract_detection_persist_result(message)
    turbine_names = [item.name for item in turbines]
    before = {
        "scope": scope,
        "turbine_count": len(turbines),
        "turbine_names": turbine_names[:20],
        "component": component,
        "analysis_window_hours": window_hours,
        "data_source": "vibration",
        "persist_result": persist_result,
    }
    after = {
        **before,
        "operation": "run_batch_fault_detection",
        "result_status": "pending_confirmation",
    }
    warnings = [
        f"批量检测将影响 {len(turbines)} 台风机，确认后会重新读取当前数据。",
        "检测结果来自已导入振动/SCADA数据与规则模型，仍需人工核验。",
    ]
    if len(turbines) > 50:
        warnings.append("影响风机数量超过50台，建议拆分范围或转后台任务。")
    if persist_result:
        warnings.append("确认后将为达到疑似故障和置信度门槛的风机新增故障记录，并跳过已有活跃同类故障。")
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="run_batch_fault_detection",
        params={
            "turbine_ids": [item.id for item in turbines],
            "scope": scope,
            "component": component,
            "window_hours": window_hours,
            "data_source": "vibration",
            "persist_result": persist_result,
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "scope": scope,
            "component": component,
            "window_hours": window_hours,
            "data_source": "vibration",
            "persist_result": persist_result,
            "turbine_count": len(turbines),
        },
        confidence=0.8,
        workflow="diagnosis.run_batch_detection",
        steps=[
            "query_fleet_overview",
            "resolve_batch_turbines",
            "validate_batch_detection_scope",
            "require_confirmation",
            "run_batch_fault_detection",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "run_batch_fault_detection",
        "workflow": "diagnosis.run_batch_detection",
        "confidence": 0.8,
        "confirmation": {
            "title": "确认执行批量故障检测",
            "summary": f"对 {len(turbines)} 台风机执行 {component} 批量故障检测，窗口 {window_hours} 小时",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_fault_processing_status(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    target_status = _extract_fault_processing_status(message)
    fault_id = _extract_fault_id(message)
    turbine_ref = _extract_turbine_ref(message)
    fault_keyword = _extract_fault_keyword(message)
    reason = _extract_reason(message)
    missing = []
    if not target_status:
        missing.append("target_processing_status")
    if not fault_id and not turbine_ref:
        missing.append("fault_ref_or_context")
    if target_status in {"closed", "failed"} and not reason:
        missing.append("reason")
    if missing:
        prompts = {
            "target_processing_status": "请说明是关闭故障还是标记处理失败。",
            "fault_ref_or_context": "请说明故障编号，或提供风机编号和故障类型。",
            "reason": "请提供关闭或失败原因，便于审计和回溯。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    resolution = await resolve_fault_by_context(
        db,
        fault_id=fault_id,
        turbine_ref=turbine_ref,
        fault_keyword=fault_keyword,
        status="active" if not fault_id else None,
        latest=True,
        limit=5,
    )
    entity = resolution.get("entity")
    candidates = resolution.get("candidates") or []
    if not entity:
        if candidates:
            names = "、".join(f"#{item.get('id')} {item.get('turbine_name') or item.get('turbine_id')} {item.get('fault_type')}" for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["fault_ref_or_context"],
                "clarification_question": f"找到多个相近故障：{names}。请明确故障编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": "未找到匹配的活跃故障。",
        }

    fault = await db.get(Fault, int(entity["id"]))
    if not fault:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": f"未找到故障 #{entity['id']}。",
        }
    if getattr(fault, "processing_status", None) in {"closed", "failed"} or fault.status == "closed":
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.84,
            "error_code": "invalid_fault_status",
            "error_message": f"故障 #{fault.id} 已处于终态，不允许重复关闭或标记失败。",
        }

    before = _fault_state(fault)
    after = {
        **before,
        "processing_status": target_status,
        "status": "closed" if target_status == "closed" else before.get("status"),
        "handler": user.username,
        "status_note": reason,
    }
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="update_fault_processing_status",
        params={
            "fault_id": fault.id,
            "processing_status": target_status,
            "handler": user.username,
            "status_note": reason,
        },
        before=before,
        after=after,
        warnings=["该动作会改变故障处理状态，并影响故障诊断页面统计。"],
        parsed_slots={
            "fault_id": fault.id,
            "turbine_ref": turbine_ref,
            "fault_keyword": fault_keyword,
            "target_processing_status": target_status,
            "reason": reason,
        },
        confidence=0.84,
        workflow="diagnosis.close_or_fail_fault",
        steps=[
            "resolve_fault_by_id_or_context",
            "validate_fault_status_transition",
            "require_confirmation",
            "update_fault_processing_status",
            "verify_status_changed",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "update_fault_processing_status",
        "workflow": "diagnosis.close_or_fail_fault",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认更新故障处理状态",
            "summary": f"将故障 #{fault.id} 标记为 {target_status}",
            "before": before,
            "after": after,
            "warnings": ["该动作会改变故障处理状态，并影响故障诊断页面统计。"],
        },
    }


async def _resolve_health_refresh_turbines(
    db: AsyncSession,
    *,
    message: str,
) -> tuple[list[Turbine], dict[str, Any], str | None]:
    scope = _extract_health_refresh_scope(message)
    turbine_ref = scope.get("turbine_ref")
    if turbine_ref:
        resolution = await resolve_turbine_by_ref(db, str(turbine_ref))
        if resolution.entity:
            return [resolution.entity], scope, None
        if resolution.candidates:
            names = "、".join(item.name for item in resolution.candidates)
            return [], scope, f"找到多个相近风机：{names}。请明确风机编号。"
        return [], scope, f"未找到风机 {turbine_ref}。"

    region = scope.get("region")
    status_scope = scope.get("status")
    if not (region or status_scope or scope.get("fleet")):
        return [], scope, "请说明要刷新哪台风机、哪个风场分组或哪类风机，例如 YD-B-007、A组预警风机或全场风机。"

    result = await db.execute(select(Turbine).order_by(Turbine.region.asc(), Turbine.name.asc()))
    turbines = list(result.scalars().all())
    if region:
        turbines = [item for item in turbines if _region_matches(item.region, str(region))]
    if status_scope:
        turbines = [item for item in turbines if item.status == status_scope]
    return turbines, scope, None


async def _plan_refresh_health_indexes(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    turbines, scope, error = await _resolve_health_refresh_turbines(db, message=message)
    if error and not turbines:
        code = "scope" if "请说明" in error or "多个相近" in error else "turbine_ref"
        status = "needs_clarification" if "请说明" in error or "多个相近" in error else "error"
        payload: dict[str, Any] = {
            "status": status,
            "task_type": "CLARIFY" if status == "needs_clarification" else "WORKFLOW",
            "confidence": 0.58,
            "error_code": None if status == "needs_clarification" else "turbine_not_found",
            "error_message": None if status == "needs_clarification" else error,
        }
        if status == "needs_clarification":
            payload["missing_slots"] = [code]
            payload["clarification_question"] = error
        return payload
    if not turbines:
        return {
            "status": "error",
            "task_type": "WORKFLOW",
            "confidence": 0.74,
            "error_code": "health_refresh_scope_empty",
            "error_message": "当前范围内没有可刷新健康指数的风机。",
        }

    before_items = [_turbine_state(item) for item in turbines[:50]]
    source_datasets = sorted({str(item.source_dataset or "unknown") for item in turbines})
    before = {
        "scope": scope,
        "affected_count": len(turbines),
        "turbine_names": [item.name for item in turbines[:50]],
        "source_datasets": source_datasets,
        "before_items": before_items,
    }
    after = {
        **before,
        "operation": "refresh_health_indexes",
        "result_status": "pending_confirmation",
        "data_source": "SCADA/HI",
    }
    warnings = [
        f"确认后将重新计算 {len(turbines)} 台风机的 HI 健康指数和状态。",
        "该动作只更新确认范围内风机，不默认刷新全场。",
    ]
    if len(turbines) > 50:
        warnings.append("影响范围超过50台，建议在低峰期执行。")
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="refresh_health_indexes",
        params={
            "turbine_ids": [item.id for item in turbines],
            "scope": scope,
            "window_rows": 144,
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "scope": scope,
            "turbine_count": len(turbines),
            "turbine_names": [item.name for item in turbines[:20]],
        },
        confidence=0.82,
        workflow="turbine.refresh_health",
        steps=[
            "resolve_turbine_by_ref",
            "query_fleet_overview",
            "validate_health_refresh_scope",
            "require_confirmation",
            "refresh_health_indexes",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "refresh_health_indexes",
        "workflow": "turbine.refresh_health",
        "confidence": 0.82,
        "confirmation": {
            "title": "确认刷新风机健康指数",
            "summary": f"刷新 {len(turbines)} 台风机的 HI 健康指数",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_update_fault_record(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    fault_id = _extract_fault_id(message)
    turbine_ref = _extract_turbine_ref(message)
    fault_keyword = _extract_fault_keyword(message)
    patch_fields = _extract_fault_patch_fields(message)
    missing: list[str] = []
    if not fault_id and not turbine_ref:
        missing.append("fault_ref_or_context")
    if not patch_fields:
        missing.append("patch_fields")
    if missing:
        prompts = {
            "fault_ref_or_context": "请说明要更新哪个故障，可以提供故障ID，或提供风机编号和故障类型。",
            "patch_fields": "请说明要修改的字段，例如置信度、优先级、故障类型、详情或处理人。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    resolution = await resolve_fault_by_context(
        db,
        fault_id=fault_id,
        turbine_ref=turbine_ref,
        fault_keyword=fault_keyword,
        status="active" if not fault_id else None,
        latest=True,
        limit=5,
    )
    entity = resolution.get("entity")
    candidates = resolution.get("candidates") or []
    if not entity:
        if candidates:
            names = "、".join(f"#{item.get('id')} {item.get('turbine_name') or item.get('turbine_id')} {item.get('fault_type')}" for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["fault_ref_or_context"],
                "clarification_question": f"找到多个相近故障：{names}。请明确故障编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": "未找到匹配的故障记录。",
        }

    fault = await db.get(Fault, int(entity["id"]))
    if not fault:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": f"未找到故障 #{entity['id']}。",
        }
    if fault.status == "closed" and str(user.role or "") != "admin":
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.8,
            "error_code": "closed_fault_admin_required",
            "error_message": f"故障 #{fault.id} 已关闭，修改核心字段需要管理员执行。",
        }

    before = _fault_state(fault)
    after = dict(before)
    if "details_description" in patch_fields:
        details = dict(fault.details or {})
        details["description"] = patch_fields["details_description"]
        after["details"] = details
    for key, value in patch_fields.items():
        if key != "details_description":
            after[key] = value
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="update_fault_record",
        params={"fault_id": fault.id, "patch_fields": patch_fields},
        before=before,
        after=after,
        warnings=["该动作会修改故障核心字段，请确认执行前后差异。"],
        parsed_slots={
            "fault_id": fault.id,
            "turbine_ref": turbine_ref,
            "fault_keyword": fault_keyword,
            "patch_fields": patch_fields,
        },
        confidence=0.84,
        workflow="diagnosis.update_fault",
        steps=[
            "resolve_fault_by_id_or_context",
            "validate_fault_patch",
            "require_confirmation",
            "update_fault_record",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "update_fault_record",
        "workflow": "diagnosis.update_fault",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认更新故障记录",
            "summary": f"修改故障 #{fault.id} 的 {len(patch_fields)} 个字段",
            "before": before,
            "after": after,
            "warnings": ["该动作会修改故障核心字段，请确认执行前后差异。"],
        },
    }


async def _plan_delete_fault_record(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    fault_id = _extract_fault_id(message)
    turbine_ref = _extract_turbine_ref(message)
    fault_keyword = _extract_fault_keyword(message)
    reason = _extract_reason(message)
    missing: list[str] = []
    if not fault_id and not turbine_ref:
        missing.append("fault_ref_or_context")
    if not reason:
        missing.append("reason")
    if missing:
        prompts = {
            "fault_ref_or_context": "请说明要删除哪个故障，可以提供故障ID，或提供风机编号和故障类型。",
            "reason": "请说明删除原因，便于审计；误报也建议写明依据。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    resolution = await resolve_fault_by_context(
        db,
        fault_id=fault_id,
        turbine_ref=turbine_ref,
        fault_keyword=fault_keyword,
        status=None if fault_id else "active",
        latest=True,
        limit=5,
    )
    entity = resolution.get("entity")
    candidates = resolution.get("candidates") or []
    if not entity:
        if candidates:
            names = "、".join(f"#{item.get('id')} {item.get('turbine_name') or item.get('turbine_id')} {item.get('fault_type')}" for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["fault_ref_or_context"],
                "clarification_question": f"找到多个相近故障：{names}。请明确故障编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": "未找到匹配的故障记录。",
        }

    fault = await db.get(Fault, int(entity["id"]))
    if not fault:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "fault_not_found",
            "error_message": f"未找到故障 #{entity['id']}。",
        }
    linked_orders = (
        await db.execute(select(WorkOrder).where(WorkOrder.fault_id == fault.id))
    ).scalars().all()
    if linked_orders:
        refs = "、".join(_workorder_ref(item) for item in linked_orders[:5])
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.84,
            "error_code": "fault_has_linked_workorders",
            "error_message": f"故障 #{fault.id} 已关联工单 {refs}，为保留追溯链，本次不允许删除；请改用关闭或标记误报。",
        }

    before = _fault_state(fault)
    after = {**before, "deleted": True, "delete_reason": reason}
    warnings = ["删除故障会同时删除该故障的信号记录；该动作不可通过页面撤销。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="delete_fault_record",
        params={"fault_id": fault.id, "reason": reason},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "fault_id": fault.id,
            "turbine_ref": turbine_ref,
            "fault_keyword": fault_keyword,
            "reason": reason,
        },
        confidence=0.86,
        workflow="diagnosis.delete_fault",
        steps=[
            "resolve_fault_by_id_or_context",
            "validate_fault_delete",
            "require_confirmation",
            "delete_fault_record",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "delete_fault_record",
        "workflow": "diagnosis.delete_fault",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认删除故障记录",
            "summary": f"删除故障 #{fault.id}，原因：{reason}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_refresh_rul_predictions(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    turbine_ref = _extract_turbine_ref(message)
    refresh_all = any(token in message for token in ("全部", "全场", "所有", "所有风机"))
    turbine: Turbine | None = None
    if turbine_ref:
        resolution = await resolve_turbine_by_ref(db, turbine_ref)
        turbine = resolution.entity
        if not turbine:
            if resolution.candidates:
                names = "、".join(item.name for item in resolution.candidates)
                return {
                    "status": "needs_clarification",
                    "task_type": "CLARIFY",
                    "confidence": 0.66,
                    "missing_slots": ["scope"],
                    "clarification_question": f"找到多个相近风机：{names}。请明确刷新范围。",
                }
            return {
                "status": "error",
                "task_type": "WRITE",
                "confidence": 0.78,
                "error_code": "turbine_not_found",
                "error_message": f"未找到风机 {turbine_ref}。",
            }
    elif not refresh_all:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["scope"],
            "clarification_question": "请说明要刷新哪台风机的RUL，或明确刷新全部风机。",
        }

    before = {
        "scope": turbine.name if turbine else "all",
        "turbine_id": turbine.id if turbine else None,
    }
    after = {
        **before,
        "operation": "refresh_rul_predictions",
    }
    warnings = ["刷新会替换目标范围内现有RUL预测结果。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="refresh_rul_predictions",
        params={"turbine_id": turbine.id if turbine else None},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"scope": turbine.name if turbine else "all", "turbine_id": turbine.id if turbine else None},
        confidence=0.82,
        workflow="prediction.refresh_rul",
        steps=[
            "resolve_turbine_by_ref",
            "validate_rul_refresh_scope",
            "require_confirmation",
            "refresh_rul_predictions",
            "verify_prediction_written",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "refresh_rul_predictions",
        "workflow": "prediction.refresh_rul",
        "confidence": 0.82,
        "confirmation": {
            "title": "确认刷新RUL预测",
            "summary": f"刷新 {'全部风机' if turbine is None else turbine.name} 的剩余寿命预测",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _build_schedule_preview(
    db: AsyncSession,
    *,
    region: str | None,
    max_days: int,
    top_n: int,
) -> dict[str, Any]:
    from app.services.maintenance_planner import generate_maintenance_plan
    from app.services.maintenance_scheduler import auto_schedule, detect_conflicts

    plan = await generate_maintenance_plan(db=db, top_n=None, region=region)
    scheduled = auto_schedule(plan, start_date=date.today(), max_days=max_days, top_n=top_n)
    conflicts = detect_conflicts(scheduled)
    overflow = [item for item in scheduled if item.get("overflow")]
    ok = [item for item in scheduled if not item.get("overflow")]
    return jsonable_encoder(
        {
            "plan_count": len(plan),
            "scheduled": ok,
            "overflow": overflow,
            "conflicts": conflicts,
            "total_scheduled": len(ok),
            "total_overflow": len(overflow),
            "conflict_count": len(conflicts),
            "total_cost_estimate": round(sum(float(item.get("cost_estimate") or 0.0) for item in ok), 2),
            "urgent_count": sum(1 for item in ok if item.get("priority") == "urgent"),
            "high_count": sum(1 for item in ok if item.get("priority") == "high"),
        }
    )


async def _plan_generate_maintenance_schedule(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    region = _extract_region(message)
    max_days = _extract_schedule_max_days(message)
    top_n = _extract_schedule_top_n(message)
    create_work_orders = _extract_schedule_create_work_orders(message)
    preview = await _build_schedule_preview(db, region=region, max_days=max_days, top_n=top_n)
    if preview["plan_count"] == 0:
        return {
            "status": "error",
            "task_type": "WORKFLOW",
            "confidence": 0.72,
            "error_code": "maintenance_plan_empty",
            "error_message": "当前没有可用于排程的RUL预测或维护计划数据，本次不会生成排程。",
        }

    before = {
        "scope": region or "all",
        "max_days": max_days,
        "top_n": top_n,
        "create_work_orders": create_work_orders,
        "plan_count": preview["plan_count"],
    }
    after = {
        **before,
        "total_scheduled": preview["total_scheduled"],
        "total_overflow": preview["total_overflow"],
        "conflict_count": preview["conflict_count"],
        "urgent_count": preview["urgent_count"],
        "high_count": preview["high_count"],
        "total_cost_estimate": preview["total_cost_estimate"],
        "preview_items": preview["scheduled"][:5],
    }
    warnings = ["维护排程会根据当前RUL、HI、故障和维修历史重新计算；确认后会再次回读数据。"]
    if create_work_orders:
        warnings.append("确认后将为排程中的紧急/高优先级项目创建工单，并跳过已存在的活跃同类工单。")
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="generate_maintenance_schedule",
        params={
            "region": region,
            "max_days": max_days,
            "top_n": top_n,
            "create_work_orders": create_work_orders,
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "scope": region or "all",
            "max_days": max_days,
            "top_n": top_n,
            "create_work_orders": create_work_orders,
        },
        confidence=0.82,
        workflow="prediction.generate_schedule",
        steps=[
            "query_rul_predictions",
            "query_maintenance_plan",
            "validate_schedule_scope",
            "require_confirmation",
            "generate_maintenance_schedule",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "generate_maintenance_schedule",
        "workflow": "prediction.generate_schedule",
        "confidence": 0.82,
        "confirmation": {
            "title": "确认生成维护排程",
            "summary": f"生成未来 {max_days} 天维护排程，预计安排 {preview['total_scheduled']} 项，溢出 {preview['total_overflow']} 项",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _get_threshold_config(db: AsyncSession, *, user: User) -> NotificationConfig | None:
    result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    return result.scalar_one_or_none()


async def _plan_update_threshold_config(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    patch = _extract_threshold_patch(message)
    if not patch:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.56,
            "missing_slots": ["threshold_payload"],
            "clarification_question": "请说明新的HI告警阈值或通知渠道，例如“把HI阈值改成75”或“开启邮件通知并发送到 ops@example.com”。",
        }

    if "hi_threshold" in patch and not (0 <= float(patch["hi_threshold"]) <= 100):
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.82,
            "error_code": "invalid_threshold",
            "error_message": "HI告警阈值必须在0到100之间，本次不会修改配置。",
        }

    config = await _get_threshold_config(db, user=user)
    before = _threshold_config_state(config, user=user)
    after = {**before, **patch}
    if after.get("email_enabled") and not after.get("email_address"):
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.62,
            "missing_slots": ["email_address"],
            "clarification_question": "开启邮件通知需要邮箱地址，请补充要接收告警的邮箱。",
        }

    changed = [key for key, value in patch.items() if before.get(key) != value]
    if not changed:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.76,
            "error_code": "no_effective_change",
            "error_message": "解析到的阈值或通知配置与当前配置一致，本次不会生成确认动作。",
        }

    labels = {
        "hi_threshold": "HI阈值",
        "email_enabled": "邮件通知",
        "email_address": "邮件地址",
        "wechat_enabled": "企业微信通知",
    }
    summary_parts = [f"{labels.get(key, key)}：{before.get(key)} -> {after.get(key)}" for key in changed]
    warnings = ["该动作会修改系统告警触发和通知配置，请确认阈值与接收渠道。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="update_threshold_config",
        params={"threshold_payload": patch},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"threshold_payload": patch},
        confidence=0.84,
        workflow="settings.update_thresholds",
        steps=[
            "query_threshold_config",
            "validate_threshold_payload",
            "require_confirmation",
            "update_threshold_config",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "update_threshold_config",
        "workflow": "settings.update_thresholds",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认更新告警阈值和通知配置",
            "summary": "；".join(summary_parts),
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_delete_ai_provider(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    provider = _extract_provider_key(message)
    if not provider:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["provider"],
            "clarification_question": "请说明要删除哪个AI供应商配置，例如 DeepSeek、Kimi 或通义千问。",
        }
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user.id,
            AIProviderConfig.provider == provider,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.8,
            "error_code": "ai_provider_not_found",
            "error_message": f"当前用户没有 {provider} 的AI供应商配置。",
        }
    before = _ai_provider_state(config)
    after = {**before, "deleted": True, "api_key": None}
    warnings = ["删除后该供应商不会再出现在AI设置和AI对话可选配置中，需要重新保存才能恢复。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WRITE",
        action="delete_ai_provider_config",
        params={"provider_id": config.id, "provider": provider},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"provider": provider, "provider_id": config.id},
        confidence=0.86,
        workflow="settings.delete_ai_provider",
        steps=[
            "query_ai_provider_config",
            "validate_ai_provider_delete",
            "require_confirmation",
            "delete_ai_provider_config",
            "verify_provider_removed",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WRITE",
        "request_id": request_id,
        "action": "delete_ai_provider_config",
        "workflow": "settings.delete_ai_provider",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认删除AI供应商配置",
            "summary": f"删除 {config.display_name or config.provider} 的AI供应商配置",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_test_ai_provider(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    provider = _extract_provider_key(message)
    if not provider:
        return {
            "status": "needs_clarification",
            "task_type": "WORKFLOW",
            "confidence": 0.44,
            "missing_slots": ["provider"],
            "clarification_question": "请说明要测试哪个AI供应商，例如 DeepSeek、Kimi、通义千问或 Ollama。",
            "workflow": "settings.test_ai_provider",
            "action": "test_ai_provider_connection",
        }

    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user.id,
            AIProviderConfig.provider == provider,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        return {
            "status": "error",
            "task_type": "WORKFLOW",
            "confidence": 0.0,
            "error_code": "ai_provider_not_found",
            "error_message": f"当前用户没有 {provider} 的AI供应商配置，请先保存供应商配置后再测试连接。",
            "workflow": "settings.test_ai_provider",
            "action": "test_ai_provider_connection",
        }

    template = _provider_template(provider)
    model = _extract_default_model(message, provider) or config.default_model or template.get("default_model") or "qwen-plus"
    before = _ai_provider_state(config)
    after = {
        **before,
        "test_model": model,
        "last_test_status": "pending_test",
        "last_test_message": "确认后将向供应商发送最小 ping 请求，并把结果写回供应商配置。",
    }
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="test_ai_provider_connection",
        params={"provider_id": config.id, "provider": provider, "model": model},
        before=before,
        after=after,
        warnings=[
            "该动作会向AI供应商发起一次真实连接测试请求。",
            "测试失败原因会写入供应商配置，但不会回显API KEY明文。",
        ],
        parsed_slots={"provider": provider, "model": model},
        confidence=0.75,
        workflow="settings.test_ai_provider",
        steps=[
            "query_ai_provider_config",
            "validate_ai_provider_payload",
            "require_confirmation",
            "test_ai_provider_connection",
            "verify_written_entity",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "action": "test_ai_provider_connection",
        "workflow": "settings.test_ai_provider",
        "request_id": request_id,
        "confidence": 0.75,
        "steps": [
            "query_ai_provider_config",
            "validate_ai_provider_payload",
            "require_confirmation",
            "test_ai_provider_connection",
            "verify_written_entity",
        ],
        "confirmation": {
            "title": "确认测试AI供应商连接",
            "summary": f"测试 {config.display_name or provider} 的模型 {model} 是否可连接",
            "before": before,
            "after": after,
            "warnings": [
                "该动作会向AI供应商发起一次真实连接测试请求。",
                "测试失败原因会写入供应商配置，但不会回显API KEY明文。",
            ],
        },
    }


async def _plan_upsert_ai_provider(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    payload = _extract_ai_provider_payload(message)
    provider = payload.get("provider")
    if not provider:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["provider"],
            "clarification_question": "请说明要新增或更新哪个AI供应商，例如 DeepSeek、Kimi、通义千问或 Ollama。",
        }
    if not payload.get("base_url"):
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["base_url"],
            "clarification_question": "请说明API地址；也可以使用系统内置供应商模板。",
        }

    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user.id,
            AIProviderConfig.provider == provider,
        )
    )
    config = result.scalar_one_or_none()
    before = _ai_provider_state(config) if config else {
        "id": None,
        "provider": provider,
        "display_name": None,
        "base_url": None,
        "api_style": None,
        "default_model": None,
        "model_options": [],
        "enabled": None,
        "last_test_status": None,
        "last_test_message": None,
        "has_api_key": False,
    }
    has_new_key = bool(payload.get("api_key"))
    after = {
        **before,
        "provider": provider,
        "display_name": payload.get("display_name"),
        "base_url": payload.get("base_url"),
        "api_style": payload.get("api_style") or "openai",
        "default_model": payload.get("default_model"),
        "model_options": payload.get("model_options") or [],
        "enabled": bool(payload.get("enabled")),
        "has_api_key": has_new_key or bool(before.get("has_api_key")) or provider == "ollama",
        "api_key_update": "provided" if has_new_key else "unchanged",
        "last_test_status": "untested" if has_new_key else before.get("last_test_status"),
    }
    warnings = [
        "该动作只保存供应商配置，不会切换当前AI对话会话模型。",
        "确认卡和审计日志不会保存 API KEY 明文。",
    ]
    if provider != "ollama" and not after["has_api_key"]:
        warnings.append("该供应商未提供API KEY，保存后仍可能无法连接。")
    safe_payload = {
        key: value for key, value in payload.items()
        if key != "api_key"
    }
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message="[redacted api key]" if has_new_key else message,
        task_type="WORKFLOW",
        action="upsert_ai_provider_config",
        params={**safe_payload, "api_key": payload.get("api_key"), "api_key_update": "provided" if has_new_key else "unchanged"},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "provider": provider,
            "base_url": payload.get("base_url"),
            "default_model": payload.get("default_model"),
            "model_options": payload.get("model_options") or [],
            "has_api_key": has_new_key or bool(before.get("has_api_key")),
        },
        confidence=0.84,
        workflow="settings.upsert_ai_provider",
        steps=[
            "query_ai_provider_config",
            "validate_ai_provider_payload",
            "require_confirmation",
            "upsert_ai_provider_config",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "upsert_ai_provider_config",
        "workflow": "settings.upsert_ai_provider",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认保存AI供应商配置",
            "summary": f"保存 {after['display_name'] or provider} 配置，默认模型 {after.get('default_model') or '-'}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _resolve_knowledge_node(
    db: AsyncSession,
    *,
    node_id: int | None = None,
    fault_type: str | None = None,
) -> tuple[FaultKnowledgeNode | None, list[FaultKnowledgeNode]]:
    if node_id is not None:
        node = await db.get(FaultKnowledgeNode, node_id)
        return node, [node] if node else []
    keyword = (fault_type or "").strip()
    if not keyword:
        return None, []
    exact = await db.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == keyword))
    node = exact.scalar_one_or_none()
    if node:
        return node, [node]
    fuzzy = await db.execute(
        select(FaultKnowledgeNode)
        .where(FaultKnowledgeNode.fault_type.ilike(f"%{keyword}%"))
        .order_by(FaultKnowledgeNode.fault_type.asc())
        .limit(5)
    )
    candidates = list(fuzzy.scalars().all())
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


async def _plan_upsert_knowledge_node(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    workorder_id = _extract_workorder_ref(message)
    source_workorder: WorkOrder | None = await _resolve_workorder(db, workorder_id) if workorder_id else None
    fault_type = (
        (source_workorder.fault_type if source_workorder and source_workorder.fault_type else None)
        or _extract_knowledge_fault_type(message)
    )
    if not fault_type:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["fault_type"],
            "clarification_question": "请说明要沉淀或更新的故障类型，例如“齿轮箱点蚀”。",
        }
    if workorder_id and not source_workorder:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.76,
            "error_code": "workorder_not_found",
            "error_message": f"未找到工单 WO-{workorder_id:04d}，无法从工单沉淀知识。",
        }

    node, candidates = await _resolve_knowledge_node(db, fault_type=fault_type)
    if candidates and not node:
        candidate_names = "、".join(item.fault_type for item in candidates)
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.66,
            "missing_slots": ["knowledge_node_ref"],
            "clarification_question": f"找到多个相近知识节点：{candidate_names}。请明确要更新哪个故障知识。",
        }

    case_payload = None
    if source_workorder:
        case_payload = {
            "workorder_ref": _workorder_ref(source_workorder),
            "title": source_workorder.title,
            "description": source_workorder.description,
            "status": source_workorder.status,
        }
    solution = {"action": message, "source": "agent_task"}
    if node:
        before = _knowledge_state(node)
        after = {
            **before,
            "source": "agent_task",
            "verified": False,
            "confidence": min(float(before.get("confidence") or 0.6), 0.8),
            "solutions": before["solutions"] or [solution],
            "cases": before["cases"] + ([case_payload] if case_payload else []),
            "extracted_from": _workorder_ref(source_workorder) if source_workorder else before.get("extracted_from"),
        }
        action_label = "更新知识库节点"
    else:
        before = {}
        after = {
            "id": None,
            "fault_type": fault_type,
            "category": _knowledge_category_for_fault(fault_type),
            "icon": "⚠️",
            "severity": "medium",
            "symptoms": [],
            "root_causes": [],
            "solutions": [solution],
            "related_faults": [],
            "spare_parts": [],
            "cases": [case_payload] if case_payload else [],
            "source": "agent_task",
            "confidence": 0.6,
            "verified": False,
            "extracted_from": _workorder_ref(source_workorder) if source_workorder else None,
        }
        action_label = "新增知识库节点"

    warnings = ["Agent沉淀的知识默认未验证；需要人工审核后才会标记为可信。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="upsert_knowledge_node",
        params={"node_id": node.id if node else None, "payload": after},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"fault_type": fault_type, "source_workorder_ref": _workorder_ref(source_workorder) if source_workorder else None},
        confidence=0.8,
        workflow="knowledge.upsert_node",
        steps=[
            "resolve_workorder_by_ref",
            "query_knowledge_context",
            "draft_knowledge_node",
            "validate_knowledge_payload",
            "require_confirmation",
            "upsert_knowledge_node",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "upsert_knowledge_node",
        "workflow": "knowledge.upsert_node",
        "confidence": 0.8,
        "confirmation": {
            "title": f"确认{action_label}",
            "summary": f"{action_label}：{fault_type}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_review_knowledge_node(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    node_id = _extract_knowledge_node_id(message)
    fault_type = _extract_knowledge_fault_type(message)
    review_action = _extract_knowledge_review_action(message)
    missing = []
    if not node_id and not fault_type:
        missing.append("knowledge_node_ref")
    if not review_action:
        missing.append("review_action")
    if missing:
        prompts = {
            "knowledge_node_ref": "请说明要审核哪个知识节点，例如节点编号或故障类型。",
            "review_action": "请说明是标记为已验证还是拒绝。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    node, candidates = await _resolve_knowledge_node(db, node_id=node_id, fault_type=fault_type)
    if not node:
        if candidates:
            candidate_names = "、".join(f"#{item.id} {item.fault_type}" for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["knowledge_node_ref"],
                "clarification_question": f"找到多个相近知识节点：{candidate_names}。请明确节点编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "knowledge_node_not_found",
            "error_message": "未找到匹配的知识节点。",
        }

    reason = _extract_reason(message)
    before = _knowledge_state(node)
    after = (
        {**before, "verified": True, "confidence": 1.0, "review_action": "verify", "review_reason": reason}
        if review_action == "verify"
        else {**before, "deleted": True, "review_action": "reject", "review_reason": reason}
    )
    warnings = ["拒绝知识节点会删除该节点；标记为已验证会提升其可信状态。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="review_knowledge_node",
        params={"node_id": node.id, "review_action": review_action, "reason": reason},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"knowledge_node_ref": node.id, "fault_type": node.fault_type, "review_action": review_action, "reason": reason},
        confidence=0.84,
        workflow="knowledge.review_node",
        steps=[
            "query_knowledge_context",
            "validate_knowledge_review",
            "require_confirmation",
            "verify_or_reject_knowledge_node",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "review_knowledge_node",
        "workflow": "knowledge.review_node",
        "confidence": 0.84,
        "confirmation": {
            "title": "确认审核知识节点",
            "summary": f"{'验证' if review_action == 'verify' else '拒绝'}知识节点 #{node.id} {node.fault_type}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_delete_knowledge_node(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    node_id = _extract_knowledge_node_id(message)
    fault_type = _extract_knowledge_fault_type(message)
    reason = _extract_reason(message)
    missing = []
    if not node_id and not fault_type:
        missing.append("knowledge_node_ref")
    if not reason:
        missing.append("reason")
    if missing:
        prompts = {
            "knowledge_node_ref": "请说明要删除哪个知识节点，例如节点编号或故障类型。",
            "reason": "请说明删除原因。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    node, candidates = await _resolve_knowledge_node(db, node_id=node_id, fault_type=fault_type)
    if not node:
        if candidates:
            candidate_names = "、".join(f"#{item.id} {item.fault_type}" for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["knowledge_node_ref"],
                "clarification_question": f"找到多个相近知识节点：{candidate_names}。请明确节点编号。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "knowledge_node_not_found",
            "error_message": "未找到匹配的知识节点。",
        }

    before = _knowledge_state(node)
    after = {**before, "deleted": True, "delete_reason": reason}
    warnings = ["删除知识节点属于高风险动作，确认后该节点会从知识库中移除。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="delete_knowledge_node",
        params={"node_id": node.id, "reason": reason},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"knowledge_node_ref": node.id, "fault_type": node.fault_type, "reason": reason},
        confidence=0.86,
        workflow="knowledge.delete_node",
        steps=[
            "query_knowledge_context",
            "validate_knowledge_delete",
            "require_confirmation",
            "delete_knowledge_node",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "delete_knowledge_node",
        "workflow": "knowledge.delete_node",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认删除知识节点",
            "summary": f"删除知识节点 #{node.id} {node.fault_type}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_upsert_personnel(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    name = _extract_personnel_name(message)
    email = _extract_email(message)
    skills = _extract_skills(message)
    region = _extract_region(message)
    if not name:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.56,
            "missing_slots": ["personnel_payload"],
            "clarification_question": "请说明维护人员姓名，例如“新增维护人员张三，邮箱 zhangsan@example.com”。",
        }

    exact = await db.execute(select(User).where(User.role == "technician", User.username == name))
    existing = exact.scalar_one_or_none()
    if not existing:
        resolution = await resolve_personnel_by_name(db, name)
        if resolution.entity:
            existing = resolution.entity
        elif resolution.candidates:
            candidate_names = "、".join(item.username for item in resolution.candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["personnel_payload"],
                "clarification_question": f"找到多个相近人员：{candidate_names}。请明确要更新哪位维护人员。",
            }

    if existing and not existing.is_active:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.76,
            "error_code": "personnel_inactive",
            "error_message": f"维护人员“{existing.username}”已被禁用；当前不自动恢复禁用人员，请先人工确认。",
        }

    if not existing and not email:
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": ["personnel_email"],
            "clarification_question": f"新增维护人员“{name}”需要邮箱地址，请补充邮箱。",
        }

    if email:
        conflict = await db.execute(select(User).where(User.email == email))
        email_owner = conflict.scalar_one_or_none()
        if email_owner and (not existing or email_owner.id != existing.id):
            return {
                "status": "error",
                "task_type": "WRITE",
                "confidence": 0.78,
                "error_code": "personnel_email_conflict",
                "error_message": f"邮箱 {email} 已被用户 {email_owner.username} 使用。",
            }

    before: dict[str, Any] = {}
    if existing:
        before = await _personnel_state(db, existing)
        after = {
            **before,
            "email": email or existing.email,
            "skills": skills or before["skills"],
            "region": region or before["region"],
            "is_active": True,
            "is_available": True,
        }
        action_label = "更新维护人员"
    else:
        after = {
            "id": None,
            "name": name,
            "email": email,
            "role": "technician",
            "is_active": True,
            "skills": skills or DEFAULT_PERSONNEL_SKILLS,
            "region": region or DEFAULT_PERSONNEL_REGION,
            "is_available": True,
            "active_workorder_count": 0,
        }
        action_label = "新增维护人员"

    warnings: list[str] = []
    if skills or region:
        warnings.append("技能和区域会写入Agent人员资料表；派工身份仍使用系统维护人员账号。")

    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="upsert_personnel",
        params={
            "personnel_id": existing.id if existing else None,
            "name": existing.username if existing else name,
            "email": after["email"],
            "skills": after["skills"],
            "region": after["region"],
        },
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={
            "personnel_name": existing.username if existing else name,
            "email": after["email"],
            "skills": after["skills"],
            "region": after["region"],
        },
        confidence=0.82,
        workflow="personnel.upsert",
        steps=[
            "resolve_personnel_by_name",
            "validate_personnel_payload",
            "require_confirmation",
            "upsert_personnel",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "upsert_personnel",
        "workflow": "personnel.upsert",
        "confidence": 0.82,
        "confirmation": {
            "title": f"确认{action_label}",
            "summary": f"{action_label}：{after['name']} / {after['email']}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def _plan_delete_personnel(db: AsyncSession, *, user: User, message: str) -> dict[str, Any]:
    name = _extract_personnel_name(message)
    reason = _extract_reason(message)
    missing = []
    if not name:
        missing.append("assignee_name")
    if not reason:
        missing.append("reason")
    if missing:
        prompts = {
            "assignee_name": "请说明要删除或禁用哪位维护人员。",
            "reason": "请说明删除或禁用原因，便于审计。",
        }
        return {
            "status": "needs_clarification",
            "task_type": "CLARIFY",
            "confidence": 0.58,
            "missing_slots": missing,
            "clarification_question": " ".join(prompts[item] for item in missing),
        }

    resolution = await resolve_personnel_by_name(db, name)
    personnel, candidates = resolution.entity, resolution.candidates
    if not personnel:
        if candidates:
            candidate_names = "、".join(item.username for item in candidates)
            return {
                "status": "needs_clarification",
                "task_type": "CLARIFY",
                "confidence": 0.66,
                "missing_slots": ["assignee_name"],
                "clarification_question": f"找到多个相近人员：{candidate_names}。请明确要删除或禁用谁。",
            }
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.78,
            "error_code": "personnel_not_found",
            "error_message": f"未找到维护人员“{name}”。",
        }

    active_count = await _active_workorder_count(db, personnel.username)
    if active_count > 0:
        return {
            "status": "error",
            "task_type": "WRITE",
            "confidence": 0.86,
            "error_code": "personnel_has_active_workorders",
            "error_message": f"维护人员“{personnel.username}”仍有 {active_count} 个未完成工单，请先转派或关闭后再禁用。",
        }

    before = await _personnel_state(db, personnel, active_count=active_count)
    after = {**before, "is_active": False, "is_available": False, "delete_reason": reason}
    warnings = ["该动作会禁用维护人员账号，并从可派工人员解析中移除。"]
    request_id = await _store_pending_action(
        db,
        user=user,
        raw_message=message,
        task_type="WORKFLOW",
        action="delete_personnel",
        params={"personnel_id": personnel.id, "reason": reason},
        before=before,
        after=after,
        warnings=warnings,
        parsed_slots={"assignee_name": personnel.username, "reason": reason},
        confidence=0.86,
        workflow="personnel.delete",
        steps=[
            "resolve_personnel_by_name",
            "query_workorder_context",
            "validate_personnel_delete",
            "require_confirmation",
            "delete_personnel",
            "verify_written_entity",
            "present_result",
        ],
    )
    return {
        "status": "pending_confirmation",
        "task_type": "WORKFLOW",
        "request_id": request_id,
        "action": "delete_personnel",
        "workflow": "personnel.delete",
        "confidence": 0.86,
        "confirmation": {
            "title": "确认禁用维护人员",
            "summary": f"禁用维护人员 {personnel.username}",
            "before": before,
            "after": after,
            "warnings": warnings,
        },
    }


async def confirm_agent_action(
    db: AsyncSession,
    *,
    user: User,
    request_id: str,
) -> dict[str, Any]:
    # P0-13: Atomically claim the action to prevent duplicate execution
    pending = await _claim_pending_action(db, user=user, request_id=request_id)
    if not pending:
        # Check if already claimed/executed or truly missing
        existing = await db.execute(
            select(AgentActionLog).where(
                AgentActionLog.request_id == request_id,
                AgentActionLog.user_id == user.id,
            )
        )
        log = existing.scalar_one_or_none()
        if log and log.status == "executing":
            return {
                "request_id": request_id,
                "action": log.action,
                "status": "failed",
                "error_code": "already_executing",
                "error_message": "该动作正在执行中，请勿重复确认。",
            }
        if log and log.status in ("completed", "failed"):
            return {
                "request_id": request_id,
                "action": log.action,
                "status": "failed",
                "error_code": "already_processed",
                "error_message": f"该动作已处理（状态: {log.status}），请勿重复确认。",
            }
        return {
            "request_id": request_id,
            "action": "unknown",
            "status": "failed",
            "error_code": "confirmation_not_found",
            "error_message": "未找到待确认动作，请重新发起 Agent 指令。",
        }
    if pending.expires_at < _utc_now():
        _PENDING_ACTIONS.pop(request_id, None)
        await _mark_log_failed(db, request_id, "confirmation_expired", "确认已过期，请重新发起 Agent 指令。")
        return {
            "request_id": request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "confirmation_expired",
            "error_message": "确认已过期，请重新发起 Agent 指令。",
        }
    if not _can_execute_agent_action(user, pending.action):
        _PENDING_ACTIONS.pop(request_id, None)
        await _mark_log_failed(db, request_id, "permission_denied", "当前账号没有执行该Agent动作的权限。")
        return {
            "request_id": request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "permission_denied",
            "error_message": f"当前账号没有执行 Agent 动作 `{pending.action}` 的权限。本次没有修改数据。",
        }
    if pending.action == "assign_workorder":
        return await _confirm_assign_workorder(db, user=user, pending=pending)
    if pending.action in ("create_workorder", "create_workorder_record"):
        return await _confirm_create_workorder(db, user=user, pending=pending)
    if pending.action == "update_workorder_record":
        return await _confirm_update_workorder_record(db, user=user, pending=pending)
    if pending.action == "cancel_workorder_record":
        return await _confirm_cancel_workorder_record(db, user=user, pending=pending)
    if pending.action == "advance_workorder_status":
        return await _confirm_advance_workorder_status(db, user=user, pending=pending)
    if pending.action == "add_maintenance_record":
        return await _confirm_add_maintenance_record(db, user=user, pending=pending)
    if pending.action == "update_fault_processing_status":
        return await _confirm_update_fault_processing_status(db, user=user, pending=pending)
    if pending.action == "create_fault_record":
        return await _confirm_create_fault_record(db, user=user, pending=pending)
    if pending.action == "update_fault_record":
        return await _confirm_update_fault_record(db, user=user, pending=pending)
    if pending.action == "delete_fault_record":
        return await _confirm_delete_fault_record(db, user=user, pending=pending)
    if pending.action == "run_auto_fault_detection":
        return await _confirm_run_auto_fault_detection(db, user=user, pending=pending)
    if pending.action == "run_batch_fault_detection":
        return await _confirm_run_batch_fault_detection(db, user=user, pending=pending)
    if pending.action == "refresh_health_indexes":
        return await _confirm_refresh_health_indexes(db, user=user, pending=pending)
    if pending.action == "refresh_rul_predictions":
        return await _confirm_refresh_rul_predictions(db, user=user, pending=pending)
    if pending.action == "generate_maintenance_schedule":
        return await _confirm_generate_maintenance_schedule(db, user=user, pending=pending)
    if pending.action == "update_threshold_config":
        return await _confirm_update_threshold_config(db, user=user, pending=pending)
    if pending.action == "upsert_ai_provider_config":
        return await _confirm_upsert_ai_provider_config(db, user=user, pending=pending)
    if pending.action == "test_ai_provider_connection":
        return await _confirm_test_ai_provider_connection(db, user=user, pending=pending)
    if pending.action == "delete_ai_provider_config":
        return await _confirm_delete_ai_provider_config(db, user=user, pending=pending)
    if pending.action == "upsert_personnel":
        return await _confirm_upsert_personnel(db, user=user, pending=pending)
    if pending.action == "delete_personnel":
        return await _confirm_delete_personnel(db, user=user, pending=pending)
    if pending.action == "upsert_knowledge_node":
        return await _confirm_upsert_knowledge_node(db, user=user, pending=pending)
    if pending.action == "review_knowledge_node":
        return await _confirm_review_knowledge_node(db, user=user, pending=pending)
    if pending.action == "delete_knowledge_node":
        return await _confirm_delete_knowledge_node(db, user=user, pending=pending)
    return {
        "request_id": request_id,
        "action": pending.action,
        "status": "failed",
        "error_code": "action_not_supported",
        "error_message": "该待确认动作当前不支持执行。",
    }


async def _confirm_upsert_knowledge_node(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    payload = dict(pending.params["payload"])
    node_id = pending.params.get("node_id")
    if node_id is not None:
        node = await db.get(FaultKnowledgeNode, int(node_id))
        if not node:
            await _mark_log_failed(db, pending.request_id, "knowledge_node_not_found", "执行前知识节点不存在。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "knowledge_node_not_found",
                "error_message": "执行前知识节点不存在，请重新发起 Agent 指令。",
            }
        for key in (
            "category",
            "icon",
            "severity",
            "symptoms",
            "root_causes",
            "solutions",
            "related_faults",
            "spare_parts",
            "cases",
            "source",
            "confidence",
            "verified",
            "extracted_from",
        ):
            setattr(node, key, payload.get(key))
        node.updated_at = _utc_now()
    else:
        conflict = await db.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == payload["fault_type"]))
        if conflict.scalar_one_or_none():
            await _mark_log_failed(db, pending.request_id, "knowledge_node_conflict", "故障知识节点已存在。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "knowledge_node_conflict",
                "error_message": f"故障知识“{payload['fault_type']}”已存在，请重新规划为更新。",
            }
        node = FaultKnowledgeNode(
            fault_type=payload["fault_type"],
            category=payload["category"],
            icon=payload.get("icon") or "⚠️",
            severity=payload.get("severity") or "medium",
            symptoms=payload.get("symptoms") or [],
            root_causes=payload.get("root_causes") or [],
            solutions=payload.get("solutions") or [],
            related_faults=payload.get("related_faults") or [],
            spare_parts=payload.get("spare_parts") or [],
            cases=payload.get("cases") or [],
            source=payload.get("source") or "agent_task",
            confidence=float(payload.get("confidence") or 0.6),
            verified=bool(payload.get("verified", False)),
            extracted_from=payload.get("extracted_from"),
        )
        db.add(node)

    await db.flush()
    await db.refresh(node)
    after = _knowledge_state(node)
    if after["fault_type"] != payload["fault_type"]:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "知识节点写入后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "知识节点写入后回读校验失败，数据库未提交本次变更。",
        }

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/knowledge", "open_entity": {"type": "knowledge_node", "id": node.id}},
    }


async def _confirm_review_knowledge_node(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    node = await db.get(FaultKnowledgeNode, int(pending.params["node_id"]))
    if not node:
        await _mark_log_failed(db, pending.request_id, "knowledge_node_not_found", "执行前知识节点不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "knowledge_node_not_found",
            "error_message": "执行前知识节点不存在，请重新发起 Agent 指令。",
        }

    review_action = str(pending.params["review_action"])
    if review_action == "verify":
        node.verified = True
        node.confidence = 1.0
        node.updated_at = _utc_now()
        await db.flush()
        await db.refresh(node)
        after = _knowledge_state(node)
        if not node.verified or float(node.confidence or 0) < 1.0:
            await db.rollback()
            await _mark_log_failed(db, pending.request_id, "verification_failed", "审核后回读校验失败。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "verification_failed",
                "error_message": "审核后回读校验失败，数据库未提交本次变更。",
            }
    else:
        after = {**_knowledge_state(node), "deleted": True, "review_reason": pending.params.get("reason")}
        node_id = node.id
        await db.delete(node)
        await db.flush()
        check = await db.get(FaultKnowledgeNode, node_id)
        if check:
            await db.rollback()
            await _mark_log_failed(db, pending.request_id, "verification_failed", "拒绝后回读校验失败。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "verification_failed",
                "error_message": "拒绝后回读校验失败，数据库未提交本次变更。",
            }

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/knowledge", "open_entity": {"type": "knowledge_node", "id": pending.params["node_id"]}},
    }


async def _confirm_delete_knowledge_node(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    node = await db.get(FaultKnowledgeNode, int(pending.params["node_id"]))
    if not node:
        await _mark_log_failed(db, pending.request_id, "knowledge_node_not_found", "执行前知识节点不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "knowledge_node_not_found",
            "error_message": "执行前知识节点不存在，请重新发起 Agent 指令。",
        }
    after = {**_knowledge_state(node), "deleted": True, "delete_reason": pending.params.get("reason")}
    node_id = node.id
    await db.delete(node)
    await db.flush()
    check = await db.get(FaultKnowledgeNode, node_id)
    if check:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "删除后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "删除后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/knowledge", "open_entity": {"type": "knowledge_node", "id": node_id}},
    }


async def _confirm_upsert_personnel(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    personnel_id = pending.params.get("personnel_id")
    name = str(pending.params["name"])
    email = str(pending.params["email"])
    skills = list(pending.params.get("skills") or DEFAULT_PERSONNEL_SKILLS)
    region = str(pending.params.get("region") or DEFAULT_PERSONNEL_REGION)

    if personnel_id is not None:
        personnel = await db.get(User, int(personnel_id))
        if not personnel or personnel.role != "technician" or not personnel.is_active:
            await _mark_log_failed(db, pending.request_id, "entity_changed", "执行前维护人员状态已变化。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "entity_changed",
                "error_message": "执行前维护人员状态已变化，请重新发起 Agent 指令。",
            }
        email_conflict = await db.execute(select(User).where(User.email == email, User.id != personnel.id))
        if email_conflict.scalar_one_or_none():
            await _mark_log_failed(db, pending.request_id, "personnel_email_conflict", "邮箱已被其他用户使用。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "personnel_email_conflict",
                "error_message": f"邮箱 {email} 已被其他用户使用。",
            }
        personnel.email = email
    else:
        conflict = await db.execute(select(User).where(or_(User.username == name, User.email == email)))
        if conflict.scalar_one_or_none():
            await _mark_log_failed(db, pending.request_id, "personnel_conflict", "维护人员名称或邮箱已存在。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "personnel_conflict",
                "error_message": "维护人员名称或邮箱已存在，请重新规划。",
            }
        personnel = User(
            username=name,
            email=email,
            password_hash=hash_password("temp123"),
            role="technician",
            is_active=True,
        )
        db.add(personnel)
        await db.flush()

    profile = await _personnel_profile(db, personnel)
    if profile:
        profile.name = personnel.username
        profile.email = personnel.email
        profile.skills = skills
        profile.region = region
        profile.is_available = True
        profile.updated_at = _utc_now()
    else:
        profile = MaintenancePersonnel(
            user_id=personnel.id,
            name=personnel.username,
            email=personnel.email,
            skills=skills,
            region=region,
            is_available=True,
        )
        db.add(profile)

    await db.flush()
    await db.refresh(personnel)
    await db.refresh(profile)
    after = await _personnel_state(db, personnel, profile=profile)
    verified = (
        personnel.role == "technician"
        and personnel.is_active
        and personnel.email == email
        and profile.user_id == personnel.id
        and profile.skills == skills
        and profile.region == region
    )
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "人员写入后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "人员写入后回读校验失败，数据库未提交本次变更。",
        }

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/settings", "open_entity": {"type": "personnel", "id": personnel.id}},
    }


async def _confirm_delete_personnel(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    personnel = await db.get(User, int(pending.params["personnel_id"]))
    if not personnel or personnel.role != "technician" or not personnel.is_active:
        await _mark_log_failed(db, pending.request_id, "entity_changed", "执行前维护人员状态已变化。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "entity_changed",
            "error_message": "执行前维护人员状态已变化，请重新发起 Agent 指令。",
        }

    active_count = await _active_workorder_count(db, personnel.username)
    if active_count > 0:
        await _mark_log_failed(db, pending.request_id, "personnel_has_active_workorders", "维护人员仍有未完成工单。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "personnel_has_active_workorders",
            "error_message": f"维护人员“{personnel.username}”仍有 {active_count} 个未完成工单，请先转派或关闭后再禁用。",
        }

    personnel.is_active = False
    profile = await _personnel_profile(db, personnel)
    if profile:
        profile.is_available = False
        profile.updated_at = _utc_now()
    await db.flush()
    await db.refresh(personnel)
    if profile:
        await db.refresh(profile)
    after = await _personnel_state(db, personnel, profile=profile, active_count=active_count)
    after["delete_reason"] = pending.params.get("reason")
    if personnel.is_active:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "禁用后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "禁用后回读校验失败，数据库未提交本次变更。",
        }

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/settings", "open_entity": {"type": "personnel", "id": personnel.id}},
    }


async def _confirm_assign_workorder(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    workorder = await _resolve_workorder(db, int(pending.params["workorder_id"]))
    assignee = await db.get(User, int(pending.params["assignee_id"]))
    if not workorder or not assignee or assignee.role != "technician" or not assignee.is_active:
        await _mark_log_failed(db, pending.request_id, "entity_changed", "执行前实体状态已变化，请重新规划。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "entity_changed",
            "error_message": "执行前工单或人员状态已变化，请重新发起 Agent 指令。",
        }
    if workorder.status in FINAL_STATUSES:
        await _mark_log_failed(db, pending.request_id, "invalid_status_transition", "工单状态已不可派工。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_status_transition",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许派工。",
        }

    before_status = workorder.status
    workorder.assignee = assignee.username
    workorder.assignee_id = assignee.id
    workorder.assignee_email = assignee.email
    if workorder.status == "pending":
        workorder.status = "assigned"
    workorder.updated_at = _utc_now()
    db.add(
        MaintenanceRecord(
            work_order_id=workorder.id,
            operator_id=user.id,
            action_type="assigned",
            content=f"Agent assigned work order to {assignee.username}",
            before_status=before_status,
            after_status=workorder.status,
            extra={"agent_request_id": pending.request_id, "assignee_email": assignee.email},
        )
    )
    await db.flush()
    await db.refresh(workorder)
    after = _workorder_state(workorder)
    verified = (
        workorder.assignee_id == assignee.id
        and workorder.assignee == assignee.username
        and workorder.assignee_email == assignee.email
    )
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "派工后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "派工后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_create_workorder(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine = await db.get(Turbine, int(pending.params["turbine_id"]))
    if not turbine:
        await _mark_log_failed(db, pending.request_id, "turbine_not_found", "执行前风机不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "turbine_not_found",
            "error_message": "执行前风机不存在，请重新发起 Agent 指令。",
        }

    assignee = None
    assignee_id = pending.params.get("assignee_id")
    if assignee_id:
        assignee = await db.get(User, int(assignee_id))
        if not assignee or assignee.role != "technician" or not assignee.is_active:
            await _mark_log_failed(db, pending.request_id, "assignee_not_found", "执行前人员不可用。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "assignee_not_found",
                "error_message": "执行前人员不可用，请重新发起 Agent 指令。",
            }

    now = _utc_now()
    workorder = WorkOrder(
        turbine_id=turbine.id,
        fault_id=pending.params.get("fault_id"),
        title=str(pending.params["title"]),
        description=str(pending.params.get("description") or ""),
        status="assigned" if assignee else "pending",
        priority=str(pending.params.get("priority") or "medium"),
        fault_type=pending.params.get("fault_type"),
        assignee=assignee.username if assignee else None,
        assignee_id=assignee.id if assignee else None,
        assignee_email=assignee.email if assignee else None,
        cost_estimate=0.0,
        created_at=now,
        updated_at=now,
    )
    db.add(workorder)
    await db.flush()
    db.add(
        MaintenanceRecord(
            work_order_id=workorder.id,
            operator_id=user.id,
            action_type="created",
            content="Agent created work order",
            before_status=None,
            after_status=workorder.status,
            extra={"agent_request_id": pending.request_id},
        )
    )
    await db.flush()
    await db.refresh(workorder)
    after = _workorder_state(workorder)
    verified = workorder.id is not None and workorder.turbine_id == turbine.id
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "创建后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "创建后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_update_workorder_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    workorder = await _resolve_workorder(db, int(pending.params["workorder_id"]))
    if not workorder:
        await _mark_log_failed(db, pending.request_id, "workorder_not_found", "执行前工单不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "workorder_not_found",
            "error_message": "执行前工单不存在，请重新发起 Agent 指令。",
        }
    if workorder.status in {"closed", "cancelled"}:
        await _mark_log_failed(db, pending.request_id, "invalid_workorder_status", "工单已处于关闭或取消状态。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许修改核心字段。",
        }

    patch_fields = dict(pending.params.get("patch_fields") or {})
    if "due_date" in patch_fields and isinstance(patch_fields["due_date"], str):
        try:
            patch_fields["due_date"] = datetime.fromisoformat(str(patch_fields["due_date"]))
        except ValueError:
            await _mark_log_failed(db, pending.request_id, "invalid_due_date", "截止日期格式无效。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "invalid_due_date",
                "error_message": "截止日期格式无效，请重新发起 Agent 指令。",
            }
    before_status = workorder.status
    for key in ("title", "description", "priority", "fault_type", "cost_estimate", "due_date"):
        if key in patch_fields:
            setattr(workorder, key, patch_fields[key])
    workorder.updated_at = _utc_now()
    db.add(
        MaintenanceRecord(
            work_order_id=workorder.id,
            operator_id=user.id,
            action_type="updated",
            content="Agent updated work order fields",
            before_status=before_status,
            after_status=workorder.status,
            extra={"agent_request_id": pending.request_id, "updated_fields": sorted(patch_fields.keys())},
        )
    )
    await db.flush()
    await db.refresh(workorder)
    after = _workorder_state(workorder)
    verified = True
    for key, expected in patch_fields.items():
        actual = getattr(workorder, key)
        if isinstance(expected, datetime):
            verified = verified and actual == expected
        else:
            verified = verified and actual == expected
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "工单字段更新后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "工单字段更新后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_cancel_workorder_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    workorder = await _resolve_workorder(db, int(pending.params["workorder_id"]))
    if not workorder:
        await _mark_log_failed(db, pending.request_id, "workorder_not_found", "执行前工单不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "workorder_not_found",
            "error_message": "执行前工单不存在，请重新发起 Agent 指令。",
        }
    if workorder.status in {"closed", "cancelled"}:
        await _mark_log_failed(db, pending.request_id, "invalid_workorder_status", "工单已处于关闭或取消状态。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许重复取消。",
        }

    before_status = workorder.status
    reason = str(pending.params.get("reason") or "")
    now = _utc_now()
    workorder.status = "cancelled"
    workorder.cancelled_at = now
    workorder.updated_at = now
    db.add(
        MaintenanceRecord(
            work_order_id=workorder.id,
            operator_id=user.id,
            action_type="cancelled",
            content=f"Agent cancelled work order. Reason: {reason}",
            before_status=before_status,
            after_status=workorder.status,
            extra={"agent_request_id": pending.request_id, "reason": reason},
        )
    )
    await db.flush()
    await db.refresh(workorder)
    after = {**_workorder_state(workorder), "cancel_reason": reason}
    if workorder.status != "cancelled" or not workorder.cancelled_at:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "工单取消后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "工单取消后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_advance_workorder_status(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    workorder = await _resolve_workorder(db, int(pending.params["workorder_id"]))
    target_status = str(pending.params["target_status"])
    if not workorder:
        await _mark_log_failed(db, pending.request_id, "workorder_not_found", "执行前工单不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "workorder_not_found",
            "error_message": "执行前工单不存在，请重新发起 Agent 指令。",
        }
    ok, reason = _validate_workorder_transition(workorder.status, target_status)
    if not ok:
        await _mark_log_failed(db, pending.request_id, "invalid_status_transition", reason or "工单状态不可变更。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_status_transition",
            "error_message": reason or "工单状态不可变更。",
        }

    before_status = workorder.status
    workorder.status = target_status
    workorder.updated_at = _utc_now()
    if target_status == "completed":
        workorder.completed_at = _utc_now()
    elif target_status == "cancelled":
        workorder.cancelled_at = _utc_now()
    note = pending.params.get("note")
    db.add(
        MaintenanceRecord(
            work_order_id=workorder.id,
            operator_id=user.id,
            action_type="status_changed",
            content=str(note or f"Agent changed status to {target_status}"),
            before_status=before_status,
            after_status=target_status,
            extra={"agent_request_id": pending.request_id},
        )
    )
    await db.flush()
    await db.refresh(workorder)
    after = _workorder_state(workorder)
    if workorder.status != target_status:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "状态变更后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "状态变更后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_add_maintenance_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    workorder = await _resolve_workorder(db, int(pending.params["workorder_id"]))
    if not workorder:
        await _mark_log_failed(db, pending.request_id, "workorder_not_found", "执行前工单不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "workorder_not_found",
            "error_message": "执行前工单不存在，请重新发起 Agent 指令。",
        }
    if workorder.status in {"closed", "cancelled"}:
        await _mark_log_failed(db, pending.request_id, "invalid_workorder_status", "工单已处于关闭或取消状态。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_workorder_status",
            "error_message": f"{_workorder_ref(workorder)} 当前状态为 {workorder.status}，不允许追加维修记录。",
        }

    target_status = pending.params.get("target_status")
    before_status = workorder.status
    if target_status:
        ok, reason = _validate_workorder_transition(workorder.status, str(target_status))
        if not ok:
            await _mark_log_failed(db, pending.request_id, "invalid_status_transition", reason or "工单状态不可变更。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "invalid_status_transition",
                "error_message": reason or "工单状态不可变更。",
            }
        workorder.status = str(target_status)
        if target_status == "completed":
            workorder.completed_at = _utc_now()
        elif target_status == "cancelled":
            workorder.cancelled_at = _utc_now()
    if pending.params.get("cost_actual") is not None:
        workorder.cost_actual = float(pending.params["cost_actual"])
    if pending.params.get("downtime_hours") is not None:
        workorder.downtime_hours = float(pending.params["downtime_hours"])
    workorder.updated_at = _utc_now()
    record = MaintenanceRecord(
        work_order_id=workorder.id,
        operator_id=user.id,
        action_type="progress",
        content=str(pending.params["content"]),
        before_status=before_status,
        after_status=workorder.status,
        extra={
            "agent_request_id": pending.request_id,
            "cost_actual": pending.params.get("cost_actual"),
            "downtime_hours": pending.params.get("downtime_hours"),
        },
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    await db.refresh(workorder)
    after = {
        **_workorder_state(workorder),
        "new_record": {
            "id": record.id,
            "action_type": record.action_type,
            "content": record.content,
            "before_status": record.before_status,
            "after_status": record.after_status,
        },
    }
    if not record.id:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "维护记录创建后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "维护记录创建后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/workorder", "open_entity": {"type": "workorder", "id": workorder.id}},
    }


async def _confirm_update_fault_processing_status(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    fault = await db.get(Fault, int(pending.params["fault_id"]))
    if not fault:
        await _mark_log_failed(db, pending.request_id, "fault_not_found", "执行前故障不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "fault_not_found",
            "error_message": "执行前故障不存在，请重新发起 Agent 指令。",
        }
    current_processing_status = getattr(fault, "processing_status", None)
    if current_processing_status in {"closed", "failed"} or fault.status == "closed":
        await _mark_log_failed(db, pending.request_id, "invalid_fault_status", "故障已处于终态。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_fault_status",
            "error_message": f"故障 #{fault.id} 已处于终态，不允许重复关闭或标记失败。",
        }

    target_status = str(pending.params["processing_status"])
    now = _utc_now()
    handler = pending.params.get("handler") or user.username
    status_note = pending.params.get("status_note")
    if target_status == "closed":
        fault.status = "closed"
    await _update_fault_runtime_columns(
        db,
        fault_id=fault.id,
        processing_status=target_status,
        handler=str(handler),
        status_note=str(status_note or ""),
        now=now,
        status=fault.status,
    )
    await db.flush()
    await db.refresh(fault)
    after = _fault_state(fault)
    after["processing_status"] = target_status
    after["handler"] = handler
    after["status_note"] = status_note
    if target_status == "closed":
        after["status"] = "closed"
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "fault", "id": fault.id}},
    }


async def _confirm_create_fault_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine = await db.get(Turbine, int(pending.params["turbine_id"]))
    if not turbine:
        await _mark_log_failed(db, pending.request_id, "turbine_not_found", "执行前风机不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "turbine_not_found",
            "error_message": "执行前风机不存在，请重新发起 Agent 指令。",
        }

    fault_type = str(pending.params.get("fault_type") or "").strip()
    if not fault_type:
        await _mark_log_failed(db, pending.request_id, "missing_required_param", "缺少故障类型。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "missing_required_param",
            "error_message": "缺少故障类型，本次没有创建故障记录。",
        }
    confidence = float(pending.params.get("confidence") if pending.params.get("confidence") is not None else 0.5)
    if not (0 <= confidence <= 1):
        await _mark_log_failed(db, pending.request_id, "invalid_confidence", "置信度必须在0到1之间。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_confidence",
            "error_message": "置信度必须在0到1之间，本次没有创建故障记录。",
        }

    duplicate_result = await db.execute(
        select(Fault).where(
            Fault.turbine_id == turbine.id,
            Fault.fault_type == fault_type,
            Fault.status.in_(["open", "active", "pending"]),
        )
    )
    duplicate = duplicate_result.scalar_one_or_none()
    if duplicate and not bool(pending.params.get("allow_duplicate")):
        await _mark_log_failed(db, pending.request_id, "duplicate_active_fault", "执行前发现同类活跃故障。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "duplicate_active_fault",
            "error_message": f"{turbine.name} 已存在同类活跃故障 #{duplicate.id}，请重新确认是否需要新增独立记录。",
        }

    now = _utc_now()
    priority = str(pending.params.get("priority") or "medium")
    details = dict(pending.params.get("details") or {})
    details["agent_request_id"] = pending.request_id
    fault = Fault(
        turbine_id=turbine.id,
        detected_at=now,
        fault_type=fault_type,
        confidence=confidence,
        status="open",
        details=details,
    )
    db.add(fault)
    await db.flush()
    await _update_fault_optional_columns(
        db,
        fault_id=fault.id,
        values={
            "priority": priority,
            "processing_status": "pending",
            "discovered_at": now,
            "last_action_at": now,
            "status_note": "Agent人工创建故障记录",
        },
    )
    await db.flush()
    await db.refresh(fault)
    if not fault.id or fault.turbine_id != turbine.id or fault.fault_type != fault_type:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "故障创建后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "故障创建后回读校验失败，数据库未提交本次变更。",
        }

    after = _fault_state(fault)
    after.update(
        {
            "turbine_name": turbine.name,
            "turbine_region": turbine.region,
            "priority": priority,
            "processing_status": "pending",
        }
    )
    await _mark_log_success(db, pending.request_id, jsonable_encoder(after))
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": jsonable_encoder(after),
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "fault", "id": fault.id}},
    }


async def _confirm_update_fault_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    fault = await db.get(Fault, int(pending.params["fault_id"]))
    if not fault:
        await _mark_log_failed(db, pending.request_id, "fault_not_found", "执行前故障不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "fault_not_found",
            "error_message": "执行前故障不存在，请重新发起 Agent 指令。",
        }
    if fault.status == "closed" and str(user.role or "") != "admin":
        await _mark_log_failed(db, pending.request_id, "closed_fault_admin_required", "已关闭故障需要管理员修改。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "closed_fault_admin_required",
            "error_message": f"故障 #{fault.id} 已关闭，修改核心字段需要管理员执行。",
        }

    patch = dict(pending.params.get("patch_fields") or {})
    if not patch:
        await _mark_log_failed(db, pending.request_id, "missing_required_param", "缺少故障修改字段。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "missing_required_param",
            "error_message": "缺少故障修改字段，本次没有修改数据。",
        }
    if "confidence" in patch and not (0 <= float(patch["confidence"]) <= 1):
        await _mark_log_failed(db, pending.request_id, "invalid_confidence", "置信度必须在0到1之间。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_confidence",
            "error_message": "置信度必须在0到1之间，本次没有修改数据。",
        }

    expected: dict[str, Any] = {}
    if "fault_type" in patch:
        fault.fault_type = str(patch["fault_type"])
        expected["fault_type"] = fault.fault_type
    if "confidence" in patch:
        fault.confidence = float(patch["confidence"])
        expected["confidence"] = fault.confidence
    if "details_description" in patch:
        details = dict(fault.details or {})
        details["description"] = str(patch["details_description"])
        details["updated_by_agent_request_id"] = pending.request_id
        fault.details = details
        expected["details"] = details

    optional_values: dict[str, Any] = {"last_action_at": _utc_now()}
    for key in ("priority", "handler", "status_note"):
        if key in patch:
            optional_values[key] = patch[key]
            expected[key] = patch[key]
    await _update_fault_optional_columns(db, fault_id=fault.id, values=optional_values)
    await db.flush()
    await db.refresh(fault)

    verified = True
    if "fault_type" in expected:
        verified = verified and fault.fault_type == expected["fault_type"]
    if "confidence" in expected:
        verified = verified and abs(float(fault.confidence or 0) - float(expected["confidence"])) < 0.0001
    if "details" in expected:
        verified = verified and dict(fault.details or {}).get("description") == expected["details"].get("description")
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "故障更新后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "故障更新后回读校验失败，数据库未提交本次变更。",
        }

    after = _fault_state(fault)
    for key in ("priority", "handler", "status_note"):
        if key in expected:
            after[key] = expected[key]
    await _mark_log_success(db, pending.request_id, jsonable_encoder(after))
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": jsonable_encoder(after),
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "fault", "id": fault.id}},
    }


async def _confirm_delete_fault_record(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    fault = await db.get(Fault, int(pending.params["fault_id"]))
    if not fault:
        await _mark_log_failed(db, pending.request_id, "fault_not_found", "执行前故障不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "fault_not_found",
            "error_message": "执行前故障不存在，请重新发起 Agent 指令。",
        }
    linked_orders = (
        await db.execute(select(WorkOrder).where(WorkOrder.fault_id == fault.id))
    ).scalars().all()
    if linked_orders:
        refs = "、".join(_workorder_ref(item) for item in linked_orders[:5])
        await _mark_log_failed(db, pending.request_id, "fault_has_linked_workorders", f"故障已关联工单 {refs}。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "fault_has_linked_workorders",
            "error_message": f"故障 #{fault.id} 已关联工单 {refs}，为保留追溯链，本次没有删除。",
        }

    deleted_snapshot = {**_fault_state(fault), "deleted": True, "delete_reason": pending.params.get("reason")}
    signals = (
        await db.execute(select(FaultSignal).where(FaultSignal.fault_id == fault.id))
    ).scalars().all()
    for signal in signals:
        await db.delete(signal)
    fault_id = fault.id
    await db.delete(fault)
    await db.flush()
    if await db.get(Fault, fault_id):
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "故障删除后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "故障删除后回读校验失败，数据库未提交本次变更。",
        }

    await _mark_log_success(db, pending.request_id, jsonable_encoder(deleted_snapshot))
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": jsonable_encoder(deleted_snapshot),
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "fault", "id": fault_id}},
    }


async def _calculate_turbine_hi_snapshot(
    db: AsyncSession,
    *,
    turbine: Turbine,
    window_rows: int,
) -> dict[str, Any]:
    records = (
        await db.execute(
            select(SCADARecord)
            .where(SCADARecord.turbine_id == turbine.id)
            .order_by(SCADARecord.timestamp.desc())
            .limit(window_rows)
        )
    ).scalars().all()
    result = calculate_care_hi_from_scada(list(records))
    return {
        "id": turbine.id,
        "name": turbine.name,
        "region": turbine.region,
        "previous_hi_value": turbine.hi_value,
        "previous_status": turbine.status,
        "hi_value": result.hi_value,
        "status": result.status,
        "component_scores": result.component_scores,
        "scada_window_rows": len(records),
        "source_dataset": turbine.source_dataset or "unknown",
    }


async def _confirm_refresh_health_indexes(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine_ids = [int(item) for item in (pending.params.get("turbine_ids") or [])]
    if not turbine_ids:
        await _mark_log_failed(db, pending.request_id, "health_refresh_scope_empty", "刷新范围为空。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "health_refresh_scope_empty",
            "error_message": "刷新范围为空，请重新发起 Agent 指令。",
        }
    result = await db.execute(
        select(Turbine).where(Turbine.id.in_(turbine_ids)).order_by(Turbine.region.asc(), Turbine.name.asc())
    )
    turbines = list(result.scalars().all())
    if not turbines:
        await _mark_log_failed(db, pending.request_id, "health_refresh_scope_empty", "刷新范围内没有可用风机。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "health_refresh_scope_empty",
            "error_message": "刷新范围内没有可用风机，请重新发起 Agent 指令。",
        }

    window_rows = int(pending.params.get("window_rows") or 144)
    updates: list[dict[str, Any]] = []
    for turbine in turbines:
        snapshot = await _calculate_turbine_hi_snapshot(db, turbine=turbine, window_rows=window_rows)
        turbine.hi_value = float(snapshot["hi_value"])
        turbine.status = str(snapshot["status"])
        updates.append(snapshot)
    await db.flush()

    refreshed = (
        await db.execute(select(Turbine).where(Turbine.id.in_([item["id"] for item in updates])))
    ).scalars().all()
    by_id = {item.id: item for item in refreshed}
    verified = True
    for item in updates:
        turbine = by_id.get(int(item["id"]))
        if not turbine:
            verified = False
            break
        verified = verified and abs(float(turbine.hi_value or 0) - float(item["hi_value"])) < 0.0001
        verified = verified and str(turbine.status) == str(item["status"])
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "健康指数刷新后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "健康指数刷新后回读校验失败，数据库未提交本次变更。",
        }

    status_summary: dict[str, int] = {}
    for item in updates:
        status = str(item.get("status") or "unknown")
        status_summary[status] = status_summary.get(status, 0) + 1
    after = jsonable_encoder(
        {
            "scope": pending.params.get("scope") or {},
            "affected_count": len(updates),
            "window_rows": window_rows,
            "source_dataset": CARE_DATASET_ID,
            "status_summary": status_summary,
            "items": updates,
        }
    )
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/dashboard", "open_entity": {"type": "health_refresh", "id": None}},
    }


async def _update_fault_optional_columns(
    db: AsyncSession,
    *,
    fault_id: int,
    values: dict[str, Any],
) -> None:
    if not values:
        return
    try:
        result = await db.execute(text("PRAGMA table_info(faults)"))
        pragma_columns = {row[1] for row in result.fetchall()}
    except Exception:
        pragma_columns = set()
    updates = {key: value for key, value in values.items() if key in pragma_columns}
    if not updates:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    params = {**updates, "fault_id": fault_id}
    await db.execute(text(f"UPDATE faults SET {assignments} WHERE id = :fault_id"), params)


async def _update_fault_runtime_columns(
    db: AsyncSession,
    *,
    fault_id: int,
    processing_status: str,
    handler: str,
    status_note: str,
    now: datetime,
    status: str,
) -> None:
    columns = {
        "processing_status": processing_status,
        "handler": handler,
        "status_note": status_note,
        "last_action_at": now,
    }
    if processing_status == "closed":
        columns["closed_at"] = now
        columns["status"] = "closed"
    elif processing_status == "failed":
        columns["failed_at"] = now
    elif processing_status == "processing":
        columns["processing_started_at"] = now
    columns["status"] = status

    available = set(columns)
    try:
        result = await db.execute(text("PRAGMA table_info(faults)"))
        pragma_columns = {row[1] for row in result.fetchall()}
        if pragma_columns:
            available = pragma_columns
    except Exception:
        available = set(columns)

    updates = {key: value for key, value in columns.items() if key in available}
    if not updates:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in updates)
    params = {**updates, "fault_id": fault_id}
    await db.execute(text(f"UPDATE faults SET {assignments} WHERE id = :fault_id"), params)


async def _confirm_run_auto_fault_detection(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine = await db.get(Turbine, int(pending.params["turbine_id"]))
    if not turbine:
        await _mark_log_failed(db, pending.request_id, "turbine_not_found", "执行前风机不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "turbine_not_found",
            "error_message": "执行前风机不存在，请重新发起 Agent 指令。",
        }

    component = str(pending.params.get("component") or "gearbox_high_speed")
    window_hours = int(pending.params.get("window_hours") or 24)
    persist_result = bool(pending.params.get("persist_result"))

    try:
        from app.api.diagnosis import _build_dataset_detection

        detection = await _build_dataset_detection(db, turbine, component, window_hours)
    except Exception as exc:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "auto_detection_failed", str(exc)[:240])
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "auto_detection_failed",
            "error_message": f"自动故障检测执行失败：{str(exc)[:180]}",
        }

    after = jsonable_encoder(
        {
            **detection,
            "turbine_name": turbine.name,
            "turbine_region": turbine.region,
            "persist_requested": persist_result,
            "persisted_fault_id": None,
            "persist_note": None,
        }
    )
    confidence = float(after.get("confidence") or 0.0)
    fault_type = str(after.get("fault_type") or "no_fault_detected")
    status = str(after.get("status") or "")

    if persist_result:
        if status != "suspected_fault" or fault_type == "no_fault_detected":
            after["persist_note"] = "检测结果未达到疑似故障状态，未新增故障记录。"
        elif confidence < 0.65:
            after["persist_note"] = "检测置信度低于0.65，按安全规则未新增故障记录。"
        else:
            fault = Fault(
                turbine_id=turbine.id,
                detected_at=_utc_now(),
                fault_type=fault_type,
                confidence=confidence,
                status="open",
                details={
                    "source": "agent_auto_detection",
                    "agent_request_id": pending.request_id,
                    "component": component,
                    "analysis_window_hours": window_hours,
                    "algorithm_status": after.get("algorithm_status"),
                    "message": after.get("message"),
                    "confidence_interval": after.get("confidence_interval"),
                },
            )
            db.add(fault)
            await db.flush()
            for signal in after.get("signals") or []:
                if not isinstance(signal, dict):
                    continue
                db.add(
                    FaultSignal(
                        fault_id=fault.id,
                        sensor_name=str(signal.get("sensor_name") or "unknown"),
                        contribution_score=float(signal.get("contribution_score") or 0.0),
                        priority=str(signal.get("priority") or "medium"),
                    )
                )
            await db.flush()
            await db.refresh(fault)
            after["persisted_fault_id"] = fault.id
            after["persist_note"] = "已根据用户确认新增故障记录。"

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "auto_detection", "id": turbine.id}},
    }


async def _confirm_run_batch_fault_detection(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine_ids = [int(item) for item in (pending.params.get("turbine_ids") or [])]
    if not turbine_ids:
        await _mark_log_failed(db, pending.request_id, "batch_scope_empty", "批量检测范围为空。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "batch_scope_empty",
            "error_message": "批量检测范围为空，请重新发起 Agent 指令。",
        }

    result = await db.execute(
        select(Turbine).where(Turbine.id.in_(turbine_ids)).order_by(Turbine.region.asc(), Turbine.name.asc())
    )
    turbines = list(result.scalars().all())
    if not turbines:
        await _mark_log_failed(db, pending.request_id, "batch_scope_empty", "批量检测范围内没有可用风机。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "batch_scope_empty",
            "error_message": "批量检测范围内没有可用风机，请重新发起 Agent 指令。",
        }

    component = str(pending.params.get("component") or "gearbox_high_speed")
    window_hours = int(pending.params.get("window_hours") or 24)
    persist_result = bool(pending.params.get("persist_result"))
    try:
        from app.api.diagnosis import _build_dataset_detection

        records: list[dict[str, Any]] = []
        group_summary: dict[str, int] = {}
        persisted_fault_ids: list[int] = []
        skipped_existing = 0
        skipped_low_confidence = 0
        for turbine in turbines:
            detection = await _build_dataset_detection(db, turbine, component, window_hours)
            record = jsonable_encoder(
                {
                    **detection,
                    "record_id": f"{turbine.id}-{_utc_now().strftime('%Y%m%d%H%M%S')}",
                    "turbine_name": turbine.name,
                    "turbine_region": turbine.region,
                    "turbine_status": turbine.status,
                    "group_key": turbine.region or "未分组",
                }
            )
            records.append(record)
            group_key = str(record.get("group_key") or "未分组")
            group_summary[group_key] = group_summary.get(group_key, 0) + 1

            if not persist_result:
                continue
            confidence = float(record.get("confidence") or 0.0)
            fault_type = str(record.get("fault_type") or "no_fault_detected")
            if record.get("status") != "suspected_fault" or fault_type == "no_fault_detected" or confidence < 0.65:
                skipped_low_confidence += 1
                continue
            existing = await db.execute(
                select(Fault).where(
                    Fault.turbine_id == turbine.id,
                    Fault.fault_type == fault_type,
                    Fault.status == "open",
                )
            )
            if existing.scalar_one_or_none():
                skipped_existing += 1
                continue
            fault = Fault(
                turbine_id=turbine.id,
                detected_at=_utc_now(),
                fault_type=fault_type,
                confidence=confidence,
                status="open",
                details={
                    "source": "agent_batch_detection",
                    "agent_request_id": pending.request_id,
                    "component": component,
                    "analysis_window_hours": window_hours,
                    "algorithm_status": record.get("algorithm_status"),
                    "message": record.get("message"),
                    "confidence_interval": record.get("confidence_interval"),
                },
            )
            db.add(fault)
            await db.flush()
            for signal in record.get("signals") or []:
                if not isinstance(signal, dict):
                    continue
                db.add(
                    FaultSignal(
                        fault_id=fault.id,
                        sensor_name=str(signal.get("sensor_name") or "unknown"),
                        contribution_score=float(signal.get("contribution_score") or 0.0),
                        priority=str(signal.get("priority") or "medium"),
                    )
                )
            await db.flush()
            persisted_fault_ids.append(fault.id)
    except Exception as exc:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "batch_detection_failed", str(exc)[:240])
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "batch_detection_failed",
            "error_message": f"批量故障检测执行失败：{str(exc)[:180]}",
        }

    after = jsonable_encoder(
        {
            "success": True,
            "total": len(records),
            "component": component,
            "analysis_window_hours": window_hours,
            "persist_requested": persist_result,
            "persisted_fault_ids": persisted_fault_ids,
            "skipped_existing_faults": skipped_existing,
            "skipped_low_confidence": skipped_low_confidence,
            "group_summary": group_summary,
            "records": records,
            "message": "已完成批量故障检测。",
        }
    )
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/diagnosis", "open_entity": {"type": "batch_detection", "id": None}},
    }


async def _confirm_refresh_rul_predictions(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    turbine_id = pending.params.get("turbine_id")
    if turbine_id is not None:
        turbine = await db.get(Turbine, int(turbine_id))
        if not turbine:
            await _mark_log_failed(db, pending.request_id, "turbine_not_found", "执行前风机不存在。")
            return {
                "request_id": pending.request_id,
                "action": pending.action,
                "status": "failed",
                "error_code": "turbine_not_found",
                "error_message": "执行前风机不存在，请重新发起 Agent 指令。",
            }
    summary = await refresh_rul_predictions(turbine_id=int(turbine_id) if turbine_id is not None else None, db=db)
    after = {
        "scope": "all" if turbine_id is None else int(turbine_id),
        "refresh_summary": summary,
    }
    if summary.get("refreshed", 0) <= 0:
        await _mark_log_failed(db, pending.request_id, "rul_refresh_empty", "刷新范围内没有可用风机。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "rul_refresh_empty",
            "error_message": "刷新范围内没有可用风机。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/prediction", "open_entity": {"type": "rul", "id": turbine_id}},
    }


async def _confirm_generate_maintenance_schedule(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    region = pending.params.get("region")
    max_days = int(pending.params.get("max_days") or 90)
    top_n = int(pending.params.get("top_n") or 30)
    create_work_orders = bool(pending.params.get("create_work_orders"))
    preview = await _build_schedule_preview(db, region=str(region) if region else None, max_days=max_days, top_n=top_n)
    if preview["plan_count"] == 0:
        await _mark_log_failed(db, pending.request_id, "maintenance_plan_empty", "当前没有可用于排程的维护计划数据。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "maintenance_plan_empty",
            "error_message": "当前没有可用于排程的RUL预测或维护计划数据，本次没有创建排程。",
        }

    created_workorders: list[dict[str, Any]] = []
    if create_work_orders:
        for item in preview["scheduled"]:
            if item.get("priority") not in ("urgent", "high"):
                continue
            component = str(item.get("component") or "维护")
            existing_result = await db.execute(
                select(WorkOrder).where(
                    WorkOrder.turbine_id == int(item["turbine_id"]),
                    WorkOrder.fault_type == component,
                    WorkOrder.status.in_(["pending", "assigned", "in_progress"]),
                )
            )
            if existing_result.scalar_one_or_none():
                continue
            scheduled_date = item.get("scheduled_date")
            due_date = None
            if scheduled_date:
                try:
                    due_date = datetime.fromisoformat(str(scheduled_date)).replace(tzinfo=timezone.utc)
                except ValueError:
                    due_date = None
            workorder = WorkOrder(
                turbine_id=int(item["turbine_id"]),
                title=f"{item.get('turbine_name', '')} {component}{item.get('action', '检修')}",
                description=(
                    f"Agent维护排程生成：RUL={float(item.get('rul_days') or 0):.0f}天，"
                    f"紧急度={item.get('urgency_score')}，建议动作={item.get('action')}。"
                ),
                status="pending",
                priority=str(item.get("priority") or "medium"),
                fault_type=component,
                cost_estimate=float(item.get("cost_estimate") or 0.0),
                due_date=due_date,
                created_at=_utc_now(),
                updated_at=_utc_now(),
                downtime_hours=float(item.get("downtime_hours") or 0.0),
            )
            db.add(workorder)
            await db.flush()
            created_workorders.append(_workorder_state(workorder))

    after = {
        "scope": region or "all",
        "max_days": max_days,
        "top_n": top_n,
        "create_work_orders": create_work_orders,
        "scheduled": preview["scheduled"],
        "overflow": preview["overflow"],
        "conflicts": preview["conflicts"],
        "total_scheduled": preview["total_scheduled"],
        "total_overflow": preview["total_overflow"],
        "conflict_count": preview["conflict_count"],
        "urgent_count": preview["urgent_count"],
        "high_count": preview["high_count"],
        "total_cost_estimate": preview["total_cost_estimate"],
        "work_orders_created": len(created_workorders),
        "created_workorders": created_workorders,
    }
    await _mark_log_success(db, pending.request_id, jsonable_encoder(after))
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": jsonable_encoder(after),
        "display": {"navigate_to": "/prediction", "open_entity": {"type": "maintenance_schedule", "id": None}},
    }


async def _confirm_update_threshold_config(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    patch = dict(pending.params.get("threshold_payload") or {})
    if "hi_threshold" in patch and not (0 <= float(patch["hi_threshold"]) <= 100):
        await _mark_log_failed(db, pending.request_id, "invalid_threshold", "HI告警阈值必须在0到100之间。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "invalid_threshold",
            "error_message": "HI告警阈值必须在0到100之间，本次没有修改配置。",
        }

    config = await _get_threshold_config(db, user=user)
    if not config:
        config = NotificationConfig(
            user_id=user.id,
            hi_threshold=70.0,
            email_enabled=True,
            email_address=user.email,
            wechat_enabled=False,
        )
        db.add(config)
        await db.flush()

    after_preview = {**_threshold_config_state(config, user=user), **patch}
    if after_preview.get("email_enabled") and not after_preview.get("email_address"):
        await _mark_log_failed(db, pending.request_id, "email_address_required", "开启邮件通知缺少邮箱地址。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "email_address_required",
            "error_message": "开启邮件通知需要邮箱地址，本次没有修改配置。",
        }

    for key in ("hi_threshold", "email_enabled", "email_address", "wechat_enabled"):
        if key in patch:
            setattr(config, key, patch[key])

    await db.flush()
    await db.refresh(config)
    after = _threshold_config_state(config, user=user)
    verified = True
    for key, expected in patch.items():
        actual = after.get(key)
        if key == "hi_threshold":
            verified = verified and abs(float(actual) - float(expected)) < 0.0001
        else:
            verified = verified and actual == expected
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "阈值配置更新后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "阈值配置更新后回读校验失败，数据库未提交本次变更。",
        }

    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/settings", "open_entity": {"type": "threshold_config", "id": config.id}},
    }


async def _confirm_test_ai_provider_connection(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    provider_id = int(pending.params.get("provider_id") or 0)
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        await _mark_log_failed(db, pending.request_id, "ai_provider_not_found", "执行前供应商配置不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "ai_provider_not_found",
            "error_message": "执行前供应商配置不存在，本次没有发起连接测试。",
        }

    template = _provider_template(config.provider)
    model = str(pending.params.get("model") or config.default_model or template.get("default_model") or "qwen-plus")
    if not config.api_key and config.provider != "ollama":
        config.last_test_status = "error"
        config.last_test_message = "未配置API Key"
        config.last_test_at = _utc_now()
        await db.flush()
        await db.refresh(config)
        after = {**_ai_provider_state(config), "test_model": model}
        await _mark_log_success(db, pending.request_id, after)
        _PENDING_ACTIONS.pop(pending.request_id, None)
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "success",
            "result": after,
            "display": {"navigate_to": "/settings", "open_entity": {"type": "ai_provider", "id": config.id}},
        }

    try:
        client = get_client(config.api_key, config.base_url)
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
            temperature=0,
        )
        sample = response.choices[0].message.content if response.choices else ""
        config.last_test_status = "success"
        config.last_test_message = "连接正常"
        config.last_test_at = _utc_now()
        await db.flush()
        await db.refresh(config)
        after = {**_ai_provider_state(config), "test_model": model, "sample": sample}
        await _mark_log_success(db, pending.request_id, after)
        _PENDING_ACTIONS.pop(pending.request_id, None)
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "success",
            "result": after,
            "display": {"navigate_to": "/settings", "open_entity": {"type": "ai_provider", "id": config.id}},
        }
    except Exception as exc:
        config.last_test_status = "error"
        config.last_test_message = _format_ai_provider_test_error(config, exc)
        config.last_test_at = _utc_now()
        await db.flush()
        await db.refresh(config)
        after = {**_ai_provider_state(config), "test_model": model}
        await _mark_log_success(db, pending.request_id, after)
        _PENDING_ACTIONS.pop(pending.request_id, None)
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "success",
            "result": after,
            "display": {"navigate_to": "/settings", "open_entity": {"type": "ai_provider", "id": config.id}},
        }


async def _confirm_upsert_ai_provider_config(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    provider = str(pending.params.get("provider") or "").strip().lower()
    provider = AI_PROVIDER_CANONICAL.get(provider, provider)
    if not provider:
        await _mark_log_failed(db, pending.request_id, "missing_required_param", "缺少供应商。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "missing_required_param",
            "error_message": "缺少供应商，本次没有保存AI配置。",
        }
    base_url = str(pending.params.get("base_url") or "").strip()
    if not base_url:
        await _mark_log_failed(db, pending.request_id, "missing_required_param", "缺少API地址。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "missing_required_param",
            "error_message": "缺少API地址，本次没有保存AI配置。",
        }
    api_key = pending.params.get("api_key")
    if api_key == "__redacted__" and pending.params.get("api_key_update") == "provided":
        await _mark_log_failed(db, pending.request_id, "sensitive_param_not_restorable", "确认动作恢复后无法读取API KEY。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "sensitive_param_not_restorable",
            "error_message": "后端重载后无法从审计日志恢复API KEY明文。请重新发起保存供应商配置，本次没有修改数据。",
        }

    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.user_id == user.id,
            AIProviderConfig.provider == provider,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        config = AIProviderConfig(user_id=user.id, provider=provider)
        db.add(config)

    template = _provider_template(provider)
    config.display_name = str(pending.params.get("display_name") or template.get("display_name") or provider)
    if isinstance(api_key, str) and api_key.strip() and api_key != "__redacted__":
        config.api_key = api_key.strip()
        config.last_test_status = "untested"
        config.last_test_message = None
        config.last_test_at = None
    config.base_url = base_url
    config.api_style = str(pending.params.get("api_style") or "openai")
    default_model = pending.params.get("default_model")
    config.default_model = str(default_model).strip() if default_model else None
    raw_options = pending.params.get("model_options") or template.get("model_options") or []
    clean_options: list[str] = []
    for option in raw_options:
        value = str(option).strip()
        if value and value not in clean_options:
            clean_options.append(value)
    if config.default_model and config.default_model not in clean_options:
        clean_options.insert(0, config.default_model)
    config.model_options = clean_options
    config.enabled = bool(pending.params.get("enabled", True))
    config.updated_at = _utc_now()
    await db.flush()
    await db.refresh(config)

    after = _ai_provider_state(config)
    verified = (
        after["provider"] == provider
        and after["base_url"] == base_url
        and after["api_style"] == config.api_style
        and after["enabled"] == bool(pending.params.get("enabled", True))
    )
    if config.default_model:
        verified = verified and after["default_model"] == config.default_model
    if not verified:
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "AI供应商配置保存后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "AI供应商配置保存后回读校验失败，数据库未提交本次变更。",
        }
    after["api_key_update"] = "provided" if isinstance(api_key, str) and api_key.strip() and api_key != "__redacted__" else "unchanged"
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/settings", "open_entity": {"type": "ai_provider", "id": config.id}},
    }


async def _confirm_delete_ai_provider_config(db: AsyncSession, *, user: User, pending: PendingAction) -> dict[str, Any]:
    provider_id = int(pending.params["provider_id"])
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    config = result.scalar_one_or_none()
    if not config:
        await _mark_log_failed(db, pending.request_id, "ai_provider_not_found", "执行前供应商配置不存在。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "ai_provider_not_found",
            "error_message": "执行前供应商配置不存在，请重新发起 Agent 指令。",
        }
    after = {**_ai_provider_state(config), "deleted": True, "api_key": None}
    await db.delete(config)
    await db.flush()
    check = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    if check.scalar_one_or_none():
        await db.rollback()
        await _mark_log_failed(db, pending.request_id, "verification_failed", "删除后回读校验失败。")
        return {
            "request_id": pending.request_id,
            "action": pending.action,
            "status": "failed",
            "error_code": "verification_failed",
            "error_message": "删除后回读校验失败，数据库未提交本次变更。",
        }
    await _mark_log_success(db, pending.request_id, after)
    _PENDING_ACTIONS.pop(pending.request_id, None)
    return {
        "request_id": pending.request_id,
        "action": pending.action,
        "status": "success",
        "result": after,
        "display": {"navigate_to": "/settings", "open_entity": {"type": "ai_provider", "id": provider_id}},
    }


async def cancel_agent_action(db: AsyncSession, *, user: User, request_id: str) -> dict[str, Any]:
    pending = await _load_pending_action(db, user=user, request_id=request_id)
    _PENDING_ACTIONS.pop(request_id, None)
    result = await db.execute(select(AgentActionLog).where(AgentActionLog.request_id == request_id, AgentActionLog.user_id == user.id))
    log = result.scalar_one_or_none()
    if log:
        log.status = "cancelled"
        log.executed_at = _utc_now()
        await db.commit()
    return {
        "request_id": request_id,
        "action": pending.action if pending else (log.action if log else "unknown"),
        "status": "cancelled",
        "result": None,
    }


async def _mark_log_success(db: AsyncSession, request_id: str, after: dict[str, Any]) -> None:
    result = await db.execute(select(AgentActionLog).where(AgentActionLog.request_id == request_id))
    log = result.scalar_one_or_none()
    if log:
        log.after_state = after
        log.status = "success"
        log.confirmed_at = _utc_now()
        log.executed_at = _utc_now()
    await db.commit()


async def _mark_log_failed(db: AsyncSession, request_id: str, error_code: str, error_message: str) -> None:
    result = await db.execute(select(AgentActionLog).where(AgentActionLog.request_id == request_id))
    log = result.scalar_one_or_none()
    if log:
        log.status = "failed"
        log.error_code = error_code
        log.error_message = error_message
        log.executed_at = _utc_now()
        await db.commit()
