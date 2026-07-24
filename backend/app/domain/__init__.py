"""Domain types for Incident state machine and evidence contracts.

Pure domain definitions — no database or HTTP dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
import uuid


# ═══════════════════════════════════════════════════════════════
# Incident state machine
# ═══════════════════════════════════════════════════════════════

class IncidentStage(str, Enum):
    DETECTED = "detected"
    CORRELATED = "correlated"
    DIAGNOSING = "diagnosing"
    DECISION_READY = "decision_ready"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


VALID_TRANSITIONS: dict[IncidentStage, set[IncidentStage]] = {
    IncidentStage.DETECTED: {IncidentStage.CORRELATED, IncidentStage.ESCALATED},
    IncidentStage.CORRELATED: {IncidentStage.DIAGNOSING, IncidentStage.ESCALATED},
    IncidentStage.DIAGNOSING: {IncidentStage.DECISION_READY, IncidentStage.ESCALATED},
    IncidentStage.DECISION_READY: {IncidentStage.AWAITING_APPROVAL, IncidentStage.EXECUTING, IncidentStage.ESCALATED},
    IncidentStage.AWAITING_APPROVAL: {IncidentStage.EXECUTING, IncidentStage.ESCALATED},
    IncidentStage.EXECUTING: {IncidentStage.VERIFYING, IncidentStage.ESCALATED},
    IncidentStage.VERIFYING: {IncidentStage.RESOLVED, IncidentStage.EXECUTING, IncidentStage.ESCALATED},
    IncidentStage.RESOLVED: set(),
    IncidentStage.ESCALATED: set(),
}


def can_transition(from_stage: str, to_stage: str) -> bool:
    """Check if stage transition is valid."""
    try:
        f = IncidentStage(from_stage)
        t = IncidentStage(to_stage)
        return t in VALID_TRANSITIONS.get(f, set())
    except ValueError:
        return False


# ═══════════════════════════════════════════════════════════════
# Evidence contract types
# ═══════════════════════════════════════════════════════════════

class EvidenceType(str, Enum):
    OBSERVATION = "observation"           # Direct sensor reading
    MODEL_PREDICTION = "model_prediction"  # ML model output
    RULE_INFERENCE = "rule_inference"     # Rule-based deduction
    LLM_HYPOTHESIS = "llm_hypothesis"     # LLM-generated hypothesis
    HUMAN_CONFIRMATION = "human_confirmation"  # Human verified
    CONFLICTING_EVIDENCE = "conflicting_evidence"  # Contradiction detected
    MISSING_EVIDENCE = "missing_evidence"  # Required but absent
    VERIFICATION_RESULT = "verification_result"  # Recovery verification


class EvidenceQuality(str, Enum):
    HIGH = "high"        # Direct measurement, calibrated sensor
    MEDIUM = "medium"    # Model output with known accuracy
    LOW = "low"          # Heuristic, LLM, or indirect inference
    UNKNOWN = "unknown"  # Cannot assess quality


@dataclass
class EvidenceContract:
    """Typed evidence item with traceability metadata."""
    id: str = field(default_factory=lambda: f"EVD-{uuid.uuid4().hex[:8]}")
    incident_id: str = ""
    evidence_type: EvidenceType = EvidenceType.OBSERVATION
    source_type: str = ""          # scada / vibration / model / rule_engine / llm / human
    source_id: str = ""            # Specific sensor, model version, user ID
    label: str = ""                # Human-readable label
    description: str = ""
    value: Optional[float] = None
    unit: str = ""
    confidence: float = 0.5        # 0.0–1.0
    quality: EvidenceQuality = EvidenceQuality.UNKNOWN
    collected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None  # Evidence freshness window
    content_hash: str = ""         # SHA-256 of data snapshot
    is_direct_observation: bool = False
    supports_hypothesis: list[str] = field(default_factory=list)    # Hypothesis IDs supported
    contradicts_hypothesis: list[str] = field(default_factory=list)  # Hypothesis IDs contradicted
    props: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvidenceCompletenessResult:
    """Result of evidence contract completeness check."""
    required_count: int = 0
    satisfied_count: int = 0
    completeness_ratio: float = 0.0
    missing_evidence: list[str] = field(default_factory=list)
    expired_evidence: list[str] = field(default_factory=list)
    conflicting_pairs: list[tuple[str, str]] = field(default_factory=list)
    can_confirm_diagnosis: bool = False
    recommendation: str = ""


# ═══════════════════════════════════════════════════════════════
# Decision twin types
# ═══════════════════════════════════════════════════════════════

class ConstraintStatus(str, Enum):
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    UNKNOWN = "unknown"


@dataclass
class ResourceSnapshot:
    """Snapshot of resource state at decision time."""
    # RUL
    rul_days: Optional[float] = None
    rul_lower: Optional[float] = None
    rul_upper: Optional[float] = None
    # Power / economics
    rated_power_kw: Optional[float] = None
    current_power_kw: Optional[float] = None
    electricity_price_cny_per_kwh: float = 0.52
    capacity_factor: float = 0.35
    # Fault
    fault_severity: str = "medium"
    fault_type: str = ""
    # Personnel
    personnel_available: list[dict[str, Any]] = field(default_factory=list)
    personnel_skills: list[str] = field(default_factory=list)
    # Spare parts
    spare_parts: list[dict[str, Any]] = field(default_factory=list)
    # Weather
    weather_windows: list[dict[str, Any]] = field(default_factory=list)
    weather_restrictions: list[str] = field(default_factory=list)
    # Work orders
    active_work_orders: list[dict[str, Any]] = field(default_factory=list)
    # History
    historical_success_rate: Optional[float] = None
    # Snapshot metadata
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data_quality: str = "partial"  # complete / partial / insufficient


@dataclass
class MaintenancePlan:
    """One maintenance plan alternative."""
    id: str = field(default_factory=lambda: f"PLAN-{uuid.uuid4().hex[:8]}")
    plan_name: str = ""
    strategy: str = ""  # immediate_repair / degraded_ops / monitor / inspect_first
    description: str = ""
    # Costs
    repair_cost: float = 0.0
    downtime_hours: float = 0.0
    downtime_loss: float = 0.0
    recovery_days: float = 0.0
    # Resource feasibility
    personnel_feasible: bool = False
    parts_feasible: bool = False
    weather_feasible: bool = False
    safety_risk: float = 0.0  # 0–100
    # Multi-criteria scores
    safety_score: float = 0.0
    economic_score: float = 0.0
    resource_score: float = 0.0
    recovery_time_score: float = 0.0
    executability_score: float = 0.0
    total_score: float = 0.0
    is_recommended: bool = False
    # Hard constraints
    infeasible_reasons: list[str] = field(default_factory=list)
    is_feasible: bool = True
    # Uncertainty
    score_confidence_interval: tuple[float, float] = (0.0, 0.0)
    sensitivity: dict[str, float] = field(default_factory=dict)
    flip_points: list[str] = field(default_factory=list)
    # Evidence
    llm_explanation: str = ""
    data_quality_warnings: list[str] = field(default_factory=list)


@dataclass
class DecisionTwinResult:
    """Complete decision twin output for an incident."""
    incident_id: str = ""
    resource_snapshot: ResourceSnapshot = field(default_factory=ResourceSnapshot)
    plans: list[MaintenancePlan] = field(default_factory=list)
    recommended_plan_id: str = ""
    insufficient_data: list[str] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seed: int = 42
    algorithm_version: str = "1.0.0"


# ═══════════════════════════════════════════════════════════════
# Investigation workflow types
# ═══════════════════════════════════════════════════════════════

class InvestigationStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    DEGRADED = "degraded"  # Completed with fallback (e.g., LLM→rules)


@dataclass
class InvestigationStep:
    """One step in the autonomous investigation workflow."""
    step_id: str
    step_name: str
    status: InvestigationStepStatus = InvestigationStepStatus.PENDING
    input_summary: str = ""
    output_summary: str = ""
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 3
    degraded: bool = False


@dataclass
class InvestigationWorkflow:
    """Resumable investigation workflow state."""
    workflow_id: str = field(default_factory=lambda: f"WF-{uuid.uuid4().hex[:12]}")
    incident_id: str = ""
    status: str = "pending"  # pending / running / paused / completed / failed
    steps: list[InvestigationStep] = field(default_factory=list)
    current_step_index: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


# ═══════════════════════════════════════════════════════════════
# Recovery verification types
# ═══════════════════════════════════════════════════════════════

class VerificationStatus(str, Enum):
    PASS = "pass"
    CONDITIONAL = "conditional"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class MetricComparison:
    """Pre/post maintenance metric comparison."""
    metric_name: str = ""
    unit: str = ""
    pre_value: Optional[float] = None
    post_value: Optional[float] = None
    threshold: Optional[float] = None
    change_pct: Optional[float] = None
    z_score: Optional[float] = None
    passed: bool = False


@dataclass
class RecoveryCertificate:
    """Issued after recovery verification."""
    certificate_id: str = field(default_factory=lambda: f"REC-{uuid.uuid4().hex[:8]}")
    incident_id: str = ""
    verification_status: VerificationStatus = VerificationStatus.INSUFFICIENT_DATA
    baseline_window: tuple[datetime, datetime] | None = None
    observation_window: tuple[datetime, datetime] | None = None
    metrics: list[MetricComparison] = field(default_factory=list)
    algorithm: str = "robust_zscore_mad"
    algorithm_version: str = "1.0.0"
    data_sources: list[str] = field(default_factory=list)
    observation_hours: float = 0.0
    minimum_hours_required: float = 24.0
    remaining_risks: list[str] = field(default_factory=list)
    evidence_hash: str = ""
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ═══════════════════════════════════════════════════════════════
# Audit chain types
# ═══════════════════════════════════════════════════════════════

@dataclass
class AuditEntry:
    """One entry in the signed audit chain."""
    seq: int = 0
    action_type: str = ""
    agent: str = ""
    input_hash: str = ""
    output_hash: str = ""
    decision: str = ""
    prev_hash: str = ""
    current_hash: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditChainVerification:
    """Result of audit chain integrity verification."""
    chain_valid: bool = False
    signature_valid: bool = False
    total_entries: int = 0
    first_broken_at: Optional[int] = None
    tampered_entries: list[int] = field(default_factory=list)
    root_hash: str = ""
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
