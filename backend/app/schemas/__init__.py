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
    model: str
    power_mw: float
    lat: float
    lng: float
    region: str
    status: str
    hi_value: float
    last_maintenance: Optional[datetime] = None

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
    detected_at: datetime
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

class FaultDetailResponse(FaultResponse):
    signals: list[FaultSignalResponse] = []

class BladeDiagnosisRequest(BaseModel):
    turbine_id: int
    image_path: str

class BladeDiagnosisResponse(BaseModel):
    turbine_id: int
    damage_type: str
    confidence: float
    damage_bbox: Optional[dict] = None
    image_path: str


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
    turbine_id: int
    fault_type: str

class CostComparisonResponse(BaseModel):
    immediate_repair_cost: float
    delayed_repair_cost: float
    downtime_loss_per_day: float
    failure_probability: float
    recommendation: str
    optimal_window_days: int


# --- WorkOrder ---
class WorkOrderCreate(BaseModel):
    turbine_id: int
    fault_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    assignee_id: Optional[int] = None
    assignee_email: Optional[str] = None
    priority: Optional[str] = "medium"
    fault_type: Optional[str] = None
    due_date: Optional[datetime] = None
    cost_estimate: float = 0.0

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
    source_type: str
    connection_params: dict

class ProfileUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    model_preference: Optional[str] = None

    model_config = {"protected_namespaces": ()}


# --- AI ---
class AISummaryRequest(BaseModel):
    page_type: str
    page_data: dict

class AISummaryResponse(BaseModel):
    conclusions: list[str]
    suggestions: list[str]

class AIFaultAnalysisRequest(BaseModel):
    turbine_id: int
    fault_type: str

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
    messages: list[dict]
    page_context: Optional[dict] = None
    knowledge_results: Optional[list[str]] = None

class AICopilotResponse(BaseModel):
    reply: str


# --- Personnel ---
class PersonnelCreate(BaseModel):
    name: str
    email: str
    skills: list[str] = []
    region: str = "陕北"

class PersonnelUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    skills: Optional[list[str]] = None
    region: Optional[str] = None

class PersonnelResponse(BaseModel):
    id: int
    name: str
    skills: list[str]
    region: str
    load: int
    email: str
