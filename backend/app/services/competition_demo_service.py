"""Strictly scoped helpers for the labelled competition demonstration."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident, SCADARecord, Turbine, VibrationData, WorkOrder


DEMO_SCENARIO_ID = "competition-yj-a-013-v1"
DEMO_INCIDENT_REF = "INC-DEMO-YJ-A-013"
DEMO_DATASET = "competition_demo"
DEMO_OBSERVATION_HOURS = 25


class CompetitionDemoError(ValueError):
    """Raised when a time replay is requested outside the labelled demo."""


def _is_demo_marker(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get("demo_scenario") == DEMO_SCENARIO_ID


async def replace_demo_telemetry(
    db: AsyncSession,
    *,
    turbine_id: int,
    maintenance_end: datetime,
) -> int:
    """Replace only telemetry carrying this competition demo's marker."""
    existing_scada = (
        await db.execute(select(SCADARecord).where(SCADARecord.turbine_id == turbine_id))
    ).scalars().all()
    for row in existing_scada:
        if _is_demo_marker(row.extra):
            await db.delete(row)

    telemetry_count = 0
    for offset in range(-48, 25):
        is_post = offset >= 0
        db.add(
            SCADARecord(
                turbine_id=turbine_id,
                timestamp=maintenance_end + timedelta(hours=offset),
                power_kw=1820.0 if is_post else 1580.0,
                wind_speed_ms=8.1,
                rotor_rpm=14.2,
                gen_temperature_c=58.0 if is_post else 66.0,
                gearbox_temperature_c=55.0 if is_post else 71.0,
                bearing_temperature_c=49.0 if is_post else 64.0,
                pitch_angle_deg=2.1,
                grid_frequency_hz=50.0,
                ambient_temp_c=18.0,
                extra={
                    "demo_scenario": DEMO_SCENARIO_ID,
                    "source_type": "demo",
                    "is_demo": True,
                },
            )
        )
        telemetry_count += 1

    existing_vibration = (
        await db.execute(select(VibrationData).where(VibrationData.turbine_id == turbine_id))
    ).scalars().all()
    for row in existing_vibration:
        if row.waveform_path == f"demo://{DEMO_SCENARIO_ID}":
            await db.delete(row)
    for offset in (-36, -24, -12, 6, 12, 24):
        db.add(
            VibrationData(
                turbine_id=turbine_id,
                timestamp=maintenance_end + timedelta(hours=offset),
                component="blade",
                rms=2.1 if offset >= 0 else 4.6,
                peak_freq_hz=18.0,
                waveform_path=f"demo://{DEMO_SCENARIO_ID}",
            )
        )
    return telemetry_count


async def replay_latest_completed_workorder(
    db: AsyncSession,
    *,
    incident_id: int,
) -> dict[str, int | str]:
    """Backdate the latest completed order and rebuild demo-only telemetry.

    This is intentionally unavailable for normal incidents and turbines.
    Recovery verification itself is not bypassed or modified.
    """
    incident = await db.get(Incident, incident_id)
    if not incident or incident.incident_id != DEMO_INCIDENT_REF:
        raise CompetitionDemoError("时间回放仅允许用于明确标注的比赛演示事件")
    turbine = await db.get(Turbine, incident.turbine_id)
    if not turbine or turbine.source_dataset != DEMO_DATASET:
        raise CompetitionDemoError("事件未关联比赛演示风机，拒绝时间回放")

    work_order = (
        await db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.incident_id == incident.id,
                WorkOrder.turbine_id == turbine.id,
                WorkOrder.status.in_(["completed", "closed"]),
                WorkOrder.deleted_at.is_(None),
            )
            .order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not work_order:
        raise CompetitionDemoError("请先把当前事件关联工单推进到已完成")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    maintenance_end = now - timedelta(hours=DEMO_OBSERVATION_HOURS)
    work_order.completed_at = maintenance_end
    work_order.updated_at = now
    turbine.last_maintenance = maintenance_end
    incident.stage = "executing"
    incident.status = "in_progress"
    incident.verification_status = "pending"
    incident.closed_at = None
    incident.resolution = None
    incident.updated_at = now

    telemetry_rows = await replace_demo_telemetry(
        db,
        turbine_id=turbine.id,
        maintenance_end=maintenance_end,
    )
    await db.commit()
    return {
        "scenario": DEMO_SCENARIO_ID,
        "incident_id": incident.id,
        "work_order_id": work_order.id,
        "simulated_elapsed_hours": DEMO_OBSERVATION_HOURS,
        "maintenance_completed_at": maintenance_end.isoformat(),
        "telemetry_rows": telemetry_rows,
    }
