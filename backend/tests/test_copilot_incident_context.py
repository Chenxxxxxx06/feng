import pytest
from sqlalchemy import select

from app.models import Incident, Turbine, WorkOrder
from app.services.agent_entities.resolver import resolve_turbine_by_ref
from app.services.agent_actions.workorder import confirm_agent_action, plan_agent_action
from app.services.copilot_context import build_copilot_context_bundle


@pytest.mark.asyncio
async def test_incident_context_reads_selected_incident(db_session, test_turbine):
    incident = Incident(
        incident_id="INC-COPILOT-001",
        turbine_id=test_turbine.id,
        title="齿轮箱振动异常",
        severity="high",
        stage="diagnosing",
        status="in_progress",
    )
    db_session.add(incident)
    await db_session.commit()
    await db_session.refresh(incident)

    bundle = await build_copilot_context_bundle(
        db_session,
        session_id="test-session",
        messages=[{"role": "user", "content": "总结当前事件"}],
        page_context={
            "page_type": "incident",
            "incident_id": incident.id,
            "incident_ref": incident.incident_id,
            "turbine_id": test_turbine.id,
        },
        selected_contexts=["incident"],
    )

    assert bundle["selected_contexts"] == ["incident"]
    assert bundle["context_sources"][0]["label"] == "事件指挥"
    summary = bundle["tools"][0]["result"]
    assert summary["incident_id"] == incident.incident_id
    assert summary["stage"] == "diagnosing"
    assert summary["evidence_count"] == 0
    assert summary["decision_plan_count"] == 0


@pytest.mark.asyncio
async def test_agent_created_workorder_keeps_selected_incident(
    db_session,
    test_turbine,
    test_user,
):
    incident = Incident(
        incident_id="INC-COPILOT-WO-001",
        turbine_id=test_turbine.id,
        title="叶片异常处置",
        severity="high",
        stage="executing",
        status="in_progress",
    )
    db_session.add(incident)
    await db_session.commit()
    await db_session.refresh(incident)

    plan = await plan_agent_action(
        db_session,
        user=test_user,
        message="为当前事件创建维修工单",
        page_context={
            "page_type": "incident",
            "incident_id": incident.id,
            "incident_ref": incident.incident_id,
            "turbine_id": test_turbine.id,
            "turbine_name": test_turbine.name,
        },
    )

    assert plan["status"] == "pending_confirmation"
    assert plan["confirmation"]["after"]["incident_id"] == incident.id

    result = await confirm_agent_action(
        db_session,
        user=test_user,
        request_id=plan["request_id"],
    )
    assert result["status"] == "success"

    workorder = (
        await db_session.execute(
            select(WorkOrder).where(WorkOrder.id == result["result"]["id"])
        )
    ).scalar_one()
    assert workorder.incident_id == incident.id
    assert workorder.turbine_id == incident.turbine_id


@pytest.mark.asyncio
async def test_agent_page_context_id_disambiguates_duplicate_turbine_names(
    db_session,
    test_turbine,
    test_user,
):
    test_turbine.name = "YJ-A-013"
    demo_turbine = Turbine(
        name="YJ-A-013",
        status="normal",
        source_dataset="competition_demo",
        source_asset_id="demo:YJ-A-013",
    )
    db_session.add(demo_turbine)
    await db_session.flush()
    incident = Incident(
        incident_id="INC-COPILOT-DUPLICATE-NAME",
        turbine_id=demo_turbine.id,
        title="同名跨数据集风机",
        stage="executing",
        status="in_progress",
    )
    db_session.add(incident)
    await db_session.commit()

    ambiguous = await resolve_turbine_by_ref(db_session, "YJ-A-013")
    assert ambiguous.entity is None
    assert ambiguous.reason == "ambiguous"

    plan = await plan_agent_action(
        db_session,
        user=test_user,
        message="为当前事件创建维修工单",
        page_context={
            "page_type": "incident",
            "incident_id": incident.id,
            "incident_ref": incident.incident_id,
            "turbine_id": demo_turbine.id,
            "turbine_name": demo_turbine.name,
        },
    )

    assert plan["status"] == "pending_confirmation"
    assert plan["confirmation"]["after"]["turbine_id"] == demo_turbine.id
    assert plan["confirmation"]["after"]["incident_id"] == incident.id
