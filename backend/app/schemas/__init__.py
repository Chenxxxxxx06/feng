from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# --- Auth ---
class UserRegister(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str
    password: str = Field(min_length=6)
    role: str = "viewer"

class UserLogin(BaseModel):
    username: str
    password: str

class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    role: str
    api_key: Optional[str] = None
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
    wechat_enabled: bool = False

class ThresholdConfigResponse(BaseModel):
    id: int
    hi_threshold: float
    email_enabled: bool
    email_address: Optional[str] = None
    wechat_enabled: bool

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


# --- AI ---
class AISummaryRequest(BaseModel):
    page_type: str = Field(min_length=1, max_length=64)
    page_data: dict

class AISummaryResponse(BaseModel):
    conclusions: list[str]
    suggestions: list[str]
    provider: Optional[str] = None
    api_provider: Optional[str] = None
    model: Optional[str] = None
    label: Optional[str] = None
    mode: Optional[str] = None
    billing: Optional[str] = None
    requires_api_key: Optional[bool] = None
    has_api_key: Optional[bool] = None

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

class AICopilotResponse(BaseModel):
    reply: str


# --- Personnel ---
class PersonnelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=128)
    skills: list[str] = Field(default_factory=list)
    region: str = Field(default="陕北", max_length=32)

class PersonnelUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    email: Optional[str] = Field(default=None, min_length=3, max_length=128)
    skills: Optional[list[str]] = None
    region: Optional[str] = Field(default=None, max_length=32)

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
