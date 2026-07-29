"""Regression tests for reproducibility, incident linkage, and write RBAC."""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.models import Incident, SCADARecord, Turbine, WorkOrder
from app.services.competition_demo_service import (
    DEMO_DATASET,
    DEMO_INCIDENT_REF,
    replay_latest_completed_workorder,
)
from app.services.recovery_verification_service import RecoveryVerificationService


async def _viewer_headers(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/api/auth/register",
        json={
            "username": "hardening_viewer",
            "email": "hardening-viewer@example.com",
            "password": "viewer-pass-123",
            "role": "admin",
        },
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "viewer"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", "/api/turbines/refresh-health", {}),
        ("post", "/api/prediction/rul/refresh", {}),
        ("patch", "/api/diagnosis/faults/999/status?processing_status=closed", {}),
        ("post", "/api/diagnosis/seed-knowledge", {}),
        ("post", "/api/competition-demo/prepare", {}),
        ("post", "/api/competition-demo/incidents/999/time-replay", {}),
        (
            "post",
            "/api/settings/data-sources/test",
            {"json": {"source_type": "scada", "connection_params": {}}},
        ),
        (
            "post",
            "/api/federated/share?farm_id=farm-a&fault_type=bearing&sample_size=10",
            {},
        ),
    ],
)
async def test_viewer_cannot_call_state_changing_endpoints(
    client: AsyncClient,
    method: str,
    path: str,
    kwargs: dict,
):
    headers = await _viewer_headers(client)
    response = await client.request(method, path, headers=headers, **kwargs)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_recovery_verification_ignores_unrelated_same_turbine_workorder(
    db_session,
    test_turbine,
):
    now = datetime.now(timezone.utc)
    incident = Incident(
        incident_id="INC-HARDEN-LINK-001",
        turbine_id=test_turbine.id,
        title="链接校验",
        opened_at=now - timedelta(hours=30),
    )
    db_session.add(incident)
    await db_session.flush()
    db_session.add(
        WorkOrder(
            turbine_id=test_turbine.id,
            title="同风机但无事件关联的工单",
            status="completed",
            completed_at=now - timedelta(hours=25),
        )
    )
    await db_session.commit()

    certificate = await RecoveryVerificationService(db_session).verify(incident)

    assert certificate.verification_status.value == "insufficient_data"
    assert certificate.observation_hours == 0
    assert certificate.metrics[0].metric_name == "Completed Work Order Link"


@pytest.mark.asyncio
async def test_workorder_incident_must_match_turbine(
    client: AsyncClient,
    auth_headers,
    db_session,
    test_turbine,
):
    other_turbine = Turbine(name="TEST-OTHER", status="normal")
    db_session.add(other_turbine)
    await db_session.flush()
    incident = Incident(
        incident_id="INC-HARDEN-LINK-002",
        turbine_id=other_turbine.id,
        title="其他风机关联校验",
    )
    db_session.add(incident)
    await db_session.commit()

    response = await client.post(
        "/api/workorders/",
        headers=auth_headers,
        json={
            "turbine_id": test_turbine.id,
            "incident_id": incident.id,
            "title": "不允许跨风机关联",
        },
    )

    assert response.status_code == 400
    assert "incident turbine_id" in response.json()["detail"]


@pytest.mark.asyncio
async def test_demo_time_replay_uses_latest_completed_linked_workorder(
    db_session,
    test_turbine,
):
    now = datetime.now(timezone.utc)
    test_turbine.source_dataset = DEMO_DATASET
    incident = Incident(
        incident_id=DEMO_INCIDENT_REF,
        turbine_id=test_turbine.id,
        title="比赛时间回放",
        stage="executing",
        status="in_progress",
    )
    db_session.add(incident)
    await db_session.flush()
    old_order = WorkOrder(
        turbine_id=test_turbine.id,
        incident_id=incident.id,
        title="旧演示工单",
        status="completed",
        completed_at=now - timedelta(days=2),
    )
    latest_order = WorkOrder(
        turbine_id=test_turbine.id,
        incident_id=incident.id,
        title="当前浏览器创建工单",
        status="completed",
        completed_at=now,
    )
    db_session.add_all([old_order, latest_order])
    await db_session.commit()

    result = await replay_latest_completed_workorder(
        db_session,
        incident_id=incident.id,
    )

    assert result["work_order_id"] == latest_order.id
    assert result["simulated_elapsed_hours"] == 25
    telemetry_count = await db_session.scalar(
        select(func.count(SCADARecord.id)).where(
            SCADARecord.turbine_id == test_turbine.id,
        )
    )
    assert telemetry_count == 73
