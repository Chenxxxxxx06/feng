"""Component digital thread — traceable component lifecycle.

Chains entities by time and source:
  turbine → component → serial/batch → measurement point
  → alarm → incident → work order → spare parts used
  → repair result → recovery certificate

Supports per-component traceability without requiring a full ERP system.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Fault,
    Incident,
    RULPrediction,
    SCADARecord,
    Turbine,
    VibrationData,
    WorkOrder,
)

logger = logging.getLogger(__name__)


@dataclass
class ComponentNode:
    """One node in the component digital thread graph."""
    entity_type: str = ""  # turbine/component/measurement/alarm/incident/workorder/spare/repair/certificate
    entity_id: str = ""
    label: str = ""
    timestamp: Optional[datetime] = None
    data: dict[str, Any] = field(default_factory=dict)
    parent_entity_id: str = ""  # Links to parent in the thread
    source: str = ""


@dataclass
class DigitalThread:
    """Complete digital thread for a component."""
    turbine_id: int = 0
    turbine_name: str = ""
    component: str = ""
    nodes: list[ComponentNode] = field(default_factory=list)
    total_events: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ComponentDigitalThreadService:
    """Traces component lifecycle across all database entities."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def trace_component(
        self, turbine_id: int, component: str
    ) -> DigitalThread:
        """Build digital thread for a specific component on a turbine."""
        turbine = await self.db.get(Turbine, turbine_id)
        turbine_name = turbine.name if turbine else f"Turbine-{turbine_id}"

        thread = DigitalThread(
            turbine_id=turbine_id,
            turbine_name=turbine_name,
            component=component,
        )

        nodes: list[ComponentNode] = []

        # 1. Turbine root
        if turbine:
            nodes.append(ComponentNode(
                entity_type="turbine",
                entity_id=str(turbine.id),
                label=turbine.name,
                timestamp=turbine.commissioned_at,
                data={
                    "model": turbine.model,
                    "power_mw": turbine.power_mw,
                    "region": turbine.region,
                    "health_index": turbine.hi_value,
                },
            ))

        # 2. SCADA measurements for this component
        scada_nodes = await self._trace_scada(turbine_id, component)
        nodes.extend(scada_nodes)

        # 3. Vibration data
        vib_nodes = await self._trace_vibration(turbine_id, component)
        nodes.extend(vib_nodes)

        # 4. RUL predictions
        rul_nodes = await self._trace_rul(turbine_id, component)
        nodes.extend(rul_nodes)

        # 5. Faults/Alarms
        fault_nodes = await self._trace_faults(turbine_id, component)
        nodes.extend(fault_nodes)

        # 6. Incidents involving this component
        inc_nodes = await self._trace_incidents(turbine_id, component)
        nodes.extend(inc_nodes)

        # 7. Work orders
        wo_nodes = await self._trace_work_orders(turbine_id, component)
        nodes.extend(wo_nodes)

        # Sort by timestamp
        nodes.sort(key=lambda n: n.timestamp or datetime.min.replace(tzinfo=timezone.utc))

        thread.nodes = nodes
        thread.total_events = len(nodes)
        return thread

    async def trace_all_components(self, turbine_id: int) -> list[DigitalThread]:
        """Build digital threads for all known components on a turbine."""
        # Discover components from RUL predictions, faults, and vibration data
        components: set[str] = set()

        # From RUL
        rul = await self.db.execute(
            select(RULPrediction.component)
            .where(RULPrediction.turbine_id == turbine_id)
            .distinct()
        )
        components.update(r[0] for r in rul.fetchall() if r[0])

        # From vibration
        vib = await self.db.execute(
            select(VibrationData.component)
            .where(VibrationData.turbine_id == turbine_id)
            .distinct()
        )
        components.update(r[0] for r in vib.fetchall() if r[0])

        # From faults
        faults = await self.db.execute(
            select(Fault.fault_type)
            .where(Fault.turbine_id == turbine_id)
            .distinct()
        )
        components.update(r[0] for r in faults.fetchall() if r[0])

        threads = []
        for comp in sorted(components):
            if comp:
                thread = await self.trace_component(turbine_id, comp)
                threads.append(thread)

        return threads

    async def _trace_scada(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        # Map component keywords to SCADA columns
        scada_cols = {
            "gearbox": "gearbox_temperature_c",
            "bearing": "bearing_temperature_c",
            "generator": "gen_temperature_c",
        }

        nodes: list[ComponentNode] = []
        for keyword, col in scada_cols.items():
            if keyword in component.lower():
                records = await self.db.execute(
                    select(SCADARecord.timestamp, getattr(SCADARecord, col))
                    .where(SCADARecord.turbine_id == turbine_id)
                    .order_by(SCADARecord.timestamp.desc())
                    .limit(50)
                )
                for row in records.fetchall():
                    if row[1] is not None:
                        nodes.append(ComponentNode(
                            entity_type="measurement",
                            entity_id=f"scada_{row[0].timestamp() if row[0] else ''}",
                            label=f"SCADA {col}",
                            timestamp=row[0],
                            data={"column": col, "value": row[1], "unit": "°C"},
                            source="scada",
                        ))
        return nodes

    async def _trace_vibration(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        nodes: list[ComponentNode] = []
        records = await self.db.execute(
            select(VibrationData)
            .where(
                VibrationData.turbine_id == turbine_id,
                VibrationData.component.contains(component.split("_")[0]),
            )
            .order_by(VibrationData.timestamp.desc())
            .limit(20)
        )
        for v in records.scalars().all():
            nodes.append(ComponentNode(
                entity_type="measurement",
                entity_id=f"vibration_{v.id}",
                label=f"Vibration: {v.component}",
                timestamp=v.timestamp,
                data={
                    "rms": v.rms,
                    "peak_freq_hz": v.peak_freq_hz,
                    "component": v.component,
                },
                source="vibration",
            ))
        return nodes

    async def _trace_rul(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        nodes: list[ComponentNode] = []
        preds = await self.db.execute(
            select(RULPrediction)
            .where(
                RULPrediction.turbine_id == turbine_id,
                RULPrediction.component.contains(component.split("_")[0]),
            )
            .order_by(RULPrediction.predicted_at.desc())
            .limit(10)
        )
        for p in preds.scalars().all():
            nodes.append(ComponentNode(
                entity_type="prediction",
                entity_id=f"rul_{p.id}",
                label=f"RUL: {p.component}",
                timestamp=p.predicted_at,
                data={
                    "remaining_life_days": p.remaining_life_days,
                    "confidence_lower": p.confidence_lower,
                    "confidence_upper": p.confidence_upper,
                },
                source="rul_model",
            ))
        return nodes

    async def _trace_faults(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        nodes: list[ComponentNode] = []
        faults = await self.db.execute(
            select(Fault)
            .where(
                Fault.turbine_id == turbine_id,
                Fault.fault_type.contains(component.split("_")[0]),
            )
            .order_by(Fault.detected_at.desc())
            .limit(20)
        )
        for f in faults.scalars().all():
            nodes.append(ComponentNode(
                entity_type="alarm",
                entity_id=str(f.id),
                label=f"Fault: {f.fault_type}",
                timestamp=f.detected_at,
                data={
                    "fault_type": f.fault_type,
                    "confidence": f.confidence,
                    "status": f.status,
                    "priority": f.priority,
                    "work_order_id": f.work_order_id,
                },
                source="fault_detection",
            ))
        return nodes

    async def _trace_incidents(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        nodes: list[ComponentNode] = []
        incidents = await self.db.execute(
            select(Incident)
            .where(Incident.turbine_id == turbine_id)
            .order_by(Incident.created_at.desc())
            .limit(20)
        )
        for inc in incidents.scalars().all():
            # Check if incident title matches component
            if component.lower() not in (inc.title or "").lower():
                continue
            nodes.append(ComponentNode(
                entity_type="incident",
                entity_id=inc.incident_id,
                label=f"Incident: {inc.title}",
                timestamp=inc.created_at,
                data={
                    "severity": inc.severity,
                    "stage": inc.stage,
                    "status": inc.status,
                    "verification_status": inc.verification_status,
                },
                source="incident",
            ))
        return nodes

    async def _trace_work_orders(
        self, turbine_id: int, component: str
    ) -> list[ComponentNode]:
        nodes: list[ComponentNode] = []
        wos = await self.db.execute(
            select(WorkOrder)
            .where(
                WorkOrder.turbine_id == turbine_id,
            )
            .order_by(WorkOrder.created_at.desc())
            .limit(20)
        )
        for w in wos.scalars().all():
            if component.lower() not in (w.title or "").lower() and \
               component.lower() not in (w.description or "").lower():
                continue
            nodes.append(ComponentNode(
                entity_type="workorder",
                entity_id=str(w.id),
                label=f"WorkOrder: {w.title}",
                timestamp=w.created_at,
                data={
                    "status": w.status,
                    "priority": w.priority,
                    "assignee": w.assignee,
                    "cost_actual": w.cost_actual,
                    "downtime_hours": w.downtime_hours,
                },
                source="work_order",
            ))
        return nodes
