"""CARE SCADA based monitoring metrics.

The functions here only use imported dataset evidence. They do not synthesize
maintenance outcomes when the source dataset does not contain them.
"""

from __future__ import annotations

import json
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SCADARecord


CARE_DATASET_ID = "care_to_compare_v6"
ANOMALY_STATUS_IDS = {"3", "4"}
SCADA_SLOT_HOURS = 10 / 60
BACKEND_DIR = Path(__file__).resolve().parents[2]
CARE_EVENT_DIR = BACKEND_DIR / "data" / "modeling" / "care_to_compare_v6" / "normalized_events"
CARE_REGION_LABELS = {
    "Wind Farm A": "榆林靖边风场A区",
    "Wind Farm B": "榆林定边风场B区",
    "Wind Farm C": "榆林横山风场C区",
}


def _extra_dict(extra: Any) -> dict[str, Any]:
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str) and extra:
        try:
            parsed = json.loads(extra)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class CareHiResult:
    hi_value: float
    status: str
    component_scores: dict[str, float]


def _score_from_penalty(penalty: float, max_penalty: float, floor: float = 35.0) -> float:
    ratio = min(1.0, max(0.0, penalty / max(max_penalty, 1e-6)))
    return round(max(floor, 100.0 - ratio * (100.0 - floor)), 1)


def calculate_care_hi_from_scada(rows: list[SCADARecord]) -> CareHiResult:
    """Calculate HI from the latest CARE SCADA rows for one turbine."""
    if not rows:
        return CareHiResult(
            hi_value=80.0,
            status="normal",
            component_scores={"performance": 80.0, "thermal": 85.0, "operation": 85.0, "event": 80.0},
        )

    performance_penalty = 0.0
    thermal_penalty = 0.0
    operation_penalty = 0.0
    event_penalty = 0.0

    for row in rows:
        extra = _extra_dict(row.extra)
        wind = row.wind_speed_ms or 0.0
        power = row.power_kw or 0.0
        gen_temp = row.gen_temperature_c
        gearbox_temp = row.gearbox_temperature_c
        rotor_rpm = row.rotor_rpm
        event_label = str(extra.get("event_label") or "").lower()
        status_type_id = str(extra.get("status_type_id") or "")

        # CARE power fields are normalized p.u. in the current import.
        # Penalize low output only when wind is sufficient for meaningful output.
        if wind >= 10 and power < 0.35:
            performance_penalty += 2.2
        elif wind >= 8 and power < 0.25:
            performance_penalty += 1.4
        elif wind >= 6 and power < 0.10:
            performance_penalty += 0.8

        if gen_temp is not None and gen_temp > 95:
            thermal_penalty += 1.4
        elif gen_temp is not None and gen_temp > 90:
            thermal_penalty += 0.8
        if gearbox_temp is not None and gearbox_temp > 88:
            thermal_penalty += 1.4
        elif gearbox_temp is not None and gearbox_temp > 82:
            thermal_penalty += 0.8

        if wind >= 7 and rotor_rpm is not None and rotor_rpm <= 0:
            operation_penalty += 1.0

        if event_label == "anomaly" or status_type_id in ANOMALY_STATUS_IDS:
            event_penalty += 1.0

    total = max(len(rows), 1)
    component_scores = {
        "performance": _score_from_penalty(performance_penalty, total * 2.2, 40.0),
        "thermal": _score_from_penalty(thermal_penalty, total * 2.8, 45.0),
        "operation": _score_from_penalty(operation_penalty, total * 1.0, 55.0),
        "event": _score_from_penalty(event_penalty, total * 1.0, 45.0),
    }
    hi = round(
        component_scores["performance"] * 0.38
        + component_scores["thermal"] * 0.24
        + component_scores["operation"] * 0.18
        + component_scores["event"] * 0.20,
        1,
    )
    if hi >= 80:
        status = "normal"
    elif hi >= 60:
        status = "warning"
    else:
        status = "fault"
    return CareHiResult(hi_value=hi, status=status, component_scores=component_scores)


async def refresh_care_hi_snapshots(
    db: AsyncSession,
    dataset_id: str = CARE_DATASET_ID,
    window_rows: int = 144,
) -> list[dict[str, Any]]:
    """Recalculate and persist CARE turbine HI snapshots."""
    turbine_rows = (
        await db.execute(
            text(
                """
                SELECT id, name
                FROM turbines
                WHERE source_dataset = :dataset_id
                ORDER BY id
                """
            ),
            {"dataset_id": dataset_id},
        )
    ).mappings().all()

    updates: list[dict[str, Any]] = []
    for turbine in turbine_rows:
        records = (
            await db.execute(
                text(
                    """
                    SELECT id
                    FROM scada_records
                    WHERE turbine_id = :turbine_id
                    ORDER BY timestamp DESC
                    LIMIT :window_rows
                    """
                ),
                {"turbine_id": turbine["id"], "window_rows": window_rows},
            )
        ).mappings().all()
        if not records:
            result = calculate_care_hi_from_scada([])
        else:
            record_ids = [row["id"] for row in records]
            scada_records = (
                await db.execute(
                    text(
                        f"""
                        SELECT *
                        FROM scada_records
                        WHERE id IN ({",".join(str(int(record_id)) for record_id in record_ids)})
                        """
                    )
                )
            ).mappings().all()

            # Convert row mappings into lightweight objects compatible with the
            # calculation function.
            lightweight_rows = []
            for row in scada_records:
                item = SCADARecord()
                item.power_kw = row["power_kw"]
                item.wind_speed_ms = row["wind_speed_ms"]
                item.rotor_rpm = row["rotor_rpm"]
                item.gen_temperature_c = row["gen_temperature_c"]
                item.gearbox_temperature_c = row["gearbox_temperature_c"]
                item.extra = row["extra"]
                lightweight_rows.append(item)
            result = calculate_care_hi_from_scada(lightweight_rows)

        updates.append(
            {
                "id": turbine["id"],
                "name": turbine["name"],
                "hi_value": result.hi_value,
                "status": result.status,
                "component_scores": result.component_scores,
            }
        )

    if updates:
        await db.execute(
            text(
                """
                UPDATE turbines
                SET hi_value = :hi_value, status = :status
                WHERE id = :id
                """
            ),
            [{"id": item["id"], "hi_value": item["hi_value"], "status": item["status"]} for item in updates],
        )
        await db.commit()
    return updates


def _is_anomaly_window(window: dict[str, Any]) -> bool:
    label = str(window.get("event_label") or "").lower()
    status_type_id = str(window.get("status_type_id") or "")
    return label == "anomaly" or status_type_id in ANOMALY_STATUS_IDS


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _window_duration_hours(window: dict[str, Any]) -> float:
    start = _parse_datetime(window.get("event_start")) or _parse_datetime(window.get("start_time"))
    end = _parse_datetime(window.get("event_end")) or _parse_datetime(window.get("end_time"))
    if start and end and end >= start:
        return max((end - start).total_seconds() / 3600, SCADA_SLOT_HOURS)
    return max(float(window.get("row_count") or 0) * SCADA_SLOT_HOURS, SCADA_SLOT_HOURS)


def _load_care_event_windows_from_files() -> list[dict[str, Any]]:
    if not CARE_EVENT_DIR.exists():
        return []

    windows: list[dict[str, Any]] = []
    for path in sorted(CARE_EVENT_DIR.rglob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            first_row = next(reader, None)
            if not first_row:
                continue

        wind_farm = first_row.get("wind_farm") or path.parent.name.replace("_", " ")
        windows.append(
            {
                "region": CARE_REGION_LABELS.get(wind_farm, wind_farm),
                "source_file": str(path),
                "event_label": first_row.get("event_label"),
                "status_type_id": first_row.get("status_type_id"),
                "event_start": first_row.get("event_start") or first_row.get("timestamp"),
                "event_end": first_row.get("event_end"),
                "row_count": 1,
            }
        )
    return windows


def _summarize_windows(windows: list[dict[str, Any]], dataset_id: str) -> dict[str, Any]:
    if not windows:
        return {
            "source_dataset": dataset_id,
            "mtbf_hours": None,
            "mttr_hours": None,
            "anomaly_window_hours": None,
            "observation_hours": 0.0,
            "event_windows": 0,
            "anomaly_windows": 0,
            "mttr_available": False,
            "mttr_note": "CARE SCADA does not contain repair completion timestamps.",
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    observation_hours = 0.0
    anomaly_durations: list[float] = []
    for window in windows:
        duration = _window_duration_hours(window)
        observation_hours += duration
        if _is_anomaly_window(window):
            anomaly_durations.append(duration)

    anomaly_count = len(anomaly_durations)
    mtbf = observation_hours / anomaly_count if anomaly_count else None
    anomaly_window_hours = sum(anomaly_durations) / anomaly_count if anomaly_count else None

    return {
        "source_dataset": dataset_id,
        "mtbf_hours": round(mtbf, 1) if mtbf is not None else None,
        "mttr_hours": None,
        "anomaly_window_hours": round(anomaly_window_hours, 1) if anomaly_window_hours is not None else None,
        "observation_hours": round(observation_hours, 1),
        "event_windows": len(windows),
        "anomaly_windows": anomaly_count,
        "mttr_available": False,
        "mttr_note": "CARE SCADA does not contain repair completion timestamps.",
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def calculate_care_reliability_metrics(
    db: AsyncSession,
    dataset_id: str = CARE_DATASET_ID,
) -> dict[str, Any]:
    """Calculate fleet reliability indicators from CARE event windows."""
    windows = _load_care_event_windows_from_files()
    if windows:
        summary = _summarize_windows(windows, dataset_id)
        by_region: dict[str, dict[str, Any]] = {}
        for region in sorted({str(window.get("region") or "") for window in windows if window.get("region")}):
            region_windows = [window for window in windows if window.get("region") == region]
            by_region[region] = _summarize_windows(region_windows, dataset_id)

        summary["by_region"] = by_region
        summary["hi_method"] = "CARE SCADA window scoring: performance, thermal, operation, event anomaly components."
        summary["mtbf_method"] = "Dataset event-window hours divided by CARE anomaly event windows."
        summary["metric_source"] = "normalized CARE event CSV metadata"
        return summary

    rows = (
        await db.execute(
            text(
                """
                SELECT
                    t.region AS region,
                    r.turbine_id AS turbine_id,
                    json_extract(r.extra, '$.source_file') AS source_file,
                    max(json_extract(r.extra, '$.event_label')) AS event_label,
                    max(json_extract(r.extra, '$.status_type_id')) AS status_type_id,
                    count(*) AS row_count
                FROM scada_records r
                JOIN turbines t ON t.id = r.turbine_id
                WHERE t.source_dataset = :dataset_id
                GROUP BY t.region, r.turbine_id, source_file
                """
            ),
            {"dataset_id": dataset_id},
        )
    ).mappings().all()

    windows = [dict(row) for row in rows if row.get("source_file")]
    summary = _summarize_windows(windows, dataset_id)

    by_region: dict[str, dict[str, Any]] = {}
    for region in sorted({str(window.get("region") or "") for window in windows if window.get("region")}):
        region_windows = [window for window in windows if window.get("region") == region]
        by_region[region] = _summarize_windows(region_windows, dataset_id)

    summary["by_region"] = by_region
    summary["hi_method"] = "CARE SCADA window scoring: performance, thermal, operation, event anomaly components."
    summary["mtbf_method"] = "Dataset observation hours divided by CARE anomaly event windows."
    return summary
