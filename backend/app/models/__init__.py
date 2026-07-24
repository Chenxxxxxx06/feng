from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship
from datetime import datetime, timezone

from app.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    role = Column(String(32), default="viewer")
    api_key = Column(String(256), nullable=True)
    api_provider = Column(String(64), nullable=True)
    api_base_url = Column(String(512), nullable=True)
    model_preference = Column(String(128), default="qwen-plus")
    preferences = Column(JSON, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    notification_configs = relationship("NotificationConfig", back_populates="user")
    ai_provider_configs = relationship("AIProviderConfig", back_populates="user", cascade="all, delete-orphan")

    @property
    def has_api_key(self) -> bool:
        """P0-05: never expose raw api_key in responses."""
        return bool(self.api_key)


class AIProviderConfig(Base):
    __tablename__ = "ai_provider_configs"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_ai_provider_user_provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    display_name = Column(String(128), nullable=True)
    api_key = Column(String(512), nullable=True)
    base_url = Column(String(512), nullable=False)
    api_style = Column(String(32), default="openai")
    default_model = Column(String(128), nullable=True)
    model_options = Column(JSON, nullable=True)
    enabled = Column(Boolean, default=True)
    last_test_status = Column(String(32), default="untested")
    last_test_message = Column(Text, nullable=True)
    last_test_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="ai_provider_configs")


class Turbine(Base):
    __tablename__ = "turbines"
    __table_args__ = (
        UniqueConstraint("source_dataset", "source_asset_id", name="uq_turbine_source_asset"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, index=True)
    model = Column(String(64), nullable=True)
    power_mw = Column(Float, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    region = Column(String(32), nullable=True)
    status = Column(String(16), default="normal")
    hi_value = Column(Float, default=100.0)
    last_maintenance = Column(DateTime(timezone=True), nullable=True)
    commissioned_at = Column(DateTime(timezone=True), nullable=True)
    source_dataset = Column(String(64), nullable=True, index=True)
    source_asset_id = Column(String(128), nullable=True, index=True)
    asset_scope = Column(String(32), default="field_asset")
    geo_scope = Column(String(32), default="known")

    scada_records = relationship("SCADARecord", back_populates="turbine")
    faults = relationship("Fault", back_populates="turbine")
    rul_predictions = relationship("RULPrediction", back_populates="turbine")


class SCADARecord(Base):
    __tablename__ = "scada_records"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    power_kw = Column(Float)
    wind_speed_ms = Column(Float)
    rotor_rpm = Column(Float)
    gen_temperature_c = Column(Float)
    gearbox_temperature_c = Column(Float)
    bearing_temperature_c = Column(Float)
    pitch_angle_deg = Column(Float)
    nacelle_direction_deg = Column(Float)
    grid_frequency_hz = Column(Float)
    ambient_temp_c = Column(Float)
    extra = Column(JSON, nullable=True)

    turbine = relationship("Turbine", back_populates="scada_records")


class VibrationData(Base):
    __tablename__ = "vibration_data"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    component = Column(String(32), nullable=False)
    rms = Column(Float)
    peak_freq_hz = Column(Float)
    waveform_path = Column(String(256))


class BladeImage(Base):
    __tablename__ = "blade_images"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    image_path = Column(String(256), nullable=False)
    diagnosis_type = Column(String(32), nullable=True)
    diagnosis_confidence = Column(Float, nullable=True)
    damage_bbox = Column(JSON, nullable=True)


class Fault(Base):
    __tablename__ = "faults"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    detected_at = Column(DateTime(timezone=True), default=func.now())
    fault_type = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(16), default="open")
    details = Column(JSON, nullable=True)
    # Business fields (P0-01: formally mapped, no longer ephemeral)
    priority = Column(String(16), default="medium")
    processing_status = Column(String(16), default="pending")
    handler = Column(String(64), nullable=True)
    discovered_at = Column(DateTime(timezone=True), nullable=True)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    failed_at = Column(DateTime(timezone=True), nullable=True)
    last_action_at = Column(DateTime(timezone=True), nullable=True)
    work_order_id = Column(Integer, nullable=True)
    work_order_title = Column(String(128), nullable=True)
    maintenance_cost_estimate = Column(Float, nullable=True)
    maintenance_cost_actual = Column(Float, nullable=True)
    status_note = Column(Text, nullable=True)

    turbine = relationship("Turbine", back_populates="faults")
    signals = relationship("FaultSignal", back_populates="fault")


class FaultSignal(Base):
    __tablename__ = "fault_signals"
    id = Column(Integer, primary_key=True, index=True)
    fault_id = Column(Integer, ForeignKey("faults.id"), nullable=False)
    sensor_name = Column(String(64), nullable=False)
    contribution_score = Column(Float, nullable=False)
    priority = Column(String(8), default="medium")

    fault = relationship("Fault", back_populates="signals")


class RULPrediction(Base):
    __tablename__ = "rul_predictions"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    component = Column(String(32), nullable=False)
    predicted_at = Column(DateTime(timezone=True), default=func.now())
    remaining_life_days = Column(Float, nullable=False)
    confidence_lower = Column(Float, nullable=False)
    confidence_upper = Column(Float, nullable=False)

    turbine = relationship("Turbine", back_populates="rul_predictions")


class WorkOrder(Base):
    __tablename__ = "work_orders"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    fault_id = Column(Integer, ForeignKey("faults.id"), nullable=True)
    title = Column(String(128), nullable=False)
    description = Column(Text)
    status = Column(String(16), default="pending")
    priority = Column(String(16), default="medium")
    fault_type = Column(String(64), nullable=True)
    assignee = Column(String(64), nullable=True)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    assignee_email = Column(String(128), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    cost_estimate = Column(Float, default=0.0)
    cost_actual = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    notification_sent_at = Column(DateTime(timezone=True), nullable=True)
    downtime_hours = Column(Float, nullable=True)


class MaintenanceRecord(Base):
    __tablename__ = "maintenance_records"
    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action_type = Column(String(32), nullable=False)
    content = Column(Text, nullable=True)
    before_status = Column(String(16), nullable=True)
    after_status = Column(String(16), nullable=True)
    extra = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())


class AgentActionLog(Base):
    __tablename__ = "agent_action_logs"
    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String(64), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    raw_message = Column(Text, nullable=True)
    parsed_action = Column(JSON, nullable=True)
    action = Column(String(64), nullable=False, index=True)
    params = Column(JSON, nullable=True)
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending")
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    executed_at = Column(DateTime(timezone=True), nullable=True)


class AgentTaskPlanState(Base):
    __tablename__ = "agent_task_plan_states"
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(String(64), nullable=False, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    raw_message = Column(Text, nullable=False)
    playbook_id = Column(String(128), nullable=False, index=True)
    page_context = Column(JSON, nullable=True)
    status = Column(String(16), nullable=False, default="pending", index=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id"), nullable=True, index=True)
    recipient_email = Column(String(128), nullable=False)
    subject = Column(String(256), nullable=True)
    channel = Column(String(32), default="email")
    status = Column(String(16), nullable=False)
    error_message = Column(Text, nullable=True)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())


class OperationLog(Base):
    __tablename__ = "operation_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    page = Column(String(64), nullable=False, index=True)
    action = Column(String(128), nullable=False)
    result = Column(Text, nullable=True)
    level = Column(String(16), default="info")
    created_at = Column(DateTime(timezone=True), default=func.now(), index=True)


class MaintenancePersonnel(Base):
    __tablename__ = "maintenance_personnel"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    name = Column(String(64), nullable=False)
    email = Column(String(128), nullable=True)
    skills = Column(JSON, default=list)
    region = Column(String(32), nullable=True)
    is_available = Column(Boolean, default=True)
    max_load = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())


class NotificationConfig(Base):
    __tablename__ = "notification_configs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    hi_threshold = Column(Float, default=70.0)
    email_enabled = Column(Boolean, default=False)
    email_address = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    user = relationship("User", back_populates="notification_configs")


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(32), nullable=False)
    name = Column(String(64), nullable=False)
    connection_params = Column(JSON, nullable=True)
    status = Column(String(16), default="disconnected")
    last_connected_at = Column(DateTime(timezone=True), nullable=True)
    last_data_at = Column(DateTime(timezone=True), nullable=True)


class DataImportBatch(Base):
    __tablename__ = "data_import_batches"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(String(64), nullable=False, index=True)
    source_type = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True))
    manifest_path = Column(Text)
    field_mapping_version = Column(Text)
    files_total = Column(Integer)
    files_imported = Column(Integer)
    rows_imported = Column(Integer)
    rows_skipped = Column(Integer)
    anonymous_assets = Column(Integer)
    summary = Column(JSON)


class FaultKnowledgeNode(Base):
    __tablename__ = "fault_knowledge"
    id = Column(Integer, primary_key=True, index=True)
    fault_type = Column(String(128), unique=True, nullable=False, index=True)
    category = Column(String(64), nullable=False, index=True)
    icon = Column(String(8), default="⚠️")
    severity = Column(String(16), default="medium")
    symptoms = Column(JSON, default=list)
    root_causes = Column(JSON, default=list)
    solutions = Column(JSON, default=list)
    related_faults = Column(JSON, default=list)
    spare_parts = Column(JSON, default=list)
    cases = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    source = Column(String(32), default="manual")
    confidence = Column(Float, default=1.0)
    verified = Column(Boolean, default=True)
    extracted_from = Column(Text, nullable=True)


# ═══════════════════════════════════════════════════════════════
# Phase 4: Innovation MVP models — Incident-centric wind ops
# ═══════════════════════════════════════════════════════════════

class Incident(Base):
    """4.1 自主运维事件指挥官 — unified maintenance event lifecycle."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(String(32), unique=True, nullable=False, index=True)  # INC-20260724-001
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    title = Column(String(256), nullable=False)
    severity = Column(String(16), default="medium")  # low/medium/high/critical
    stage = Column(String(32), default="detected")  # detected→correlated→...→resolved
    status = Column(String(16), default="open")  # open/in_progress/resolved/escalated
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    selected_plan_id = Column(Integer, nullable=True)
    verification_status = Column(String(16), nullable=True)  # pending/pass/fail
    alarm_count = Column(Integer, default=0)
    compressed_count = Column(Integer, default=0)  # alarms before compression
    trace_id = Column(String(64), nullable=True, index=True)
    summary = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    opened_at = Column(DateTime(timezone=True), default=func.now())
    closed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    turbine = relationship("Turbine")
    alarms = relationship("AlarmRecord", back_populates="incident")
    evidence_nodes = relationship("EvidenceNode", back_populates="incident")
    decision_plans = relationship("DecisionPlan", back_populates="incident")


class AlarmRecord(Base):
    """4.2 告警风暴压缩 — individual alarm within a compressed cluster."""
    __tablename__ = "alarm_records"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False)
    fault_id = Column(Integer, ForeignKey("faults.id"), nullable=True)
    source = Column(String(64), nullable=False)  # scada/vibration/opcua/manual
    alarm_type = Column(String(128), nullable=False)
    component = Column(String(64), nullable=True)
    severity = Column(String(16), default="medium")
    message = Column(Text, nullable=True)
    value = Column(Float, nullable=True)
    threshold = Column(Float, nullable=True)
    is_primary = Column(Boolean, default=False)  # primary alarm in cluster
    compression_rule = Column(String(64), nullable=True)  # which rule compressed it
    compressed = Column(Boolean, default=False)  # whether this was merged
    fired_at = Column(DateTime(timezone=True), default=func.now())

    incident = relationship("Incident", back_populates="alarms")


class EvidenceNode(Base):
    """4.3 因果证据图 — observation/hypothesis/check/action/result."""
    __tablename__ = "evidence_nodes"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    node_type = Column(String(32), nullable=False)  # observation/hypothesis/check/action/result
    label = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    source = Column(String(32), default="rule")  # observation/rule/model/llm/human
    confidence = Column(Float, default=0.5)
    props = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    incident = relationship("Incident", back_populates="evidence_nodes")


class EvidenceEdge(Base):
    """4.3 因果证据图 — supports/contradicts/requires_check/caused_by/resolved_by."""
    __tablename__ = "evidence_edges"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    source_node_id = Column(Integer, ForeignKey("evidence_nodes.id"), nullable=False)
    target_node_id = Column(Integer, ForeignKey("evidence_nodes.id"), nullable=False)
    edge_type = Column(String(32), nullable=False)  # supports/contradicts/requires_check/caused_by/resolved_by
    source = Column(String(32), default="rule")  # observation/rule/model/llm/human
    confidence = Column(Float, default=0.5)
    evidence_ref = Column(Text, nullable=True)  # traceable reference
    created_at = Column(DateTime(timezone=True), default=func.now())


class DecisionPlan(Base):
    """4.4 反事实维修决策沙盘 — one executable plan among alternatives."""
    __tablename__ = "decision_plans"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=False, index=True)
    plan_name = Column(String(128), nullable=False)  # "立即停机维修" / "降载运行+计划维修" / "继续监测"
    strategy = Column(String(64), nullable=False)  # immediate_repair / degraded_ops / monitor
    safety_risk = Column(Float, default=0.0)  # 0-100
    downtime_loss = Column(Float, default=0.0)  # estimated CNY
    repair_cost = Column(Float, default=0.0)
    recovery_days = Column(Float, default=0.0)
    personnel_available = Column(Boolean, default=True)
    parts_available = Column(Boolean, default=True)
    weather_compatible = Column(Boolean, default=True)
    total_score = Column(Float, default=0.0)
    is_recommended = Column(Boolean, default=False)
    llm_explanation = Column(Text, nullable=True)
    decision_flip_point = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    incident = relationship("Incident", back_populates="decision_plans")


class PolicyRule(Base):
    """4.5 工业安全策略引擎 — executable policy rules."""
    __tablename__ = "policy_rules"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(String(64), unique=True, nullable=False, index=True)
    description = Column(String(256), nullable=False)
    action_pattern = Column(String(128), nullable=False)  # close_incident/assign_workorder/control_device
    risk_level = Column(Integer, default=0)  # L0(read-only) to L4(device control)
    rule_type = Column(String(16), default="deny")  # allow/deny/require_approval/require_dual
    condition_json = Column(JSON, nullable=True)  # structured condition
    is_active = Column(Boolean, default=True)
    version = Column(String(16), default="1.0")
    created_at = Column(DateTime(timezone=True), default=func.now())


class PolicyDecision(Base):
    """4.5 工业安全策略引擎 — audit log of policy decisions."""
    __tablename__ = "policy_decisions"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True, index=True)
    rule_id = Column(String(64), nullable=False, index=True)
    action = Column(String(128), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    decision = Column(String(16), nullable=False)  # allowed/denied/approved/escalated
    reason = Column(Text, nullable=True)
    rule_version = Column(String(16), nullable=True)
    decided_at = Column(DateTime(timezone=True), default=func.now())


class AgentTrace(Base):
    """4.6 Agent飞行记录器 — root trace for each agent run."""
    __tablename__ = "agent_traces"

    id = Column(Integer, primary_key=True, index=True)
    trace_id = Column(String(64), unique=True, nullable=False, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(16), default="running")  # running/completed/failed/degraded
    total_spans = Column(Integer, default=0)
    total_duration_ms = Column(Float, default=0.0)
    token_usage = Column(JSON, nullable=True)
    cost_estimate = Column(Float, default=0.0)
    error_code = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)


class AgentSpan(Base):
    """4.6 Agent飞行记录器 — individual span within an agent trace."""
    __tablename__ = "agent_spans"

    id = Column(Integer, primary_key=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    parent_span_id = Column(String(64), nullable=True, index=True)
    span_id = Column(String(64), unique=True, nullable=False, index=True)
    span_name = Column(String(128), nullable=False)
    agent_name = Column(String(64), nullable=True)
    tool_name = Column(String(128), nullable=True)
    step_order = Column(Integer, default=0)
    input_digest = Column(Text, nullable=True)
    output_digest = Column(Text, nullable=True)
    status = Column(String(16), default="running")
    duration_ms = Column(Float, default=0.0)
    policy_decision = Column(String(16), nullable=True)  # allowed/denied/approved
    approval_by = Column(String(64), nullable=True)
    error_code = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), default=func.now())
    ended_at = Column(DateTime(timezone=True), nullable=True)
