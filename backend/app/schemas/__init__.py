import re

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime


EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_format(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    cleaned = value.strip()
    if not cleaned or not EMAIL_PATTERN.fullmatch(cleaned):
        raise ValueError("Invalid email format")
    return cleaned


# --- Auth ---
class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str
    password: str = Field(min_length=6)
    role: str = "viewer"

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_format(value) or value

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    has_api_key: bool = False
    api_provider: Optional[str] = None
    api_base_url: Optional[str] = None
    model_preference: str
    is_active: bool

    model_config = {"from_attributes": True, "protected_namespaces": ()}

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


# --- Turbine ---
class TurbineResponse(BaseModel):
    id: int
    name: str
    model: Optional[str] = None
    power_mw: Optional[float] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    region: Optional[str] = None
    status: str
    hi_value: float
    last_maintenance: Optional[datetime] = None
    source_dataset: Optional[str] = None
    source_asset_id: Optional[str] = None
    asset_scope: str = "field_asset"
    geo_scope: str = "known"

    model_config = {"from_attributes": True}

class TurbineListResponse(BaseModel):
    turbines: list[TurbineResponse]
    total: int
    healthy: int
    warning: int
    faulty: int

class SCADADataPoint(BaseModel):
    timestamp: datetime
    power_kw: Optional[float] = None
    wind_speed_ms: Optional[float] = None
    rotor_rpm: Optional[float] = None
    gen_temperature_c: Optional[float] = None
    gearbox_temperature_c: Optional[float] = None
    pitch_angle_deg: Optional[float] = None


# --- Diagnosis ---
class FaultResponse(BaseModel):
    id: int
    turbine_id: int
    turbine_name: str = ""
    turbine_region: str = ""
    detected_at: datetime
    discovered_at: Optional[datetime] = None
    processing_started_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    failed_at: Optional[datetime] = None
    handler: Optional[str] = None
    processing_status: str = "pending"
    priority: str = "medium"
    work_order_id: Optional[int] = None
    work_order_title: Optional[str] = None
    last_action_at: Optional[datetime] = None
    maintenance_cost_estimate: Optional[float] = None
    maintenance_cost_actual: Optional[float] = None
    status_note: str = ""
    fault_type: str
    confidence: float
    status: str
    details: Optional[dict] = None

    model_config = {"from_attributes": True}

class FaultSignalResponse(BaseModel):
    id: int
    sensor_name: str
    contribution_score: float
    priority: str

    model_config = {"from_attributes": True}

class DiagnosisSignalInsight(BaseModel):
    sensor_name: str
    value: str
    normal_range: str
    contribution_score: float
    priority: str
    finding: str

class TroubleshootingStep(BaseModel):
    order: int
    title: str
    action: str
    expected_effect: str

class FaultDetailResponse(FaultResponse):
    signals: list[FaultSignalResponse] = []
    signal_insights: list[DiagnosisSignalInsight] = []
    troubleshooting_steps: list[TroubleshootingStep] = []

class AutoFaultDetectionRequest(BaseModel):
    turbine_id: int
    component: str = "gearbox_high_speed"
    window_hours: int = Field(default=24, ge=1, le=168)
    data_source: str = "vibration"

class AutoFaultDetectionResponse(BaseModel):
    turbine_id: int
    component: str
    analysis_window_hours: int
    status: str
    fault_type: str
    confidence: float
    confidence_interval: list[float]
    algorithm_status: str
    message: str
    generated_at: datetime
    signals: list[DiagnosisSignalInsight] = []
    troubleshooting_steps: list[TroubleshootingStep] = []

class BatchAutoFaultDetectionRequest(BaseModel):
    turbine_ids: list[int] = []
    region: Optional[str] = None
    status: Optional[str] = None
    component: str = "gearbox_high_speed"
    window_hours: int = Field(default=24, ge=1, le=168)
    data_source: str = "vibration"

class BatchAutoFaultRecord(BaseModel):
    record_id: str
    turbine_id: int
    turbine_name: str
    region: str
    turbine_status: str
    component: str
    analysis_window_hours: int
    status: str
    fault_type: str
    confidence: float
    confidence_interval: list[float]
    algorithm_status: str
    message: str
    generated_at: datetime
    group_key: str
    signals: list[DiagnosisSignalInsight] = []
    troubleshooting_steps: list[TroubleshootingStep] = []

class BatchAutoFaultDetectionResponse(BaseModel):
    success: bool
    total: int
    generated_at: datetime
    records: list[BatchAutoFaultRecord] = []
    group_summary: dict[str, int] = {}
    message: str

class VibrationPreviewResponse(BaseModel):
    turbine_id: int
    component: str
    timestamp: datetime
    duration_seconds: float
    sample_rate_hz: int
    sample_count: Optional[int] = None
    rms: float
    waveform: list[float]
    spectrum: list[float]
    peak_frequencies: list[dict]
    fault_detected: bool
    quality: Optional[dict] = None
    source_dataset: Optional[str] = None
    data_source: Optional[str] = None
    waveform_path: Optional[str] = None
    peak_freq_hz: Optional[float] = None
    algorithm_status: str
    message: str

class BladeDiagnosisRequest(BaseModel):
    turbine_id: int = Field(gt=0)
    image_path: str = ""

class BladeDiagnosisResponse(BaseModel):
    turbine_id: int
    damage_type: str
    confidence: Optional[float] = None
    damage_bbox: Optional[dict] = None
    image_path: str
    image_url: Optional[str] = None
    severity: str = "normal"
    recommended_action: str = ""
    evidence: list[str] = []
    quality: Optional[dict] = None
    algorithm_status: str = "stub_pending_external_model"
    message: str = ""
    damage_regions: list[dict] = []
    troubleshooting_steps: list[TroubleshootingStep] = []


# --- Prediction ---
class RULResponse(BaseModel):
    turbine_id: int
    turbine_name: str = ""
    component: str
    remaining_life_days: float
    confidence_lower: float
    confidence_upper: float
    predicted_at: datetime

class RULListResponse(BaseModel):
    predictions: list[RULResponse]

class CostComparisonRequest(BaseModel):
    turbine_id: int = Field(gt=0)
    fault_type: str = Field(min_length=1, max_length=64)

class CostComparisonResponse(BaseModel):
    immediate_repair_cost: float
    delayed_repair_cost: float
    downtime_loss_per_day: float
    failure_probability: float
    recommendation: str
    optimal_window_days: int
    risk_level: str
    estimated_saving: float
    cost_drivers: list[str]


# --- WorkOrder ---
class WorkOrderCreate(BaseModel):
    turbine_id: int = Field(gt=0)
    fault_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=128)
    description: Optional[str] = None
    assignee: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_email: Optional[str] = None
    priority: Optional[str] = "medium"
    fault_type: Optional[str] = None
    due_date: Optional[datetime] = None
    cost_estimate: float = Field(default=0.0, ge=0)

class WorkOrderUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    assignee: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_email: Optional[str] = None
    priority: Optional[str] = None
    fault_type: Optional[str] = None
    due_date: Optional[datetime] = None
    cost_estimate: Optional[float] = None
    cost_actual: Optional[float] = None
    downtime_hours: Optional[float] = None

class WorkOrderEmailRequest(BaseModel):
    recipient_user_ids: list[int] = []
    recipient_emails: list[str] = []
    subject: Optional[str] = None
    content: Optional[str] = None
    use_preview_template: bool = True

class MaintenanceRecordCreate(BaseModel):
    action_type: str = Field(default="progress", min_length=1, max_length=32)
    content: Optional[str] = None
    status: Optional[str] = None

class MaintenanceRecordResponse(BaseModel):
    id: int
    work_order_id: int
    operator_id: Optional[int] = None
    action_type: str
    content: Optional[str] = None
    before_status: Optional[str] = None
    after_status: Optional[str] = None
    extra: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}

class NotificationLogResponse(BaseModel):
    id: int
    work_order_id: Optional[int] = None
    recipient_email: str
    subject: Optional[str] = None
    channel: str
    status: str
    error_message: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}

class WorkOrderResponse(BaseModel):
    id: int
    turbine_id: int
    fault_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    status: str
    priority: Optional[str] = None
    fault_type: Optional[str] = None
    due_date: Optional[datetime] = None
    assignee_id: Optional[int] = None
    assignee: Optional[str] = None
    assignee_email: Optional[str] = None
    cost_estimate: float
    cost_actual: Optional[float] = None
    downtime_hours: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    notification_sent_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class WorkOrderDetailResponse(WorkOrderResponse):
    records: list[MaintenanceRecordResponse] = []
    notification_logs: list[NotificationLogResponse] = []


# --- Settings ---
class ThresholdConfigRequest(BaseModel):
    hi_threshold: float = Field(ge=0, le=100)
    email_enabled: bool = False
    email_address: Optional[str] = None

    @field_validator("email_address")
    @classmethod
    def validate_email_address(cls, value: Optional[str]) -> Optional[str]:
        return validate_email_format(value) if value else None

class ThresholdConfigResponse(BaseModel):
    id: int
    hi_threshold: float
    email_enabled: bool
    email_address: Optional[str] = None

    model_config = {"from_attributes": True}


class ThresholdAlertTurbine(BaseModel):
    id: int
    name: str
    region: Optional[str] = None
    status: str
    hi_value: float
    model: Optional[str] = None


class ThresholdAlertStatus(BaseModel):
    threshold: float
    low_count: int
    turbines: list[ThresholdAlertTurbine]
    email_enabled: bool
    email_address: Optional[str] = None
    checked_at: datetime


class OperationLogCreate(BaseModel):
    page: str = Field(default="system-settings", min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=128)
    result: Optional[str] = Field(default=None, max_length=512)
    level: str = Field(default="info", max_length=16)


class OperationLogResponse(BaseModel):
    id: int
    page: str
    action: str
    result: Optional[str] = None
    level: str
    created_at: datetime

    model_config = {"from_attributes": True}

class DataSourceResponse(BaseModel):
    id: int
    source_type: str
    name: str
    status: str
    last_connected_at: Optional[datetime] = None
    last_data_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class DataSourceTestRequest(BaseModel):
    source_type: str = Field(min_length=1, max_length=32)
    connection_params: dict = Field(default_factory=dict)

class ProfileUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_provider: Optional[str] = None
    api_base_url: Optional[str] = Field(default=None, max_length=512)
    model_preference: Optional[str] = Field(default=None, max_length=128)

    model_config = {"protected_namespaces": ()}


class AITestConnectionRequest(BaseModel):
    api_key: str
    model: str
    base_url: str


class AIProviderConfigCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    display_name: Optional[str] = Field(default=None, max_length=128)
    api_key: Optional[str] = Field(default=None, max_length=512)
    base_url: str = Field(min_length=1, max_length=512)
    api_style: str = Field(default="openai", max_length=32)
    default_model: Optional[str] = Field(default=None, max_length=128)
    model_options: list[str] = Field(default_factory=list)
    enabled: bool = True

    model_config = {"protected_namespaces": ()}


class AIProviderConfigResponse(BaseModel):
    id: int
    provider: str
    display_name: Optional[str] = None
    base_url: str
    api_style: str
    default_model: Optional[str] = None
    model_options: list[str] = Field(default_factory=list)
    enabled: bool
    has_api_key: bool = False
    last_test_status: Optional[str] = None
    last_test_message: Optional[str] = None
    last_test_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class AIProviderTestRequest(BaseModel):
    model: Optional[str] = Field(default=None, max_length=128)

    model_config = {"protected_namespaces": ()}


# --- AI ---
class AISummaryRequest(BaseModel):
    page_type: str = Field(min_length=1, max_length=64)
    page_data: dict = Field(default_factory=dict)
    turbine_id: Optional[int] = Field(default=None, gt=0)
    provider_config_id: Optional[int] = Field(default=None, gt=0)
    model: Optional[str] = Field(default=None, max_length=128)

    model_config = {"protected_namespaces": ()}

class AISummaryResponse(BaseModel):
    conclusions: list[str]
    suggestions: list[str]
    status: str = "success"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    model_status: Optional[dict] = None
    warnings: list[str] = Field(default_factory=list)
    provider: Optional[str] = None
    api_provider: Optional[str] = None
    model: Optional[str] = None
    label: Optional[str] = None
    mode: Optional[str] = None
    billing: Optional[str] = None
    requires_api_key: Optional[bool] = None
    has_api_key: Optional[bool] = None

    model_config = {"protected_namespaces": ()}

class AIFaultAnalysisRequest(BaseModel):
    turbine_id: int = Field(gt=0)
    fault_type: str = Field(min_length=1, max_length=64)

class AnomalyItem(BaseModel):
    indicator: str
    value: str
    normal: str
    deviation: str
    level: str

class AIFaultAnalysisResponse(BaseModel):
    turbine_name: str
    fault_type: str
    diagnosis: str
    anomalies: list[AnomalyItem]

class AICopilotRequest(BaseModel):
    messages: list[dict] = Field(min_length=1)
    page_context: Optional[dict] = None
    knowledge_results: Optional[list[str]] = None
    screenshot: Optional[str] = None  # base64-encoded JPEG screenshot of current page
    selected_contexts: list[str] = Field(default_factory=list)
    session_id: Optional[str] = Field(default=None, max_length=128)
    provider_config_id: Optional[int] = Field(default=None, gt=0)
    model: Optional[str] = Field(default=None, max_length=128)
    session_title_needed: bool = False

    model_config = {"protected_namespaces": ()}

class AICopilotResponse(BaseModel):
    reply: str
    status: str = "success"
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    model_status: Optional[dict] = None
    warnings: list[str] = Field(default_factory=list)
    session_title: Optional[str] = None
    context_sources: list[dict] = Field(default_factory=list)

    model_config = {"protected_namespaces": ()}


# --- Personnel ---
class PersonnelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=128)
    skills: list[str] = Field(default_factory=list)
    region: str = Field(default="陕北", max_length=32)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_format(value) or value

class PersonnelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    email: Optional[str] = Field(default=None, min_length=3, max_length=128)
    skills: Optional[list[str]] = None
    region: Optional[str] = Field(default=None, max_length=32)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: Optional[str]) -> Optional[str]:
        return validate_email_format(value) if value else None

class PersonnelResponse(BaseModel):
    id: int
    name: str
    skills: list[str]
    region: str
    load: int
    email: str


# --- Agent Execute ---
class AgentExecuteRequest(BaseModel):
    command: str = Field(min_length=1, max_length=512)
    current_page: Optional[str] = None
    dry_run: bool = False

class AgentAtomicStep(BaseModel):
    order: int
    skill: str
    params: dict = Field(default_factory=dict)
    reason: str = ""

class AgentSceneSkill(BaseModel):
    skill: str
    params: dict = Field(default_factory=dict)

class AgentExecuteResponse(BaseModel):
    intent_type: str
    confidence: float
    entities: dict = Field(default_factory=dict)
    scene_skills: list[AgentSceneSkill] = Field(default_factory=list)
    atomic_steps: list[AgentAtomicStep] = Field(default_factory=list)
    explanation: str = ""
    follow_up_analysis: Optional[str] = None
    requires_clarification: bool = False
    clarification_question: Optional[str] = None


# --- Agent Action Gateway ---
class AgentActionPlanRequest(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    page_context: dict = Field(default_factory=dict)


class AgentActionConfirmation(BaseModel):
    title: str
    summary: str
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AgentActionPlanResponse(BaseModel):
    status: str
    task_type: Optional[str] = None
    workflow: Optional[str] = None
    request_id: Optional[str] = None
    action: Optional[str] = None
    confidence: float = 0.0
    confirmation: Optional[AgentActionConfirmation] = None
    missing_slots: list[str] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class AgentActionConfirmResponse(BaseModel):
    request_id: str
    action: str
    status: str
    result: Optional[dict] = None
    display: Optional[dict] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# --- Unified Agent Task Planner ---
class AgentTaskPlanRequest(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    page_context: dict = Field(default_factory=dict)
    plan_id: Optional[str] = None
    provider_config_id: Optional[int] = Field(default=None, gt=0)
    model: Optional[str] = Field(default=None, max_length=128)

    model_config = {"protected_namespaces": ()}


class AgentTaskStep(BaseModel):
    order: int
    step: str
    type: str = "read"
    status: str = "planned"
    description: str = ""


class AgentTaskCandidate(BaseModel):
    id: str
    name: str = ""
    category: str = ""
    implementation_status: Optional[str] = None
    task_kind: str = ""
    score: Optional[int] = None


class AgentTaskPlanResponse(BaseModel):
    status: str
    task_type: Optional[str] = None
    task_kind: Optional[str] = None
    planner_source: Optional[str] = None
    plan_id: Optional[str] = None
    playbook_id: Optional[str] = None
    workflow: Optional[str] = None
    action: Optional[str] = None
    request_id: Optional[str] = None
    confidence: float = 0.0
    answer: Optional[str] = None
    slots: dict = Field(default_factory=dict)
    steps: list[AgentTaskStep] = Field(default_factory=list)
    candidates: list[AgentTaskCandidate] = Field(default_factory=list)
    display: Optional[dict] = None
    confirmation: Optional[AgentActionConfirmation] = None
    missing_slots: list[str] = Field(default_factory=list)
    clarification_question: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class AgentTaskCancelResponse(BaseModel):
    plan_id: str
    status: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# Phase 4: Innovation schemas
# ═══════════════════════════════════════════════════════════════

# ── 4.1 Incident ──

class IncidentCreate(BaseModel):
    turbine_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=256)
    severity: str = Field(default="medium", max_length=16)
    summary: Optional[str] = None


class IncidentUpdate(BaseModel):
    title: Optional[str] = None
    severity: Optional[str] = None
    stage: Optional[str] = None
    status: Optional[str] = None
    owner_id: Optional[int] = None
    summary: Optional[str] = None
    resolution: Optional[str] = None


class IncidentStageTransition(BaseModel):
    target_stage: str = Field(min_length=1, max_length=32)
    note: Optional[str] = None


class IncidentResponse(BaseModel):
    id: int
    incident_id: str
    turbine_id: int
    turbine_name: str = ""
    title: str
    severity: str
    stage: str
    status: str
    owner_id: Optional[int] = None
    verification_status: Optional[str] = None
    alarm_count: int = 0
    compressed_count: int = 0
    trace_id: Optional[str] = None
    summary: Optional[str] = None
    resolution: Optional[str] = None
    opened_at: datetime
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── 4.2 Alarm ──

class AlarmResponse(BaseModel):
    id: int
    incident_id: int
    turbine_id: int
    fault_id: Optional[int] = None
    source: str
    alarm_type: str
    component: Optional[str] = None
    severity: str
    message: Optional[str] = None
    value: Optional[float] = None
    threshold: Optional[float] = None
    is_primary: bool = False
    compression_rule: Optional[str] = None
    compressed: bool = False
    fired_at: datetime

    model_config = {"from_attributes": True}


class AlarmClusterRequest(BaseModel):
    turbine_id: int = Field(gt=0)
    window_minutes: int = Field(default=15, ge=1, le=120)


class AlarmClusterResponse(BaseModel):
    incident_id: str
    primary_alarm: Optional[AlarmResponse] = None
    total_alarms: int
    compressed_alarms: int
    compression_rules: list[str] = Field(default_factory=list)
    alarms: list[AlarmResponse] = Field(default_factory=list)


# ── 4.3 Evidence Graph ──

class EvidenceNodeCreate(BaseModel):
    node_type: str = Field(min_length=1, max_length=32)
    label: str = Field(min_length=1, max_length=256)
    description: Optional[str] = None
    source: str = Field(default="rule", max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)
    props: Optional[dict] = None


class EvidenceEdgeCreate(BaseModel):
    source_node_id: int = Field(gt=0)
    target_node_id: int = Field(gt=0)
    edge_type: str = Field(min_length=1, max_length=32)
    source: str = Field(default="rule", max_length=32)
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_ref: Optional[str] = None


class EvidenceNodeResponse(BaseModel):
    id: int
    incident_id: int
    node_type: str
    label: str
    description: Optional[str] = None
    source: str
    confidence: float
    props: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceEdgeResponse(BaseModel):
    id: int
    incident_id: int
    source_node_id: int
    target_node_id: int
    edge_type: str
    source: str
    confidence: float
    evidence_ref: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class EvidenceGraphResponse(BaseModel):
    nodes: list[EvidenceNodeResponse] = Field(default_factory=list)
    edges: list[EvidenceEdgeResponse] = Field(default_factory=list)


# ── 4.4 Decision Sandbox ──

class DecisionPlanResponse(BaseModel):
    id: int
    incident_id: int
    plan_name: str
    strategy: str
    safety_risk: float
    downtime_loss: float
    repair_cost: float
    recovery_days: float
    personnel_available: bool
    parts_available: bool
    weather_compatible: bool
    total_score: float
    is_recommended: bool
    llm_explanation: Optional[str] = None
    decision_flip_point: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DecisionSandboxResponse(BaseModel):
    incident_id: str
    plans: list[DecisionPlanResponse] = Field(default_factory=list)
    recommended_index: int = -1


# ── 4.5 Policy ──

class PolicyRuleResponse(BaseModel):
    id: int
    rule_id: str
    description: str
    action_pattern: str
    risk_level: int
    rule_type: str
    is_active: bool
    version: str

    model_config = {"from_attributes": True}


class PolicyCheckRequest(BaseModel):
    action: str = Field(min_length=1, max_length=128)
    incident_id: Optional[int] = None
    context: dict = Field(default_factory=dict)


class PolicyCheckResponse(BaseModel):
    action: str
    decision: str  # allowed/denied/require_approval
    matched_rules: list[str] = Field(default_factory=list)
    reason: Optional[str] = None


# ── 4.6 Flight Recorder ──

class AgentSpanResponse(BaseModel):
    id: int
    trace_id: str
    parent_span_id: Optional[str] = None
    span_id: str
    span_name: str
    agent_name: Optional[str] = None
    tool_name: Optional[str] = None
    step_order: int
    input_digest: Optional[str] = None
    output_digest: Optional[str] = None
    status: str
    duration_ms: float
    policy_decision: Optional[str] = None
    approval_by: Optional[str] = None
    error_code: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AgentTraceResponse(BaseModel):
    id: int
    trace_id: str
    incident_id: Optional[int] = None
    user_id: Optional[int] = None
    status: str
    total_spans: int
    total_duration_ms: float
    token_usage: Optional[dict] = None
    cost_estimate: float
    error_code: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    spans: list[AgentSpanResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}
