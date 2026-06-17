"""Regression tests for the unified Agent task planner.

These tests lock down the new Agent contract:
- every input receives a structured planner response,
- missing slots create resumable clarification plans,
- LLM planning is advisory and safely falls back to deterministic planning.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIProviderConfig,
    AgentActionLog,
    AgentTaskPlanState,
    Fault,
    FaultKnowledgeNode,
    MaintenancePersonnel,
    RULPrediction,
    Turbine,
    User,
    WorkOrder,
)
import app.services.agent_actions.workorder as action_gateway
from app.services.agent_playbooks import load_agent_knowledge_base, retrieve_playbook_matches, validate_agent_knowledge_base
from app.services.agent_llm_planner import LLMPlannerResult
from app.services.agent_task_planner import cancel_agent_task_plan, plan_agent_task


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _seed_agent_turbine(db: AsyncSession, *, status: str = "fault") -> Turbine:
    turbine = Turbine(
        name="YD-B-007",
        model="GW150-3MW",
        power_mw=3.0,
        region="风场B",
        status=status,
        hi_value=59.6 if status == "fault" else 82.0,
    )
    db.add(turbine)
    await db.flush()
    db.add(
        Fault(
            turbine_id=turbine.id,
            detected_at=_now(),
            fault_type="齿轮箱点蚀",
            confidence=0.91,
            status="open",
            details={"source": "test"},
        )
    )
    await db.commit()
    await db.refresh(turbine)
    return turbine


async def _seed_agent_matrix_context(db: AsyncSession) -> None:
    turbine = await _seed_agent_turbine(db)
    technician = User(
        username="张三",
        email="zhangsan@example.com",
        password_hash="x",
        role="technician",
        is_active=True,
    )
    db.add(technician)
    db.add(
        WorkOrder(
            turbine_id=turbine.id,
            title="YD-B-007 齿轮箱点蚀维修工单",
            description="矩阵测试种子工单",
            status="pending",
            priority="urgent",
            fault_type="齿轮箱点蚀",
            cost_estimate=0.0,
            created_at=_now(),
        )
    )
    db.add(
        RULPrediction(
            turbine_id=turbine.id,
            component="gearbox",
            predicted_at=_now(),
            remaining_life_days=20.0,
            confidence_lower=15.0,
            confidence_upper=28.0,
        )
    )
    db.add(
        FaultKnowledgeNode(
            fault_type="齿轮箱点蚀",
            category="gearbox",
            severity="high",
            symptoms=["振动异常"],
            root_causes=["润滑不足"],
            solutions=["检查齿面并评估齿轮更换"],
            spare_parts=["齿轮"],
            verified=True,
        )
    )
    await db.commit()


def _assert_structured_response(data: dict) -> None:
    assert data["status"] in {"answered", "pending_confirmation", "needs_clarification", "unsupported", "error"}
    assert "task_kind" in data
    assert "planner_source" in data
    assert isinstance(data.get("slots"), dict)
    assert isinstance(data.get("steps"), list)
    assert isinstance(data.get("candidates"), list)


@pytest.mark.asyncio
async def test_read_task_returns_structured_internal_response(db_session: AsyncSession, test_user: User):
    await _seed_agent_turbine(db_session)

    data = await plan_agent_task(
        db_session,
        user=test_user,
        message="哪些风机有故障",
        page_context={"page_type": "diagnosis"},
    )

    _assert_structured_response(data)
    assert data["status"] == "answered"
    assert data["task_kind"] == "read_task"
    assert data["planner_source"] == "deterministic"
    assert data["playbook_id"] == "diagnosis.list_faulty_turbines"
    assert data["workflow"] == "diagnosis.list_faulty_turbines"
    assert data["steps"]
    assert "这是非诊断类问题" not in (data.get("answer") or "")


@pytest.mark.asyncio
async def test_agent_write_permission_boundaries(db_session: AsyncSession, test_user: User):
    await _seed_agent_turbine(db_session)
    technician = User(
        username="张三",
        email="zhangsan@example.com",
        password_hash="x",
        role="technician",
        is_active=True,
    )
    viewer = User(
        username="viewer_agent",
        email="viewer_agent@example.com",
        password_hash="x",
        role="viewer",
        is_active=True,
    )
    db_session.add_all([technician, viewer])
    await db_session.commit()
    await db_session.refresh(technician)
    await db_session.refresh(viewer)

    viewer_read = await plan_agent_task(
        db_session,
        user=viewer,
        message="哪些风机有故障",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured_response(viewer_read)
    assert viewer_read["status"] == "answered"

    viewer_write = await plan_agent_task(
        db_session,
        user=viewer,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "workorder"},
    )
    _assert_structured_response(viewer_write)
    assert viewer_write["status"] == "error"
    assert viewer_write["error_code"] == "permission_denied"
    assert not viewer_write.get("request_id")

    technician_write = await plan_agent_task(
        db_session,
        user=technician,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "workorder"},
    )
    _assert_structured_response(technician_write)
    assert technician_write["status"] == "pending_confirmation"

    technician_admin_action = await plan_agent_task(
        db_session,
        user=technician,
        message="删除维护人员张三，原因是权限验证",
        page_context={"page_type": "settings"},
    )
    _assert_structured_response(technician_admin_action)
    assert technician_admin_action["status"] == "error"
    assert technician_admin_action["error_code"] == "permission_denied"


def test_agent_knowledge_base_examples_route_to_own_playbook():
    assert validate_agent_knowledge_base() == []
    kb = load_agent_knowledge_base()
    audited = 0
    for group, key in (("read_tasks", "tasks"), ("advanced_workflows", "workflows")):
        for item in kb[group].get(key, []):
            playbook_id = item.get("id")
            for example in item.get("intent_examples", []):
                audited += 1
                matches = retrieve_playbook_matches(example, top_k=5)
                actual = matches[0].get("id") if matches else None
                assert actual == playbook_id, {"example": example, "expected": playbook_id, "actual": actual}
    assert audited >= 90


@pytest.mark.asyncio
async def test_natural_language_matrix_routes_to_expected_playbooks(db_session: AsyncSession, test_user: User):
    await _seed_agent_matrix_context(db_session)
    cases = [
        ("当前风场运行状态如何", "monitoring.view_fleet_status"),
        ("打开风场监控", "monitoring.view_fleet_status"),
        ("查看YD-B-007详情", "monitoring.view_turbine_detail"),
        ("YD-B-007有故障吗", "diagnosis.inspect_turbine_faults"),
        ("哪些风机有故障", "diagnosis.list_faulty_turbines"),
        ("查看YD-B-007的振动波形", "diagnosis.view_vibration"),
        ("看YD-B-007齿轮箱频谱", "diagnosis.view_vibration"),
        ("哪些风机要优先维修", "prediction.view_rul_and_plan"),
        ("查看待处理工单", "workorder.query_workorders"),
        ("查齿轮箱点蚀怎么处理", "knowledge.search_fault_knowledge"),
        ("新增主轴裂纹处理方案", "knowledge.upsert_node"),
        ("把齿轮箱点蚀知识标记为已验证", "knowledge.review_node"),
        ("删除齿轮箱点蚀知识节点，原因是重复", "knowledge.delete_node"),
        ("查看AI供应商配置", "settings.view_system_configuration"),
        ("生成下周维护排程", "prediction.generate_schedule"),
        ("帮YD-B-007创建维修工单", "workorder.create"),
        ("把WO-0001分配给张三师傅", "workorder.assign"),
        ("把WO-0001优先级改成紧急", "workorder.update_fields"),
        ("取消WO-0001，原因是误创建", "workorder.cancel_or_delete"),
        ("新增维护人员李四，邮箱 lisi@example.com，负责齿轮箱，区域B组", "personnel.upsert"),
        ("删除维护人员李四，原因是验证回收", "personnel.delete"),
    ]

    for message, expected_playbook in cases:
        data = await plan_agent_task(
            db_session,
            user=test_user,
            message=message,
            page_context={"page_type": "dashboard"},
        )
        _assert_structured_response(data)
        actual = data.get("playbook_id") or data.get("workflow")
        assert actual == expected_playbook, {"message": message, "actual": actual, "data": data}

    unknown = await plan_agent_task(
        db_session,
        user=test_user,
        message="今天风场适合喝咖啡吗",
        page_context={"page_type": "dashboard"},
    )
    assert unknown["task_kind"] == "unmatched"


@pytest.mark.asyncio
async def test_workorder_update_and_cancel_gateways(db_session: AsyncSession, test_user: User):
    await _seed_agent_matrix_context(db_session)

    update_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="把WO-0001优先级改成紧急",
        page_context={"page_type": "workorder"},
    )
    _assert_structured_response(update_plan)
    assert update_plan["status"] == "pending_confirmation"
    assert update_plan["playbook_id"] == "workorder.update_fields"
    assert update_plan["action"] == "update_workorder_record"

    update_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=update_plan["request_id"])
    assert update_result["status"] == "success"
    workorder = await db_session.get(WorkOrder, 1)
    assert workorder.priority == "urgent"

    cancel_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="取消WO-0001，原因是误创建",
        page_context={"page_type": "workorder"},
    )
    _assert_structured_response(cancel_plan)
    assert cancel_plan["status"] == "pending_confirmation"
    assert cancel_plan["playbook_id"] == "workorder.cancel_or_delete"
    assert cancel_plan["action"] == "cancel_workorder_record"

    cancel_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=cancel_plan["request_id"])
    assert cancel_result["status"] == "success"
    await db_session.refresh(workorder)
    assert workorder.status == "cancelled"
    assert workorder.cancelled_at is not None


@pytest.mark.asyncio
async def test_personnel_gateway_upsert_and_delete(db_session: AsyncSession, test_user: User):
    create_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="新增维护人员李四，邮箱 lisi@example.com，负责齿轮箱，区域B组",
        page_context={"page_type": "settings"},
    )

    _assert_structured_response(create_plan)
    assert create_plan["status"] == "pending_confirmation"
    assert create_plan["playbook_id"] == "personnel.upsert"
    assert create_plan["action"] == "upsert_personnel"

    create_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=create_plan["request_id"])
    assert create_result["status"] == "success"
    created = (
        await db_session.execute(select(User).where(User.username == "李四", User.role == "technician"))
    ).scalar_one()
    profile = (
        await db_session.execute(select(MaintenancePersonnel).where(MaintenancePersonnel.user_id == created.id))
    ).scalar_one()
    assert created.email == "lisi@example.com"
    assert "齿轮箱检修" in profile.skills
    assert profile.region == "B组"

    delete_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="删除维护人员李四，原因是验证回收",
        page_context={"page_type": "settings"},
    )

    _assert_structured_response(delete_plan)
    assert delete_plan["status"] == "pending_confirmation"
    assert delete_plan["playbook_id"] == "personnel.delete"
    assert delete_plan["action"] == "delete_personnel"

    delete_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=delete_plan["request_id"])
    assert delete_result["status"] == "success"
    await db_session.refresh(created)
    await db_session.refresh(profile)
    assert created.is_active is False
    assert profile.is_available is False


@pytest.mark.asyncio
async def test_knowledge_gateway_upsert_review_and_delete(db_session: AsyncSession, test_user: User):
    create_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="新增主轴裂纹处理方案",
        page_context={"page_type": "knowledge"},
    )

    _assert_structured_response(create_plan)
    assert create_plan["status"] == "pending_confirmation"
    assert create_plan["playbook_id"] == "knowledge.upsert_node"
    assert create_plan["action"] == "upsert_knowledge_node"

    create_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=create_plan["request_id"])
    assert create_result["status"] == "success"
    node = (
        await db_session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "主轴裂纹"))
    ).scalar_one()
    assert node.verified is False
    assert node.source == "agent_task"

    review_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="把主轴裂纹知识标记为已验证",
        page_context={"page_type": "knowledge"},
    )

    _assert_structured_response(review_plan)
    assert review_plan["status"] == "pending_confirmation"
    assert review_plan["playbook_id"] == "knowledge.review_node"
    assert review_plan["action"] == "review_knowledge_node"

    review_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=review_plan["request_id"])
    assert review_result["status"] == "success"
    await db_session.refresh(node)
    assert node.verified is True
    assert node.confidence == 1.0

    delete_plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="删除主轴裂纹知识节点，原因是验证回收",
        page_context={"page_type": "knowledge"},
    )

    _assert_structured_response(delete_plan)
    assert delete_plan["status"] == "pending_confirmation"
    assert delete_plan["playbook_id"] == "knowledge.delete_node"
    assert delete_plan["action"] == "delete_knowledge_node"

    delete_result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=delete_plan["request_id"])
    assert delete_result["status"] == "success"
    missing = (
        await db_session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "主轴裂纹"))
    ).scalar_one_or_none()
    assert missing is None


@pytest.mark.asyncio
async def test_pending_action_can_be_restored_from_audit_log(db_session: AsyncSession, test_user: User):
    plan = await plan_agent_task(
        db_session,
        user=test_user,
        message="新增机舱过热处理方案",
        page_context={"page_type": "knowledge"},
    )

    _assert_structured_response(plan)
    assert plan["status"] == "pending_confirmation"
    request_id = plan["request_id"]
    action_gateway._PENDING_ACTIONS.pop(request_id, None)

    result = await action_gateway.confirm_agent_action(db_session, user=test_user, request_id=request_id)
    assert result["status"] == "success"
    restored = (
        await db_session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "机舱过热"))
    ).scalar_one()
    assert restored.source == "agent_task"


@pytest.mark.asyncio
async def test_missing_slot_plan_can_resume_to_pending_confirmation(db_session: AsyncSession, test_user: User):
    await _seed_agent_turbine(db_session)

    first = await plan_agent_task(
        db_session,
        user=test_user,
        message="发起一份维修工单",
        page_context={"page_type": "workorder"},
    )

    _assert_structured_response(first)
    assert first["status"] == "needs_clarification"
    assert first["task_kind"] == "advanced_workflow"
    assert first["playbook_id"] == "workorder.create"
    assert first["plan_id"]

    stored = (
        await db_session.execute(
            select(AgentTaskPlanState).where(AgentTaskPlanState.plan_id == first["plan_id"])
        )
    ).scalar_one()
    assert stored.status == "pending"
    assert stored.playbook_id == "workorder.create"

    second = await plan_agent_task(
        db_session,
        user=test_user,
        message="YD-B-007",
        page_context={"page_type": "workorder"},
        plan_id=first["plan_id"],
    )

    _assert_structured_response(second)
    assert second["status"] == "pending_confirmation"
    assert second["task_kind"] == "advanced_workflow"
    assert second["planner_source"] == "pending_plan"
    assert second["playbook_id"] == "workorder.create"
    assert second["action"] == "create_workorder_record"
    assert second["confirmation"]
    assert second["slots"]["turbine_ref"]["value"] == "YD-B-007"

    workorders = (await db_session.execute(select(WorkOrder))).scalars().all()
    assert workorders == []

    log = (
        await db_session.execute(select(AgentActionLog).where(AgentActionLog.request_id == second["request_id"]))
    ).scalar_one()
    assert log.status == "pending"


@pytest.mark.asyncio
async def test_unknown_input_still_has_internal_response(db_session: AsyncSession, test_user: User):
    data = await plan_agent_task(
        db_session,
        user=test_user,
        message="今天风场适合喝咖啡吗",
        page_context={"page_type": "dashboard"},
    )

    _assert_structured_response(data)
    assert data["status"] == "unsupported"
    assert data["task_kind"] == "unmatched"
    assert data["planner_source"] == "deterministic"
    assert data["error_code"] == "playbook_not_found"
    assert [step["step"] for step in data["steps"]] == ["retrieve_playbook", "refuse_guessing"]


@pytest.mark.asyncio
async def test_llm_planner_can_select_valid_playbook(monkeypatch, db_session: AsyncSession, test_user: User):
    await _seed_agent_turbine(db_session)

    async def fake_plan_with_llm(**kwargs):
        return LLMPlannerResult(
            playbook_id="workorder.create",
            confidence=0.92,
            slots={"turbine_ref": "YD-B-007"},
            missing_slots=[],
            reasoning="test override",
            raw="{}",
        )

    monkeypatch.setattr("app.services.agent_task_planner.plan_with_llm", fake_plan_with_llm)

    data = await plan_agent_task(
        db_session,
        user=test_user,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "diagnosis"},
        provider_config_id=None,
        model="test-model",
    )

    _assert_structured_response(data)
    assert data["planner_source"] == "llm"
    assert data["playbook_id"] == "workorder.create"
    assert data["status"] in {"pending_confirmation", "needs_clarification"}
    assert data["slots"]["turbine_ref"]["value"] == "YD-B-007"


@pytest.mark.asyncio
async def test_invalid_llm_playbook_falls_back_to_deterministic(monkeypatch, db_session: AsyncSession, test_user: User):
    await _seed_agent_turbine(db_session)

    async def fake_plan_with_llm(**kwargs):
        return LLMPlannerResult(
            playbook_id=None,
            confidence=0.0,
            slots={},
            missing_slots=[],
            reasoning="unknown id",
            raw="{}",
            error="unknown_playbook_id:bad.workflow",
        )

    monkeypatch.setattr("app.services.agent_task_planner.plan_with_llm", fake_plan_with_llm)

    data = await plan_agent_task(
        db_session,
        user=test_user,
        message="查看YD-B-007详情",
        page_context={"page_type": "dashboard"},
        provider_config_id=None,
        model="test-model",
    )

    _assert_structured_response(data)
    assert data["status"] == "answered"
    assert data["planner_source"] == "deterministic_after_llm_error"
    assert data["playbook_id"] == "monitoring.view_turbine_detail"
    assert data["slots"]["turbine_ref"]["value"] == "YD-B-007"


@pytest.mark.asyncio
async def test_agent_task_api_accepts_model_config_and_does_not_call_legacy_agent(
    monkeypatch,
    client: AsyncClient,
    auth_headers: dict,
    db_session: AsyncSession,
    test_user: User,
):
    await _seed_agent_turbine(db_session)
    provider = AIProviderConfig(
        user_id=test_user.id,
        provider="deepseek",
        display_name="DeepSeek",
        api_key="sk-test",
        base_url="https://example.invalid/v1",
        default_model="deepseek-chat",
        model_options=["deepseek-chat"],
        enabled=True,
    )
    db_session.add(provider)
    await db_session.commit()
    await db_session.refresh(provider)

    async def fake_plan_with_llm(**kwargs):
        return LLMPlannerResult(
            playbook_id="diagnosis.list_faulty_turbines",
            confidence=0.88,
            slots={},
            missing_slots=[],
            reasoning="test override",
            raw="{}",
        )

    monkeypatch.setattr("app.services.agent_task_planner.plan_with_llm", fake_plan_with_llm)

    response = await client.post(
        "/api/agent-tasks/plan",
        headers=auth_headers,
        json={
            "message": "哪些风机有故障",
            "page_context": {"page_type": "diagnosis"},
            "provider_config_id": provider.id,
            "model": "deepseek-chat",
        },
    )

    assert response.status_code == 200
    data = response.json()
    _assert_structured_response(data)
    assert data["status"] == "answered"
    assert data["planner_source"] == "llm"
    assert data["playbook_id"] == "diagnosis.list_faulty_turbines"
    assert "这是非诊断类问题" not in (data.get("answer") or "")


@pytest.mark.asyncio
async def test_cancel_pending_plan_marks_state_cancelled(db_session: AsyncSession, test_user: User):
    first = await plan_agent_task(
        db_session,
        user=test_user,
        message="发起一份维修工单",
        page_context={"page_type": "workorder"},
    )
    assert first["status"] == "needs_clarification"

    cancelled = await cancel_agent_task_plan(db_session, user=test_user, plan_id=first["plan_id"])
    assert cancelled["status"] == "cancelled"
    row = (
        await db_session.execute(
            select(AgentTaskPlanState).where(AgentTaskPlanState.plan_id == first["plan_id"])
        )
    ).scalar_one()
    assert row.status == "cancelled"
