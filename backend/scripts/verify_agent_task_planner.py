"""Run a dependency-light smoke verification for the unified Agent planner.

This script is intentionally independent from pytest so developers can verify
the Agent contract even when the local Python environment only has the runtime
dependencies installed.

Usage:
    python scripts/verify_agent_task_planner.py
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import AgentActionLog, Fault, FaultKnowledgeNode, MaintenancePersonnel, NotificationConfig, RULPrediction, Turbine, User, WorkOrder
from app.models import AIProviderConfig
import app.services.agent_actions.workorder as action_gateway
from app.services.agent_playbooks import load_agent_knowledge_base, retrieve_playbook_matches, validate_agent_knowledge_base
from app.services.agent_llm_planner import LLMPlannerResult
import app.services.agent_task_planner as planner


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_structured(data: dict) -> None:
    assert data["status"] in {"answered", "pending_confirmation", "needs_clarification", "unsupported", "error"}, data
    assert "task_kind" in data, data
    assert "planner_source" in data, data
    assert isinstance(data.get("slots"), dict), data
    assert isinstance(data.get("steps"), list), data
    assert isinstance(data.get("candidates"), list), data


async def _seed(session: AsyncSession) -> User:
    user = User(
        username="agent_smoke",
        email="agent_smoke@example.com",
        password_hash="not-used",
        role="admin",
        is_active=True,
    )
    technician = User(
        username="张三",
        email="zhangsan@example.com",
        password_hash="not-used",
        role="technician",
        is_active=True,
    )
    viewer = User(
        username="viewer_smoke",
        email="viewer_smoke@example.com",
        password_hash="not-used",
        role="viewer",
        is_active=True,
    )
    turbine = Turbine(
        name="YD-B-007",
        model="GW150-3MW",
        power_mw=3.0,
        region="风场B",
        status="fault",
        hi_value=59.6,
    )
    session.add_all([user, technician, viewer, turbine])
    await session.flush()
    session.add(
        Fault(
            turbine_id=turbine.id,
            detected_at=_now(),
            fault_type="齿轮箱点蚀",
            confidence=0.91,
            status="open",
            details={"source": "agent_smoke"},
        )
    )
    session.add(
        WorkOrder(
            turbine_id=turbine.id,
            title="YD-B-007 齿轮箱点蚀维修工单",
            description="验证脚本种子工单",
            status="pending",
            priority="urgent",
            fault_type="齿轮箱点蚀",
            cost_estimate=0.0,
            created_at=_now(),
        )
    )
    session.add(
        RULPrediction(
            turbine_id=turbine.id,
            component="gearbox",
            predicted_at=_now(),
            remaining_life_days=20.0,
            confidence_lower=15.0,
            confidence_upper=28.0,
        )
    )
    session.add(
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
    await session.commit()
    await session.refresh(user)
    return user


async def _run_checks(session: AsyncSession, user: User) -> list[str]:
    results: list[str] = []

    validation_errors = validate_agent_knowledge_base()
    assert validation_errors == [], validation_errors
    results.append("knowledge_base_validation: ok")

    kb = load_agent_knowledge_base()
    audited_examples = 0
    for group, key in (("read_tasks", "tasks"), ("advanced_workflows", "workflows")):
        for item in kb[group].get(key, []):
            playbook_id = item.get("id")
            for example in item.get("intent_examples", []):
                audited_examples += 1
                matches = retrieve_playbook_matches(example, top_k=5)
                actual = matches[0].get("id") if matches else None
                assert actual == playbook_id, {"example": example, "expected": playbook_id, "actual": actual}
    results.append(f"playbook_example_routing: ok ({audited_examples} examples)")

    matrix_cases = [
        ("当前风场运行状态如何", "monitoring.view_fleet_status"),
        ("打开风场监控", "monitoring.view_fleet_status"),
        ("查看YD-B-007详情", "monitoring.view_turbine_detail"),
        ("YD-B-007有故障吗", "diagnosis.inspect_turbine_faults"),
        ("哪些风机有故障", "diagnosis.list_faulty_turbines"),
        ("对YD-B-007运行自动故障检测", "diagnosis.run_auto_detection"),
        ("批量检测故障风机齿轮箱", "diagnosis.run_batch_detection"),
        ("给YD-B-007登记叶片裂纹故障，置信度80%", "diagnosis.create_fault"),
        ("把故障1置信度改成90%", "diagnosis.update_fault"),
        ("删除故障1，原因是误报", "diagnosis.delete_fault"),
        ("查看YD-B-007的振动波形", "diagnosis.view_vibration"),
        ("看YD-B-007齿轮箱频谱", "diagnosis.view_vibration"),
        ("哪些风机要优先维修", "prediction.view_rul_and_plan"),
        ("查看待处理工单", "workorder.query_workorders"),
        ("查齿轮箱点蚀怎么处理", "knowledge.search_fault_knowledge"),
        ("新增主轴裂纹处理方案", "knowledge.upsert_node"),
        ("把齿轮箱点蚀知识标记为已验证", "knowledge.review_node"),
        ("删除齿轮箱点蚀知识节点，原因是重复", "knowledge.delete_node"),
        ("查看AI供应商配置", "settings.view_system_configuration"),
        ("把HI告警阈值改成75", "settings.update_thresholds"),
        ("开启邮件通知并发送到admin@example.com", "settings.update_thresholds"),
        ("新增Ollama配置，地址http://localhost:11434/v1，默认模型qwen2.5", "settings.upsert_ai_provider"),
        ("测试DeepSeek连接", "settings.test_ai_provider"),
        ("刷新YD-B-007健康指数", "turbine.refresh_health"),
        ("生成下周维护排程", "prediction.generate_schedule"),
        ("帮YD-B-007创建维修工单", "workorder.create"),
        ("把WO-0001分配给张三师傅", "workorder.assign"),
        ("把WO-0001优先级改成紧急", "workorder.update_fields"),
        ("取消WO-0001，原因是误创建", "workorder.cancel_or_delete"),
        ("新增维护人员李四，邮箱 lisi@example.com，负责齿轮箱，区域B组", "personnel.upsert"),
        ("删除维护人员李四，原因是验证回收", "personnel.delete"),
    ]
    for message, expected_playbook in matrix_cases:
        data = await planner.plan_agent_task(
            session,
            user=user,
            message=message,
            page_context={"page_type": "dashboard"},
        )
        _assert_structured(data)
        actual = data.get("playbook_id") or data.get("workflow")
        assert actual == expected_playbook, {"message": message, "expected": expected_playbook, "actual": actual, "data": data}
    results.append(f"natural_language_matrix: ok ({len(matrix_cases)} cases)")

    read = await planner.plan_agent_task(
        session,
        user=user,
        message="哪些风机有故障",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(read)
    assert read["status"] == "answered", read
    assert read["task_kind"] == "read_task", read
    assert read["playbook_id"] == "diagnosis.list_faulty_turbines", read
    assert "这是非诊断类问题" not in (read.get("answer") or ""), read
    results.append("read_faulty_turbines: ok")

    viewer = (
        await session.execute(select(User).where(User.username == "viewer_smoke"))
    ).scalar_one()
    viewer_read = await planner.plan_agent_task(
        session,
        user=viewer,
        message="哪些风机有故障",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(viewer_read)
    assert viewer_read["status"] == "answered", viewer_read
    viewer_write = await planner.plan_agent_task(
        session,
        user=viewer,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "workorder"},
    )
    _assert_structured(viewer_write)
    assert viewer_write["status"] == "error", viewer_write
    assert viewer_write["error_code"] == "permission_denied", viewer_write
    assert not viewer_write.get("request_id"), viewer_write
    results.append("viewer_read_allowed_write_denied: ok")

    technician = (
        await session.execute(select(User).where(User.username == "张三"))
    ).scalar_one()
    technician_write = await planner.plan_agent_task(
        session,
        user=technician,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "workorder"},
    )
    _assert_structured(technician_write)
    assert technician_write["status"] == "pending_confirmation", technician_write
    technician_admin_action = await planner.plan_agent_task(
        session,
        user=technician,
        message="删除维护人员张三，原因是权限验证",
        page_context={"page_type": "settings"},
    )
    _assert_structured(technician_admin_action)
    assert technician_admin_action["status"] == "error", technician_admin_action
    assert technician_admin_action["error_code"] == "permission_denied", technician_admin_action
    technician_threshold = await planner.plan_agent_task(
        session,
        user=technician,
        message="把HI告警阈值改成80",
        page_context={"page_type": "settings"},
    )
    _assert_structured(technician_threshold)
    assert technician_threshold["status"] == "error", technician_threshold
    assert technician_threshold["error_code"] == "permission_denied", technician_threshold
    results.append("technician_write_allowed_admin_action_denied: ok")

    first = await planner.plan_agent_task(
        session,
        user=user,
        message="发起一份维修工单",
        page_context={"page_type": "workorder"},
    )
    _assert_structured(first)
    assert first["status"] == "needs_clarification", first
    assert first["plan_id"], first

    second = await planner.plan_agent_task(
        session,
        user=user,
        message="YD-B-007",
        page_context={"page_type": "workorder"},
        plan_id=first["plan_id"],
    )
    _assert_structured(second)
    assert second["status"] == "pending_confirmation", second
    assert second["planner_source"] == "pending_plan", second
    assert second["action"] == "create_workorder_record", second
    assert second["slots"]["turbine_ref"]["value"] == "YD-B-007", second
    workorder_count = len((await session.execute(select(WorkOrder))).scalars().all())
    assert workorder_count == 1, second
    action_log = (
        await session.execute(select(AgentActionLog).where(AgentActionLog.request_id == second["request_id"]))
    ).scalar_one()
    assert action_log.status == "pending"
    results.append("clarification_resume_without_write: ok")

    unknown = await planner.plan_agent_task(
        session,
        user=user,
        message="今天风场适合喝咖啡吗",
        page_context={"page_type": "dashboard"},
    )
    _assert_structured(unknown)
    assert unknown["status"] == "unsupported", unknown
    assert unknown["task_kind"] == "unmatched", unknown
    assert [step["step"] for step in unknown["steps"]] == ["retrieve_playbook", "refuse_guessing"], unknown
    results.append("unknown_input_internal_response: ok")

    original_llm = planner.plan_with_llm

    async def fake_valid_llm(**kwargs):
        return LLMPlannerResult(
            playbook_id="workorder.create",
            confidence=0.92,
            slots={"turbine_ref": "YD-B-007"},
            missing_slots=[],
            reasoning="smoke test",
            raw="{}",
        )

    planner.plan_with_llm = fake_valid_llm
    llm = await planner.plan_agent_task(
        session,
        user=user,
        message="帮YD-B-007创建维修工单",
        page_context={"page_type": "diagnosis"},
        provider_config_id=None,
        model="smoke-model",
    )
    _assert_structured(llm)
    assert llm["planner_source"] == "llm", llm
    assert llm["playbook_id"] == "workorder.create", llm
    results.append("llm_valid_playbook_advisory: ok")

    async def fake_bad_llm(**kwargs):
        return LLMPlannerResult(
            playbook_id=None,
            confidence=0.0,
            slots={},
            missing_slots=[],
            reasoning="bad id",
            raw="{}",
            error="unknown_playbook_id:bad.workflow",
        )

    planner.plan_with_llm = fake_bad_llm
    fallback = await planner.plan_agent_task(
        session,
        user=user,
        message="查看YD-B-007详情",
        page_context={"page_type": "dashboard"},
        provider_config_id=None,
        model="smoke-model",
    )
    _assert_structured(fallback)
    assert fallback["status"] == "answered", fallback
    assert fallback["planner_source"] == "deterministic_after_llm_error", fallback
    assert fallback["playbook_id"] == "monitoring.view_turbine_detail", fallback
    results.append("llm_error_fallback: ok")

    planner.plan_with_llm = original_llm

    detection_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="对YD-B-007运行自动故障检测",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(detection_plan)
    assert detection_plan["status"] == "pending_confirmation", detection_plan
    assert detection_plan["playbook_id"] == "diagnosis.run_auto_detection", detection_plan
    assert detection_plan["action"] == "run_auto_fault_detection", detection_plan
    detection_result = await action_gateway.confirm_agent_action(session, user=user, request_id=detection_plan["request_id"])
    assert detection_result["status"] == "success", detection_result
    assert detection_result["result"]["turbine_name"] == "YD-B-007", detection_result
    assert detection_result["result"]["status"] in {"suspected_fault", "no_fault_detected"}, detection_result
    results.append("auto_fault_detection_gateway: ok")

    batch_detection_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="批量检测故障风机齿轮箱",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(batch_detection_plan)
    assert batch_detection_plan["status"] == "pending_confirmation", batch_detection_plan
    assert batch_detection_plan["playbook_id"] == "diagnosis.run_batch_detection", batch_detection_plan
    assert batch_detection_plan["action"] == "run_batch_fault_detection", batch_detection_plan
    batch_detection_result = await action_gateway.confirm_agent_action(session, user=user, request_id=batch_detection_plan["request_id"])
    assert batch_detection_result["status"] == "success", batch_detection_result
    assert batch_detection_result["result"]["total"] >= 1, batch_detection_result
    assert batch_detection_result["result"]["records"][0]["turbine_name"] == "YD-B-007", batch_detection_result
    results.append("batch_fault_detection_gateway: ok")

    create_fault_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="给YD-B-007登记叶片裂纹故障，置信度80%",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(create_fault_plan)
    assert create_fault_plan["status"] == "pending_confirmation", create_fault_plan
    assert create_fault_plan["playbook_id"] == "diagnosis.create_fault", create_fault_plan
    assert create_fault_plan["action"] == "create_fault_record", create_fault_plan
    assert create_fault_plan["confirmation"]["after"]["confidence"] == 0.8, create_fault_plan
    create_fault_result = await action_gateway.confirm_agent_action(session, user=user, request_id=create_fault_plan["request_id"])
    assert create_fault_result["status"] == "success", create_fault_result
    created_fault_id = create_fault_result["result"]["id"]
    created_fault = await session.get(Fault, created_fault_id)
    assert created_fault is not None
    assert created_fault.fault_type == "叶片裂纹"
    assert abs(float(created_fault.confidence or 0) - 0.8) < 0.0001
    assert created_fault.status == "open"
    results.append("fault_create_gateway: ok")

    update_fault_plan = await planner.plan_agent_task(
        session,
        user=user,
        message=f"把故障{created_fault_id}置信度改成90%",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(update_fault_plan)
    assert update_fault_plan["status"] == "pending_confirmation", update_fault_plan
    assert update_fault_plan["playbook_id"] == "diagnosis.update_fault", update_fault_plan
    assert update_fault_plan["action"] == "update_fault_record", update_fault_plan
    update_fault_result = await action_gateway.confirm_agent_action(session, user=user, request_id=update_fault_plan["request_id"])
    assert update_fault_result["status"] == "success", update_fault_result
    await session.refresh(created_fault)
    assert abs(float(created_fault.confidence or 0) - 0.9) < 0.0001
    results.append("fault_update_gateway: ok")

    delete_fault_plan = await planner.plan_agent_task(
        session,
        user=user,
        message=f"删除故障{created_fault_id}，原因是误报",
        page_context={"page_type": "diagnosis"},
    )
    _assert_structured(delete_fault_plan)
    assert delete_fault_plan["status"] == "pending_confirmation", delete_fault_plan
    assert delete_fault_plan["playbook_id"] == "diagnosis.delete_fault", delete_fault_plan
    assert delete_fault_plan["action"] == "delete_fault_record", delete_fault_plan
    delete_fault_result = await action_gateway.confirm_agent_action(session, user=user, request_id=delete_fault_plan["request_id"])
    assert delete_fault_result["status"] == "success", delete_fault_result
    assert await session.get(Fault, created_fault_id) is None
    results.append("fault_delete_gateway: ok")

    threshold_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="把HI告警阈值改成75",
        page_context={"page_type": "settings"},
    )
    _assert_structured(threshold_plan)
    assert threshold_plan["status"] == "pending_confirmation", threshold_plan
    assert threshold_plan["playbook_id"] == "settings.update_thresholds", threshold_plan
    assert threshold_plan["action"] == "update_threshold_config", threshold_plan
    threshold_result = await action_gateway.confirm_agent_action(session, user=user, request_id=threshold_plan["request_id"])
    assert threshold_result["status"] == "success", threshold_result
    threshold_config = (
        await session.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    ).scalar_one()
    assert threshold_config.hi_threshold == 75.0
    results.append("threshold_update_gateway: ok")

    email_threshold_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="开启邮件通知并发送到admin@example.com",
        page_context={"page_type": "settings"},
    )
    _assert_structured(email_threshold_plan)
    assert email_threshold_plan["status"] == "pending_confirmation", email_threshold_plan
    assert email_threshold_plan["playbook_id"] == "settings.update_thresholds", email_threshold_plan
    email_threshold_result = await action_gateway.confirm_agent_action(session, user=user, request_id=email_threshold_plan["request_id"])
    assert email_threshold_result["status"] == "success", email_threshold_result
    await session.refresh(threshold_config)
    assert threshold_config.email_enabled is True
    assert threshold_config.email_address == "admin@example.com"
    results.append("threshold_email_gateway: ok")

    provider_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="新增Ollama配置，地址http://localhost:11434/v1，默认模型qwen2.5",
        page_context={"page_type": "settings"},
    )
    _assert_structured(provider_plan)
    assert provider_plan["status"] == "pending_confirmation", provider_plan
    assert provider_plan["playbook_id"] == "settings.upsert_ai_provider", provider_plan
    assert provider_plan["action"] == "upsert_ai_provider_config", provider_plan
    provider_result = await action_gateway.confirm_agent_action(session, user=user, request_id=provider_plan["request_id"])
    assert provider_result["status"] == "success", provider_result
    provider_config = (
        await session.execute(select(AIProviderConfig).where(AIProviderConfig.user_id == user.id, AIProviderConfig.provider == "ollama"))
    ).scalar_one()
    assert provider_config.base_url == "http://localhost:11434/v1"
    assert provider_config.default_model == "qwen2.5"
    assert provider_config.model_options and "qwen2.5" in provider_config.model_options
    assert provider_result["result"]["has_api_key"] is False
    results.append("ai_provider_upsert_gateway: ok")

    deepseek_config = AIProviderConfig(
        user_id=user.id,
        provider="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_style="openai",
        default_model="deepseek-chat",
        model_options=["deepseek-chat"],
        enabled=True,
        last_test_status="untested",
    )
    session.add(deepseek_config)
    await session.commit()
    ai_test_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="测试DeepSeek连接",
        page_context={"page_type": "settings"},
    )
    _assert_structured(ai_test_plan)
    assert ai_test_plan["status"] == "pending_confirmation", ai_test_plan
    assert ai_test_plan["playbook_id"] == "settings.test_ai_provider", ai_test_plan
    assert ai_test_plan["action"] == "test_ai_provider_connection", ai_test_plan
    ai_test_result = await action_gateway.confirm_agent_action(session, user=user, request_id=ai_test_plan["request_id"])
    assert ai_test_result["status"] == "success", ai_test_result
    await session.refresh(deepseek_config)
    assert deepseek_config.last_test_status == "error"
    assert deepseek_config.last_test_message == "未配置API Key"
    assert ai_test_result["result"]["last_test_status"] == "error"
    assert ai_test_result["result"]["last_test_message"] == "未配置API Key"
    results.append("ai_provider_test_gateway: ok")

    schedule_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="生成下周维护排程",
        page_context={"page_type": "prediction"},
    )
    _assert_structured(schedule_plan)
    assert schedule_plan["status"] == "pending_confirmation", schedule_plan
    assert schedule_plan["playbook_id"] == "prediction.generate_schedule", schedule_plan
    assert schedule_plan["action"] == "generate_maintenance_schedule", schedule_plan
    schedule_result = await action_gateway.confirm_agent_action(session, user=user, request_id=schedule_plan["request_id"])
    assert schedule_result["status"] == "success", schedule_result
    assert schedule_result["result"]["max_days"] == 7, schedule_result
    assert schedule_result["result"]["total_scheduled"] >= 1, schedule_result
    results.append("maintenance_schedule_gateway: ok")

    update_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="把WO-0001优先级改成紧急",
        page_context={"page_type": "workorder"},
    )
    _assert_structured(update_plan)
    assert update_plan["status"] == "pending_confirmation", update_plan
    assert update_plan["playbook_id"] == "workorder.update_fields", update_plan
    assert update_plan["action"] == "update_workorder_record", update_plan
    update_result = await action_gateway.confirm_agent_action(session, user=user, request_id=update_plan["request_id"])
    assert update_result["status"] == "success", update_result
    updated_workorder = await session.get(WorkOrder, 1)
    assert updated_workorder and updated_workorder.priority == "urgent"
    results.append("workorder_update_fields_gateway: ok")

    cancel_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="取消WO-0001，原因是误创建",
        page_context={"page_type": "workorder"},
    )
    _assert_structured(cancel_plan)
    assert cancel_plan["status"] == "pending_confirmation", cancel_plan
    assert cancel_plan["playbook_id"] == "workorder.cancel_or_delete", cancel_plan
    assert cancel_plan["action"] == "cancel_workorder_record", cancel_plan
    cancel_result = await action_gateway.confirm_agent_action(session, user=user, request_id=cancel_plan["request_id"])
    assert cancel_result["status"] == "success", cancel_result
    await session.refresh(updated_workorder)
    assert updated_workorder.status == "cancelled"
    assert updated_workorder.cancelled_at is not None
    results.append("workorder_cancel_gateway: ok")

    personnel_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="新增维护人员李四，邮箱 lisi@example.com，负责齿轮箱，区域B组",
        page_context={"page_type": "settings"},
    )
    _assert_structured(personnel_plan)
    assert personnel_plan["status"] == "pending_confirmation", personnel_plan
    assert personnel_plan["playbook_id"] == "personnel.upsert", personnel_plan
    assert personnel_plan["action"] == "upsert_personnel", personnel_plan
    personnel_result = await action_gateway.confirm_agent_action(session, user=user, request_id=personnel_plan["request_id"])
    assert personnel_result["status"] == "success", personnel_result
    created_personnel = (
        await session.execute(select(User).where(User.username == "李四", User.role == "technician"))
    ).scalar_one()
    profile = (
        await session.execute(select(MaintenancePersonnel).where(MaintenancePersonnel.user_id == created_personnel.id))
    ).scalar_one()
    assert created_personnel.email == "lisi@example.com"
    assert "齿轮箱检修" in profile.skills
    assert profile.region == "B组"
    results.append("personnel_upsert_gateway: ok")

    delete_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="删除维护人员李四，原因是验证回收",
        page_context={"page_type": "settings"},
    )
    _assert_structured(delete_plan)
    assert delete_plan["status"] == "pending_confirmation", delete_plan
    assert delete_plan["playbook_id"] == "personnel.delete", delete_plan
    assert delete_plan["action"] == "delete_personnel", delete_plan
    delete_result = await action_gateway.confirm_agent_action(session, user=user, request_id=delete_plan["request_id"])
    assert delete_result["status"] == "success", delete_result
    await session.refresh(created_personnel)
    await session.refresh(profile)
    assert created_personnel.is_active is False
    assert profile.is_available is False
    results.append("personnel_delete_gateway: ok")

    knowledge_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="新增主轴裂纹处理方案",
        page_context={"page_type": "knowledge"},
    )
    _assert_structured(knowledge_plan)
    assert knowledge_plan["status"] == "pending_confirmation", knowledge_plan
    assert knowledge_plan["playbook_id"] == "knowledge.upsert_node", knowledge_plan
    assert knowledge_plan["action"] == "upsert_knowledge_node", knowledge_plan
    knowledge_result = await action_gateway.confirm_agent_action(session, user=user, request_id=knowledge_plan["request_id"])
    assert knowledge_result["status"] == "success", knowledge_result
    new_node = (
        await session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "主轴裂纹"))
    ).scalar_one()
    assert new_node.verified is False
    assert new_node.source == "agent_task"
    results.append("knowledge_upsert_gateway: ok")

    review_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="把主轴裂纹知识标记为已验证",
        page_context={"page_type": "knowledge"},
    )
    _assert_structured(review_plan)
    assert review_plan["status"] == "pending_confirmation", review_plan
    assert review_plan["playbook_id"] == "knowledge.review_node", review_plan
    review_result = await action_gateway.confirm_agent_action(session, user=user, request_id=review_plan["request_id"])
    assert review_result["status"] == "success", review_result
    await session.refresh(new_node)
    assert new_node.verified is True
    assert new_node.confidence == 1.0
    results.append("knowledge_review_gateway: ok")

    knowledge_delete_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="删除主轴裂纹知识节点，原因是验证回收",
        page_context={"page_type": "knowledge"},
    )
    _assert_structured(knowledge_delete_plan)
    assert knowledge_delete_plan["status"] == "pending_confirmation", knowledge_delete_plan
    assert knowledge_delete_plan["playbook_id"] == "knowledge.delete_node", knowledge_delete_plan
    knowledge_delete_result = await action_gateway.confirm_agent_action(session, user=user, request_id=knowledge_delete_plan["request_id"])
    assert knowledge_delete_result["status"] == "success", knowledge_delete_result
    missing_node = (
        await session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "主轴裂纹"))
    ).scalar_one_or_none()
    assert missing_node is None
    results.append("knowledge_delete_gateway: ok")

    health_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="刷新YD-B-007健康指数",
        page_context={"page_type": "dashboard"},
    )
    _assert_structured(health_plan)
    assert health_plan["status"] == "pending_confirmation", health_plan
    assert health_plan["playbook_id"] == "turbine.refresh_health", health_plan
    assert health_plan["action"] == "refresh_health_indexes", health_plan
    health_result = await action_gateway.confirm_agent_action(session, user=user, request_id=health_plan["request_id"])
    assert health_result["status"] == "success", health_result
    assert health_result["result"]["affected_count"] == 1, health_result
    refreshed_turbine = (
        await session.execute(select(Turbine).where(Turbine.name == "YD-B-007"))
    ).scalar_one()
    assert refreshed_turbine.hi_value == 80.0
    assert refreshed_turbine.status == "normal"
    results.append("health_refresh_gateway: ok")

    restored_plan = await planner.plan_agent_task(
        session,
        user=user,
        message="新增机舱过热处理方案",
        page_context={"page_type": "knowledge"},
    )
    _assert_structured(restored_plan)
    assert restored_plan["status"] == "pending_confirmation", restored_plan
    request_id = restored_plan["request_id"]
    action_gateway._PENDING_ACTIONS.pop(request_id, None)
    restored_result = await action_gateway.confirm_agent_action(session, user=user, request_id=request_id)
    assert restored_result["status"] == "success", restored_result
    restored_node = (
        await session.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == "机舱过热"))
    ).scalar_one()
    assert restored_node.source == "agent_task"
    results.append("db_restored_pending_action_confirmation: ok")

    return results


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with session_factory() as session:
            user = await _seed(session)
            results = await _run_checks(session, user)
            for line in results:
                print(line)
            print("AGENT_TASK_PLANNER_VERIFY_OK")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
