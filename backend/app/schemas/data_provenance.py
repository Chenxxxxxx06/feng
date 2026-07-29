"""Shared API fields that describe where displayed data comes from."""

from typing import Literal, Optional

from pydantic import BaseModel


SourceType = Literal["historical", "simulated", "demo"]


class DataTimeRange(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


class DataProvenanceMixin(BaseModel):
    source_type: SourceType
    data_time_range: DataTimeRange
    is_demo: bool
    source_label: str
    source_description: str
