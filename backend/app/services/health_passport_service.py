"""Turbine health digital passport — cross-event digital thread.

Provides a single-page view of a turbine's complete maintenance history:
- Health index history
- Incident timeline
- Fault, maintenance, and replacement records
- RUL predictions with confidence intervals
- Agent recommendations vs human final decisions
- Recovery certificates
- Model/rule/playbook versions
- Audit root hash
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DecisionPlan,
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
class HealthPassport:
    """Complete digital thread for one turbine."""
    turbine_id: int = 0
    turbine_name: str = ""
    turbine_model: str = ""
    power_mw: Optional[float] = None
    region: str = ""
    commissioned_at: Optional[datetime] = None
    # Health
    current_health_index: Optional[float] = None
    health_trend: str = "stable"  # improving / stable / declining / critical
    # Statistics
    total_incidents: int = 0
    total_faults: int = 0
    total_work_orders: int = 0
    total_maintenance_cost: float = 0.0
    # Timeline
    incidents: list[dict[str, Any]] = field(default_factory=list)
    recent_faults: list[dict[str, Any]] = field(default_factory=list)
    rul_predictions: list[dict[str, Any]] = field(default_factory=list)
    agent_decisions: list[dict[str, Any]] = field(default_factory=list)
    maintenance_history: list[dict[str, Any]] = field(default_factory=list)
    # Versions
    model_versions: dict[str, str] = field(default_factory=dict)
    # Meta
    audit_root_hash: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class HealthPassportService:
    """Generates turbine health digital passports."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate(self, turbine: Turbine) -> HealthPassport:
        """Generate complete health passport for a turbine."""
        passport = HealthPassport(
            turbine_id=turbine.id,
            turbine_name=turbine.name,
            turbine_model=turbine.model or "unknown",
            power_mw=turbine.power_mw,
            region=turbine.region or "unknown",
            commissioned_at=turbine.commissioned_at,
            current_health_index=turbine.hi_value,
        )

        # Health trend
        passport.health_trend = await self._assess_health_trend(turbine.id)

        # Incidents
        await self._load_incidents(turbine.id, passport)

        # Faults
        await self._load_faults(turbine.id, passport)

        # RUL predictions
        await self._load_rul(turbine.id, passport)

        # Maintenance history
        await self._load_maintenance(turbine.id, passport)

        # Agent decisions
        await self._load_agent_decisions(turbine.id, passport)

        # Totals
        passport.total_incidents = len(passport.incidents)
        passport.total_faults = len(passport.recent_faults)
        passport.total_work_orders = len(passport.maintenance_history)

        return passport

    async def _assess_health_trend(self, turbine_id: int) -> str:
        """Assess health trend from recent SCADA and RUL data."""
        # Get recent RUL predictions
        preds = await self.db.execute(
            select(RULPrediction.remaining_life_days)
            .where(RULPrediction.turbine_id == turbine_id)
            .order_by(RULPrediction.predicted_at.desc())
            .limit(10)
        )
        rul_values = [r[0] for r in preds.fetchall() if r[0] is not None]

        if not rul_values:
            # Fall back to health index
            turbine = await self.db.get(Turbine, turbine_id)
            if turbine and turbine.hi_value is not None:
                if turbine.hi_value >= 85:
                    return "stable"
                elif turbine.hi_value >= 70:
                    return "declining"
                else:
                    return "critical"
            return "stable"

        # Simple trend: compare first half vs second half
        mid = len(rul_values) // 2
        if mid >= 2:
            early_avg = sum(rul_values[:mid]) / mid
            late_avg = sum(rul_values[mid:]) / (len(rul_values) - mid)
            if late_avg > early_avg * 1.1:
                return "improving"
            elif late_avg < early_avg * 0.9:
                return "declining"

        # Check absolute values
        min_rul = min(rul_values)
        if min_rul < 30:
            return "critical"
        elif min_rul < 90:
            return "declining"

        return "stable"

    async def _load_incidents(self, turbine_id: int, passport: HealthPassport) -> None:
        incidents = await self.db.execute(
            select(Incident)
            .where(Incident.turbine_id == turbine_id)
            .order_by(Incident.created_at.desc())
            .limit(20)
        )
        inc_list = incidents.scalars().all()

        passport.incidents = [
            {
                "incident_id": inc.incident_id,
                "title": inc.title,
                "severity": inc.severity,
                "stage": inc.stage,
                "status": inc.status,
                "verification_status": inc.verification_status,
                "opened_at": inc.opened_at.isoformat() if inc.opened_at else None,
                "closed_at": inc.closed_at.isoformat() if inc.closed_at else None,
                "trace_id": inc.trace_id,
            }
            for inc in inc_list
        ]

    async def _load_faults(self, turbine_id: int, passport: HealthPassport) -> None:
        faults = await self.db.execute(
            select(Fault)
            .where(Fault.turbine_id == turbine_id)
            .order_by(Fault.detected_at.desc())
            .limit(20)
        )
        fault_list = faults.scalars().all()

        passport.recent_faults = [
            {
                "id": f.id,
                "fault_type": f.fault_type,
                "confidence": f.confidence,
                "status": f.status,
                "priority": f.priority,
                "detected_at": f.detected_at.isoformat() if f.detected_at else None,
                "handler": f.handler,
                "work_order_id": f.work_order_id,
            }
            for f in fault_list
        ]

    async def _load_rul(self, turbine_id: int, passport: HealthPassport) -> None:
        preds = await self.db.execute(
            select(RULPrediction)
            .where(RULPrediction.turbine_id == turbine_id)
            .order_by(RULPrediction.predicted_at.desc())
            .limit(10)
        )
        pred_list = preds.scalars().all()

        passport.rul_predictions = [
            {
                "component": p.component,
                "remaining_life_days": p.remaining_life_days,
                "confidence_lower": p.confidence_lower,
                "confidence_upper": p.confidence_upper,
                "predicted_at": p.predicted_at.isoformat() if p.predicted_at else None,
            }
            for p in pred_list
        ]

    async def _load_maintenance(
        self, turbine_id: int, passport: HealthPassport
    ) -> None:
        wos = await self.db.execute(
            select(WorkOrder)
            .where(WorkOrder.turbine_id == turbine_id)
            .order_by(WorkOrder.created_at.desc())
            .limit(20)
        )
        wo_list = wos.scalars().all()

        total_cost = 0.0
        history = []
        for w in wo_list:
            total_cost += w.cost_actual or w.cost_estimate or 0
            history.append({
                "id": w.id,
                "title": w.title,
                "status": w.status,
                "priority": w.priority,
                "assignee": w.assignee,
                "cost_actual": w.cost_actual,
                "cost_estimate": w.cost_estimate,
                "created_at": w.created_at.isoformat() if w.created_at else None,
                "completed_at": w.completed_at.isoformat() if w.completed_at else None,
                "downtime_hours": w.downtime_hours,
            })

        passport.maintenance_history = history
        passport.total_maintenance_cost = total_cost

    async def _load_agent_decisions(
        self, turbine_id: int, passport: HealthPassport
    ) -> None:
        """Load agent recommendations vs human decisions."""
        # Get decision plans for this turbine's incidents
        incidents = await self.db.execute(
            select(Incident.id).where(Incident.turbine_id == turbine_id)
        )
        inc_ids = [r[0] for r in incidents.fetchall()]

        if not inc_ids:
            return

        plans = await self.db.execute(
            select(DecisionPlan)
            .where(DecisionPlan.incident_id.in_(inc_ids[:10]))
            .order_by(DecisionPlan.created_at.desc())
            .limit(20)
        )
        plan_list = plans.scalars().all()

        passport.agent_decisions = [
            {
                "plan_name": p.plan_name,
                "strategy": p.strategy,
                "total_score": p.total_score,
                "is_recommended": p.is_recommended,
                "safety_risk": p.safety_risk,
                "repair_cost": p.repair_cost,
                "llm_explanation": p.llm_explanation,
            }
            for p in plan_list
        ]
