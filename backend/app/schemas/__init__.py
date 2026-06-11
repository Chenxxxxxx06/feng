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
    turbine_id: int = Field(gt=0)
    image_path: str = ""

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
    turbine_id: int = Field(gt=0)
    fault_type: str = Field(min_length=1, max_length=64)

class CostComparisonResponse(BaseModel):
    immediate_repair_cost: float
    delayed_repair_cost: float
    downtime_loss_per_day: float
    failure_probability: float
    recommendation: str
    optimal_window_days: int


# --- WorkOrder ---
class WorkOrderCreate(BaseModel):
    turbine_id: int = Field(gt=0)
    fault_id: Optional[int] = None
    title: str = Field(min_length=1, max_length=128)
    description: Optional[str] = None
    assignee: Optional[str] = None
    cost_estimate: float = Field(default=0.0, ge=0)

class WorkOrderUpdate(BaseModel):
    status: Optional[str] = Field(default=None, max_length=16)
    assignee: Optional[str] = None
    cost_actual: Optional[float] = Field(default=None, ge=0)
    downtime_hours: Optional[float] = Field(default=None, ge=0)

class WorkOrderResponse(BaseModel):
    id: int
    turbine_id: int
    fault_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    status: str
    assignee: Optional[str] = None
    cost_estimate: float
    cost_actual: Optional[float] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    downtime_hours: Optional[float] = None

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
    source_type: str = Field(min_length=1, max_length=32)
    connection_params: dict = Field(default_factory=dict)

class ProfileUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    api_provider: Optional[str] = None
    model_preference: Optional[str] = Field(default=None, max_length=64)

    model_config = {"protected_namespaces": ()}


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
