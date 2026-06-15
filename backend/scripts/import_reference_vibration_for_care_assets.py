"""Attach public vibration reference waveforms to CARE display assets.

The CARE SCADA dataset does not contain vibration channels. This script maps
real public vibration samples to CARE assets as diagnostic reference waveforms
for UI demonstration and reasoning. It does not claim the samples were measured
from the same physical turbine.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import defaultdict
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "fengdiao_phm.db"
FEATURES_CSV_CANDIDATES = (
    ROOT / "docs" / "reports" / "data_processing" / "vibration_features.csv",
    ROOT / "reports" / "data_processing" / "vibration_features.csv",
    ROOT / "fengdiao_dataset_db_handoff_20260611" / "datasets" / "processed_features" / "vibration_features.csv",
)
DATA_DIR = ROOT / "backend" / "data"
OUT_DIR = DATA_DIR / "vibration" / "care_reference_waveforms"
DATASET_ID = "care_public_vibration_reference"
COMPONENT = "blade"


@lru_cache(maxsize=1)
def raw_vibration_files_by_name() -> dict[str, Path]:
    raw_root = DATA_DIR / "curated_datasets" / "raw" / "vibration"
    if not raw_root.exists():
        return {}
    return {
        path.name.lower(): path
        for path in raw_root.rglob("*.csv")
    }


def resolve_existing_path(raw_path: str) -> Path | None:
    path = Path(raw_path)
    candidates = [path] if path.is_absolute() else [
        ROOT / path,
        ROOT / "backend" / path,
        DATA_DIR / path,
        DATA_DIR / "curated_datasets" / "raw" / "vibration" / path.name,
    ]
    existing = next((candidate for candidate in candidates if candidate.exists()), None)
    if existing:
        return existing
    return raw_vibration_files_by_name().get(path.name.lower())


def resolve_features_csv() -> Path:
    return next((path for path in FEATURES_CSV_CANDIDATES if path.exists()), FEATURES_CSV_CANDIDATES[0])


def read_numeric_series(path: Path) -> tuple[np.ndarray, str, float]:
    try:
        frame = pd.read_csv(path)
    except UnicodeDecodeError:
        frame = pd.read_csv(path, encoding="latin1")
    candidates = []
    for column in frame.columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() > 0:
            candidates.append((column, numeric))
    if not candidates:
        frame = pd.read_csv(path, sep=None, engine="python", header=None)
        for column in frame.columns:
            numeric = pd.to_numeric(frame[column], errors="coerce")
            if numeric.notna().sum() > 0:
                candidates.append((column, numeric))
    if not candidates:
        raise ValueError(f"No numeric vibration column found in {path}")
    column_name, raw = max(candidates, key=lambda item: item[1].notna().sum())
    series = raw.dropna().to_numpy(dtype=float)
    completeness_pct = round(float(series.size / len(raw) * 100), 2) if len(raw) else 0.0
    return series, str(column_name), completeness_pct


def spectrum(series: np.ndarray, sample_rate: int) -> list[dict]:
    demeaned = series - np.mean(series)
    fft = np.abs(np.fft.rfft(demeaned))
    freqs = np.fft.rfftfreq(series.size, d=1 / sample_rate)
    if fft.size <= 1:
        return []
    peak_idx = np.argsort(fft[1:])[-5:][::-1] + 1
    return [
        {"frequency_hz": round(float(freqs[i]), 2), "amplitude": round(float(fft[i] / series.size * 2), 6)}
        for i in peak_idx
    ]


def load_sample_catalog() -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    features_csv = resolve_features_csv()
    with features_csv.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            path = resolve_existing_path(row["source_file"])
            if path is None or path.suffix.lower() != ".csv":
                continue
            row["source_file"] = str(path)
            label = row["label"].strip().lower()
            grouped[label].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda item: item["source_file"])
    return grouped


def severity_for_turbine(status: str, hi: float) -> tuple[str, list[str]]:
    if status == "fault" or hi < 60:
        return "fault", ["crack", "unbalance", "erosion"]
    if status == "warning" or hi < 75:
        return "pre_fault", ["erosion", "unbalance", "crack"]
    if hi < 88:
        return "degraded", ["unbalance", "erosion"]
    return "healthy", ["healthy"]


def pick_sample(catalog: dict[str, list[dict]], labels: list[str], index: int) -> dict:
    available = [item for label in labels for item in catalog.get(label, [])]
    if not available:
        raise RuntimeError(f"No vibration sample for labels: {labels}")
    return available[index % len(available)]


def table_columns(con: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info({table_name})")}


def load_target_turbines(con: sqlite3.Connection) -> list[sqlite3.Row]:
    columns = table_columns(con, "turbines")
    source_asset_expr = "source_asset_id" if "source_asset_id" in columns else "NULL AS source_asset_id"
    where_clause = "WHERE source_dataset = 'care_to_compare_v6'" if "source_dataset" in columns else ""
    return con.execute(
        f"""
        SELECT id, name, status, hi_value, {source_asset_expr}
        FROM turbines
        {where_clause}
        ORDER BY id
        """
    ).fetchall()


def scale_series(series: np.ndarray, severity: str, hi: float) -> np.ndarray:
    if severity == "healthy":
        return series
    if severity == "degraded":
        return series * 1.15
    if severity == "pre_fault":
        return series * 1.35
    # Keep fault samples visibly stronger, while preserving the real waveform shape.
    return series * max(1.55, min(2.1, 2.2 - hi / 100))


def main() -> None:
    catalog = load_sample_catalog()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    turbines = load_target_turbines(con)

    now = datetime.now(timezone.utc).isoformat()
    imported = 0
    updated = 0

    with con:
        for index, turbine in enumerate(turbines):
            severity, labels = severity_for_turbine(turbine["status"], float(turbine["hi_value"]))
            sample = pick_sample(catalog, labels, index)
            source_path = Path(sample["source_file"])
            series, channel_name, completeness_pct = read_numeric_series(source_path)
            sample_rate = int(float(sample.get("sample_rate_hz") or 1000))
            adjusted = scale_series(series, severity, float(turbine["hi_value"]))
            rms = float(math.sqrt(np.mean(np.square(adjusted))))
            peaks = spectrum(adjusted, sample_rate)
            fault_detected = severity != "healthy"

            payload = {
                "turbine_id": turbine["id"],
                "turbine_name": turbine["name"],
                "component": COMPONENT,
                "timestamp": now,
                "sample_rate_hz": sample_rate,
                "sample_count": int(adjusted.size),
                "duration_seconds": round(adjusted.size / sample_rate, 4),
                "rms": round(rms, 6),
                "waveform": [round(float(value), 6) for value in adjusted[:2048]],
                "peak_frequencies": peaks,
                "fault_detected": fault_detected,
                "fault_info": {
                    "type": sample["label"] if fault_detected else "healthy",
                    "label_source": "public_dataset_status_mapping",
                    "mapped_severity": severity,
                },
                "quality": {
                    "source_dataset": DATASET_ID,
                    "source_file": str(source_path),
                    "source_channel": channel_name,
                    "source_label": sample["label"],
                    "label_source": "public_dataset_label",
                    "completeness_pct": completeness_pct,
                    "mapping_role": "diagnostic_reference_sample",
                    "mapping_note": (
                        "CARE SCADA has no vibration channel; this waveform is a real public "
                        "vibration sample mapped by HI/status for diagnostic UI reference."
                    ),
                    "care_source_asset_id": turbine["source_asset_id"],
                    "care_status": turbine["status"],
                    "care_hi_value": turbine["hi_value"],
                },
                "data_source": "real_public_reference_dataset",
            }

            out_path = OUT_DIR / f"turbine_{turbine['id']}_{turbine['name']}.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            rel_path = out_path.relative_to(DATA_DIR).as_posix()

            existing = con.execute(
                """
                SELECT id FROM vibration_data
                WHERE turbine_id = ? AND component = ? AND waveform_path = ?
                """,
                (turbine["id"], COMPONENT, rel_path),
            ).fetchone()
            if existing:
                con.execute(
                    """
                    UPDATE vibration_data
                    SET timestamp = ?, rms = ?, peak_freq_hz = ?, waveform_path = ?
                    WHERE id = ?
                    """,
                    (
                        now,
                        payload["rms"],
                        peaks[0]["frequency_hz"] if peaks else None,
                        rel_path,
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                con.execute(
                    """
                    INSERT INTO vibration_data
                    (turbine_id, timestamp, component, rms, peak_freq_hz, waveform_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        turbine["id"],
                        now,
                        COMPONENT,
                        payload["rms"],
                        peaks[0]["frequency_hz"] if peaks else None,
                        rel_path,
                    ),
                )
                imported += 1

    print(json.dumps({
        "dataset_id": DATASET_ID,
        "component": COMPONENT,
        "care_assets": len(turbines),
        "inserted": imported,
        "updated": updated,
        "output_dir": str(OUT_DIR),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
