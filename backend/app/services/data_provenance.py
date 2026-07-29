"""Build consistent, JSON-safe data provenance metadata for API responses."""

from datetime import date, datetime, time, timezone
from typing import Iterable

from app.schemas.data_provenance import SourceType


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_data_provenance(
    *,
    source_type: SourceType,
    source_label: str,
    source_description: str,
    is_demo: bool,
    timestamps: Iterable[object] = (),
) -> dict[str, object]:
    normalized = [parsed for value in timestamps if (parsed := _as_datetime(value))]
    return {
        "source_type": source_type,
        "data_time_range": {
            "start": min(normalized).isoformat() if normalized else None,
            "end": max(normalized).isoformat() if normalized else None,
        },
        "is_demo": is_demo,
        "source_label": source_label,
        "source_description": source_description,
    }
