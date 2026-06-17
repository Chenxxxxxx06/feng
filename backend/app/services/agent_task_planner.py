"""Unified Agent task planner.

This module is the routing boundary for Agent mode. It uses the local
Playbook knowledge base to identify the business task first, then delegates
execution to deterministic read tools or controlled action executors.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AIProviderConfig, AgentTaskPlanState, User
from app.services.agent_actions.workorder import plan_agent_action
from app.services.agent_llm_planner import LLMPlannerResult, plan_with_llm
from app.services.agent_playbooks import load_agent_knowledge_base, retrieve_playbook_matches, validate_agent_knowledge_base
from app.services.agent_read_tasks import answer_read_task
from app.services.agent_slot_extractor import extract_agent_slots

logger = logging.getLogger(__name__)

PENDING_PLAN_TTL = timedelta(minutes=10)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _is_expired(expires_at: datetime | None) -> bool:
    if not expires_at:
        return True
    now = _utc_now()
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


def _playbook_sets() -> tuple[set[str], set[str], dict[str, dict[str, Any]]]:
    kb = load_agent_knowledge_base()
    read_tasks = {
        item.get("id"): item
        for item in kb["read_tasks"].get("tasks", [])
        if item.get("id")
    }
    workflows = {
        item.get("id"): item
        for item in kb["advanced_workflows"].get("workflows", [])
        if item.get("id")
    }
    primitive_actions = {
        item.get("id"): item
        for item in kb["primitive_actions"].get("actions", [])
        if item.get("id")
    }
    return set(read_tasks), set(workflows), primitive_actions


def _playbook_by_id(playbook_id: str) -> dict[str, Any] | None:
    kb = load_agent_knowledge_base()
    for group in ("advanced_workflows", "read_tasks"):
        for item in kb[group].get("workflows" if group == "advanced_workflows" else "tasks", []):
            if item.get("id") == playbook_id:
                return dict(item)
    return None


async def _store_pending_plan(
    db: AsyncSession,
    *,
    user: User,
    raw_message: str,
    playbook_id: str,
    page_context: dict[str, Any],
    plan_id: str | None = None,
) -> str:
    now = _utc_now()
    row = None
    if plan_id:
        result = await db.execute(
            select(AgentTaskPlanState).where(
                AgentTaskPlanState.plan_id == plan_id,
                AgentTaskPlanState.user_id == user.id,
            )
        )
        row = result.scalar_one_or_none()
    if row:
        row.raw_message = raw_message
        row.playbook_id = playbook_id
        row.page_context = dict(page_context)
        row.status = "pending"
        row.updated_at = now
        row.expires_at = now + PENDING_PLAN_TTL
        row.completed_at = None
        row.error_code = None
        row.error_message = None
        await db.commit()
        return row.plan_id

    next_plan_id = f"plan_{uuid.uuid4().hex[:16]}"
    db.add(
        AgentTaskPlanState(
            plan_id=next_plan_id,
            user_id=user.id,
            raw_message=raw_message,
            playbook_id=playbook_id,
            page_context=dict(page_context),
            status="pending",
            created_at=now,
            updated_at=now,
            expires_at=now + PENDING_PLAN_TTL,
        )
    )
    await db.commit()
    return next_plan_id


async def _get_pending_plan(db: AsyncSession, *, user: User, plan_id: str | None) -> AgentTaskPlanState | None:
    if not plan_id:
        return None
    result = await db.execute(
        select(AgentTaskPlanState).where(
            AgentTaskPlanState.plan_id == plan_id,
            AgentTaskPlanState.user_id == user.id,
            AgentTaskPlanState.status == "pending",
        )
    )
    pending = result.scalar_one_or_none()
    if not pending:
        return None
    if _is_expired(pending.expires_at):
        pending.status = "expired"
        pending.error_code = "pending_plan_expired"
        pending.error_message = "追问计划已过期。"
        pending.completed_at = _utc_now()
        await db.commit()
        return None
    return pending


async def _finish_pending_plan(
    db: AsyncSession,
    pending: AgentTaskPlanState | None,
    *,
    status: str = "completed",
    error_code: str | None = None,
    error_message: str | None = None,
) -> None:
    if not pending:
        return
    pending.status = status
    pending.completed_at = _utc_now()
    pending.updated_at = _utc_now()
    pending.error_code = error_code
    pending.error_message = error_message
    await db.commit()


async def cancel_agent_task_plan(db: AsyncSession, *, user: User, plan_id: str) -> dict[str, Any]:
    result = await db.execute(
        select(AgentTaskPlanState).where(
            AgentTaskPlanState.plan_id == plan_id,
            AgentTaskPlanState.user_id == user.id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return {
            "plan_id": plan_id,
            "status": "failed",
            "error_code": "pending_plan_not_found",
            "error_message": "未找到待取消的 Agent 追问计划。",
        }
    if row.status != "pending":
        return {
            "plan_id": plan_id,
            "status": row.status,
            "error_code": None,
            "error_message": None,
        }
    row.status = "cancelled"
    row.completed_at = _utc_now()
    row.updated_at = _utc_now()
    await db.commit()
    return {"plan_id": plan_id, "status": "cancelled"}


def _merge_pending_message(pending: AgentTaskPlanState, message: str) -> str:
    return f"{pending.raw_message}\n补充信息：{message}"


def _task_kind(playbook: dict[str, Any], read_ids: set[str], workflow_ids: set[str]) -> str:
    playbook_id = str(playbook.get("id") or "")
    if playbook_id in workflow_ids:
        return "advanced_workflow"
    if playbook_id in read_ids:
        return "read_task"
    return "unknown"


def _candidate(playbook: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "id": str(playbook.get("id") or ""),
        "name": str(playbook.get("name") or ""),
        "category": str(playbook.get("category") or ""),
        "implementation_status": playbook.get("implementation_status"),
        "task_kind": kind,
        "score": playbook.get("_score"),
    }


def _candidate_from_llm(playbook: dict[str, Any], kind: str, llm_result: LLMPlannerResult) -> dict[str, Any]:
    item = dict(playbook)
    item["_score"] = int(round(llm_result.confidence * 100))
    return _candidate(item, kind)


def _steps(playbook: dict[str, Any], primitive_actions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, item in enumerate(playbook.get("standard_workflow", []) or [], start=1):
        step = str(item.get("step") or "")
        primitive = primitive_actions.get(step, {})
        output.append(
            {
                "order": index,
                "step": step,
                "type": str(item.get("type") or primitive.get("type") or "read"),
                "status": "planned",
                "description": str(primitive.get("description") or ""),
            }
        )
    return output


def _planner_step(order: int, step: str, *, status: str, description: str, step_type: str = "system") -> dict[str, Any]:
    return {
        "order": order,
        "step": step,
        "type": step_type,
        "status": status,
        "description": description,
    }


def _display(playbook: dict[str, Any]) -> dict[str, Any] | None:
    presentation = playbook.get("result_presentation") or {}
    if isinstance(presentation, dict) and presentation.get("navigate_to"):
        return {"navigate_to": presentation.get("navigate_to"), "open_entity": presentation.get("open_entity")}

    targets = playbook.get("page_targets") or []
    for target in targets:
        if isinstance(target, str) and "{" not in target:
            return {"navigate_to": target}
    return None


def _mutation_hint(message: str) -> bool:
    return any(
        token in message
        for token in (
            "创建", "新建", "发起", "生成", "建立", "建一个", "建个", "开工单",
            "新增", "登记", "录入", "沉淀",
            "分配", "派给", "派工", "指派", "交给", "安排给",
            "关闭", "标记", "完成", "取消", "删除", "移除", "审核", "验证", "拒绝",
            "刷新", "重新计算", "重新预测", "更新",
            "追加", "记录", "修改", "设置", "改成", "改为", "调整",
            "开启", "启用", "打开", "停用", "禁用",
            "检测", "诊断", "批量",
        )
    )


def _select_playbook(matches: list[dict[str, Any]], read_ids: set[str], workflow_ids: set[str], message: str) -> dict[str, Any] | None:
    if not matches:
        return None
    if _mutation_hint(message):
        implemented = [
            item for item in matches
            if _task_kind(item, read_ids, workflow_ids) == "advanced_workflow"
            and item.get("implementation_status") == "implemented_gateway"
        ]
        if implemented:
            return implemented[0]
        workflows = [item for item in matches if _task_kind(item, read_ids, workflow_ids) == "advanced_workflow"]
        if workflows:
            return workflows[0]
    read_tasks = [item for item in matches if _task_kind(item, read_ids, workflow_ids) == "read_task"]
    if read_tasks:
        return read_tasks[0]
    return matches[0]


async def _get_provider_config(
    db: AsyncSession,
    *,
    user: User,
    provider_config_id: int | None,
) -> AIProviderConfig | None:
    if not provider_config_id:
        return None
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.id == provider_config_id,
            AIProviderConfig.user_id == user.id,
        )
    )
    return result.scalar_one_or_none()


async def _select_with_optional_llm(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    page_context: dict[str, Any],
    provider_config_id: int | None,
    model: str | None,
    read_ids: set[str],
    workflow_ids: set[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str, LLMPlannerResult | None]:
    deterministic_matches = retrieve_playbook_matches(message, top_k=5)
    deterministic = _select_playbook(deterministic_matches, read_ids, workflow_ids, message)
    provider = await _get_provider_config(db, user=user, provider_config_id=provider_config_id)
    llm_result = await plan_with_llm(
        message=message,
        page_context=page_context,
        provider_config=provider,
        model=model,
    )
    if llm_result and llm_result.playbook_id and llm_result.confidence >= 0.45:
        llm_playbook = _playbook_by_id(llm_result.playbook_id)
        if llm_playbook:
            ids = {str(llm_playbook.get("id") or "")}
            merged = [llm_playbook]
            for item in deterministic_matches:
                item_id = str(item.get("id") or "")
                if item_id and item_id not in ids:
                    merged.append(item)
                    ids.add(item_id)
            return llm_playbook, merged[:5], "llm", llm_result
    if llm_result and llm_result.error:
        logger.info("Agent LLM planner fallback: %s", llm_result.error)
        return deterministic, deterministic_matches, "deterministic_after_llm_error", llm_result
    if llm_result:
        return deterministic, deterministic_matches, "deterministic_after_llm_low_confidence", llm_result
    return deterministic, deterministic_matches, "deterministic", None


def _generic_unmatched_answer(message: str) -> str:
    return (
        "我已收到这条 Agent 指令，但当前知识库没有匹配到可执行或可查询的任务模板。\n"
        "为了避免误操作，系统不会猜测执行。你可以补充目标对象和动作，例如风机编号、工单编号、"
        "故障类型、目标状态或负责人。"
    )


def _generic_read_answer(playbook: dict[str, Any]) -> str:
    page = (_display(playbook) or {}).get("navigate_to")
    lines = [
        f"已识别为查看类任务：{playbook.get('name') or playbook.get('id')}。",
        "该任务已有知识库拆解，但当前尚未接入专用确定性回答器。",
    ]
    if page:
        lines.append(f"可先打开对应页面 `{page}`，再结合页面数据继续查询。")
    return "\n".join(lines)


def _planned_workflow_answer(playbook: dict[str, Any]) -> str:
    status = playbook.get("implementation_status") or "planned"
    return (
        f"已识别为受控业务流程：{playbook.get('name') or playbook.get('id')}。\n"
        f"当前知识库状态为 `{status}`，还没有接入可执行的后端 executor。"
        "因此本次不会执行数据变更。"
    )


async def _wrap_action_plan(
    action_plan: dict[str, Any],
    *,
    db: AsyncSession,
    user: User,
    raw_message: str,
    playbook: dict[str, Any],
    steps: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    slots: dict[str, Any],
    kind: str,
    page_context: dict[str, Any],
    plan_id: str | None = None,
) -> dict[str, Any]:
    status = action_plan.get("status") or "error"
    response = {
        "status": status,
        "task_type": action_plan.get("task_type") or "WORKFLOW",
        "task_kind": kind,
        "playbook_id": playbook.get("id"),
        "workflow": action_plan.get("workflow") or playbook.get("id"),
        "action": action_plan.get("action"),
        "request_id": action_plan.get("request_id"),
        "confidence": float(action_plan.get("confidence") or 0.0),
        "slots": slots,
        "steps": steps,
        "candidates": candidates,
        "confirmation": action_plan.get("confirmation"),
        "missing_slots": action_plan.get("missing_slots") or [],
        "clarification_question": action_plan.get("clarification_question"),
        "error_code": action_plan.get("error_code"),
        "error_message": action_plan.get("error_message"),
    }
    if status == "needs_clarification":
        response["plan_id"] = await _store_pending_plan(
            db,
            user=user,
            raw_message=raw_message,
            playbook_id=str(playbook.get("id") or ""),
            page_context=page_context,
            plan_id=plan_id,
        )
    if status == "unsupported":
        response["answer"] = _planned_workflow_answer(playbook)
    return response


async def plan_agent_task(
    db: AsyncSession,
    *,
    user: User,
    message: str,
    page_context: dict[str, Any] | None = None,
    plan_id: str | None = None,
    provider_config_id: int | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Plan and, for read-only tasks, answer an Agent request.

    The returned shape is intentionally broader than the action gateway:
    read tasks, write tasks, clarifications, and unsupported-but-understood
    tasks all produce a user-visible response.
    """
    validation_errors = validate_agent_knowledge_base()
    if validation_errors:
        return {
            "status": "error",
            "task_type": "SYSTEM",
            "task_kind": "system",
            "planner_source": "system",
            "confidence": 0.0,
            "slots": {},
            "steps": [
                _planner_step(
                    1,
                    "validate_agent_knowledge_base",
                    status="failed",
                    description="Agent任务知识库未通过启动前校验。",
                )
            ],
            "error_code": "agent_knowledge_base_invalid",
            "error_message": "Agent任务知识库校验失败。",
            "answer": "\n".join(validation_errors[:10]),
        }

    page_context = page_context or {}
    pending = await _get_pending_plan(db, user=user, plan_id=plan_id)
    effective_message = _merge_pending_message(pending, message) if pending else message

    read_ids, workflow_ids, primitive_actions = _playbook_sets()
    if plan_id and not pending:
        slots = extract_agent_slots(effective_message, page_context=page_context)
        return {
            "status": "error",
            "task_type": "CLARIFY",
            "task_kind": "clarification",
            "planner_source": "pending_plan",
            "confidence": 0.0,
            "slots": slots,
            "answer": "之前的追问上下文已过期或不存在，请重新发起 Agent 指令。",
            "steps": [
                _planner_step(
                    1,
                    "resume_pending_plan",
                    status="failed",
                    description="前端提交了 plan_id，但后端没有找到可继续的待追问计划。",
                )
            ],
            "candidates": [],
            "error_code": "pending_plan_not_found",
            "error_message": "之前的追问上下文已过期或不存在。",
        }

    if pending:
        playbook = _playbook_by_id(pending.playbook_id)
        matches = [playbook] if playbook else []
        page_context = {**pending.page_context, **page_context}
        planner_source = "pending_plan"
        llm_result = None
    else:
        playbook, matches, planner_source, llm_result = await _select_with_optional_llm(
            db,
            user=user,
            message=effective_message,
            page_context=page_context,
            provider_config_id=provider_config_id,
            model=model,
            read_ids=read_ids,
            workflow_ids=workflow_ids,
        )
    candidates = [_candidate(item, _task_kind(item, read_ids, workflow_ids)) for item in matches if item]
    if llm_result and playbook and not any(item.get("id") == playbook.get("id") for item in candidates):
        candidates.insert(0, _candidate_from_llm(playbook, _task_kind(playbook, read_ids, workflow_ids), llm_result))
    slots = extract_agent_slots(effective_message, page_context=page_context, playbook=playbook)
    if llm_result and llm_result.slots:
        for key, value in llm_result.slots.items():
            slots.setdefault(key, {"value": value, "source": "llm"})
    if not playbook:
        return {
            "status": "unsupported",
            "task_type": "UNKNOWN",
            "task_kind": "unmatched",
            "planner_source": planner_source,
            "confidence": 0.0,
            "slots": slots,
            "answer": _generic_unmatched_answer(message),
            "candidates": [],
            "steps": [
                _planner_step(
                    1,
                    "retrieve_playbook",
                    status="completed",
                    description="已检索本地Agent任务知识库，但没有达到安全匹配阈值的任务模板。",
                    step_type="read",
                ),
                _planner_step(
                    2,
                    "refuse_guessing",
                    status="completed",
                    description="为避免误操作，本次不猜测执行；用户可补充对象、动作或状态。",
                    step_type="verify",
                ),
            ],
            "error_code": "playbook_not_found",
            "error_message": "当前知识库没有匹配到任务模板。",
        }

    kind = _task_kind(playbook, read_ids, workflow_ids)
    steps = _steps(playbook, primitive_actions)

    if kind == "advanced_workflow":
        if playbook.get("implementation_status") != "implemented_gateway":
            return {
                "status": "unsupported",
                "task_type": "WORKFLOW",
                "task_kind": kind,
                "planner_source": planner_source,
                "playbook_id": playbook.get("id"),
                "workflow": playbook.get("id"),
                "confidence": 0.62,
                "slots": slots,
                "answer": _planned_workflow_answer(playbook),
                "steps": steps,
                "candidates": candidates,
                "display": _display(playbook),
                "error_code": "workflow_executor_not_ready",
                "error_message": "该业务流程尚未接入可执行后端。",
            }
        try:
            action_plan = await plan_agent_action(db, user=user, message=effective_message, page_context=page_context)
        except Exception as exc:
            logger.exception("Agent action planning failed")
            return {
                "status": "error",
                "task_type": "WORKFLOW",
                "task_kind": kind,
                "planner_source": planner_source,
                "playbook_id": playbook.get("id"),
                "workflow": playbook.get("id"),
                "confidence": 0.0,
                "answer": "Agent已识别任务，但动作规划器执行异常。本次不会执行任何数据变更。",
                "slots": slots,
                "steps": steps + [
                    _planner_step(
                        len(steps) + 1,
                        "plan_action_gateway",
                        status="failed",
                        description="受控动作规划器异常，已阻断写操作。",
                    )
                ],
                "candidates": candidates,
                "display": _display(playbook),
                "error_code": "action_planner_failed",
                "error_message": str(exc)[:240],
            }
        action_workflow = str(action_plan.get("workflow") or "")
        if action_workflow and action_workflow != str(playbook.get("id") or ""):
            action_playbook = _playbook_by_id(action_workflow)
            if action_playbook:
                playbook = action_playbook
                kind = _task_kind(playbook, read_ids, workflow_ids)
                steps = _steps(playbook, primitive_actions)
                if not any(item.get("id") == playbook.get("id") for item in candidates):
                    candidates.insert(0, _candidate(playbook, kind))
        wrapped = await _wrap_action_plan(
            action_plan,
            db=db,
            user=user,
            raw_message=effective_message,
            playbook=playbook,
            steps=steps,
            candidates=candidates,
            slots=slots,
            kind=kind,
            page_context=page_context,
            plan_id=pending.plan_id if pending else None,
        )
        wrapped["planner_source"] = planner_source
        if wrapped.get("status") != "needs_clarification" and pending:
            await _finish_pending_plan(db, pending)
        return wrapped

    try:
        read_result = await answer_read_task(
            db,
            message=effective_message,
            page_context=page_context,
            playbook_id=str(playbook.get("id") or ""),
            user=user,
        )
    except Exception as exc:
        logger.exception("Agent read task failed")
        return {
            "status": "error",
            "task_type": "READ",
            "task_kind": kind,
            "planner_source": planner_source,
            "playbook_id": playbook.get("id"),
            "workflow": playbook.get("id"),
            "confidence": 0.0,
            "answer": "Agent已识别查看类任务，但只读数据工具执行异常。本次没有进行任何数据变更。",
            "slots": slots,
            "steps": steps + [
                _planner_step(
                    len(steps) + 1,
                    "answer_read_task",
                    status="failed",
                    description="只读任务回答器异常。",
                )
            ],
            "candidates": candidates,
            "display": _display(playbook),
            "error_code": "read_task_failed",
            "error_message": str(exc)[:240],
        }
    if read_result.get("status") in {"success", "needs_clarification", "error"}:
        response = {
            "status": "answered" if read_result.get("status") == "success" else read_result.get("status"),
            "task_type": "READ",
            "task_kind": kind,
            "planner_source": planner_source,
            "playbook_id": read_result.get("workflow") or playbook.get("id"),
            "workflow": read_result.get("workflow") or playbook.get("id"),
            "confidence": float(read_result.get("confidence") or 0.0),
            "answer": read_result.get("answer"),
            "slots": slots,
            "steps": steps,
            "candidates": candidates,
            "display": read_result.get("display") or _display(playbook),
            "missing_slots": read_result.get("missing_slots") or [],
            "clarification_question": read_result.get("clarification_question"),
            "error_code": read_result.get("error_code"),
            "error_message": read_result.get("error_message"),
        }
        if read_result.get("status") == "needs_clarification":
            response["plan_id"] = await _store_pending_plan(
                db,
                user=user,
                raw_message=effective_message,
                playbook_id=str(playbook.get("id") or ""),
                page_context=page_context,
                plan_id=pending.plan_id if pending else None,
            )
        elif pending:
            await _finish_pending_plan(db, pending)
        return response

    return {
        "status": "answered",
        "task_type": "READ",
        "task_kind": kind,
        "planner_source": planner_source,
        "playbook_id": playbook.get("id"),
        "workflow": playbook.get("id"),
        "confidence": 0.58,
        "answer": _generic_read_answer(playbook),
        "slots": slots,
        "steps": steps,
        "candidates": candidates,
        "display": _display(playbook),
    }
