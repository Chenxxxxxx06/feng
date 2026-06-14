"""Curate real datasets and compute first-pass PHM indicators.

This script does not generate synthetic data. It organizes verified real
dataset files under backend/data/curated_datasets and writes small processing
reports under reports/data_processing.
"""

from __future__ import annotations

import csv
import json
import math
import os
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from PIL import Image
from scipy.io import loadmat, whosmat


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CURATED = BACKEND / "data" / "curated_datasets"
ARCHIVES = CURATED / "archives"
RAW = CURATED / "raw"
REPORTS = ROOT / "reports" / "data_processing"

MAIN_DATA = Path(r"C:\Users\ASUS\Desktop\maindata")

SOURCES = {
    "care_to_compare_v6": {
        "source": MAIN_DATA / "CARE_To_Compare.zip",
        "archive": ARCHIVES / "scada" / "care_to_compare_v6" / "CARE_To_Compare.zip",
        "expected_size": 5_503_439_673,
        "expected_md5": "2547b58c21ac8c242d13232860cf500c",
    },
    "dtu_drone_inspection": {
        "source": MAIN_DATA / "backend" / "data" / "blade_images" / "dtu_drone_inspection" / "hd96prn3nc-2.zip",
        "archive": ARCHIVES / "blade_images" / "dtu_drone_inspection" / "hd96prn3nc-2.zip",
        "expected_size": 3_029_715_385,
    },
    "yolo_annotated_wind_turbine_surface_damage": {
        # The maindata copy has the expected size but a zero-filled tail.
        # Use the already verified zip in the project data directory.
        "source": BACKEND / "data" / "blade_images" / "yolo_annotated_wind_turbine_surface_damage" / "t6fwpc735s-1.zip",
        "archive": ARCHIVES / "blade_images" / "yolo_annotated_wind_turbine_surface_damage" / "t6fwpc735s-1.zip",
        "expected_size": 2_756_431_451,
    },
    "nrel_grc_gearbox_cm": {
        "source_dir": BACKEND / "data" / "vibration" / "nrel_grc_gearbox_cm" / "raw",
        "raw_dir": RAW / "vibration" / "nrel_grc_gearbox_cm",
    },
    "mendeley_blade_vibration_faults": {
        "source_dir": BACKEND / "data" / "vibration" / "mendeley_blade_vibration_faults" / "raw",
        "raw_dir": RAW / "vibration" / "mendeley_blade_vibration_faults",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def link_or_copy_file(source: Path, target: Path) -> dict[str, Any]:
    ensure_parent(target)
    result = {
        "source": str(source),
        "target": str(target),
        "source_exists": source.exists(),
        "status": "missing_source",
    }
    if not source.exists():
        return result

    result["source_size"] = source.stat().st_size
    if target.exists():
        result["target_size"] = target.stat().st_size
        result["status"] = "already_present" if source.stat().st_size == target.stat().st_size else "target_size_mismatch"
        return result

    try:
        os.link(source, target)
        result["status"] = "hardlinked"
    except OSError:
        shutil.copy2(source, target)
        result["status"] = "copied"
    result["target_size"] = target.stat().st_size
    return result


def mirror_tree_with_hardlinks(source_dir: Path, target_dir: Path) -> dict[str, Any]:
    result = {"source_dir": str(source_dir), "target_dir": str(target_dir), "files": 0, "bytes": 0, "status": "ok"}
    if not source_dir.exists():
        result["status"] = "missing_source"
        return result
    for source in source_dir.rglob("*"):
        if not source.is_file():
            continue
        rel = source.relative_to(source_dir)
        target = target_dir / rel
        file_result = link_or_copy_file(source, target)
        if file_result["status"] in {"hardlinked", "copied", "already_present"}:
            result["files"] += 1
            result["bytes"] += source.stat().st_size
    return result


def zip_summary(path: Path) -> dict[str, Any]:
    item: dict[str, Any] = {"path": str(path), "exists": path.exists(), "zip_ok": False}
    if not path.exists():
        return item
    item["size"] = path.stat().st_size
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
            ext_counts = Counter((Path(info.filename).suffix.lower() or "<dir>") for info in infos)
            item.update({
                "zip_ok": True,
                "entries": len(infos),
                "extensions": dict(sorted(ext_counts.items())),
                "first_entries": [info.filename for info in infos[:10]],
            })
    except Exception as exc:
        item["error"] = repr(exc)
    return item


def extract_zip_once(zip_path: Path, dest: Path, marker_name: str = ".extract_complete.json") -> dict[str, Any]:
    marker = dest / marker_name
    result = {"zip_path": str(zip_path), "dest": str(dest), "status": "not_started"}
    if marker.exists():
        result["status"] = "already_extracted"
        return result
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
        result["entries"] = len(zf.infolist())
    marker.write_text(json.dumps({"zip_path": str(zip_path), "extracted_at": now_iso()}, ensure_ascii=False, indent=2), encoding="utf-8")
    result["status"] = "extracted"
    return result


def label_from_name(path: Path) -> str:
    text = path.name.lower()
    parts = [part.lower() for part in path.parts]
    if "healthy" in parts or text.startswith("h-") or text.startswith("h "):
        return "healthy"
    if "damaged" in parts:
        return "damaged"
    if "crack" in text:
        return "crack"
    if "erosion" in text:
        return "erosion"
    if "unbalance" in text or "unbalnce" in text:
        return "unbalance"
    if "twist" in text or "twsist" in text:
        return "twist"
    return "unknown"


def compute_series_features(series: np.ndarray, sample_rate_hz: float | None) -> dict[str, Any]:
    clean = series.astype(float)
    clean = clean[np.isfinite(clean)]
    n = int(clean.size)
    if n == 0:
        raise ValueError("empty numeric series")
    mean = float(np.mean(clean))
    std = float(np.std(clean, ddof=1)) if n > 1 else 0.0
    rms = float(math.sqrt(np.mean(np.square(clean))))
    peak = float(np.max(np.abs(clean)))
    abs_mean = float(np.mean(np.abs(clean)))
    sqrt_abs_mean = float(np.mean(np.sqrt(np.abs(clean))))
    centered = clean - mean
    if std > 0:
        skewness = float(np.mean((centered / std) ** 3))
        kurtosis = float(np.mean((centered / std) ** 4))
    else:
        skewness = 0.0
        kurtosis = 0.0

    fft_samples = clean[: min(n, 262_144)]
    demeaned = fft_samples - np.mean(fft_samples)
    spectrum = np.abs(np.fft.rfft(demeaned))
    peak_bin = None
    peak_frequency_hz = None
    if spectrum.size > 1:
        peak_bin = int(np.argmax(spectrum[1:]) + 1)
        if sample_rate_hz:
            peak_frequency_hz = round(float(np.fft.rfftfreq(fft_samples.size, d=1 / sample_rate_hz)[peak_bin]), 6)

    return {
        "sample_count": n,
        "mean": round(mean, 8),
        "std": round(std, 8),
        "rms": round(rms, 8),
        "peak": round(peak, 8),
        "peak_to_peak": round(float(np.max(clean) - np.min(clean)), 8),
        "skewness": round(skewness, 8),
        "kurtosis": round(kurtosis, 8),
        "crest_factor": round(float(peak / rms), 8) if rms else None,
        "impulse_factor": round(float(peak / abs_mean), 8) if abs_mean else None,
        "shape_factor": round(float(rms / abs_mean), 8) if abs_mean else None,
        "clearance_factor": round(float(peak / (sqrt_abs_mean ** 2)), 8) if sqrt_abs_mean else None,
        "peak_frequency_hz": peak_frequency_hz,
        "peak_frequency_bin": peak_bin,
    }


def read_mendeley_series(path: Path) -> tuple[np.ndarray, str]:
    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, sep=";")
        if len(df.columns) == 1:
            df = pd.read_csv(path, sep=None, engine="python")
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(f"unsupported file type: {path.suffix}")
    numeric = df.select_dtypes(include=["number"])
    if numeric.empty:
        raise ValueError("no numeric columns")
    preferred = [col for col in numeric.columns if "amplitude" in str(col).lower()]
    column = preferred[0] if preferred else numeric.columns[-1]
    return numeric[column].dropna().to_numpy(dtype=float), str(column)


def process_vibration() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    mendeley_root = RAW / "vibration" / "mendeley_blade_vibration_faults"
    for path in sorted(p for p in mendeley_root.rglob("*") if p.suffix.lower() in {".csv", ".xlsx", ".xls"}):
        try:
            series, channel = read_mendeley_series(path)
            features = compute_series_features(series, sample_rate_hz=1000.0)
            rows.append({
                "dataset_id": "mendeley_blade_vibration_faults",
                "source_file": str(path),
                "label": label_from_name(path),
                "component": "blade",
                "channel": channel,
                "sample_rate_hz": 1000,
                **features,
            })
        except Exception as exc:
            rows.append({
                "dataset_id": "mendeley_blade_vibration_faults",
                "source_file": str(path),
                "label": label_from_name(path),
                "component": "blade",
                "error": repr(exc),
            })

    nrel_root = RAW / "vibration" / "nrel_grc_gearbox_cm"
    for path in sorted(nrel_root.rglob("*.mat")):
        try:
            variables = [name for name, *_ in whosmat(path)]
            channel = "AN3" if "AN3" in variables else variables[0]
            mat = loadmat(path, variable_names=[channel])
            series = np.asarray(mat[channel]).reshape(-1)
            features = compute_series_features(series, sample_rate_hz=None)
            rows.append({
                "dataset_id": "nrel_grc_gearbox_cm",
                "source_file": str(path),
                "label": label_from_name(path),
                "component": "gearbox",
                "channel": channel,
                "sample_rate_hz": None,
                **features,
            })
        except Exception as exc:
            rows.append({
                "dataset_id": "nrel_grc_gearbox_cm",
                "source_file": str(path),
                "label": label_from_name(path),
                "component": "gearbox",
                "error": repr(exc),
            })
    return rows


def image_summary_for_yolo(root: Path) -> dict[str, Any]:
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
    class_name_files = sorted(p for p in root.rglob("labels.txt"))
    class_names: dict[str, str] = {}
    if class_name_files:
        names = [
            line.strip()
            for line in class_name_files[0].read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
        class_names = {str(index): name for index, name in enumerate(names)}
    labels = sorted(p for p in root.rglob("*.txt") if p.name.lower() != "labels.txt")
    image_stems = {p.stem for p in images}
    label_stems = {p.stem for p in labels}
    paired = image_stems & label_stems
    class_counts: Counter[str] = Counter()
    bbox_areas: list[float] = []
    invalid_labels = 0
    for label in labels:
        try:
            for line in label.read_text(encoding="utf-8", errors="ignore").splitlines():
                parts = line.split()
                if len(parts) < 5:
                    invalid_labels += 1
                    continue
                class_counts[parts[0]] += 1
                w = float(parts[3])
                h = float(parts[4])
                bbox_areas.append(w * h)
        except Exception:
            invalid_labels += 1

    dim_counter: Counter[str] = Counter()
    for image in images[:200]:
        try:
            with Image.open(image) as img:
                dim_counter[f"{img.width}x{img.height}"] += 1
        except Exception:
            dim_counter["open_error"] += 1

    return {
        "dataset_id": "yolo_annotated_wind_turbine_surface_damage",
        "source_root": str(root),
        "image_files": len(images),
        "label_files": len(labels),
        "paired_image_label_count": len(paired),
        "unpaired_images": len(image_stems - label_stems),
        "unpaired_labels": len(label_stems - image_stems),
        "class_names": class_names,
        "class_id_counts": dict(sorted(class_counts.items())),
        "class_name_counts": {
            class_names.get(class_id, class_id): count
            for class_id, count in sorted(class_counts.items())
        },
        "bbox_count": len(bbox_areas),
        "bbox_area_ratio_mean": round(float(np.mean(bbox_areas)), 8) if bbox_areas else None,
        "bbox_area_ratio_min": round(float(np.min(bbox_areas)), 8) if bbox_areas else None,
        "bbox_area_ratio_max": round(float(np.max(bbox_areas)), 8) if bbox_areas else None,
        "invalid_label_lines": invalid_labels,
        "sample_dimensions": dict(dim_counter),
    }


def image_summary_for_raw(root: Path) -> dict[str, Any]:
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"})
    dim_counter: Counter[str] = Counter()
    open_errors = 0
    for image in images[:200]:
        try:
            with Image.open(image) as img:
                dim_counter[f"{img.width}x{img.height}"] += 1
        except Exception:
            open_errors += 1
    return {
        "dataset_id": "dtu_drone_inspection",
        "source_root": str(root),
        "image_files": len(images),
        "sample_dimensions": dict(dim_counter),
        "sample_open_errors": open_errors,
        "label_files": 0,
    }


def detect_csv_delimiter(path: Path) -> str | None:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        sample = fh.read(8192)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        return dialect.delimiter
    except csv.Error:
        first_line = sample.splitlines()[0] if sample else ""
        counts = {delimiter: first_line.count(delimiter) for delimiter in [",", ";", "\t", "|"]}
        delimiter, count = max(counts.items(), key=lambda item: item[1])
        return delimiter if count > 0 else None


def process_care_scada(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.csv")):
        rel_parts = path.relative_to(root).parts
        wind_farm = rel_parts[0] if rel_parts else ""
        if path.name == "event_info.csv":
            file_type = "event_info"
        elif path.name == "feature_description.csv":
            file_type = "feature_description"
        elif "datasets" in rel_parts:
            file_type = "event_dataset"
        else:
            file_type = "csv_metadata"
        try:
            delimiter = detect_csv_delimiter(path)
            if delimiter:
                header = pd.read_csv(path, nrows=0, sep=delimiter).columns.tolist()
            else:
                header = pd.read_csv(path, nrows=0, sep=None, engine="python").columns.tolist()
            with path.open("rb") as fh:
                line_count = sum(1 for _ in fh)
            lower_cols = {str(col).lower(): col for col in header}
            timestamp_candidates = [col for key, col in lower_cols.items() if "time" in key or "date" in key]
            rows.append({
                "dataset_id": "care_to_compare_v6",
                "wind_farm": wind_farm,
                "source_file": str(path),
                "file_size_bytes": path.stat().st_size,
                "file_type": file_type,
                "row_count_excluding_header": max(0, line_count - 1),
                "delimiter": delimiter,
                "column_count": len(header),
                "timestamp_candidates": ";".join(map(str, timestamp_candidates[:5])),
                "columns": ";".join(map(str, header)),
            })
        except Exception as exc:
            rows.append({
                "dataset_id": "care_to_compare_v6",
                "wind_farm": wind_farm,
                "source_file": str(path),
                "file_size_bytes": path.stat().st_size,
                "file_type": file_type,
                "error": repr(exc),
            })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    CURATED.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    actions: dict[str, Any] = {"started_at": now_iso(), "file_links": [], "mirrors": [], "extractions": [], "zip_summaries": []}

    for dataset_id in ["care_to_compare_v6", "dtu_drone_inspection", "yolo_annotated_wind_turbine_surface_damage"]:
        spec = SOURCES[dataset_id]
        link_result = link_or_copy_file(spec["source"], spec["archive"])
        link_result["dataset_id"] = dataset_id
        link_result["expected_size"] = spec.get("expected_size")
        link_result["size_matches_expected"] = (
            link_result.get("target_size") == spec.get("expected_size")
            if spec.get("expected_size") is not None and link_result.get("target_size") is not None
            else None
        )
        actions["file_links"].append(link_result)
        actions["zip_summaries"].append({"dataset_id": dataset_id, **zip_summary(spec["archive"])})

    for dataset_id in ["nrel_grc_gearbox_cm", "mendeley_blade_vibration_faults"]:
        spec = SOURCES[dataset_id]
        mirror_result = mirror_tree_with_hardlinks(spec["source_dir"], spec["raw_dir"])
        mirror_result["dataset_id"] = dataset_id
        actions["mirrors"].append(mirror_result)

    care_extract = extract_zip_once(
        SOURCES["care_to_compare_v6"]["archive"],
        RAW / "scada" / "care_to_compare_v6",
    )
    actions["extractions"].append({"dataset_id": "care_to_compare_v6", **care_extract})

    dtu_extract = extract_zip_once(
        SOURCES["dtu_drone_inspection"]["archive"],
        RAW / "blade_images" / "dtu_drone_inspection",
    )
    actions["extractions"].append({"dataset_id": "dtu_drone_inspection", **dtu_extract})

    yolo_outer_dest = RAW / "blade_images" / "yolo_annotated_wind_turbine_surface_damage" / "outer"
    yolo_outer = extract_zip_once(SOURCES["yolo_annotated_wind_turbine_surface_damage"]["archive"], yolo_outer_dest)
    actions["extractions"].append({"dataset_id": "yolo_annotated_wind_turbine_surface_damage_outer", **yolo_outer})
    nested = next(yolo_outer_dest.rglob("NordTank586x371.zip"), None)
    if nested:
        yolo_inner = extract_zip_once(nested, RAW / "blade_images" / "yolo_annotated_wind_turbine_surface_damage" / "extracted")
        actions["extractions"].append({"dataset_id": "yolo_annotated_wind_turbine_surface_damage_inner", **yolo_inner})
    else:
        actions["extractions"].append({"dataset_id": "yolo_annotated_wind_turbine_surface_damage_inner", "status": "missing_nested_zip"})

    vibration_rows = process_vibration()
    write_csv(REPORTS / "vibration_features.csv", vibration_rows)

    image_rows = [
        image_summary_for_yolo(RAW / "blade_images" / "yolo_annotated_wind_turbine_surface_damage" / "extracted"),
        image_summary_for_raw(RAW / "blade_images" / "dtu_drone_inspection"),
    ]
    write_csv(REPORTS / "image_dataset_quality.csv", image_rows)

    care_root = RAW / "scada" / "care_to_compare_v6" / "CARE_To_Compare"
    care_rows = process_care_scada(care_root)
    write_csv(REPORTS / "care_scada_files.csv", care_rows)

    summary = {
        **actions,
        "completed_at": now_iso(),
        "outputs": {
            "vibration_features": str(REPORTS / "vibration_features.csv"),
            "image_dataset_quality": str(REPORTS / "image_dataset_quality.csv"),
            "care_scada_files": str(REPORTS / "care_scada_files.csv"),
        },
        "counts": {
            "vibration_feature_rows": len(vibration_rows),
            "image_quality_rows": len(image_rows),
            "care_csv_rows": len(care_rows),
            "care_event_dataset_files": sum(1 for row in care_rows if row.get("file_type") == "event_dataset"),
            "care_metadata_files": sum(1 for row in care_rows if row.get("file_type") != "event_dataset"),
        },
        "notes": [
            "Reports are first-pass processing artifacts based on MATHEMATICAL_MODELING_DESIGN.md.",
            "No database rows were inserted by this script.",
            "Large curated data files are under backend/data/curated_datasets and are ignored by Git.",
        ],
    }
    (REPORTS / "dataset_processing_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["counts"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
