"""Entity resolution helpers for Agent workflows."""

from .resolver import (
    EntityResolution,
    extract_turbine_ref,
    normalize_turbine_ref,
    resolve_personnel_by_name,
    resolve_turbine_by_ref,
    resolve_workorder_by_ref,
)

__all__ = [
    "EntityResolution",
    "extract_turbine_ref",
    "normalize_turbine_ref",
    "resolve_personnel_by_name",
    "resolve_turbine_by_ref",
    "resolve_workorder_by_ref",
]
