"""Prepare CARE SCADA data for modeling and later database import.

This script reads the verified CARE to Compare v6 dataset and creates:
- standard field mappings derived from CARE feature descriptions;
- normalized per-event SCADA CSV files with only project-standard fields;
- event window and modeling-readiness reports.

It does not invent turbine identities, coordinates, business records, labels, or
costs. Derived columns are computed only from documented CARE sensor columns and
their source columns are recorded in the mapping report.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
CARE_ROOT = BACKEND / "data" / "curated_datasets" / "raw" / "scada" / "care_to_compare_v6" / "CARE_To_Compare"
MODELING_ROOT = BACKEND / "data" / "modeling" / "care_to_compare_v6"
NORMALIZED_DIR = MODELING_ROOT / "normalized_events"
REPORTS = ROOT / "reports" / "data_processing"

STANDARD_FIELDS = [
    "power_kw",
    "wind_speed_ms",
    "rotor_rpm",
    "gen_temperature_c",
    "gearbox_temperature_c",
    "bearing_temperature_c",
    "pitch_angle_deg",
    "nacelle_direction_deg",
    "grid_frequency_hz",
    "ambient_temp_c",
]

CARE_FIELD_MAPPINGS: dict[str, dict[str, dict[str, Any]]] = {
    "Wind Farm A": {
        "power_kw": {
            "source_columns": ["power_30_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Grid power in kW",
        },
        "wind_speed_ms": {
            "source_columns": ["wind_speed_3_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Measured windspeed in m/s",
        },
        "rotor_rpm": {
            "source_columns": ["sensor_52_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Rotor rpm",
        },
        "gen_temperature_c": {
            "source_columns": ["sensor_15_avg", "sensor_16_avg", "sensor_17_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Generator stator winding temperatures, phases 1-3",
        },
        "gearbox_temperature_c": {
            "source_columns": ["sensor_12_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Gearbox oil temperature",
        },
        "bearing_temperature_c": {
            "source_columns": ["sensor_11_avg"],
            "transform": "identity",
            "confidence": "medium",
            "basis": "Gearbox bearing temperature on high speed shaft",
        },
        "pitch_angle_deg": {
            "source_columns": ["sensor_5_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Pitch angle",
        },
        "nacelle_direction_deg": {
            "source_columns": ["sensor_42_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Nacelle direction",
        },
        "grid_frequency_hz": {
            "source_columns": ["sensor_26_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Grid frequency",
        },
        "ambient_temp_c": {
            "source_columns": ["sensor_0_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Ambient temperature",
        },
    },
    "Wind Farm B": {
        "power_kw": {
            "source_columns": ["power_62_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Active power in kW",
        },
        "wind_speed_ms": {
            "source_columns": ["wind_speed_61_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Wind speed in m/s",
        },
        "rotor_rpm": {
            "source_columns": ["sensor_25_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Rotor speed in rpm",
        },
        "gen_temperature_c": {
            "source_columns": ["sensor_32_avg", "sensor_33_avg"],
            "transform": "row_mean",
            "confidence": "medium",
            "basis": "Generator bearing temperatures 1-2; used as generator temperature proxy",
        },
        "gearbox_temperature_c": {
            "source_columns": ["sensor_38_avg", "sensor_39_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Gearbox oil inlet and tank temperatures",
        },
        "bearing_temperature_c": {
            "source_columns": ["sensor_51_avg", "sensor_52_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Rotor bearing temperatures 1-2",
        },
        "pitch_angle_deg": {
            "source_columns": ["sensor_10_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Pitch angle",
        },
        "nacelle_direction_deg": {
            "source_columns": ["sensor_21_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Nacelle direction",
        },
        "grid_frequency_hz": {
            "source_columns": ["sensor_23_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Grid frequency",
        },
        "ambient_temp_c": {
            "source_columns": ["sensor_8_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Outside temperature",
        },
    },
    "Wind Farm C": {
        "power_kw": {
            "source_columns": ["power_6_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Active power HV grid in kW",
        },
        "wind_speed_ms": {
            "source_columns": ["wind_speed_236_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Combined wind speed 1+2 in m/s",
        },
        "rotor_rpm": {
            "source_columns": ["sensor_144_avg", "sensor_145_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Rotor speed 1 and 2 in 1/min",
        },
        "gen_temperature_c": {
            "source_columns": [
                "sensor_199_avg",
                "sensor_200_avg",
                "sensor_201_avg",
                "sensor_202_avg",
                "sensor_203_avg",
                "sensor_204_avg",
            ],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Generator stator winding temperatures U/V/W",
        },
        "gearbox_temperature_c": {
            "source_columns": ["sensor_186_avg", "sensor_187_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Gearbox oil temperatures 1-2",
        },
        "bearing_temperature_c": {
            "source_columns": ["sensor_196_avg", "sensor_197_avg", "sensor_198_avg"],
            "transform": "row_mean",
            "confidence": "high",
            "basis": "Rotor bearing temperatures 1-3",
        },
        "pitch_angle_deg": {
            "source_columns": ["sensor_76_avg"],
            "transform": "identity",
            "confidence": "medium",
            "basis": "Minimum pitch angle; not a full blade pitch aggregate",
        },
        "grid_frequency_hz": {
            "source_columns": ["sensor_47_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Mains frequency OS-side",
        },
        "ambient_temp_c": {
            "source_columns": ["sensor_177_avg"],
            "transform": "identity",
            "confidence": "high",
            "basis": "Outside temperature",
        },
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


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


def classify_event(description: Any) -> str:
    text = str(description).lower()
    if not text or text == "nan":
        return "normal_or_unlabeled"
    if "gearbox" in text or "gear oil" in text:
        return "gearbox"
    if "bearing" in text:
        return "bearing"
    if "generator" in text:
        return "generator"
    if "transformer" in text:
        return "transformer"
    if "hydraulic" in text or "oil" in text:
        return "hydraulic_oil"
    if "pitch" in text or "axis" in text:
        return "pitch"
    if "blade" in text:
        return "blade"
    if "rotor" in text or "brake" in text:
        return "rotor_brake"
    if "converter" in text or "fuse" in text:
        return "converter_electrical"
    if "communication" in text or "plug" in text or "wiring" in text:
        return "communication_electrical"
    return "other_anomaly"


def load_event_info() -> dict[tuple[str, int], dict[str, Any]]:
    events: dict[tuple[str, int], dict[str, Any]] = {}
    for farm_dir in sorted(path for path in CARE_ROOT.iterdir() if path.is_dir()):
        path = farm_dir / "event_info.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, sep=";")
        asset_col = "asset_id" if "asset_id" in df.columns else "asset"
        for _, row in df.iterrows():
            event_id = int(row["event_id"])
            description = row.get("event_description")
            events[(farm_dir.name, event_id)] = {
                "wind_farm": farm_dir.name,
                "source_asset_id": str(row[asset_col]),
                "event_id": event_id,
                "event_label": row.get("event_label"),
                "event_start": row.get("event_start"),
                "event_start_id": row.get("event_start_id"),
                "event_end": row.get("event_end"),
                "event_end_id": row.get("event_end_id"),
                "event_description": None if pd.isna(description) else str(description),
                "event_component_category": classify_event(description),
            }
    return events


def load_feature_descriptions() -> dict[str, pd.DataFrame]:
    descriptions: dict[str, pd.DataFrame] = {}
    for farm_dir in sorted(path for path in CARE_ROOT.iterdir() if path.is_dir()):
        path = farm_dir / "feature_description.csv"
        if path.exists():
            descriptions[farm_dir.name] = pd.read_csv(path, sep=";")
    return descriptions


def source_sensor_name(column: str) -> str:
    for suffix in ["_avg", "_min", "_max", "_std"]:
        if column.endswith(suffix):
            return column[: -len(suffix)]
    return column


def describe_sources(farm: str, columns: list[str], feature_descriptions: dict[str, pd.DataFrame]) -> str:
    df = feature_descriptions.get(farm)
    if df is None or df.empty:
        return ""
    descriptions = []
    for column in columns:
        sensor = source_sensor_name(column)
        matched = df[df["sensor_name"].astype(str) == sensor]
        if matched.empty:
            descriptions.append(f"{column}: <not found in feature_description>")
            continue
        item = matched.iloc[0]
        descriptions.append(f"{column}: {item.get('description')} [{item.get('unit')}]")
    return " | ".join(descriptions)


def build_mapping_rows(feature_descriptions: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for farm, mapping in CARE_FIELD_MAPPINGS.items():
        for field in STANDARD_FIELDS:
            spec = mapping.get(field)
            if spec is None:
                rows.append({
                    "wind_farm": farm,
                    "standard_field": field,
                    "mapped": False,
                    "source_columns": "",
                    "transform": "",
                    "confidence": "missing",
                    "basis": "No CARE feature was mapped to this project standard field",
                    "source_descriptions": "",
                })
                continue
            columns = list(spec["source_columns"])
            rows.append({
                "wind_farm": farm,
                "standard_field": field,
                "mapped": True,
                "source_columns": ";".join(columns),
                "transform": spec["transform"],
                "confidence": spec["confidence"],
                "basis": spec["basis"],
                "source_descriptions": describe_sources(farm, columns, feature_descriptions),
            })
    return rows


def apply_field_mapping(df: pd.DataFrame, spec: dict[str, Any]) -> pd.Series:
    columns = [column for column in spec["source_columns"] if column in df.columns]
    if not columns:
        return pd.Series([pd.NA] * len(df), index=df.index, dtype="Float64")
    numeric = df[columns].apply(pd.to_numeric, errors="coerce")
    if spec["transform"] == "identity":
        return numeric[columns[0]]
    if spec["transform"] == "row_mean":
        return numeric.mean(axis=1, skipna=True)
    if spec["transform"] == "row_max":
        return numeric.max(axis=1, skipna=True)
    raise ValueError(f"Unsupported transform: {spec['transform']}")


def normalized_columns() -> list[str]:
    return [
        "timestamp",
        "source_turbine_id",
        "event_id",
        "wind_farm",
        "event_label",
        "event_component_category",
        "event_start",
        "event_end",
        "train_test",
        "status_type_id",
        "source_row_id",
        *STANDARD_FIELDS,
    ]


def normalize_chunk(
    chunk: pd.DataFrame,
    farm: str,
    event_meta: dict[str, Any],
    mapping: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    out = pd.DataFrame(index=chunk.index)
    out["timestamp"] = pd.to_datetime(chunk["time_stamp"], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
    out["source_turbine_id"] = chunk.get("asset_id", event_meta.get("source_asset_id"))
    out["event_id"] = event_meta["event_id"]
    out["wind_farm"] = farm
    out["event_label"] = event_meta.get("event_label")
    out["event_component_category"] = event_meta.get("event_component_category")
    out["event_start"] = event_meta.get("event_start")
    out["event_end"] = event_meta.get("event_end")
    out["train_test"] = chunk.get("train_test")
    out["status_type_id"] = chunk.get("status_type_id")
    out["source_row_id"] = chunk.get("id")

    for field in STANDARD_FIELDS:
        spec = mapping.get(field)
        if spec:
            out[field] = apply_field_mapping(chunk, spec)
        else:
            out[field] = pd.NA
    return out[normalized_columns()]


def update_counter(counter: Counter[str], values: pd.Series) -> None:
    for key, count in values.fillna("<missing>").astype(str).value_counts().to_dict().items():
        counter[key] += int(count)


def write_normalized_event(
    csv_path: Path,
    output_path: Path,
    farm: str,
    event_meta: dict[str, Any],
    mapping: dict[str, dict[str, Any]],
    chunksize: int,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    total_rows = 0
    valid_timestamps = 0
    field_non_null: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    train_test_counts: Counter[str] = Counter()
    min_ts = None
    max_ts = None
    first_write = True

    for chunk in pd.read_csv(csv_path, sep=";", chunksize=chunksize):
        normalized = normalize_chunk(chunk, farm, event_meta, mapping)
        timestamps = pd.to_datetime(normalized["timestamp"], errors="coerce")
        valid_mask = timestamps.notna()
        total_rows += len(normalized)
        valid_timestamps += int(valid_mask.sum())
        if valid_mask.any():
            chunk_min = timestamps[valid_mask].min()
            chunk_max = timestamps[valid_mask].max()
            min_ts = chunk_min if min_ts is None or chunk_min < min_ts else min_ts
            max_ts = chunk_max if max_ts is None or chunk_max > max_ts else max_ts
        for field in STANDARD_FIELDS:
            field_non_null[field] += int(pd.to_numeric(normalized[field], errors="coerce").notna().sum())
        update_counter(status_counts, normalized["status_type_id"])
        update_counter(train_test_counts, normalized["train_test"])
        normalized.to_csv(output_path, index=False, mode="w" if first_write else "a", header=first_write, encoding="utf-8-sig")
        first_write = False

    present_fields = [field for field in STANDARD_FIELDS if field_non_null[field] > 0]
    required_scada_fields = {"power_kw", "wind_speed_ms"}
    ready_for_scada_indicators = required_scada_fields.issubset(present_fields) and valid_timestamps > 0
    ready_for_temperature_indicators = any(
        field in present_fields for field in ["gen_temperature_c", "gearbox_temperature_c", "bearing_temperature_c", "ambient_temp_c"]
    )
    ready_for_hi_input = ready_for_scada_indicators and ready_for_temperature_indicators
    ready_for_rul_window = bool(event_meta.get("event_label") and event_meta.get("event_start") and event_meta.get("event_end"))

    return {
        "dataset_id": "care_to_compare_v6",
        "wind_farm": farm,
        "event_id": event_meta["event_id"],
        "event_label": event_meta.get("event_label"),
        "event_component_category": event_meta.get("event_component_category"),
        "source_asset_id": event_meta.get("source_asset_id"),
        "source_file": str(csv_path),
        "normalized_file": str(output_path),
        "row_count": total_rows,
        "valid_timestamp_rows": valid_timestamps,
        "valid_timestamp_rate": round(valid_timestamps / total_rows, 6) if total_rows else 0.0,
        "time_start": min_ts.isoformat() if min_ts is not None else None,
        "time_end": max_ts.isoformat() if max_ts is not None else None,
        "event_start": event_meta.get("event_start"),
        "event_end": event_meta.get("event_end"),
        "present_standard_fields": ";".join(present_fields),
        "missing_standard_fields": ";".join(field for field in STANDARD_FIELDS if field not in present_fields),
        "field_non_null_counts": dict(field_non_null),
        "status_type_counts": dict(sorted(status_counts.items())),
        "train_test_counts": dict(sorted(train_test_counts.items())),
        "ready_for_scada_indicators": ready_for_scada_indicators,
        "ready_for_temperature_indicators": ready_for_temperature_indicators,
        "ready_for_hi_input": ready_for_hi_input,
        "ready_for_rul_window": ready_for_rul_window,
    }


def write_event_windows(events: dict[tuple[str, int], dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for _, item in sorted(events.items(), key=lambda pair: (pair[0][0], pair[0][1])):
        rows.append({
            "dataset_id": "care_to_compare_v6",
            **item,
        })
    write_csv(REPORTS / "care_event_windows_normalized.csv", rows)
    return rows


def write_import_plan(manifest_rows: list[dict[str, Any]]) -> None:
    ready_count = sum(1 for row in manifest_rows if row["ready_for_scada_indicators"])
    hi_count = sum(1 for row in manifest_rows if row["ready_for_hi_input"])
    content = f"""# CARE 主时间线接入计划

## 当前状态

CARE 已生成规范化事件级 SCADA 文件，位置为：

`{NORMALIZED_DIR}`

本目录包含 95 个事件 CSV。每个文件保留 `timestamp`、`source_turbine_id`、`event_id`、`event_label`、`status_type_id`、`train_test` 和项目标准 SCADA 字段。当前有 {ready_count} 个事件文件具备风速和功率字段，可用于 SCADA 运行指标；{hi_count} 个事件文件具备 HI 输入所需的基础 SCADA 与温度字段。

## 数据边界

CARE 风机 ID、时间戳和传感器均为匿名数据。当前不能把 CARE 资产映射成真实经纬度、真实机型或真实额定功率，也不能与 NREL、Mendeley、DTU、YOLO 样本伪造成同一台风机的完整证据链。

## 入库约束

现有 `SCADARecord` 表要求绑定项目内 `turbine_id`。直接把 36 个 CARE 匿名资产写入现有真实风机表会造成事实混淆。因此入库前需要二选一：

1. 增加匿名 CARE 资产台账表或扩展 Turbine 模型，允许 `source_dataset`、`source_asset_id`、`geo_scope=anonymous` 且经纬度为空。
2. 由用户提供真实风机台账，并明确 CARE 是否允许映射到该台账。没有明确来源时不能映射。

## 可执行导入前提

当数据库支持匿名资产后，规范化 CSV 可用现有 SCADA 导入器读取，因为字段名已经对齐：

```powershell
python -m scripts.import_real_datasets scada-csv `
  --path <normalized_event_csv> `
  --dataset-id care_to_compare_v6 `
  --turbine-id <匿名资产对应的内部ID> `
  --timestamp-column timestamp `
  --power-column power_kw `
  --wind-speed-column wind_speed_ms `
  --rotor-rpm-column rotor_rpm `
  --gen-temperature-column gen_temperature_c `
  --gearbox-temperature-column gearbox_temperature_c `
  --bearing-temperature-column bearing_temperature_c `
  --pitch-angle-column pitch_angle_deg `
  --nacelle-direction-column nacelle_direction_deg `
  --grid-frequency-column grid_frequency_hz `
  --ambient-temperature-column ambient_temp_c `
  --source-turbine-column source_turbine_id
```

## 下一步开发

1. 将数据库资产模型改为支持匿名公开数据资产，避免伪造经纬度和机型。
2. 基于 `care_normalized_event_manifest.csv` 建立入库批次日志和字段映射版本。
3. 用正常事件窗口拟合功率曲线与温度基线，再计算 HI 分项。
4. 用 anomaly 事件窗口做 RUL 风险趋势验证，不声称工业级寿命预测已经完成。
"""
    (REPORTS / "CARE_MODELING_IMPORT_PLAN.md").write_text(content, encoding="utf-8")


def main() -> None:
    if not CARE_ROOT.exists():
        raise FileNotFoundError(CARE_ROOT)

    if NORMALIZED_DIR.exists():
        shutil.rmtree(NORMALIZED_DIR)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    events = load_event_info()
    feature_descriptions = load_feature_descriptions()
    mapping_rows = build_mapping_rows(feature_descriptions)
    write_csv(REPORTS / "care_standard_field_mapping.csv", mapping_rows)
    event_window_rows = write_event_windows(events)

    manifest_rows: list[dict[str, Any]] = []
    chunksize = 50_000
    for farm_dir in sorted(path for path in CARE_ROOT.iterdir() if path.is_dir()):
        farm = farm_dir.name
        mapping = CARE_FIELD_MAPPINGS.get(farm, {})
        for csv_path in sorted((farm_dir / "datasets").glob("*.csv"), key=lambda p: int(p.stem)):
            event_id = int(csv_path.stem)
            event_meta = events.get((farm, event_id))
            if not event_meta:
                event_meta = {
                    "wind_farm": farm,
                    "source_asset_id": None,
                    "event_id": event_id,
                    "event_label": None,
                    "event_start": None,
                    "event_end": None,
                    "event_component_category": "missing_event_info",
                }
            out_path = NORMALIZED_DIR / sanitize_name(farm) / f"event_{event_id}.csv"
            manifest_rows.append(write_normalized_event(csv_path, out_path, farm, event_meta, mapping, chunksize))

    write_csv(REPORTS / "care_normalized_event_manifest.csv", manifest_rows)
    status_rows = []
    for row in manifest_rows:
        for status, count in row["status_type_counts"].items():
            status_rows.append({
                "dataset_id": row["dataset_id"],
                "wind_farm": row["wind_farm"],
                "event_id": row["event_id"],
                "event_label": row["event_label"],
                "status_type_id": status,
                "row_count": count,
            })
    write_csv(REPORTS / "care_status_type_distribution.csv", status_rows)
    write_import_plan(manifest_rows)

    summary = {
        "generated_at": now_iso(),
        "dataset_id": "care_to_compare_v6",
        "normalized_root": str(NORMALIZED_DIR),
        "event_window_rows": len(event_window_rows),
        "normalized_event_files": len(manifest_rows),
        "total_normalized_rows": sum(int(row["row_count"]) for row in manifest_rows),
        "ready_for_scada_indicator_files": sum(1 for row in manifest_rows if row["ready_for_scada_indicators"]),
        "ready_for_hi_input_files": sum(1 for row in manifest_rows if row["ready_for_hi_input"]),
        "ready_for_rul_window_files": sum(1 for row in manifest_rows if row["ready_for_rul_window"]),
        "outputs": {
            "care_standard_field_mapping": str(REPORTS / "care_standard_field_mapping.csv"),
            "care_event_windows_normalized": str(REPORTS / "care_event_windows_normalized.csv"),
            "care_normalized_event_manifest": str(REPORTS / "care_normalized_event_manifest.csv"),
            "care_status_type_distribution": str(REPORTS / "care_status_type_distribution.csv"),
            "care_modeling_import_plan": str(REPORTS / "CARE_MODELING_IMPORT_PLAN.md"),
        },
        "notes": [
            "Normalized event CSV files are generated from real CARE SCADA only.",
            "No coordinates, turbine models, business costs, work orders, or cross-dataset asset links were generated.",
            "Large normalized CSV files are under backend/data/modeling and are ignored by Git.",
        ],
    }
    (REPORTS / "care_modeling_dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
