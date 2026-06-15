"""Audit real dataset coverage for user stories and PHM indicators.

The audit is evidence-based: it reads the downloaded/curated real datasets and
existing requirement matrix, then writes lightweight reports under
reports/data_processing. It does not create synthetic data, labels, images,
costs, work orders, or diagnostic conclusions.
"""

from __future__ import annotations

import ast
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "data_processing"
CARE_ROOT = ROOT / "backend" / "data" / "curated_datasets" / "raw" / "scada" / "care_to_compare_v6" / "CARE_To_Compare"
USER_STORY_MATRIX = ROOT / "reports" / "user_story_data_requirements_updated.xlsx"


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


def parse_dict_cell(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def classify_care_feature(row: pd.Series) -> str:
    name = str(row.get("sensor_name", "")).lower()
    desc = str(row.get("description", "")).lower()
    unit = str(row.get("unit", "")).lower()
    text = f"{name} {desc} {unit}"

    if "wind speed" in text or "windspeed" in text or name.startswith("wind_speed"):
        return "wind_speed"
    if "active power" in text or name.startswith("power_"):
        return "active_power"
    if "reactive power" in text or name.startswith("reactive_power"):
        return "reactive_power"
    if "temperature" in text or "temp" in text or unit in {"celsius", "c"}:
        return "temperature"
    if "pitch" in text:
        return "pitch"
    if "yaw" in text or "nacelle direction" in text or "wind direction" in text or "absolute direction" in text:
        return "direction_yaw"
    if "rpm" in text or "rotor speed" in text or "generator speed" in text or "angle speed" in text:
        return "rotational_speed"
    if "bearing" in text:
        return "bearing"
    if "gearbox" in text or "gear oil" in text:
        return "gearbox"
    if "generator" in text:
        return "generator"
    if "transformer" in text:
        return "transformer"
    if "hydraulic" in text:
        return "hydraulic"
    if "voltage" in text or "current" in text:
        return "electrical"
    if bool(row.get("is_counter", False)):
        return "counter"
    return "other_sensor"


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


def build_care_feature_catalog() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for farm_dir in sorted(p for p in CARE_ROOT.iterdir() if p.is_dir()):
        path = farm_dir / "feature_description.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, sep=";")
        for _, row in df.iterrows():
            rows.append({
                "dataset_id": "care_to_compare_v6",
                "wind_farm": farm_dir.name,
                "sensor_name": row.get("sensor_name"),
                "statistics_type": row.get("statistics_type"),
                "description": row.get("description"),
                "unit": row.get("unit"),
                "is_angle": row.get("is_angle"),
                "is_counter": row.get("is_counter"),
                "feature_category": classify_care_feature(row),
            })
    return rows


def build_care_event_summary() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for farm_dir in sorted(p for p in CARE_ROOT.iterdir() if p.is_dir()):
        path = farm_dir / "event_info.csv"
        if not path.exists():
            continue
        df = pd.read_csv(path, sep=";")
        asset_col = "asset_id" if "asset_id" in df.columns else "asset"
        event_categories = Counter(classify_event(value) for value in df.get("event_description", []))
        labels = Counter(str(value) for value in df.get("event_label", []))
        rows.append({
            "dataset_id": "care_to_compare_v6",
            "wind_farm": farm_dir.name,
            "event_count": len(df),
            "anomaly_count": labels.get("anomaly", 0),
            "normal_count": labels.get("normal", 0),
            "asset_count": df[asset_col].nunique() if asset_col in df.columns else None,
            "event_category_counts": dict(sorted(event_categories.items())),
        })
    return rows


def collect_facts() -> dict[str, Any]:
    care_files = pd.read_csv(REPORTS / "care_scada_files.csv")
    vibration = pd.read_csv(REPORTS / "vibration_features.csv")
    images = pd.read_csv(REPORTS / "image_dataset_quality.csv")
    modeling_summary_path = REPORTS / "care_modeling_dataset_summary.json"
    modeling_summary: dict[str, Any] = {}
    if modeling_summary_path.exists():
        modeling_summary = json.loads(modeling_summary_path.read_text(encoding="utf-8"))
    import_summary_path = REPORTS / "care_scada_import_batch_summary.json"
    import_summary: dict[str, Any] = {}
    if import_summary_path.exists():
        import_summary = json.loads(import_summary_path.read_text(encoding="utf-8"))

    care_event_files = int((care_files["file_type"] == "event_dataset").sum()) if "file_type" in care_files.columns else 95
    care_metadata_files = int((care_files["file_type"] != "event_dataset").sum()) if "file_type" in care_files.columns else 6

    care_events = build_care_event_summary()
    care_features = build_care_feature_catalog()
    feature_counts = Counter(row["feature_category"] for row in care_features)
    event_count = sum(int(row["event_count"]) for row in care_events)
    anomaly_count = sum(int(row["anomaly_count"]) for row in care_events)
    normal_count = sum(int(row["normal_count"]) for row in care_events)
    asset_count = sum(int(row["asset_count"]) for row in care_events)

    vibration_counts = vibration.groupby("dataset_id").size().to_dict()
    vibration_labels = {
        dataset_id: dict(sorted(group["label"].fillna("unknown").astype(str).value_counts().to_dict().items()))
        for dataset_id, group in vibration.groupby("dataset_id")
    }

    image_profiles: dict[str, dict[str, Any]] = {}
    for _, row in images.iterrows():
        dataset_id = str(row.get("dataset_id"))
        image_profiles[dataset_id] = {
            "image_files": int(row.get("image_files") or 0),
            "label_files": int(row.get("label_files") or 0),
            "paired_image_label_count": int(row.get("paired_image_label_count") or 0)
            if not pd.isna(row.get("paired_image_label_count"))
            else None,
            "class_name_counts": parse_dict_cell(row.get("class_name_counts")),
        }

    return {
        "care_event_dataset_files": care_event_files,
        "care_metadata_files": care_metadata_files,
        "care_event_count": event_count,
        "care_anomaly_count": anomaly_count,
        "care_normal_count": normal_count,
        "care_asset_count": asset_count,
        "care_feature_category_counts": dict(sorted(feature_counts.items())),
        "vibration_counts": {str(key): int(value) for key, value in vibration_counts.items()},
        "vibration_labels": vibration_labels,
        "image_profiles": image_profiles,
        "care_modeling_summary": modeling_summary,
        "care_import_summary": import_summary,
    }


def build_dataset_capability_profile(facts: dict[str, Any]) -> list[dict[str, Any]]:
    yolo = facts["image_profiles"].get("yolo_annotated_wind_turbine_surface_damage", {})
    dtu = facts["image_profiles"].get("dtu_drone_inspection", {})
    care_modeling = facts.get("care_modeling_summary", {})
    normalized_note = (
        f"; normalized {care_modeling.get('normalized_event_files')} event files with "
        f"{care_modeling.get('total_normalized_rows')} rows"
        if care_modeling
        else ""
    )
    care_import = facts.get("care_import_summary", {})
    if care_import.get("dry_run") is False:
        import_note = (
            f"; imported {care_import.get('database_scada_records_for_dataset', care_import.get('rows_imported'))} "
            f"SCADA rows into SQLite with {care_import.get('anonymous_assets')} anonymous assets"
        )
    elif care_import.get("dry_run") is True:
        import_note = (
            f"; import dry-run passed for {care_import.get('files_ready')} files and "
            f"{care_import.get('estimated_import_rows')} estimated rows"
        )
    else:
        import_note = ""
    return [
        {
            "dataset_id": "care_to_compare_v6",
            "data_type": "SCADA time series and event windows",
            "available_evidence": (
                f"{facts['care_event_dataset_files']} event datasets; "
                f"{facts['care_event_count']} event_info rows; "
                f"{facts['care_anomaly_count']} anomaly and {facts['care_normal_count']} normal events; "
                f"{facts['care_asset_count']} farm-scoped anonymous asset references"
                f"{normalized_note}"
                f"{import_note}"
            ),
            "serves": "SCADA运行指标、数据质量、故障窗口、HI/RUL入口、数据源监控、离线建模",
            "limitations": "匿名数据；没有真实经纬度、真实风机型号、真实额定功率、业务工单和成本；导入时必须使用匿名资产模式；不能与振动/图像样本伪造成同一台风机证据",
            "coverage_level": "核心技术数据已标准化，支持匿名资产入库",
        },
        {
            "dataset_id": "nrel_grc_gearbox_cm",
            "data_type": "Gearbox vibration samples",
            "available_evidence": f"{facts['vibration_counts'].get('nrel_grc_gearbox_cm', 0)} processed MAT samples; labels {facts['vibration_labels'].get('nrel_grc_gearbox_cm', {})}",
            "serves": "齿轮箱振动波形、时域/频域指标、样本级故障诊断解释",
            "limitations": "不是 CARE 同一风机；当前未确认所有通道采样率；只能作为诊断样本库和算法演示来源",
            "coverage_level": "样本级覆盖",
        },
        {
            "dataset_id": "mendeley_blade_vibration_faults",
            "data_type": "Blade vibration samples",
            "available_evidence": f"{facts['vibration_counts'].get('mendeley_blade_vibration_faults', 0)} processed CSV/XLSX samples; labels {facts['vibration_labels'].get('mendeley_blade_vibration_faults', {})}",
            "serves": "叶片振动波形、时域/频域指标、样本级故障诊断解释",
            "limitations": "不是 CARE 同一风机；标签来自真实文件名/数据集结构，后续要保留来源说明",
            "coverage_level": "样本级覆盖",
        },
        {
            "dataset_id": "yolo_annotated_wind_turbine_surface_damage",
            "data_type": "Blade surface image detection samples",
            "available_evidence": f"{yolo.get('image_files', 0)} images; {yolo.get('label_files', 0)} YOLO label files; {yolo.get('paired_image_label_count', 0)} paired image-label samples; class counts {yolo.get('class_name_counts', {})}",
            "serves": "叶片图像损伤定位、bbox面积占比、图像诊断证据",
            "limitations": "类别以数据集 labels.txt 为准；不生成模型置信度；不代表 CARE 风机现场巡检历史",
            "coverage_level": "样本级覆盖",
        },
        {
            "dataset_id": "dtu_drone_inspection",
            "data_type": "Raw drone inspection images",
            "available_evidence": f"{dtu.get('image_files', 0)} raw images; labels {dtu.get('label_files', 0)}",
            "serves": "真实巡检图像展示、图像质量检查、来源追溯",
            "limitations": "没有检测标注；不能编造损伤类别或 bbox",
            "coverage_level": "图像展示覆盖，标注诊断缺失",
        },
        {
            "dataset_id": "era5_or_site_weather",
            "data_type": "External weather",
            "available_evidence": "not downloaded",
            "serves": "环境背景、RUL增强、页面解释",
            "limitations": "需要真实坐标和时间范围后再匹配；不能替代 SCADA 传感器",
            "coverage_level": "缺失，可后置",
        },
        {
            "dataset_id": "business_records",
            "data_type": "Work orders, costs, inventory, personnel",
            "available_evidence": "not available from public datasets",
            "serves": "成本决策、维护日历、工单闭环、备件采购",
            "limitations": "必须由系统真实操作积累或用户提供带来源记录；不能预置伪造历史",
            "coverage_level": "缺失，需要自建或导入",
        },
    ]


def build_indicator_coverage(facts: dict[str, Any]) -> list[dict[str, Any]]:
    care_modeling = facts.get("care_modeling_summary", {})
    care_import = facts.get("care_import_summary", {})
    normalized_summary = (
        f"CARE 已规范化 {care_modeling.get('normalized_event_files')} 个事件文件、"
        f"{care_modeling.get('total_normalized_rows')} 行"
        if care_modeling
        else "CARE 文件级摘要"
    )
    if care_import.get("dry_run") is False:
        db_import_summary = (
            f"CARE 已入库 {care_import.get('database_scada_records_for_dataset', care_import.get('rows_imported'))} 条 SCADA 记录、"
            f"{care_import.get('anonymous_assets')} 个匿名资产，并保留批次日志"
        )
        data_quality_pending = "传感器异常值分布、页面级质量聚合和阈值标定"
        scada_pending = "真实额定功率、真实机型、真实地理位置和正常基线标定"
    else:
        db_import_summary = normalized_summary
        data_quality_pending = "导入批次级质量日志、数据库记录数校验、传感器异常值分布和页面级质量聚合"
        scada_pending = "全量入库批次执行、真实额定功率、真实机型、真实地理位置和正常基线标定"
    return [
        {
            "indicator_group": "数据质量评分",
            "coverage_level": "部分覆盖",
            "covered_by": "CARE 文件结构、时间戳字段、行数；YOLO 图像/标签配对；振动样本可读性",
            "can_compute_now": f"文件级完整性、SCADA 行级时间戳有效率、标准字段非空计数、图像标注配对率、振动特征行数；{db_import_summary}",
            "missing_or_pending": data_quality_pending,
        },
        {
            "indicator_group": "SCADA运行指标",
            "coverage_level": "部分覆盖",
            "covered_by": f"CARE feature_description categories {facts['care_feature_category_counts']}",
            "can_compute_now": f"运行状态、事件窗口、风速、功率、转速、温度、桨距、方向等标准字段已可计算；{db_import_summary}",
            "missing_or_pending": scada_pending,
        },
        {
            "indicator_group": "振动诊断指标",
            "coverage_level": "已覆盖",
            "covered_by": "NREL 齿轮箱 MAT；Mendeley 叶片振动 CSV/XLSX",
            "can_compute_now": "RMS、峰值、峰峰值、标准差、偏度、峭度、波峰因子、脉冲因子、形状因子、裕度因子、主频/主频bin",
            "missing_or_pending": "NREL 采样率和更多通道选择策略；阈值标定；诊断 API 接入",
        },
        {
            "indicator_group": "叶片图像损伤指标",
            "coverage_level": "已覆盖",
            "covered_by": "YOLO 标注图像；DTU 原始巡检图像",
            "can_compute_now": "真实图像展示、YOLO bbox、类别 dirt/damage、bbox面积占比、标注配对率",
            "missing_or_pending": "模型训练/推理置信度；DTU 无标注；严重度阈值需标定",
        },
        {
            "indicator_group": "健康指数 HI",
            "coverage_level": "部分覆盖",
            "covered_by": "CARE SCADA、振动特征、图像 bbox 指标",
            "can_compute_now": "CARE 标准化 SCADA 可支持功率、温度、运行状态分项；振动和图像可支持样本级分项",
            "missing_or_pending": "权重、阈值、跨源资产关联边界、数据库入库后的统一计算",
        },
        {
            "indicator_group": "故障贡献排序",
            "coverage_level": "部分覆盖",
            "covered_by": "CARE 事件窗口、振动特征、YOLO bbox 指标",
            "can_compute_now": "基于来源明确的规则型证据排序",
            "missing_or_pending": "训练后的特征贡献、SHAP/模型解释、历史阈值验证",
        },
        {
            "indicator_group": "RUL预测",
            "coverage_level": "部分覆盖",
            "covered_by": "CARE 长期 SCADA 时间序列和事件窗口",
            "can_compute_now": "风险趋势、事件前窗口、HI 趋势入口；CARE 事件窗口已规范化",
            "missing_or_pending": "真实维修记录、失效阈值、寿命终点定义、工业级验证",
        },
        {
            "indicator_group": "维护成本决策",
            "coverage_level": "缺失",
            "covered_by": "当前无真实业务成本数据",
            "can_compute_now": "公式框架和用户输入参数计算",
            "missing_or_pending": "人工、备件、停机、电价、外包、库存、历史工单等真实业务数据",
        },
        {
            "indicator_group": "工单优先级",
            "coverage_level": "部分覆盖",
            "covered_by": "诊断/RUL/HI 可作为风险输入",
            "can_compute_now": "规则框架",
            "missing_or_pending": "真实工单、人员、库存、备件、SLA 和业务权重",
        },
        {
            "indicator_group": "数据源监控与页面总结",
            "coverage_level": "部分覆盖",
            "covered_by": "本地数据清单、处理摘要、质量报告、业务 API",
            "can_compute_now": "下载/解压/处理状态、缺失项说明、页面数据来源说明",
            "missing_or_pending": "导入批次日志、数据库记录数、字段映射版本、页面级数据质量聚合",
        },
    ]


def build_user_story_coverage(facts: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    stories = pd.read_excel(USER_STORY_MATRIX, sheet_name=0)
    care_import = (facts or {}).get("care_import_summary", {})
    if care_import.get("dry_run") is False:
        care_db_evidence = (
            f"CARE 已完成匿名资产入库："
            f"{care_import.get('database_scada_records_for_dataset', care_import.get('rows_imported'))} 条 SCADA 记录、"
            f"{care_import.get('anonymous_assets')} 个匿名资产；仍缺真实坐标、机型、额定功率和现场台账。"
        )
    else:
        care_db_evidence = "CARE 已规范化匿名 asset_id、timestamp、status_type_id，并支持匿名资产入库；仍缺真实坐标、机型、额定功率和现场台账。"
    coverage_by_story = {
        "US01": ("部分覆盖", care_db_evidence),
        "US02": ("部分覆盖", "CARE 可支持状态和后续 HI；缺机型、额定功率、区域标签、投运信息等真实台账字段。"),
        "US03": ("部分覆盖", f"{care_db_evidence} CARE 已映射风速、功率、转速、温度、桨距、方向等字段；ERA5/现场气象未接入。"),
        "US04": ("部分覆盖", "CARE 事件窗口已规范化；NREL/Mendeley 有振动样本；YOLO 有图像标注；模型置信度和跨源融合尚未实现。"),
        "US05": ("已覆盖", "YOLO 有真实图像、真实 bbox、类别 dirt/damage；DTU 有真实巡检图像但无标注。"),
        "US06": ("已覆盖", "NREL/Mendeley 原始振动数据已整理，并已计算 55 行首批时域/频域特征。"),
        "US07": ("部分覆盖", "有可解释指标输入，但贡献排序算法、权重、SHAP 或历史阈值仍待建立。"),
        "US08": ("部分覆盖", "CARE 长期 SCADA 和事件窗口已标准化，可做风险趋势入口；缺维修记录、寿命终点和工业级 RUL 验证。"),
        "US09": ("缺失", "公开数据集不提供真实成本、备件、人工、停机损失；只能等待用户录入或真实业务导入。"),
        "US10": ("部分覆盖", "诊断/RUL 风险输入可逐步形成；备件、库存、采购周期、人员排班和天气窗口缺失。"),
        "US11": ("缺失", "真实工单流程数据应由系统操作积累或用户导入；不能沿用 demo 工单。"),
        "US12": ("部分覆盖", "阈值配置可先做系统配置；HI 输出、阈值版本和误报漏报统计要等真实指标运行后沉淀。"),
        "US13": ("部分覆盖", "可以总结真实数据状态和缺失项；完整页面摘要依赖各模块 API 入库和质量标记。"),
        "US14": ("部分覆盖", f"{care_db_evidence} 已有真实数据源、处理摘要、字段映射、规范化清单、质量报告和入库批次日志。"),
    }
    rows: list[dict[str, Any]] = []
    for _, story in stories.iterrows():
        story_id = str(story.iloc[0])
        level, evidence = coverage_by_story.get(story_id, ("待评估", "未在覆盖规则中定义"))
        rows.append({
            "story_id": story_id,
            "user_story": story.iloc[1],
            "coverage_level": level,
            "evidence": evidence,
            "must_data": story.iloc[3],
            "gap_action": {
                "已覆盖": "接入后端 API 和前端展示，保留来源字段",
                "部分覆盖": "先完成字段映射、入库和指标标定，再开放完整功能",
                "缺失": "从空状态开始，由系统真实积累或用户提供带来源数据",
            }.get(level, "继续核查"),
            "boundary": story.iloc[7],
        })
    return rows


def markdown_table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")).replace("\n", " ") for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def write_markdown_report(
    facts: dict[str, Any],
    dataset_profile: list[dict[str, Any]],
    indicator_coverage: list[dict[str, Any]],
    story_coverage: list[dict[str, Any]],
) -> None:
    covered = sum(1 for row in story_coverage if row["coverage_level"] == "已覆盖")
    partial = sum(1 for row in story_coverage if row["coverage_level"] == "部分覆盖")
    missing = sum(1 for row in story_coverage if row["coverage_level"] == "缺失")
    content = f"""# 数据集覆盖评估

## 评估结论

现有真实数据集可以覆盖大部分技术类功能的样本演示和首批指标计算，但不能完整覆盖业务闭环。14 个用户故事中，已覆盖 {covered} 个，部分覆盖 {partial} 个，缺失 {missing} 个。缺口主要集中在真实风机台账/地理坐标、ERA5 或现场气象、工单、成本、备件、库存、人员排班和维护历史。

必须保留事实边界：CARE 是匿名 SCADA 主时间线；NREL/Mendeley 是振动诊断样本库；YOLO/DTU 是图像诊断与巡检图像样本库。它们不能被伪造成同一台风机、同一时间、同一故障的完整证据链。

## 关键数据事实

- CARE：{facts['care_event_dataset_files']} 个事件时间序列文件，{facts['care_metadata_files']} 个元数据文件，事件表共 {facts['care_event_count']} 条，其中 anomaly {facts['care_anomaly_count']} 条、normal {facts['care_normal_count']} 条。
- CARE 规范化：`{json.dumps(facts.get('care_modeling_summary', {}), ensure_ascii=False)}`。
- CARE 入库：`{json.dumps(facts.get('care_import_summary', {}), ensure_ascii=False)}`。
- CARE 字段类别：`{json.dumps(facts['care_feature_category_counts'], ensure_ascii=False)}`。
- 振动样本：`{json.dumps(facts['vibration_counts'], ensure_ascii=False)}`。
- 图像样本：`{json.dumps(facts['image_profiles'], ensure_ascii=False)}`。

## 数据集能力画像

{markdown_table(dataset_profile, ["dataset_id", "coverage_level", "serves", "available_evidence", "limitations"])}

## 建模指标覆盖

{markdown_table(indicator_coverage, ["indicator_group", "coverage_level", "can_compute_now", "missing_or_pending"])}

## 用户故事覆盖

{markdown_table(story_coverage, ["story_id", "user_story", "coverage_level", "evidence", "gap_action"])}

## 开发优先级

1. CARE 字段语义映射和主时间线入库：先解决 US01、US02、US03、US08、US14 的数据底座。
2. 振动与图像样本库接入诊断页面：先解决 US04、US05、US06、US07 的真实证据展示。
3. HI 与贡献排序做规则型版本：先输出来源明确的分项分数，不写死未标定权重。
4. RUL 先做风险趋势和事件窗口解释：不声称工业级寿命预测已经完成。
5. 业务数据从空状态开始：工单、成本、库存、人员排班必须由系统真实积累或用户导入。
"""
    (REPORTS / "DATASET_COVERAGE_ASSESSMENT.md").write_text(content, encoding="utf-8")


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    care_feature_catalog = build_care_feature_catalog()
    care_event_summary = build_care_event_summary()
    write_csv(REPORTS / "care_feature_catalog.csv", care_feature_catalog)
    write_csv(REPORTS / "care_event_summary.csv", care_event_summary)

    facts = collect_facts()
    dataset_profile = build_dataset_capability_profile(facts)
    indicator_coverage = build_indicator_coverage(facts)
    story_coverage = build_user_story_coverage(facts)

    write_csv(REPORTS / "dataset_capability_profile.csv", dataset_profile)
    write_csv(REPORTS / "modeling_indicator_dataset_coverage.csv", indicator_coverage)
    write_csv(REPORTS / "user_story_dataset_coverage.csv", story_coverage)
    write_markdown_report(facts, dataset_profile, indicator_coverage, story_coverage)

    print(json.dumps({
        "dataset_profiles": len(dataset_profile),
        "indicator_rows": len(indicator_coverage),
        "user_story_rows": len(story_coverage),
        "care_feature_rows": len(care_feature_catalog),
        "care_event_summary_rows": len(care_event_summary),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
