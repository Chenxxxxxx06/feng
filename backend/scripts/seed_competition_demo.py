"""Create one deterministic, explicitly labelled closed-loop demo scenario.

This script is idempotent: rerunning it refreshes the same scenario instead of
creating duplicate incidents, work orders, faults, or telemetry.

Usage (from ``backend``):
    python -m scripts.seed_competition_demo
"""

from __future__ import annotations

import asyncio
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import and_, delete, or_, select, update  # noqa: E402

from app.database import Base, async_session, engine  # noqa: E402
from app.models import (  # noqa: E402
    AgentSpan,
    AgentTrace,
    AlarmRecord,
    DecisionPlan,
    EvidenceEdge,
    EvidenceNode,
    Fault,
    Incident,
    InspectionMission,
    MaintenanceRecord,
    NotificationLog,
    PolicyDecision,
    RULPrediction,
    Turbine,
    WorkOrder,
)
from app.services.competition_demo_service import (  # noqa: E402
    DEMO_SCENARIO_ID,
    replace_demo_telemetry,
)


DEMO_INCIDENT_ID = "INC-DEMO-YJ-A-013"
DEMO_WORKORDER_TITLE = "YJ-A-013 叶片前缘侵蚀修复（演示）"
LEGACY_DEMO_WORKORDER_PREFIX = "[黄金Demo] YJ-A-013"


async def _prune_legacy_demo_incidents(
    db,
    *,
    include_playwright_e2e: bool = False,
) -> int:
    """Remove only known, explicitly named legacy smoke/demo incidents.

    The predicates intentionally do not match generic Chinese ``演示`` text, so
    user-created incidents are never removed by this cleanup.
    """
    predicates = [
        Incident.title.like("Demo:%"),
        Incident.title.like("Demo Run %"),
        Incident.title == "Smoke Test",
        Incident.title == "Test",
        and_(
            Incident.incident_id.like("INC-GOLDEN-%"),
            Incident.title == "无人机巡检: YJ-A-013 叶片前缘侵蚀",
        ),
    ]
    if include_playwright_e2e:
        predicates.append(Incident.title.like("Playwright E2E:%"))
    legacy = (
        await db.execute(select(Incident).where(or_(*predicates)))
    ).scalars().all()
    incident_ids = [item.id for item in legacy]
    if not incident_ids:
        return 0

    trace_ids = (
        await db.execute(
            select(AgentTrace.trace_id).where(AgentTrace.incident_id.in_(incident_ids))
        )
    ).scalars().all()
    if trace_ids:
        await db.execute(delete(AgentSpan).where(AgentSpan.trace_id.in_(trace_ids)))

    # Preserve unrelated operational records while removing their stale demo link.
    await db.execute(
        update(InspectionMission)
        .where(InspectionMission.incident_id.in_(incident_ids))
        .values(incident_id=None)
    )
    await db.execute(
        update(WorkOrder)
        .where(WorkOrder.incident_id.in_(incident_ids))
        .values(incident_id=None)
    )

    for model in (
        EvidenceEdge,
        EvidenceNode,
        AlarmRecord,
        DecisionPlan,
        PolicyDecision,
        AgentTrace,
    ):
        await db.execute(delete(model).where(model.incident_id.in_(incident_ids)))
    await db.execute(delete(Incident).where(Incident.id.in_(incident_ids)))
    return len(incident_ids)


async def _prune_legacy_demo_workorders(db) -> int:
    """Remove the old, explicitly labelled golden-demo work-order duplicates."""
    legacy_ids = (
        await db.execute(
            select(WorkOrder.id).where(
                or_(
                    WorkOrder.title.like(f"{LEGACY_DEMO_WORKORDER_PREFIX}%"),
                    WorkOrder.title.like("E2E-闭环关联-%"),
                )
            )
        )
    ).scalars().all()
    if not legacy_ids:
        return 0
    await db.execute(
        delete(MaintenanceRecord).where(MaintenanceRecord.work_order_id.in_(legacy_ids))
    )
    await db.execute(
        delete(NotificationLog).where(NotificationLog.work_order_id.in_(legacy_ids))
    )
    await db.execute(delete(WorkOrder).where(WorkOrder.id.in_(legacy_ids)))
    return len(legacy_ids)


async def _remove_duplicate_demo_workorders(db, turbine_id: int) -> WorkOrder | None:
    candidates = (
        await db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.turbine_id == turbine_id,
                or_(
                    WorkOrder.title == DEMO_WORKORDER_TITLE,
                    WorkOrder.title.like(f"{LEGACY_DEMO_WORKORDER_PREFIX}%"),
                ),
            )
            .order_by(WorkOrder.id.asc())
        )
    ).scalars().all()
    if not candidates:
        return None

    canonical, *duplicates = candidates
    duplicate_ids = [item.id for item in duplicates]
    if duplicate_ids:
        await db.execute(
            delete(MaintenanceRecord).where(
                MaintenanceRecord.work_order_id.in_(duplicate_ids)
            )
        )
        await db.execute(
            delete(NotificationLog).where(NotificationLog.work_order_id.in_(duplicate_ids))
        )
        await db.execute(delete(WorkOrder).where(WorkOrder.id.in_(duplicate_ids)))
    return canonical


def _is_demo_marker(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("demo_scenario") == DEMO_SCENARIO_ID


async def _get_or_create_turbine(db) -> Turbine:
    result = await db.execute(
        select(Turbine).where(
            Turbine.source_dataset == "competition_demo",
            Turbine.source_asset_id == "demo:YJ-A-013",
        )
    )
    turbine = result.scalar_one_or_none()
    if turbine is None:
        turbine = Turbine(
            name="YJ-A-013",
            model="演示机组",
            power_mw=2.0,
            lat=36.5,
            lng=109.5,
            region="演示风场",
            source_dataset="competition_demo",
            source_asset_id="demo:YJ-A-013",
            asset_scope="demo_asset",
            geo_scope="demo",
        )
        db.add(turbine)
        await db.flush()
    turbine.status = "normal"
    turbine.hi_value = 86.0
    return turbine


async def seed_demo(
    *,
    prune_legacy_demo: bool = False,
    prune_playwright_e2e: bool = False,
) -> dict[str, int | str]:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(timezone.utc).replace(microsecond=0)
    maintenance_end = now - timedelta(hours=25)
    incident_opened = maintenance_end - timedelta(hours=5)

    async with async_session() as db:
        legacy_incidents_removed = (
            await _prune_legacy_demo_incidents(
                db,
                include_playwright_e2e=prune_playwright_e2e,
            )
            if prune_legacy_demo or prune_playwright_e2e
            else 0
        )
        legacy_workorders_removed = (
            await _prune_legacy_demo_workorders(db) if prune_legacy_demo else 0
        )
        turbine = await _get_or_create_turbine(db)

        incident_result = await db.execute(
            select(Incident).where(Incident.incident_id == DEMO_INCIDENT_ID)
        )
        incident = incident_result.scalar_one_or_none()
        if incident is None:
            incident = Incident(
                incident_id=DEMO_INCIDENT_ID,
                turbine_id=turbine.id,
                title="YJ-A-013 叶片前缘侵蚀异常（演示数据）",
            )
            db.add(incident)
            await db.flush()
        incident.turbine_id = turbine.id
        incident.title = "YJ-A-013 叶片前缘侵蚀异常（演示数据）"
        incident.severity = "high"
        incident.stage = "executing"
        incident.status = "in_progress"
        incident.verification_status = "pending"
        incident.summary = "比赛演示场景；所有新增遥测均标记为 demo，不代表现场实时数据。"
        incident.resolution = None
        incident.opened_at = incident_opened
        incident.closed_at = None
        incident.updated_at = now

        fault_rows = (
            await db.execute(select(Fault).where(Fault.turbine_id == turbine.id))
        ).scalars().all()
        fault = next((item for item in fault_rows if _is_demo_marker(item.details)), None)
        if fault is None:
            fault = Fault(
                turbine_id=turbine.id,
                fault_type="blade_leading_edge_erosion",
                confidence=0.91,
            )
            db.add(fault)
            await db.flush()
        fault.detected_at = incident_opened
        fault.discovered_at = incident_opened
        fault.status = "closed"
        fault.processing_status = "closed"
        fault.priority = "high"
        fault.closed_at = maintenance_end
        fault.details = {
            "demo_scenario": DEMO_SCENARIO_ID,
            "source_type": "demo",
            "is_demo": True,
            "statement": "合成演示事件，仅用于验证闭环功能。",
        }

        work_order = await _remove_duplicate_demo_workorders(db, turbine.id)
        if work_order is None:
            work_order = WorkOrder(
                turbine_id=turbine.id,
                incident_id=incident.id,
                title=DEMO_WORKORDER_TITLE,
            )
            db.add(work_order)
        work_order.turbine_id = turbine.id
        work_order.incident_id = incident.id
        work_order.title = DEMO_WORKORDER_TITLE
        work_order.fault_id = fault.id
        work_order.description = "演示工单：完成叶片前缘检查、打磨、补强与复测。"
        work_order.status = "completed"
        work_order.priority = "high"
        work_order.fault_type = "blade_leading_edge_erosion"
        work_order.cost_estimate = 35000.0
        work_order.cost_actual = 33200.0
        work_order.created_at = incident_opened + timedelta(hours=1)
        work_order.updated_at = maintenance_end
        work_order.completed_at = maintenance_end
        work_order.deleted_at = None
        turbine.last_maintenance = maintenance_end

        telemetry_count = await replace_demo_telemetry(
            db,
            turbine_id=turbine.id,
            maintenance_end=maintenance_end,
        )

        rul_result = await db.execute(
            select(RULPrediction).where(
                RULPrediction.turbine_id == turbine.id,
                RULPrediction.component == "叶片",
            )
        )
        rul = rul_result.scalars().first()
        if rul is None:
            rul = RULPrediction(turbine_id=turbine.id, component="叶片")
            db.add(rul)
        rul.predicted_at = now
        rul.remaining_life_days = 240.0
        rul.confidence_lower = 190.0
        rul.confidence_upper = 285.0

        await db.commit()
        return {
            "scenario": DEMO_SCENARIO_ID,
            "turbine_id": turbine.id,
            "incident_id": incident.id,
            "work_order_id": work_order.id,
            "telemetry_rows": telemetry_count,
            "legacy_incidents_removed": legacy_incidents_removed,
            "legacy_workorders_removed": legacy_workorders_removed,
        }


async def main() -> int:
    parser = argparse.ArgumentParser(description="准备比赛评审闭环演示数据")
    parser.add_argument(
        "--prune-legacy-demo",
        action="store_true",
        help="清理标题为 Demo / Demo Run / Smoke Test 的旧演示事件",
    )
    parser.add_argument(
        "--prune-playwright-e2e",
        action="store_true",
        help="额外清理标题以 Playwright E2E: 开头的自动化测试事件",
    )
    args = parser.parse_args()
    result = await seed_demo(
        prune_legacy_demo=args.prune_legacy_demo,
        prune_playwright_e2e=args.prune_playwright_e2e,
    )
    print("比赛演示场景已准备完成：")
    for key, value in result.items():
        print(f"  {key}: {value}")
    print("数据标记：source_type=demo, is_demo=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
