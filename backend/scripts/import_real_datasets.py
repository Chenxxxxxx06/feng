r"""Import real diagnosis datasets.

This script does not generate data. It imports files downloaded from public or
measured datasets into the PHM demo database.

Examples:
    python -m scripts.import_real_datasets blade-yolo --dataset-dir C:\data\blade_yolo --turbine-id 1 --classes crack,erosion,delamination
    python -m scripts.import_real_datasets vibration-csv --path C:\data\nrel_vibration.csv --turbine-id 1 --component gearbox_high_speed --sample-rate 97656
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from sqlalchemy import select

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models import BladeImage, DataSource, SCADARecord, VibrationData
from app.services.data_pipeline import SourceStatus, set_source_status


BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
BLADE_DIR = DATA_DIR / "blade_images"
VIBRATION_DIR = DATA_DIR / "vibration"
SCADA_DIR = DATA_DIR / "scada"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SCADA_COLUMN_ALIASES = {
    "timestamp": ["timestamp", "time", "datetime", "date_time", "date/time", "turbine_time", "turbine_timestamp"],
    "power_kw": ["power_kw", "active_power", "activepower", "power", "p", "grid_active_power", "active power"],
    "wind_speed_ms": ["wind_speed_ms", "wind_speed", "windspeed", "wind speed", "wind_speed_avg"],
    "rotor_rpm": ["rotor_rpm", "rotor_speed", "rotor speed", "rotor_speed_rpm"],
    "gen_temperature_c": ["gen_temperature_c", "generator_temperature", "generator temp", "gen_temp"],
    "gearbox_temperature_c": ["gearbox_temperature_c", "gearbox_temperature", "gearbox temp", "gearbox_temp"],
    "bearing_temperature_c": ["bearing_temperature_c", "bearing_temperature", "bearing temp", "bearing_temp"],
    "pitch_angle_deg": ["pitch_angle_deg", "pitch_angle", "pitch angle", "blade_pitch_angle"],
    "nacelle_direction_deg": ["nacelle_direction_deg", "nacelle_direction", "nacelle direction", "yaw_angle"],
    "grid_frequency_hz": ["grid_frequency_hz", "grid_frequency", "frequency", "grid frequency"],
    "ambient_temp_c": ["ambient_temp_c", "ambient_temperature", "outdoor_temperature", "temperature", "air_temperature"],
}


def _relative_to_data(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def _normalize_column_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _resolve_column(df: pd.DataFrame, explicit: str | None, aliases: list[str], required: bool = False) -> str | None:
    columns = list(df.columns)
    if explicit:
        if explicit not in columns:
            raise ValueError(f"Column not found: {explicit}")
        return explicit

    normalized = {_normalize_column_name(str(col)): str(col) for col in columns}
    for alias in aliases:
        found = normalized.get(_normalize_column_name(alias))
        if found:
            return found
    if required:
        raise ValueError(f"Required column not found. Tried aliases: {aliases}")
    return None


def _optional_float(value) -> float | None:
    if pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_classes(classes: str | None, names_file: str | None) -> list[str]:
    if names_file:
        names = Path(names_file).read_text(encoding="utf-8").splitlines()
        return [n.strip() for n in names if n.strip()]
    if classes:
        return [c.strip() for c in classes.split(",") if c.strip()]
    return ["damage"]


def _read_yolo_label(
    label_path: Path,
    width: int,
    height: int,
    class_names: list[str],
    dataset_id: str,
    source_file: str,
    source_doi: str | None,
    source_url: str | None,
    source_license: str | None,
) -> tuple[str, dict] | tuple[None, dict]:
    metadata = {
        "label_source": "YOLO_public_dataset",
        "source_dataset": dataset_id,
        "source_file": source_file,
        "source_doi": source_doi,
        "source_url": source_url,
        "source_license": source_license,
        "image_width": width,
        "image_height": height,
    }
    if not label_path.exists():
        metadata["label_source"] = "label_file_not_found"
        return None, metadata
    lines = [line.strip() for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        metadata["label_source"] = "YOLO_empty_label_file"
        return "no_damage", metadata

    boxes = []
    for line in lines:
        parts = line.split()
        if len(parts) < 5:
            raise ValueError(f"Invalid YOLO label: {label_path}")

        cls_idx = int(float(parts[0]))
        x_center, y_center, box_w, box_h = map(float, parts[1:5])
        if not all(0 <= v <= 1 for v in (x_center, y_center, box_w, box_h)):
            raise ValueError(f"YOLO label coordinates out of range: {label_path}")
        boxes.append((cls_idx, x_center, y_center, box_w, box_h))

    cls_idx, x_center, y_center, box_w, box_h = max(boxes, key=lambda item: item[3] * item[4])
    x = max(0, int((x_center - box_w / 2) * width))
    y = max(0, int((y_center - box_h / 2) * height))
    w = min(width - x, int(box_w * width))
    h = min(height - y, int(box_h * height))
    damage_type = class_names[cls_idx] if cls_idx < len(class_names) else f"class_{cls_idx}"
    return damage_type, {
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "label_source": "YOLO_public_dataset",
        "source_dataset": dataset_id,
        "source_file": source_file,
        "source_doi": source_doi,
        "source_url": source_url,
        "source_license": source_license,
        "image_width": width,
        "image_height": height,
        "object_count": len(boxes),
        "all_labels": [
            class_names[idx] if idx < len(class_names) else f"class_{idx}"
            for idx, *_ in boxes
        ],
    }


async def import_blade_yolo(args: argparse.Namespace) -> None:
    dataset_dir = Path(args.dataset_dir).resolve()
    if not dataset_dir.exists():
        raise FileNotFoundError(dataset_dir)

    class_names = _parse_classes(args.classes, args.names_file)
    target_dir = BLADE_DIR / args.dataset_id
    target_dir.mkdir(parents=True, exist_ok=True)

    image_paths = [p for p in dataset_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS]
    imported = 0
    skipped = 0
    async with async_session() as db:
        for image_path in image_paths:
            label_path = image_path.with_suffix(".txt")
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
                    if width < args.min_width or height < args.min_height:
                        skipped += 1
                        continue
                dest = target_dir / image_path.name
                source_file = str(image_path)
                damage_type, bbox = _read_yolo_label(
                    label_path,
                    width,
                    height,
                    class_names,
                    args.dataset_id,
                    source_file,
                    args.source_doi,
                    args.source_url,
                    args.source_license,
                )
                if damage_type is None and args.require_label:
                    skipped += 1
                    continue

                shutil.copy2(image_path, dest)
                db.add(BladeImage(
                    turbine_id=args.turbine_id,
                    timestamp=datetime.now(timezone.utc),
                    image_path=_relative_to_data(dest),
                    diagnosis_type=damage_type or "unknown",
                    diagnosis_confidence=None,
                    damage_bbox=bbox,
                ))
                imported += 1
            except Exception as exc:
                skipped += 1
                print(f"skip {image_path}: {exc}")
        await db.commit()

    print(json.dumps({
        "dataset_type": "blade_yolo",
        "dataset_id": args.dataset_id,
        "imported": imported,
        "skipped": skipped,
        "source_dir": str(dataset_dir),
        "quality_rules": {
            "min_width": args.min_width,
            "min_height": args.min_height,
            "require_label": args.require_label,
        },
    }, ensure_ascii=False, indent=2))


def _read_numeric_series(path: Path) -> tuple[np.ndarray, float, str]:
    if path.suffix.lower() in {".csv", ".txt"}:
        try:
            df = pd.read_csv(path)
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin1")
        numeric = df.select_dtypes(include=["number"])
        if numeric.empty:
            df = pd.read_csv(path, sep=None, engine="python", header=None)
            numeric = df.select_dtypes(include=["number"])
    else:
        raise ValueError(f"Unsupported vibration file type: {path.suffix}")
    if numeric.empty:
        raise ValueError("No numeric vibration columns found")
    raw_series = numeric.iloc[:, 0]
    series = raw_series.dropna().to_numpy(dtype=float)
    if series.size == 0:
        raise ValueError("Empty vibration series")
    completeness_pct = round(float(series.size / len(raw_series) * 100), 2) if len(raw_series) else 0.0
    return series, completeness_pct, str(raw_series.name)


def _spectrum(series: np.ndarray, sample_rate: int) -> list[dict]:
    demeaned = series - np.mean(series)
    fft = np.abs(np.fft.rfft(demeaned))
    freqs = np.fft.rfftfreq(series.size, d=1 / sample_rate)
    if fft.size <= 1:
        return []
    peak_idx = np.argsort(fft[1:])[-5:][::-1] + 1
    return [
        {"frequency_hz": round(float(freqs[i]), 2), "amplitude": round(float(fft[i] / series.size * 2), 4)}
        for i in peak_idx
    ]


async def import_vibration_csv(args: argparse.Namespace) -> None:
    paths = [Path(args.path)]
    if paths[0].is_dir():
        paths = sorted([p for p in paths[0].rglob("*") if p.suffix.lower() in {".csv", ".txt"}])

    VIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped = 0
    async with async_session() as db:
        for path in paths:
            try:
                series, completeness_pct, channel_name = _read_numeric_series(path)
                if series.size < args.min_samples:
                    skipped += 1
                    continue
                rms = float(math.sqrt(np.mean(np.square(series))))
                peaks = _spectrum(series, args.sample_rate)
                payload = {
                    "turbine_id": args.turbine_id,
                    "component": args.component,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "sample_rate_hz": args.sample_rate,
                    "sample_count": int(series.size),
                    "duration_seconds": round(series.size / args.sample_rate, 4),
                    "rms": round(rms, 5),
                    "waveform": [round(float(v), 6) for v in series[: args.max_display_samples]],
                    "peak_frequencies": peaks,
                    "fault_detected": args.label.lower() not in {"healthy", "normal", "no_fault"},
                    "fault_info": {
                        "type": args.label,
                        "label_source": args.label_source,
                    },
                    "quality": {
                        "source_dataset": args.dataset_id,
                        "source_file": str(path),
                        "source_channel": channel_name,
                        "source_doi": args.source_doi,
                        "source_url": args.source_url,
                        "source_license": args.source_license,
                        "source_label": args.label,
                        "label_source": args.label_source,
                        "completeness_pct": completeness_pct,
                    },
                    "data_source": "real_dataset",
                }
                out = VIBRATION_DIR / args.dataset_id / f"{path.stem}.json"
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                db.add(VibrationData(
                    turbine_id=args.turbine_id,
                    timestamp=datetime.now(timezone.utc),
                    component=args.component,
                    rms=payload["rms"],
                    peak_freq_hz=peaks[0]["frequency_hz"] if peaks else None,
                    waveform_path=_relative_to_data(out),
                ))
                imported += 1
            except Exception as exc:
                skipped += 1
                print(f"skip {path}: {exc}")
        await db.commit()

    print(json.dumps({
        "dataset_type": "vibration_csv",
        "dataset_id": args.dataset_id,
        "imported": imported,
        "skipped": skipped,
        "quality_rules": {
            "sample_rate_hz": args.sample_rate,
            "min_samples": args.min_samples,
        },
    }, ensure_ascii=False, indent=2))


def _read_csv_frame(path: Path, max_rows: int | None = None) -> pd.DataFrame:
    try:
        return pd.read_csv(path, nrows=max_rows)
    except UnicodeDecodeError:
        return pd.read_csv(path, nrows=max_rows, encoding="latin1")


def _scada_column_map(df: pd.DataFrame, args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "timestamp": _resolve_column(df, args.timestamp_column, SCADA_COLUMN_ALIASES["timestamp"], required=True),
        "power_kw": _resolve_column(df, args.power_column, SCADA_COLUMN_ALIASES["power_kw"]),
        "wind_speed_ms": _resolve_column(df, args.wind_speed_column, SCADA_COLUMN_ALIASES["wind_speed_ms"]),
        "rotor_rpm": _resolve_column(df, args.rotor_rpm_column, SCADA_COLUMN_ALIASES["rotor_rpm"]),
        "gen_temperature_c": _resolve_column(df, args.gen_temperature_column, SCADA_COLUMN_ALIASES["gen_temperature_c"]),
        "gearbox_temperature_c": _resolve_column(df, args.gearbox_temperature_column, SCADA_COLUMN_ALIASES["gearbox_temperature_c"]),
        "bearing_temperature_c": _resolve_column(df, args.bearing_temperature_column, SCADA_COLUMN_ALIASES["bearing_temperature_c"]),
        "pitch_angle_deg": _resolve_column(df, args.pitch_angle_column, SCADA_COLUMN_ALIASES["pitch_angle_deg"]),
        "nacelle_direction_deg": _resolve_column(df, args.nacelle_direction_column, SCADA_COLUMN_ALIASES["nacelle_direction_deg"]),
        "grid_frequency_hz": _resolve_column(df, args.grid_frequency_column, SCADA_COLUMN_ALIASES["grid_frequency_hz"]),
        "ambient_temp_c": _resolve_column(df, args.ambient_temperature_column, SCADA_COLUMN_ALIASES["ambient_temp_c"]),
        "source_turbine_id": _resolve_column(df, args.source_turbine_column, []) if args.source_turbine_column else None,
    }


async def import_scada_csv(args: argparse.Namespace) -> None:
    paths = [Path(args.path)]
    if paths[0].is_dir():
        paths = sorted([p for p in paths[0].rglob("*.csv")])
    if not paths:
        raise FileNotFoundError(args.path)

    SCADA_DIR.joinpath(args.dataset_id).mkdir(parents=True, exist_ok=True)
    imported = 0
    skipped_rows = 0
    skipped_files = 0
    min_ts = None
    max_ts = None
    column_maps: dict[str, dict[str, str | None]] = {}

    async with async_session() as db:
        for path in paths:
            try:
                df = _read_csv_frame(path, args.max_rows)
                if df.empty:
                    skipped_files += 1
                    continue
                col_map = _scada_column_map(df, args)
                column_maps[str(path)] = col_map
            except Exception as exc:
                skipped_files += 1
                print(f"skip {path}: {exc}")
                continue

            for row_number, row in df.iterrows():
                parsed_ts = pd.to_datetime(row[col_map["timestamp"]], errors="coerce", utc=True)
                if pd.isna(parsed_ts):
                    skipped_rows += 1
                    continue
                timestamp = parsed_ts.to_pydatetime()
                min_ts = timestamp if min_ts is None or timestamp < min_ts else min_ts
                max_ts = timestamp if max_ts is None or timestamp > max_ts else max_ts
                extra = {
                    "source_dataset": args.dataset_id,
                    "source_file": str(path),
                    "source_row": int(row_number) + 2,
                    "source_doi": args.source_doi,
                    "source_url": args.source_url,
                    "source_license": args.source_license,
                    "dataset_role": "primary_scada_timeline",
                    "field_mapping": {k: v for k, v in col_map.items() if v},
                }
                if col_map.get("source_turbine_id"):
                    extra["source_turbine_id"] = str(row[col_map["source_turbine_id"]])

                db.add(SCADARecord(
                    turbine_id=args.turbine_id,
                    timestamp=timestamp,
                    power_kw=_optional_float(row[col_map["power_kw"]]) if col_map.get("power_kw") else None,
                    wind_speed_ms=_optional_float(row[col_map["wind_speed_ms"]]) if col_map.get("wind_speed_ms") else None,
                    rotor_rpm=_optional_float(row[col_map["rotor_rpm"]]) if col_map.get("rotor_rpm") else None,
                    gen_temperature_c=_optional_float(row[col_map["gen_temperature_c"]]) if col_map.get("gen_temperature_c") else None,
                    gearbox_temperature_c=_optional_float(row[col_map["gearbox_temperature_c"]]) if col_map.get("gearbox_temperature_c") else None,
                    bearing_temperature_c=_optional_float(row[col_map["bearing_temperature_c"]]) if col_map.get("bearing_temperature_c") else None,
                    pitch_angle_deg=_optional_float(row[col_map["pitch_angle_deg"]]) if col_map.get("pitch_angle_deg") else None,
                    nacelle_direction_deg=_optional_float(row[col_map["nacelle_direction_deg"]]) if col_map.get("nacelle_direction_deg") else None,
                    grid_frequency_hz=_optional_float(row[col_map["grid_frequency_hz"]]) if col_map.get("grid_frequency_hz") else None,
                    ambient_temp_c=_optional_float(row[col_map["ambient_temp_c"]]) if col_map.get("ambient_temp_c") else None,
                    extra=extra,
                ))
                imported += 1

                if imported % args.batch_size == 0:
                    await db.commit()

        source_result = await db.execute(select(DataSource).where(DataSource.source_type == "scada"))
        source = source_result.scalar_one_or_none()
        if not source:
            source = DataSource(source_type="scada", name=args.dataset_id)
            db.add(source)
        source.name = args.dataset_id
        source.status = "connected" if imported else "disconnected"
        source.last_connected_at = datetime.now(timezone.utc)
        source.last_data_at = max_ts
        source.connection_params = {
            "dataset_id": args.dataset_id,
            "source_doi": args.source_doi,
            "source_url": args.source_url,
            "source_license": args.source_license,
            "source_paths": [str(p) for p in paths],
            "column_maps": column_maps,
            "dataset_role": "primary_scada_timeline",
        }
        await db.commit()

    set_source_status("scada", SourceStatus.CONNECTED if imported else SourceStatus.DISCONNECTED, imported)
    print(json.dumps({
        "dataset_type": "scada_csv",
        "dataset_id": args.dataset_id,
        "imported": imported,
        "skipped_rows": skipped_rows,
        "skipped_files": skipped_files,
        "time_range": {
            "start": min_ts.isoformat() if min_ts else None,
            "end": max_ts.isoformat() if max_ts else None,
        },
        "quality_rules": [
            "timestamp column is required",
            "rows with invalid timestamps are skipped",
            "all imported rows preserve source file and source row",
            "missing optional sensor columns stay null instead of being filled",
        ],
    }, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import real PHM diagnosis datasets")
    sub = parser.add_subparsers(dest="command", required=True)

    blade = sub.add_parser("blade-yolo")
    blade.add_argument("--dataset-dir", required=True)
    blade.add_argument("--dataset-id", default="public_blade_dataset")
    blade.add_argument("--turbine-id", type=int, required=True)
    blade.add_argument("--classes")
    blade.add_argument("--names-file")
    blade.add_argument("--source-doi")
    blade.add_argument("--source-url")
    blade.add_argument("--source-license")
    blade.add_argument("--min-width", type=int, default=320)
    blade.add_argument("--min-height", type=int, default=240)
    blade.add_argument("--require-label", action="store_true")

    vib = sub.add_parser("vibration-csv")
    vib.add_argument("--path", required=True)
    vib.add_argument("--dataset-id", default="public_vibration_dataset")
    vib.add_argument("--turbine-id", type=int, required=True)
    vib.add_argument("--component", default="gearbox_high_speed")
    vib.add_argument("--label", default="healthy")
    vib.add_argument("--label-source", default="public_dataset_label")
    vib.add_argument("--source-doi")
    vib.add_argument("--source-url")
    vib.add_argument("--source-license")
    vib.add_argument("--sample-rate", type=int, default=10240)
    vib.add_argument("--min-samples", type=int, default=1024)
    vib.add_argument("--max-display-samples", type=int, default=2048)

    scada = sub.add_parser("scada-csv")
    scada.add_argument("--path", required=True)
    scada.add_argument("--dataset-id", default="care_to_compare_v6")
    scada.add_argument("--turbine-id", type=int, required=True)
    scada.add_argument("--source-doi")
    scada.add_argument("--source-url")
    scada.add_argument("--source-license")
    scada.add_argument("--timestamp-column")
    scada.add_argument("--power-column")
    scada.add_argument("--wind-speed-column")
    scada.add_argument("--rotor-rpm-column")
    scada.add_argument("--gen-temperature-column")
    scada.add_argument("--gearbox-temperature-column")
    scada.add_argument("--bearing-temperature-column")
    scada.add_argument("--pitch-angle-column")
    scada.add_argument("--nacelle-direction-column")
    scada.add_argument("--grid-frequency-column")
    scada.add_argument("--ambient-temperature-column")
    scada.add_argument("--source-turbine-column")
    scada.add_argument("--max-rows", type=int)
    scada.add_argument("--batch-size", type=int, default=1000)
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "blade-yolo":
        await import_blade_yolo(args)
    elif args.command == "vibration-csv":
        await import_vibration_csv(args)
    elif args.command == "scada-csv":
        await import_scada_csv(args)


if __name__ == "__main__":
    asyncio.run(main())
