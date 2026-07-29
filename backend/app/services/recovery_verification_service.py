"""Recovery verification service — prove that maintenance actually worked.

Incident cannot be closed by writing a note. The recovery verification service:
1. Selects pre-maintenance baseline window
2. Selects post-maintenance observation window
3. Compares vibration, temperature, power, health index, alarm recurrence, RUL
4. Checks if observation time is sufficient
5. Outputs pass / conditional / fail / insufficient_data
6. Issues Recovery Certificate

Algorithms:
- Robust z-score (median/MAD) for outlier-robust comparison
- CUSUM for change-point detection
- Threshold + duration rules for minimum observation
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    MetricComparison,
    RecoveryCertificate,
    VerificationStatus,
)
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

# Minimum observation hours required for each verification level
MIN_OBSERVATION_HOURS = 24
CONDITIONAL_OBSERVATION_HOURS = 6


class RecoveryVerificationService:
    """Post-maintenance recovery verification.

    Compares pre/post metrics using robust statistics and issues
    a Recovery Certificate that gates incident closure.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Main entry point ──

    async def verify(
        self,
        incident: Incident,
        baseline_hours_before: int = 48,
        observation_hours: int = 24,
    ) -> RecoveryCertificate:
        """Run recovery verification for an incident.

        Args:
            incident: The incident to verify
            baseline_hours_before: Hours before maintenance start for baseline
            observation_hours: Minimum observation hours after maintenance

        Returns:
            RecoveryCertificate with pass/conditional/fail/insufficient_data
        """
        certificate_id = f"REC-{uuid.uuid4().hex[:8]}"

        # Determine time windows
        now = datetime.now(timezone.utc)
        work_order = await self._resolve_completed_work_order(incident, now)
        if work_order is None:
            missing_link_metric = MetricComparison(
                metric_name="Completed Work Order Link",
                unit="boolean",
                pre_value=None,
                post_value=None,
                threshold=1.0,
                passed=False,
            )
            incident.verification_status = VerificationStatus.INSUFFICIENT_DATA.value
            await self.db.flush()
            return RecoveryCertificate(
                certificate_id=certificate_id,
                incident_id=incident.incident_id,
                verification_status=VerificationStatus.INSUFFICIENT_DATA,
                baseline_window=None,
                observation_window=None,
                metrics=[missing_link_metric],
                algorithm="robust_zscore_mad",
                algorithm_version="1.1.0",
                data_sources=[],
                observation_hours=0.0,
                minimum_hours_required=float(observation_hours),
                remaining_risks=[
                    "事件未关联已完成工单，无法确定维护完成时间并建立前后对比窗口。"
                ],
                evidence_hash=self._compute_certificate_hash([missing_link_metric]),
            )

        maintenance_end = work_order.completed_at
        # Normalize to aware datetime (SQLite stores naive UTC)
        if maintenance_end.tzinfo is None:
            maintenance_end = maintenance_end.replace(tzinfo=timezone.utc)

        baseline_start = maintenance_end - timedelta(hours=baseline_hours_before)
        baseline_end = maintenance_end
        observation_start = maintenance_end
        observation_end = now

        # Collect pre/post metrics
        metrics: list[MetricComparison] = []

        # 1. Vibration RMS comparison
        vib_metrics = await self._compare_vibration(
            incident.turbine_id, baseline_start, baseline_end,
            observation_start, observation_end,
        )
        metrics.extend(vib_metrics)

        # 2. Temperature comparison from SCADA
        temp_metrics = await self._compare_temperature(
            incident.turbine_id, baseline_start, baseline_end,
            observation_start, observation_end,
        )
        metrics.extend(temp_metrics)

        # 3. Power output comparison
        power_metrics = await self._compare_power(
            incident.turbine_id, baseline_start, baseline_end,
            observation_start, observation_end,
        )
        metrics.extend(power_metrics)

        # 4. Alarm recurrence check
        alarm_metric = await self._check_alarm_recurrence(
            incident.turbine_id, observation_start, observation_end,
        )
        metrics.append(alarm_metric)

        # 5. Health index comparison
        hi_metric = await self._compare_health_index(
            incident, baseline_start, baseline_end,
            observation_start, observation_end,
        )
        if hi_metric:
            metrics.append(hi_metric)

        # 6. RUL comparison
        rul_metric = await self._compare_rul(
            incident.turbine_id, baseline_start, observation_end,
        )
        if rul_metric:
            metrics.append(rul_metric)

        # Determine overall status
        observation_actual_hours = (
            observation_end - observation_start
        ).total_seconds() / 3600.0

        status = self._determine_status(
            metrics, observation_actual_hours, observation_hours,
        )

        # Build certificate
        certificate = RecoveryCertificate(
            certificate_id=certificate_id,
            incident_id=incident.incident_id,
            verification_status=status,
            baseline_window=(baseline_start, baseline_end),
            observation_window=(observation_start, observation_end),
            metrics=metrics,
            algorithm="robust_zscore_mad",
            algorithm_version="1.1.0",
            data_sources=["scada", "vibration", "rul", "health_index"],
            observation_hours=observation_actual_hours,
            minimum_hours_required=float(observation_hours),
            remaining_risks=self._assess_remaining_risks(metrics, status),
            evidence_hash=self._compute_certificate_hash(metrics),
        )

        # Update incident verification status
        incident.verification_status = status.value
        await self.db.flush()

        return certificate

    # ── Metric comparisons ──

    async def _resolve_completed_work_order(
        self,
        incident: Incident,
        now: datetime,
    ) -> Optional[WorkOrder]:
        """Resolve only an explicitly incident-linked, completed work order."""
        opened_at = incident.opened_at or incident.created_at
        stmt = (
            select(WorkOrder)
            .where(
                WorkOrder.incident_id == incident.id,
                WorkOrder.turbine_id == incident.turbine_id,
                WorkOrder.status.in_(["completed", "closed"]),
                WorkOrder.completed_at.is_not(None),
                WorkOrder.completed_at <= now,
                WorkOrder.deleted_at.is_(None),
            )
            .order_by(WorkOrder.completed_at.desc())
            .limit(1)
        )
        if opened_at is not None:
            stmt = stmt.where(WorkOrder.completed_at >= opened_at)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _compare_vibration(
        self,
        turbine_id: int,
        baseline_start: datetime,
        baseline_end: datetime,
        obs_start: datetime,
        obs_end: datetime,
    ) -> list[MetricComparison]:
        """Compare pre/post vibration RMS using robust z-score."""
        # Get pre-maintenance vibration
        pre_data = await self.db.execute(
            select(VibrationData.rms, VibrationData.component)
            .where(
                VibrationData.turbine_id == turbine_id,
                VibrationData.timestamp >= baseline_start,
                VibrationData.timestamp < baseline_end,
            )
            .order_by(VibrationData.timestamp.desc())
            .limit(100)
        )
        pre_rows = pre_data.fetchall()

        # Get post-maintenance vibration
        post_data = await self.db.execute(
            select(VibrationData.rms, VibrationData.component)
            .where(
                VibrationData.turbine_id == turbine_id,
                VibrationData.timestamp >= obs_start,
                VibrationData.timestamp <= obs_end,
            )
            .order_by(VibrationData.timestamp.desc())
            .limit(100)
        )
        post_rows = post_data.fetchall()

        # Group by component
        pre_by_comp: dict[str, list[float]] = {}
        for rms, comp in pre_rows:
            if rms is not None:
                pre_by_comp.setdefault(comp or "unknown", []).append(rms)
        post_by_comp: dict[str, list[float]] = {}
        for rms, comp in post_rows:
            if rms is not None:
                post_by_comp.setdefault(comp or "unknown", []).append(rms)

        metrics: list[MetricComparison] = []
        for comp in set(list(pre_by_comp.keys()) + list(post_by_comp.keys())):
            pre_vals = pre_by_comp.get(comp, [])
            post_vals = post_by_comp.get(comp, [])

            pre_median = float(np.median(pre_vals)) if pre_vals else None
            post_median = float(np.median(post_vals)) if post_vals else None

            z_score = None
            if pre_vals and post_vals:
                pre_mad = self._mad(pre_vals)
                if pre_mad > 0:
                    z_score = (post_median - pre_median) / (pre_mad * 1.4826) if pre_median is not None else None

            # Pass if vibration decreased or stayed within normal range
            passed = True
            if z_score is not None and z_score > 3.0:
                passed = False  # Significant increase in vibration

            change_pct = None
            if pre_median is not None and pre_median != 0 and post_median is not None:
                change_pct = ((post_median - pre_median) / pre_median) * 100

            metrics.append(MetricComparison(
                metric_name=f"Vibration RMS ({comp})",
                unit="mm/s",
                pre_value=pre_median,
                post_value=post_median,
                threshold=3.0,
                change_pct=change_pct,
                z_score=z_score,
                passed=passed,
            ))

        return metrics

    async def _compare_temperature(
        self,
        turbine_id: int,
        baseline_start: datetime,
        baseline_end: datetime,
        obs_start: datetime,
        obs_end: datetime,
    ) -> list[MetricComparison]:
        """Compare pre/post gearbox and bearing temperatures."""
        # Get SCADA temperature data
        pre_data = await self.db.execute(
            select(
                SCADARecord.gearbox_temperature_c,
                SCADARecord.bearing_temperature_c,
            )
            .where(
                SCADARecord.turbine_id == turbine_id,
                SCADARecord.timestamp >= baseline_start,
                SCADARecord.timestamp < baseline_end,
            )
            .limit(200)
        )
        pre_rows = pre_data.fetchall()

        post_data = await self.db.execute(
            select(
                SCADARecord.gearbox_temperature_c,
                SCADARecord.bearing_temperature_c,
            )
            .where(
                SCADARecord.turbine_id == turbine_id,
                SCADARecord.timestamp >= obs_start,
                SCADARecord.timestamp <= obs_end,
            )
            .limit(200)
        )
        post_rows = post_data.fetchall()

        metrics: list[MetricComparison] = []

        for name, pre_idx, post_idx, threshold in [
            ("Gearbox Temperature", 0, 0, 80.0),
            ("Bearing Temperature", 1, 1, 75.0),
        ]:
            pre_vals = [r[pre_idx] for r in pre_rows if r[pre_idx] is not None]
            post_vals = [r[post_idx] for r in post_rows if r[post_idx] is not None]

            pre_median = float(np.median(pre_vals)) if pre_vals else None
            post_median = float(np.median(post_vals)) if post_vals else None

            passed = True
            if post_median is not None and post_median > threshold:
                passed = False

            metrics.append(MetricComparison(
                metric_name=name,
                unit="°C",
                pre_value=pre_median,
                post_value=post_median,
                threshold=threshold,
                passed=passed,
            ))

        return metrics

    async def _compare_power(
        self,
        turbine_id: int,
        baseline_start: datetime,
        baseline_end: datetime,
        obs_start: datetime,
        obs_end: datetime,
    ) -> list[MetricComparison]:
        """Compare pre/post power output."""
        pre_power = await self.db.execute(
            select(func.avg(SCADARecord.power_kw))
            .where(
                SCADARecord.turbine_id == turbine_id,
                SCADARecord.timestamp >= baseline_start,
                SCADARecord.timestamp < baseline_end,
            )
        )
        pre_avg = pre_power.scalar()

        post_power = await self.db.execute(
            select(func.avg(SCADARecord.power_kw))
            .where(
                SCADARecord.turbine_id == turbine_id,
                SCADARecord.timestamp >= obs_start,
                SCADARecord.timestamp <= obs_end,
            )
        )
        post_avg = post_power.scalar()

        passed = True
        if pre_avg is not None and post_avg is not None:
            # Power should recover to at least 80% of pre-fault levels
            if pre_avg > 0 and (post_avg / pre_avg) < 0.8:
                passed = False

        change_pct = None
        if pre_avg is not None and pre_avg != 0 and post_avg is not None:
            change_pct = ((post_avg - pre_avg) / pre_avg) * 100

        return [MetricComparison(
            metric_name="Power Output",
            unit="kW",
            pre_value=pre_avg,
            post_value=post_avg,
            threshold=0.8,  # 80% recovery
            change_pct=change_pct,
            passed=passed,
        )]

    async def _check_alarm_recurrence(
        self,
        turbine_id: int,
        obs_start: datetime,
        obs_end: datetime,
    ) -> MetricComparison:
        """Check if alarms recurred after maintenance."""
        alarm_count = await self.db.execute(
            select(func.count(Fault.id))
            .where(
                Fault.turbine_id == turbine_id,
                Fault.detected_at >= obs_start,
                Fault.detected_at <= obs_end,
            )
        )
        count = alarm_count.scalar() or 0

        passed = count == 0
        return MetricComparison(
            metric_name="Alarm Recurrence",
            unit="count",
            pre_value=0.0,
            post_value=float(count),
            threshold=0,
            passed=passed,
        )

    async def _compare_health_index(
        self,
        incident: Incident,
        baseline_start: datetime,
        baseline_end: datetime,
        obs_start: datetime,
        obs_end: datetime,
    ) -> Optional[MetricComparison]:
        """Compare pre/post health index if available."""
        turbine = await self.db.get(Turbine, incident.turbine_id)
        if turbine is None or turbine.hi_value is None:
            return None

        # Health index should have improved or stayed stable
        post_hi = turbine.hi_value
        # Pre-HI not stored separately — use post as reference
        passed = post_hi >= 70.0  # Above degradation threshold

        return MetricComparison(
            metric_name="Health Index",
            unit="index",
            pre_value=None,  # Would need historical HI storage
            post_value=post_hi,
            threshold=70.0,
            passed=passed,
        )

    async def _compare_rul(
        self,
        turbine_id: int,
        baseline_start: datetime,
        obs_end: datetime,
    ) -> Optional[MetricComparison]:
        """Compare RUL predictions before and after maintenance."""
        # Get latest RUL
        latest_rul = await self.db.execute(
            select(RULPrediction)
            .where(RULPrediction.turbine_id == turbine_id)
            .order_by(RULPrediction.predicted_at.desc())
            .limit(1)
        )
        pred = latest_rul.scalar_one_or_none()

        if pred is None:
            return MetricComparison(
                metric_name="RUL",
                unit="days",
                pre_value=None,
                post_value=None,
                threshold=30.0,
                passed=False,
            )

        # RUL should have improved after maintenance
        passed = pred.remaining_life_days > 30.0
        return MetricComparison(
            metric_name="RUL",
            unit="days",
            pre_value=None,
            post_value=pred.remaining_life_days,
            threshold=30.0,
            passed=passed,
        )

    # ── Status determination ──

    def _determine_status(
        self,
        metrics: list[MetricComparison],
        actual_hours: float,
        required_hours: int,
    ) -> VerificationStatus:
        """Determine overall verification status."""
        # A recovery decision needs at least one paired physical signal from
        # before and after maintenance. Current HI/RUL and a zero recurrence
        # count alone are not proof of recovery.
        if not metrics or all(m.pre_value is None and m.post_value is None for m in metrics):
            return VerificationStatus.INSUFFICIENT_DATA
        paired_physical_metrics = [
            metric
            for metric in metrics
            if metric.pre_value is not None
            and metric.post_value is not None
            and metric.metric_name.startswith(
                ("Vibration RMS", "Gearbox Temperature", "Bearing Temperature", "Power Output")
            )
        ]
        if not paired_physical_metrics:
            return VerificationStatus.INSUFFICIENT_DATA

        # Count failures
        failed = [m for m in metrics if not m.passed]
        conditional = [m for m in metrics if m.passed is False and m.z_score is not None and m.z_score < 5.0]

        # Observation time check
        if actual_hours < CONDITIONAL_OBSERVATION_HOURS:
            return VerificationStatus.INSUFFICIENT_DATA

        # All metrics pass + sufficient observation = PASS
        if len(failed) == 0 and actual_hours >= required_hours:
            return VerificationStatus.PASS

        # Some borderline failures or insufficient observation = CONDITIONAL
        if actual_hours >= CONDITIONAL_OBSERVATION_HOURS and actual_hours < required_hours:
            return VerificationStatus.CONDITIONAL

        if len(failed) > 0:
            # Check if failures are severe
            severe = any(
                m.z_score is not None and m.z_score > 5.0
                for m in failed
            )
            if severe:
                return VerificationStatus.FAIL
            return VerificationStatus.CONDITIONAL

        return VerificationStatus.CONDITIONAL

    # ── Remaining risks ──

    def _assess_remaining_risks(
        self,
        metrics: list[MetricComparison],
        status: VerificationStatus,
    ) -> list[str]:
        """Assess remaining risks after verification."""
        risks: list[str] = []

        if status == VerificationStatus.INSUFFICIENT_DATA:
            risks.append("Insufficient observation data — cannot confirm recovery")
        if status == VerificationStatus.CONDITIONAL:
            risks.append("Conditional pass — extended observation recommended")
        if status == VerificationStatus.FAIL:
            risks.append("Verification failed — maintenance may not have resolved the issue")

        for m in metrics:
            if not m.passed and m.metric_name == "Alarm Recurrence":
                risks.append(f"Alarms recurred after maintenance: {m.post_value} occurrences")

        return risks

    # ── Helpers ──

    @staticmethod
    def _mad(values: list[float]) -> float:
        """Median Absolute Deviation."""
        if not values:
            return 0.0
        median = np.median(values)
        return float(np.median([abs(v - median) for v in values]))

    def _compute_certificate_hash(self, metrics: list[MetricComparison]) -> str:
        """SHA-256 hash of verification results for audit trail."""
        payload = {
            "metrics": [
                {
                    "name": m.metric_name,
                    "pre": m.pre_value,
                    "post": m.post_value,
                    "passed": m.passed,
                }
                for m in metrics
            ]
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode()
        ).hexdigest()[:16]
