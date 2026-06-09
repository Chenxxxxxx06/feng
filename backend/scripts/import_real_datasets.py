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

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models import BladeImage, VibrationData


BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
BLADE_DIR = DATA_DIR / "blade_images"
VIBRATION_DIR = DATA_DIR / "vibration"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _relative_to_data(path: Path) -> str:
    return path.resolve().relative_to(DATA_DIR.resolve()).as_posix()


def _parse_classes(classes: str | None, names_file: str | None) -> list[str]:
    if names_file:
        names = Path(names_file).read_text(encoding="utf-8").splitlines()
        return [n.strip() for n in names if n.strip()]
    if classes:
        return [c.strip() for c in classes.split(",") if c.strip()]
    return ["damage"]


def _read_yolo_label(label_path: Path, width: int, height: int, class_names: list[str]) -> tuple[str, dict] | tuple[None, None]:
    if not label_path.exists():
        return None, None
    lines = [line.strip() for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        return "no_damage", None

    parts = lines[0].split()
    if len(parts) < 5:
        raise ValueError(f"Invalid YOLO label: {label_path}")

    cls_idx = int(float(parts[0]))
    x_center, y_center, box_w, box_h = map(float, parts[1:5])
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
        "image_width": width,
        "image_height": height,
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
                damage_type, bbox = _read_yolo_label(label_path, width, height, class_names)
                if damage_type is None and args.require_label:
                    skipped += 1
                    continue

                dest = target_dir / image_path.name
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


def _read_numeric_series(path: Path) -> np.ndarray:
    if path.suffix.lower() in {".csv", ".txt"}:
        df = pd.read_csv(path)
    else:
        raise ValueError(f"Unsupported vibration file type: {path.suffix}")
    numeric = df.select_dtypes(include=["number"])
    if numeric.empty:
        raise ValueError("No numeric vibration columns found")
    series = numeric.iloc[:, 0].dropna().to_numpy(dtype=float)
    if series.size == 0:
        raise ValueError("Empty vibration series")
    return series


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
                series = _read_numeric_series(path)
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
                    "fault_info": {"type": args.label, "label_source": "public_dataset_label"},
                    "quality": {
                        "source_dataset": args.dataset_id,
                        "source_file": str(path),
                        "label_source": "public_dataset_label",
                        "completeness_pct": 100.0,
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import real PHM diagnosis datasets")
    sub = parser.add_subparsers(dest="command", required=True)

    blade = sub.add_parser("blade-yolo")
    blade.add_argument("--dataset-dir", required=True)
    blade.add_argument("--dataset-id", default="public_blade_dataset")
    blade.add_argument("--turbine-id", type=int, required=True)
    blade.add_argument("--classes")
    blade.add_argument("--names-file")
    blade.add_argument("--min-width", type=int, default=320)
    blade.add_argument("--min-height", type=int, default=240)
    blade.add_argument("--require-label", action="store_true")

    vib = sub.add_parser("vibration-csv")
    vib.add_argument("--path", required=True)
    vib.add_argument("--dataset-id", default="public_vibration_dataset")
    vib.add_argument("--turbine-id", type=int, required=True)
    vib.add_argument("--component", default="gearbox_high_speed")
    vib.add_argument("--label", default="healthy")
    vib.add_argument("--sample-rate", type=int, default=10240)
    vib.add_argument("--min-samples", type=int, default=1024)
    vib.add_argument("--max-display-samples", type=int, default=2048)
    return parser


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "blade-yolo":
        await import_blade_yolo(args)
    elif args.command == "vibration-csv":
        await import_vibration_csv(args)


if __name__ == "__main__":
    asyncio.run(main())
