from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, JSON, Text
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
    model_preference = Column(String(64), default="gpt-4")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    notification_configs = relationship("NotificationConfig", back_populates="user")


class Turbine(Base):
    __tablename__ = "turbines"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, index=True)
    model = Column(String(64), nullable=False)
    power_mw = Column(Float, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    region = Column(String(32), nullable=False)
    status = Column(String(16), default="normal")
    hi_value = Column(Float, default=100.0)
    last_maintenance = Column(DateTime, nullable=True)
    commissioned_at = Column(DateTime, nullable=True)

    scada_records = relationship("SCADARecord", back_populates="turbine")
    faults = relationship("Fault", back_populates="turbine")
    rul_predictions = relationship("RULPrediction", back_populates="turbine")


class SCADARecord(Base):
    __tablename__ = "scada_records"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
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
    timestamp = Column(DateTime, nullable=False, index=True)
    component = Column(String(32), nullable=False)
    rms = Column(Float)
    peak_freq_hz = Column(Float)
    waveform_path = Column(String(256))


class BladeImage(Base):
    __tablename__ = "blade_images"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False)
    image_path = Column(String(256), nullable=False)
    diagnosis_type = Column(String(32), nullable=True)
    diagnosis_confidence = Column(Float, nullable=True)
    damage_bbox = Column(JSON, nullable=True)


class Fault(Base):
    __tablename__ = "faults"
    id = Column(Integer, primary_key=True, index=True)
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=False, index=True)
    detected_at = Column(DateTime, default=datetime.now(timezone.utc))
    fault_type = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False)
    status = Column(String(16), default="open")
    details = Column(JSON, nullable=True)

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
    predicted_at = Column(DateTime, default=datetime.now(timezone.utc))
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
    assignee = Column(String(64), nullable=True)
    cost_estimate = Column(Float, default=0.0)
    cost_actual = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
    downtime_hours = Column(Float, nullable=True)


class NotificationConfig(Base):
    __tablename__ = "notification_configs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    hi_threshold = Column(Float, default=70.0)
    email_enabled = Column(Boolean, default=False)
    email_address = Column(String(128), nullable=True)
    wechat_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now(timezone.utc))

    user = relationship("User", back_populates="notification_configs")


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String(32), nullable=False)
    name = Column(String(64), nullable=False)
    connection_params = Column(JSON, nullable=True)
    status = Column(String(16), default="disconnected")
    last_connected_at = Column(DateTime, nullable=True)
    last_data_at = Column(DateTime, nullable=True)
