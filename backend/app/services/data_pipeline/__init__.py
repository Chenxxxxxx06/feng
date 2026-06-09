"""Data Pipeline — unified interface for all data sources."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import random


class SourceStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass
class PipelineState:
    scada: SourceStatus = SourceStatus.DISCONNECTED
    vibration: SourceStatus = SourceStatus.DISCONNECTED
    image: SourceStatus = SourceStatus.DISCONNECTED
    weather: SourceStatus = SourceStatus.DISCONNECTED
    last_scada: Optional[datetime] = None
    last_vibration: Optional[datetime] = None
    last_image: Optional[datetime] = None
    last_weather: Optional[datetime] = None
    scada_records: int = 0
    vibration_files: int = 0
    image_files: int = 0
    weather_updates: int = 0
    errors: list[str] = field(default_factory=list)


_pipeline_state = PipelineState()


def get_pipeline_state() -> PipelineState:
    return _pipeline_state


def set_source_status(source: str, status: SourceStatus, record_count: int = 0):
    now = datetime.now(timezone.utc)
    if source == "scada":
        _pipeline_state.scada = status
        _pipeline_state.last_scada = now
        _pipeline_state.scada_records += record_count
    elif source == "vibration":
        _pipeline_state.vibration = status
        _pipeline_state.last_vibration = now
        _pipeline_state.vibration_files += record_count
    elif source == "image":
        _pipeline_state.image = status
        _pipeline_state.last_image = now
        _pipeline_state.image_files += record_count
    elif source == "weather":
        _pipeline_state.weather = status
        _pipeline_state.last_weather = now
        _pipeline_state.weather_updates += record_count


def log_pipeline_error(source: str, error: str):
    _pipeline_state.errors.append(f"[{source}] {error}")
    if len(_pipeline_state.errors) > 100:
        _pipeline_state.errors = _pipeline_state.errors[-50:]
