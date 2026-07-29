from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import re
from uuid import uuid4

from sqlalchemy import select

from app.database import get_db
from app.models import BladeImage, Fault, FaultKnowledgeNode, FaultSignal, SCADARecord, Turbine, User, VibrationData, WorkOrder
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
    AutoFaultDetectionRequest, AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest, BatchAutoFaultDetectionResponse, BatchAutoFaultRecord,
    DiagnosisSignalInsight, TroubleshootingStep, VibrationPreviewResponse,
)
from app.api.auth import get_current_user, require_role
from app.services.blade_yolo_service import BladeModelUnavailable, blade_yolo_service
from app.services.care_monitoring_metrics import ANOMALY_STATUS_IDS, CARE_DATASET_ID
from app.services.diagnosis_orchestrator import build_signal_insights, build_troubleshooting_steps

router = APIRouter(dependencies=[Depends(get_current_user)])
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_BLADE_IMAGE_DIR = DATA_DIR / "curated_datasets" / "raw" / "blade_images"
UPLOAD_BLADE_IMAGE_DIR = DATA_DIR / "uploads" / "blade_diagnosis"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_UPLOAD_IMAGE_MB = 50
INSPECTION_TURBINE_SLOTS = 36


def _data_url(relative_path: str) -> str:
    return f"/data/{quote(relative_path, safe='/')}"


def _resolve_data_file(relative_path: str) -> Path:
    candidate = (DATA_DIR / relative_path).resolve()
    data_root = DATA_DIR.resolve()
    if not candidate.is_relative_to(data_root):
        raise HTTPException(status_code=400, detail="Invalid data path")
    return candidate


def _blade_model_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BladeModelUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="Blade image file not found")
    return HTTPException(status_code=500, detail=f"Blade YOLO inference failed: {exc}")


def _source_dataset_from_path(path: Path) -> str:
    parts = set(path.parts)
    if "dtu_drone_inspection" in parts:
        return "dtu_drone_inspection"
    if "yolo_annotated_wind_turbine_surface_damage" in parts:
        return "yolo_annotated_wind_turbine_surface_damage"
    return "blade_image_dataset"


def _resolve_vibration_source_dataset(payload: dict, record: VibrationData) -> str | None:
    quality = payload.get("quality") or {}
    source_file = str(quality.get("source_file") or "").lower()
    waveform_path = str(record.waveform_path or "").lower()

    if "mendeley" in source_file or "blade_vibration" in source_file:
        return "mendeley_blade_vibration_faults"
    if "nrel" in source_file or "gearbox" in source_file:
        return "nrel_gearbox_vibration"
    if "care_reference_waveforms" in waveform_path:
        return "care_reference_waveforms"

    source_dataset = quality.get("source_dataset")
    if source_dataset == "care_public_vibration_reference":
        return "care_reference_waveforms"
    return source_dataset


def _normalized_dtu_stem(path: Path) -> str:
    return re.sub(r"\s*\(\d+\)$", "", path.stem)


def _blade_campaign(path: Path) -> str | None:
    return next((part for part in path.parts if part.startswith("Nordtank ")), None)


@lru_cache(maxsize=1)
def _dtu_blade_catalog() -> list[dict]:
    dtu_dir = RAW_BLADE_IMAGE_DIR / "dtu_drone_inspection"
    if not dtu_dir.exists():
        return []

    paths = [
        path
        for path in sorted(dtu_dir.rglob("*"))
        if path.suffix.lower() in IMAGE_EXTS
    ]

    catalog: list[dict] = []
    for path in paths:
        key = _normalized_dtu_stem(path)
        rel_path = path.relative_to(DATA_DIR).as_posix()
        campaign = _blade_campaign(path)
        catalog.append({
            "image_path": rel_path,
            "image_url": _data_url(rel_path),
            "source_dataset": "dtu_drone_inspection",
            "view": campaign or "DTU 原始巡检",
            "diagnosis_type": "inspection_image",
            "has_damage": False,
            "timestamp": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
            "frame_label": key,
            "campaign": campaign,
        })
    return catalog

@lru_cache(maxsize=1)
def _raw_blade_catalog() -> list[dict]:
    dtu_catalog = _dtu_blade_catalog()
    if dtu_catalog:
        return dtu_catalog

    catalog: list[dict] = []
    for path in sorted(RAW_BLADE_IMAGE_DIR.rglob("*")):
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        rel_path = path.relative_to(DATA_DIR).as_posix()
        label_path = path.with_suffix(".txt")
        label_lines: list[str] = []
        if label_path.exists():
            try:
                label_lines = [line.strip() for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            except UnicodeDecodeError:
                label_lines = []
        catalog.append({
            "image_path": rel_path,
            "image_url": _data_url(rel_path),
            "source_dataset": _source_dataset_from_path(path),
            "view": path.parent.name,
            "diagnosis_type": "surface_damage" if label_lines else "inspection_image",
            "has_damage": bool(label_lines),
            "timestamp": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return catalog


@lru_cache(maxsize=1)
def _blade_inspection_slots() -> tuple[tuple[dict, ...], ...]:
    catalog = _raw_blade_catalog()
    if not catalog:
        return tuple(tuple() for _ in range(INSPECTION_TURBINE_SLOTS))

    grouped: dict[str, list[dict]] = {}
    for item in catalog:
        grouped.setdefault(str(item.get("frame_label") or item["image_path"]), []).append(item)

    slots: list[list[dict]] = [[] for _ in range(INSPECTION_TURBINE_SLOTS)]
    slot_stems: list[set[str]] = [set() for _ in range(INSPECTION_TURBINE_SLOTS)]
    for group_index, stem in enumerate(sorted(grouped)):
        group = grouped[stem]
        for copy_index, item in enumerate(group):
            preferred_start = (group_index + copy_index) % INSPECTION_TURBINE_SLOTS
            candidates = sorted(
                range(INSPECTION_TURBINE_SLOTS),
                key=lambda slot: (
                    stem in slot_stems[slot],
                    len(slots[slot]),
                    (slot - preferred_start) % INSPECTION_TURBINE_SLOTS,
                ),
            )
            slot = candidates[0]
            slots[slot].append(item)
            slot_stems[slot].add(stem)

    return tuple(tuple(slot) for slot in slots)


def _raw_blade_inspection_images(turbine_id: int) -> list[dict]:
    slots = _blade_inspection_slots()
    if not slots:
        return []

    slot_index = (turbine_id - 1) % INSPECTION_TURBINE_SLOTS
    slot_items = list(slots[slot_index])
    image_count = len(slot_items)
    inspection_id = f"dtu-inspection-slot-{slot_index + 1:02d}"
    images: list[dict] = []
    for image_index, source in enumerate(slot_items):
        item = dict(source)
        item["inspection_id"] = inspection_id
        item["inspection_slot"] = slot_index + 1
        item["image_index"] = image_index
        item["image_count"] = image_count
        item["quality"] = {
            "display_mode": "inspection_album",
            "allocation": "all_dtu_images_balanced_across_36_slots",
        }
        images.append(item)
    return images


def _parse_extra(extra) -> dict:
    if isinstance(extra, dict):
        return extra
    if isinstance(extra, str) and extra:
        try:
            parsed = json.loads(extra)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_dt(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _confidence_interval(confidence: float) -> list[float]:
    return [round(max(0.0, confidence - 0.06), 2), round(min(1.0, confidence + 0.04), 2)]


def _severity_from_priority(priority: str) -> str:
    if priority == "high":
        return "high"
    if priority == "low":
        return "low"
    return "medium"


def _processing_status(fault: Fault, work_order: WorkOrder | None) -> str:
    if work_order:
        if work_order.status in {"completed", "closed"}:
            return "closed"
        if work_order.status == "cancelled":
            return "failed"
        if work_order.status in {"in_progress", "review"}:
            return "processing"
        if work_order.status == "assigned":
            return "assigned"
        return "pending"
    if fault.status in {"closed", "resolved"}:
        return "closed"
    return "pending"


def _priority_from_fault(fault: Fault, work_order: WorkOrder | None) -> str:
    if work_order and work_order.priority:
        return work_order.priority
    if fault.confidence >= 0.9:
        return "urgent"
    if fault.confidence >= 0.8:
        return "high"
    if fault.confidence < 0.6:
        return "low"
    return "medium"


def _fault_status_note(work_order: WorkOrder | None) -> str:
    if not work_order:
        return "未关联工单"
    if work_order.status == "cancelled":
        return "关联工单已取消"
    if work_order.status in {"completed", "closed"}:
        return "关联工单已完成"
    return "已关联工单"


def _care_fault_type(turbine: Turbine, vibration_payload: dict | None = None) -> str:
    fault_info = (vibration_payload or {}).get("fault_info") or {}
    source_type = str(fault_info.get("type") or "").strip().lower()
    if source_type:
        return source_type
    if turbine.status in {"fault", "warning"}:
        return "care_scada_anomaly"
    return "no_fault_detected"


def _spectrum_from_waveform(waveform: list[float], sample_rate_hz: int, max_bins: int = 120) -> list[float]:
    if not waveform:
        return []

    n = len(waveform)
    usable_bins = min(max_bins, max(1, n // 2))
    mean_value = sum(waveform) / n
    centered = [float(value) - mean_value for value in waveform]
    spectrum: list[float] = []
    for k in range(1, usable_bins + 1):
        real = 0.0
        imag = 0.0
        for index, value in enumerate(centered):
            angle = 2.0 * math.pi * k * index / n
            real += value * math.cos(angle)
            imag -= value * math.sin(angle)
        spectrum.append(round((real * real + imag * imag) ** 0.5 / n, 8))
    return spectrum


def _load_vibration_payload(record: VibrationData) -> dict:
    if not record.waveform_path:
        return {}
    path = (DATA_DIR / record.waveform_path).resolve()
    if not path.is_relative_to(DATA_DIR.resolve()):
        return {}
    if not path.exists():
        return {}
    stat = path.stat()
    return _load_vibration_payload_file(str(path), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=128)
def _load_vibration_payload_file(path: str, _mtime_ns: int, _size: int) -> dict:
    """Parse an immutable imported waveform once per file revision."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _downsample_series(values: list, max_points: int) -> list[float]:
    """Preserve the full time span while bounding browser payload/render cost."""
    numeric = [float(value) for value in values]
    if len(numeric) <= max_points:
        return numeric
    if max_points <= 1:
        return numeric[:1]
    last_index = len(numeric) - 1
    return [
        numeric[round(index * last_index / (max_points - 1))]
        for index in range(max_points)
    ]


def _public_quality_fields(quality: dict | None) -> dict | None:
    if not quality:
        return None
    allowed = {
        "source_dataset",
        "source_file",
        "source_channel",
        "source_label",
        "label_source",
        "completeness_pct",
    }
    return {key: value for key, value in quality.items() if key in allowed}


async def _select_vibration_record(
    db: AsyncSession,
    turbine_id: int,
    component: str | None,
) -> VibrationData | None:
    q = select(VibrationData).where(VibrationData.turbine_id == turbine_id)
    if component:
        exact = await db.execute(q.where(VibrationData.component == component).order_by(VibrationData.timestamp.desc()))
        record = exact.scalars().first()
        if record:
            return record
    result = await db.execute(q.order_by(VibrationData.timestamp.desc()))
    return result.scalars().first()


async def _latest_scada_window(db: AsyncSession, turbine_id: int, limit: int = 144) -> list[SCADARecord]:
    result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == turbine_id)
        .order_by(SCADARecord.timestamp.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


def _scada_anomaly_summary(rows: list[SCADARecord]) -> dict:
    if not rows:
        return {"total": 0, "anomaly": 0, "ratio": 0.0, "latest": None}

    anomaly = 0
    for row in rows:
        extra = _parse_extra(row.extra)
        label = str(extra.get("event_label") or "").lower()
        status_type_id = str(extra.get("status_type_id") or "")
        if label == "anomaly" or status_type_id in ANOMALY_STATUS_IDS:
            anomaly += 1
    latest = rows[0]
    return {
        "total": len(rows),
        "anomaly": anomaly,
        "ratio": anomaly / max(len(rows), 1),
        "latest": latest,
    }


async def _rms_percentile_reference(db: AsyncSession, component: str, percentile: float = 0.75) -> float | None:
    result = await db.execute(select(VibrationData.rms).where(VibrationData.component == component))
    values = sorted(float(value) for value in result.scalars().all() if value is not None)
    if not values:
        return None
    index = min(len(values) - 1, max(0, int(round((len(values) - 1) * percentile))))
    return values[index]


async def _build_vibration_preview(
    db: AsyncSession,
    turbine_id: int,
    component: str,
    fault_type: str | None = None,
) -> dict:
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    record = await _select_vibration_record(db, turbine_id, component)
    if not record:
        raise HTTPException(status_code=404, detail="No imported vibration data for this turbine")

    payload = _load_vibration_payload(record)
    waveform = [float(value) for value in payload.get("waveform", [])]
    sample_rate_hz = int(payload.get("sample_rate_hz") or 1000)
    spectrum = payload.get("spectrum") or _spectrum_from_waveform(waveform, sample_rate_hz)
    timestamp = _parse_dt(payload.get("timestamp")) or record.timestamp
    source_dataset = _resolve_vibration_source_dataset(payload, record)
    quality = _public_quality_fields(payload.get("quality") if isinstance(payload.get("quality"), dict) else None)

    return {
        "turbine_id": turbine_id,
        "component": record.component,
        "timestamp": timestamp,
        "duration_seconds": float(payload.get("duration_seconds") or (len(waveform) / max(sample_rate_hz, 1))),
        "sample_rate_hz": sample_rate_hz,
        "sample_count": int(payload.get("sample_count") or len(waveform)),
        "rms": float(payload.get("rms", record.rms or 0.0)),
        "waveform": waveform,
        "spectrum": spectrum,
        "peak_frequencies": payload.get("peak_frequencies", []),
        "fault_detected": bool(payload.get("fault_detected", False)),
        "quality": quality,
        "source_dataset": source_dataset,
        "data_source": payload.get("data_source", "imported_dataset"),
        "waveform_path": record.waveform_path,
        "peak_freq_hz": record.peak_freq_hz,
        "algorithm_status": "imported_vibration_dataset",
        "message": f"振动波形来自 {source_dataset or 'imported vibration dataset'}，频谱由当前波形窗口计算。",
    }


async def _diagnosis_steps(db: AsyncSession, fault_type: str, signals: list) -> list[TroubleshootingStep]:
    """Get troubleshooting steps from fault knowledge base, with fallback."""
    if fault_type == "no_fault_detected":
        return [
            TroubleshootingStep(order=1, title="保持监测", action="继续观察CARE SCADA与振动窗口的变化。", expected_effect="确认当前窗口是否稳定。"),
        ]
    # Query DB knowledge base
    from app.services.diagnosis_orchestrator import build_troubleshooting_steps
    return await build_troubleshooting_steps(db, fault_type, signals)


async def _build_dataset_detection(db: AsyncSession, turbine: Turbine, component: str, window_hours: int) -> dict:
    vibration = None
    vibration_payload = None
    try:
        vibration = await _build_vibration_preview(db, turbine.id, component)
        record = await _select_vibration_record(db, turbine.id, component)
        vibration_payload = _load_vibration_payload(record) if record else None
    except HTTPException:
        vibration = None

    scada_rows = await _latest_scada_window(db, turbine.id, max(1, int(window_hours * 6)))
    scada_summary = _scada_anomaly_summary(scada_rows)
    source_dataset = (vibration or {}).get("source_dataset") or turbine.source_dataset
    fault_type = _care_fault_type(turbine, vibration_payload)
    has_fault = (
        bool((vibration or {}).get("fault_detected"))
        or turbine.status in {"warning", "fault"}
        or scada_summary["anomaly"] > 0
    )

    if has_fault:
        status = "suspected_fault"
        confidence = 0.55
        if vibration and vibration.get("fault_detected"):
            confidence += 0.18
        if turbine.status == "warning":
            confidence += 0.08
        if turbine.status == "fault":
            confidence += 0.16
        confidence += min(0.12, scada_summary["ratio"] * 0.4)
        confidence = round(min(0.94, confidence), 2)
    else:
        status = "no_fault_detected"
        confidence = round(0.72 if turbine.hi_value >= 85 else 0.62, 2)

    signals: list[DiagnosisSignalInsight] = []
    if vibration:
        rms_ref = await _rms_percentile_reference(db, vibration["component"])
        rms_range = f"同批P75 {rms_ref:.6f}" if rms_ref is not None else "同批样本待补充"
        signals.append(DiagnosisSignalInsight(
            sensor_name="振动RMS",
            value=f"{vibration['rms']:.6f}",
            normal_range=rms_range,
            contribution_score=0.82 if vibration.get("fault_detected") else 0.42,
            priority="high" if vibration.get("fault_detected") else "medium",
            finding=f"来自 {source_dataset or 'imported vibration dataset'} 的振动窗口。",
        ))
        peaks = vibration.get("peak_frequencies") or []
        if peaks:
            first_peak = peaks[0]
            signals.append(DiagnosisSignalInsight(
                sensor_name="主频峰值",
                value=f"{float(first_peak.get('frequency_hz', 0.0)):.1f} Hz",
                normal_range="按导入波形频谱计算",
                contribution_score=0.68,
                priority="medium",
                finding="主频来自当前振动波形窗口的频谱结果。",
            ))

    signals.append(DiagnosisSignalInsight(
        sensor_name="HI健康指数",
        value=f"{float(turbine.hi_value or 0.0):.1f}",
        normal_range=f">=80正常, 60-79预警, <60故障 (异常标记: {', '.join(sorted(ANOMALY_STATUS_IDS))})",
        contribution_score=0.9 if turbine.status == "fault" else 0.65 if turbine.status == "warning" else 0.28,
        priority="high" if turbine.status == "fault" else "medium" if turbine.status == "warning" else "low",
        finding=f"HI来自CARE SCADA窗口4维罚分计算; 状态={turbine.status}",
    ))
    signals.append(DiagnosisSignalInsight(
        sensor_name="SCADA异常窗口",
        value=f"{scada_summary['anomaly']}/{scada_summary['total']} (占比{scada_summary['ratio']:.1%})",
        normal_range=f"异常标记status_type_id∈{{{','.join(sorted(ANOMALY_STATUS_IDS))}}}时应为0",
        contribution_score=round(min(0.9, 0.25 + scada_summary["ratio"]), 3),
        priority="high" if scada_summary["ratio"] > 0.3 else "medium" if scada_summary["anomaly"] else "low",
        finding=f"CARE SCADA event_label/status_type_id最近{scada_summary['total']}窗口异常统计。",
    ))

    return {
        "turbine_id": turbine.id,
        "component": vibration["component"] if vibration else component,
        "analysis_window_hours": window_hours,
        "status": status,
        "fault_type": fault_type if has_fault else "no_fault_detected",
        "confidence": confidence,
        "confidence_interval": _confidence_interval(confidence),
        "algorithm_status": "dataset_rule_vibration_scada",
        "message": f"诊断结果基于已导入数据：{turbine.source_dataset or CARE_DATASET_ID}；{source_dataset or 'imported vibration dataset'}。",
        "generated_at": datetime.now(timezone.utc),
        "signals": signals,
        "troubleshooting_steps": await _diagnosis_steps(db, fault_type if has_fault else "no_fault_detected", signals),
    }


async def _care_fault_response_for_turbine(db: AsyncSession, turbine: Turbine) -> FaultResponse:
    scada_rows = await _latest_scada_window(db, turbine.id, 144)
    latest_anomaly = next(
        (
            row for row in scada_rows
            if str(_parse_extra(row.extra).get("event_label") or "").lower() == "anomaly"
            or str(_parse_extra(row.extra).get("status_type_id") or "") in ANOMALY_STATUS_IDS
        ),
        scada_rows[0] if scada_rows else None,
    )
    detection = await _build_dataset_detection(db, turbine, "blade", 24)
    return FaultResponse(
        id=-int(turbine.id),
        turbine_id=turbine.id,
        turbine_name=turbine.name,
        turbine_region=turbine.region or "",
        detected_at=(latest_anomaly.timestamp if latest_anomaly else datetime.now(timezone.utc)),
        discovered_at=(latest_anomaly.timestamp if latest_anomaly else None),
        fault_type=detection["fault_type"],
        confidence=detection["confidence"],
        status="open",
        priority="high" if turbine.status == "fault" else "medium",
        processing_status="pending",
        status_note=f"来自 {turbine.source_dataset or CARE_DATASET_ID} 的状态/异常窗口。",
        details={
            "source_dataset": turbine.source_dataset,
            "source_asset_id": turbine.source_asset_id,
            "turbine_status": turbine.status,
            "hi_value": turbine.hi_value,
        },
    )


async def _care_fault_detail(db: AsyncSession, fault_id: int) -> FaultDetailResponse:
    turbine = await db.get(Turbine, abs(fault_id))
    if not turbine or turbine.source_dataset != CARE_DATASET_ID:
        raise HTTPException(status_code=404, detail="Fault not found")
    response = await _care_fault_response_for_turbine(db, turbine)
    detection = await _build_dataset_detection(db, turbine, "blade", 24)
    return FaultDetailResponse(
        **response.model_dump(),
        signals=[],
        signal_insights=detection["signals"],
        troubleshooting_steps=detection["troubleshooting_steps"],
    )


def _fault_response(
    fault: Fault,
    turbine_name: str,
    turbine_region: str | None,
    work_order: WorkOrder | None,
) -> FaultResponse:
    processing_status = _processing_status(fault, work_order)
    processing_started_at = None
    closed_at = None
    failed_at = None
    if work_order:
        if work_order.status in {"assigned", "in_progress", "review", "completed", "closed"}:
            processing_started_at = work_order.created_at
        if work_order.status in {"completed", "closed"}:
            closed_at = work_order.completed_at or work_order.updated_at
        if work_order.status == "cancelled":
            failed_at = work_order.cancelled_at or work_order.updated_at

    return FaultResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine_name,
        turbine_region=turbine_region or "",
        detected_at=fault.detected_at,
        discovered_at=fault.detected_at,
        processing_started_at=processing_started_at,
        closed_at=closed_at,
        failed_at=failed_at,
        handler=work_order.assignee if work_order else None,
        processing_status=processing_status,
        priority=_priority_from_fault(fault, work_order),
        work_order_id=work_order.id if work_order else None,
        work_order_title=work_order.title if work_order else None,
        last_action_at=work_order.updated_at if work_order else fault.detected_at,
        maintenance_cost_estimate=work_order.cost_estimate if work_order else None,
        maintenance_cost_actual=work_order.cost_actual if work_order else None,
        status_note=_fault_status_note(work_order),
        fault_type=fault.fault_type,
        confidence=fault.confidence,
        status=fault.status,
        details=fault.details,
    )


async def _latest_workorders_by_fault(db: AsyncSession, fault_ids: list[int]) -> dict[int, WorkOrder]:
    if not fault_ids:
        return {}
    result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.fault_id.in_(fault_ids), WorkOrder.deleted_at.is_(None))
        .order_by(WorkOrder.fault_id.asc(), WorkOrder.created_at.desc())
    )
    mapping: dict[int, WorkOrder] = {}
    for work_order in result.scalars().all():
        if work_order.fault_id is not None and work_order.fault_id not in mapping:
            mapping[work_order.fault_id] = work_order
    return mapping


@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    turbine_id: int | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    care_q = select(Turbine).where(Turbine.source_dataset == CARE_DATASET_ID)
    if turbine_id:
        care_q = care_q.where(Turbine.id == turbine_id)
    care_q = care_q.where(Turbine.status.in_(["warning", "fault"])).order_by(Turbine.status.desc(), Turbine.hi_value.asc())
    care_result = await db.execute(care_q)
    care_items = []
    if not status or status == "open":
        for turbine in care_result.scalars().all():
            care_items.append(await _care_fault_response_for_turbine(db, turbine))

    q = select(Fault, Turbine.name, Turbine.region, Turbine.source_dataset).join(Turbine, Turbine.id == Fault.turbine_id)
    if turbine_id:
        q = q.where(Fault.turbine_id == turbine_id)
    if status:
        q = q.where(Fault.status == status)
    q = q.where(Turbine.source_dataset.is_not(None))
    q = q.order_by(Fault.detected_at.desc())
    result = await db.execute(q)
    rows = result.all()
    workorders = await _latest_workorders_by_fault(db, [fault.id for fault, _, _, _ in rows])
    db_items = [
        _fault_response(fault, turbine_name, region, workorders.get(fault.id))
        for fault, turbine_name, region, source_dataset in rows
    ]
    return care_items + db_items


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
    if fault_id < 0:
        return await _care_fault_detail(db, fault_id)

    result = await db.execute(
        select(Fault, Turbine.name, Turbine.region)
        .join(Turbine, Turbine.id == Fault.turbine_id)
        .where(Fault.id == fault_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Fault not found")
    fault, turbine_name, turbine_region = row
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")

    sig_result = await db.execute(
        select(FaultSignal).where(FaultSignal.fault_id == fault_id).order_by(FaultSignal.contribution_score.desc())
    )
    signals = sig_result.scalars().all()
    workorders = await _latest_workorders_by_fault(db, [fault.id])
    signal_insights = build_signal_insights(signals, fault.fault_type, fault.turbine_id)
    troubleshooting_steps = await build_troubleshooting_steps(db, fault.fault_type, signal_insights)

    base = _fault_response(fault, turbine_name, turbine_region, workorders.get(fault.id))
    return FaultDetailResponse(
        **base.model_dump(),
        signals=[FaultSignalResponse.model_validate(s) for s in signals],
        signal_insights=signal_insights,
        troubleshooting_steps=troubleshooting_steps,
    )


@router.post("/faults", response_model=FaultResponse, status_code=201)
async def create_fault(
    turbine_id: int = Query(...),
    fault_type: str = Query(...),
    confidence: float = Query(0.5, ge=0, le=1),
    priority: str = Query("medium"),
    details: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_role("engineer")),
):
    """Create a new fault record. Requires engineer+ role."""
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")
    now = datetime.now(timezone.utc)
    fault = Fault(
        turbine_id=turbine_id,
        fault_type=fault_type,
        confidence=confidence,
        status="open",
    )
    if details:
        try:
            fault.details = json.loads(details)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"details must be valid JSON: {exc.msg}") from exc
    fault.priority = priority
    fault.processing_status = "pending"
    fault.discovered_at = now
    db.add(fault)
    await db.commit()
    await db.refresh(fault)
    return FaultResponse(
        id=fault.id, turbine_id=fault.turbine_id,
        turbine_name=turbine.name, turbine_region=turbine.region or "",
        detected_at=fault.detected_at or now, fault_type=fault.fault_type,
        confidence=fault.confidence or 0, status=fault.status or "open",
        processing_status=getattr(fault, 'processing_status', None) or "pending",
        priority=fault.priority or "medium", details=fault.details,
    )


@router.put("/faults/{fault_id}", response_model=FaultResponse)
async def update_fault(
    fault_id: int,
    fault_type: str | None = Query(None),
    confidence: float | None = Query(None, ge=0, le=1),
    priority: str | None = Query(None),
    handler: str | None = Query(None),
    status_note: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_role("engineer")),
):
    """Update fault record fields. Requires engineer+ role."""
    if fault_id < 0:
        raise HTTPException(status_code=400, detail="Cannot update CARE-synthetic faults")
    fault = await db.get(Fault, fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")
    if fault_type:
        fault.fault_type = fault_type
    if confidence is not None:
        fault.confidence = confidence
    if priority:
        fault.priority = priority
    if handler:
        fault.handler = handler
    if status_note:
        fault.status_note = status_note
    fault.last_action_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(fault)
    return _fault_dict(fault)


@router.delete("/faults/{fault_id}")
async def delete_fault(fault_id: int, db: AsyncSession = Depends(get_db), _auth: User = Depends(require_role("admin"))):
    """Delete a fault and its signals. Requires admin role."""
    if fault_id < 0:
        raise HTTPException(status_code=400, detail="Cannot delete CARE-synthetic faults")
    fault = await db.get(Fault, fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")
    signals = (await db.execute(
        select(FaultSignal).where(FaultSignal.fault_id == fault_id)
    )).scalars().all()
    for s in signals:
        await db.delete(s)
    await db.delete(fault)
    await db.commit()
    return {"success": True, "message": f"Fault #{fault_id} deleted"}


@router.patch("/faults/{fault_id}/status")
async def update_fault_status(
    fault_id: int,
    processing_status: str = Query(...),
    handler: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_role("engineer")),
):
    """Update fault processing_status: pending→assigned→processing→closed."""
    valid = {"pending", "assigned", "processing", "closed", "failed"}
    if processing_status not in valid:
        raise HTTPException(status_code=422, detail=f"Invalid status. Must be: {valid}")
    if fault_id < 0:
        raise HTTPException(status_code=400, detail="Cannot update CARE-synthetic faults")
    fault = await db.get(Fault, fault_id)
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")
    fault.processing_status = processing_status
    if handler:
        fault.handler = handler
    now = datetime.now(timezone.utc)
    fault.last_action_at = now
    if processing_status == "closed":
        fault.closed_at = now
        fault.status = "closed"
    elif processing_status == "failed":
        fault.failed_at = now
    elif processing_status == "processing":
        fault.processing_started_at = now
    await db.commit()
    return {"success": True, "fault_id": fault_id, "processing_status": processing_status}


def _fault_dict(f: Fault) -> dict:
    return FaultResponse(
        id=f.id, turbine_id=f.turbine_id,
        turbine_name="", turbine_region="",
        detected_at=f.detected_at or datetime.now(timezone.utc),
        fault_type=f.fault_type, confidence=f.confidence or 0,
        status=f.status or "open",
        processing_status=f.processing_status or "pending",
        priority=f.priority or "medium", details=f.details,
    ).model_dump()


@router.get("/vibration-preview", response_model=VibrationPreviewResponse)
async def get_vibration_preview(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Return imported vibration data in the shape expected by the diagnosis page."""
    return await _build_vibration_preview(db, turbine_id, component, fault_type)


@router.post("/auto-detect", response_model=AutoFaultDetectionResponse)
async def auto_detect_fault(
    data: AutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")
    return await _build_dataset_detection(db, turbine, data.component, data.window_hours)


@router.post("/auto-detect/batch", response_model=BatchAutoFaultDetectionResponse)
async def batch_auto_detect_faults(
    data: BatchAutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    q = select(Turbine).where(Turbine.source_dataset == CARE_DATASET_ID)
    if data.turbine_ids:
        q = q.where(Turbine.id.in_(data.turbine_ids))
    if data.region:
        q = q.where(Turbine.region == data.region)
    if data.status:
        q = q.where(Turbine.status == data.status)
    q = q.order_by(Turbine.region.asc(), Turbine.name.asc())

    result = await db.execute(q)
    turbines = result.scalars().all()
    generated_at = datetime.now(timezone.utc)
    records: list[BatchAutoFaultRecord] = []
    group_summary: dict[str, int] = {}

    for turbine in turbines:
        detection = await _build_dataset_detection(db, turbine, data.component, data.window_hours)
        group_key = turbine.region or "未分组"
        group_summary[group_key] = group_summary.get(group_key, 0) + 1
        records.append(
            BatchAutoFaultRecord(
                record_id=f"{turbine.id}-{generated_at.strftime('%Y%m%d%H%M%S')}",
                turbine_id=turbine.id,
                turbine_name=turbine.name,
                region=group_key,
                turbine_status=turbine.status,
                component=detection["component"],
                analysis_window_hours=data.window_hours,
                status=detection["status"],
                fault_type=detection["fault_type"],
                confidence=detection["confidence"],
                confidence_interval=detection["confidence_interval"],
                algorithm_status=detection["algorithm_status"],
                message=detection["message"],
                generated_at=detection["generated_at"],
                group_key=group_key,
                signals=detection["signals"],
                troubleshooting_steps=detection["troubleshooting_steps"],
            )
        )

    return BatchAutoFaultDetectionResponse(
        success=bool(records),
        total=len(records),
        generated_at=generated_at,
        records=records,
        group_summary=group_summary,
        message=f"已基于 {CARE_DATASET_ID} 与已导入振动数据完成分组诊断。" if records else "没有符合条件的风机。",
    )


@router.post("/blade-diagnosis", response_model=BladeDiagnosisResponse)
async def diagnose_blade(
    data: BladeDiagnosisRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run blade image diagnosis using the imported DTU-trained YOLO model."""
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")
    if not data.image_path:
        raise HTTPException(status_code=400, detail="image_path is required")

    try:
        image_path = _resolve_data_file(data.image_path)
        return BladeDiagnosisResponse(**blade_yolo_service.predict(image_path, data.turbine_id))
    except Exception as exc:
        raise _blade_model_error(exc) from exc


@router.post("/blade-diagnosis/upload", response_model=BladeDiagnosisResponse)
async def diagnose_blade_upload(
    turbine_id: int = Form(...),
    image: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Run blade image diagnosis on an uploaded JPG/PNG image."""
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    suffix = Path(image.filename or "").suffix.lower()
    if suffix not in IMAGE_EXTS:
        raise HTTPException(status_code=400, detail="Only image files are supported")

    content = await image.read()
    if len(content) > MAX_UPLOAD_IMAGE_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {MAX_UPLOAD_IMAGE_MB}MB)")

    UPLOAD_BLADE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_BLADE_IMAGE_DIR / f"{uuid4().hex}{suffix}"
    save_path.write_bytes(content)

    try:
        return BladeDiagnosisResponse(**blade_yolo_service.predict(save_path, turbine_id))
    except Exception as exc:
        raise _blade_model_error(exc) from exc


@router.get("/vibration")
async def get_vibration_data(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
    max_points: int = Query(1024, ge=128, le=4096),
    db: AsyncSession = Depends(get_db),
):
    """Get vibration waveform for a turbine component.

    Supports optional fault injection for demonstration.
    """
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    record = await _select_vibration_record(db, turbine_id, component)
    if not record:
        raise HTTPException(status_code=404, detail="No imported vibration data for this turbine")

    payload = _load_vibration_payload(record)

    full_waveform = payload.get("waveform", [])
    waveform = _downsample_series(full_waveform, max_points)
    spectrum = _downsample_series(payload.get("spectrum", []), min(max_points, 512))
    sample_rate = payload.get("sample_rate_hz", 1000)
    # Compute spectrum if not in payload
    if waveform and not spectrum:
        spectrum = _spectrum_from_waveform(waveform, sample_rate)

    return {
        "turbine_id": turbine_id,
        "component": record.component,
        "timestamp": record.timestamp.isoformat(),
        "message": "ok" if waveform else "波形数据缺失",
        "duration_seconds": payload.get("duration_seconds") or 0,
        "sample_rate_hz": sample_rate,
        "sample_count": payload.get("sample_count", len(full_waveform)),
        "returned_sample_count": len(waveform),
        "rms": payload.get("rms", record.rms),
        "waveform": waveform,
        "spectrum": spectrum,
        "peak_frequencies": payload.get("peak_frequencies", []),
        "fault_detected": payload.get("fault_detected", False),
        "fault_info": payload.get("fault_info"),
        "quality": {"display_mode": "wall_clock_24h_loop"} if payload else None,
        "source_dataset": _resolve_vibration_source_dataset(payload, record),
        "algorithm_status": payload.get("algorithm_status", "imported_vibration_dataset"),
        "waveform_path": record.waveform_path,
        "peak_freq_hz": record.peak_freq_hz,
    }


@router.get("/blade-images")
async def list_blade_images(
    turbine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get blade inspection images for a turbine.

    Returns imported inspection images. In production, these come from the database.
    """
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    result = await db.execute(
        select(BladeImage)
        .where(BladeImage.turbine_id == turbine_id)
        .order_by(BladeImage.timestamp.desc())
    )
    images = result.scalars().all()
    if not images:
        return [
            {
                "id": None,
                "turbine_id": turbine_id,
                "timestamp": item["timestamp"],
                "image_path": item["image_path"],
                "image_url": item["image_url"],
                "diagnosis_type": item["diagnosis_type"],
                "confidence": None,
                "damage_bbox": None,
                "has_damage": item["has_damage"],
                "source_dataset": item["source_dataset"],
                "view": item["view"],
                "frame_label": item.get("frame_label"),
                "campaign": item.get("campaign"),
                "inspection_id": item["inspection_id"],
                "inspection_slot": item["inspection_slot"],
                "image_index": item["image_index"],
                "image_count": item["image_count"],
                "quality": item["quality"],
            }
            for item in _raw_blade_inspection_images(turbine_id)
        ]

    return [
        {
            "id": image.id,
            "turbine_id": image.turbine_id,
            "timestamp": image.timestamp.isoformat(),
            "image_path": image.image_path,
            "image_url": _data_url(image.image_path),
            "diagnosis_type": image.diagnosis_type,
            "confidence": image.diagnosis_confidence,
            "damage_bbox": image.damage_bbox,
            "has_damage": bool(image.diagnosis_type and image.diagnosis_type != "no_damage"),
            "source_dataset": _source_dataset_from_path(DATA_DIR / image.image_path),
            "view": None,
            "frame_label": None,
        }
        for image in images
    ]


@router.post("/refresh-faults-from-events")
async def refresh_faults_from_care_events(
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_role("engineer")),
):
    """Sync faults from CARE event CSV files. Replaces seed_data demo faults.

    Reads 95 CARE normalized event CSVs, extracts anomaly events (status_type_id in {3,4}
    or event_label='anomaly'), matches to turbines by source_asset_id + wind_farm,
    and creates/updates Fault records with real dataset provenance.
    """
    from app.services.care_monitoring_metrics import (
        _load_care_event_windows_from_files, ANOMALY_STATUS_IDS, CARE_REGION_LABELS,
    )

    windows = _load_care_event_windows_from_files()
    if not windows:
        raise HTTPException(status_code=404, detail="CARE event files not found in data/modeling/")

    # Delete all existing faults (replace seed_data demo with CARE events)
    from sqlalchemy import delete as sqldelete
    await db.execute(sqldelete(FaultSignal))
    await db.execute(sqldelete(Fault))
    await db.commit()

    # Map wind farm names back from Chinese labels
    FARM_REVERSE = {v: k for k, v in CARE_REGION_LABELS.items()}

    # Pre-load all CARE turbines indexed by source_asset_id
    all_turbines = (await db.execute(
        select(Turbine).where(Turbine.source_dataset == CARE_DATASET_ID)
    )).scalars().all()
    turbine_by_asset: dict[str, Turbine] = {
        t.source_asset_id: t for t in all_turbines if t.source_asset_id
    }

    def _event_source_turbine_id(csv_path: str) -> str | None:
        """Read source_turbine_id from the first data row of a CARE event CSV."""
        import csv as _csv
        try:
            with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
                first_row = next(_csv.DictReader(fh), None)
        except OSError:
            return None
        value = str((first_row or {}).get("source_turbine_id") or "").strip()
        return value or None

    farm_rr: dict[str, int] = {}
    created = 0
    for window in windows:
        labels = str(window.get("event_label") or "").lower()
        status_id = str(window.get("status_type_id") or "")
        if labels != "anomaly" and status_id not in ANOMALY_STATUS_IDS:
            continue

        region_label = window.get("region")
        wind_farm = FARM_REVERSE.get(region_label, region_label)
        source_file = window.get("source_file", "")

        # Match turbine: prefer exact source_asset_id ("<wind_farm>:<source_turbine_id>")
        matched = None
        approximate = False
        src_turbine_id = _event_source_turbine_id(source_file)
        if src_turbine_id is not None:
            matched = turbine_by_asset.get(f"{wind_farm}:{src_turbine_id}")
        if not matched:
            # Approximate fallback: round-robin across the farm's turbines so
            # events do not all pile onto a single turbine.
            candidates = [t for asset_id, t in sorted(turbine_by_asset.items()) if wind_farm in asset_id]
            if not candidates:
                continue
            idx = farm_rr.get(wind_farm, 0)
            matched = candidates[idx % len(candidates)]
            farm_rr[wind_farm] = idx + 1
            approximate = True

        # Derive fault type from event component category (from CSV)
        component = str(window.get("event_component_category") or "bearing")
        fault_type_map = {
            "bearing": "bearing_inner_race_wear",
            "gearbox": "gearbox_tooth_pitting",
            "generator": "generator_overheat",
            "blade": "blade_leading_edge_erosion",
            "pitch": "pitch_system_fault",
            "main_shaft": "main_shaft_misalignment",
            "cooling": "cooling_system_fault",
            "electrical": "electrical_connection",
        }
        fault_type = fault_type_map.get(component, "bearing_inner_race_wear")

        # Check for existing fault for this event
        existing = await db.execute(
            select(Fault).where(
                Fault.turbine_id == matched.id,
                Fault.fault_type == fault_type,
                Fault.details.contains(source_file),
            )
        )
        if existing.scalar_one_or_none():
            continue

        event_start = window.get("event_start") or datetime.now(timezone.utc).isoformat()
        confidence = 0.75 if status_id == "4" else 0.62 if status_id == "3" else 0.55

        fault = Fault(
            turbine_id=matched.id,
            detected_at=datetime.now(timezone.utc),
            fault_type=fault_type,
            confidence=confidence,
            status="open",
            details={
                "source_dataset": CARE_DATASET_ID,
                "source_file": source_file,
                "wind_farm": wind_farm,
                "event_label": window.get("event_label"),
                "event_start": event_start,
                "event_end": window.get("event_end"),
                "component": component,
                "method": "care_event_csv_sync",
                "approximate": approximate,
                "match_method": "farm_round_robin" if approximate else "exact_asset_id",
            },
            processing_status="pending",
            discovered_at=datetime.now(timezone.utc),
        )
        db.add(fault)
        created += 1

    await db.commit()
    return {
        "success": True,
        "message": f"Synced {created} faults from CARE event files",
        "total_events_checked": len(windows),
        "faults_created": created,
    }


@router.post("/seed-knowledge")
async def seed_knowledge_base(
    db: AsyncSession = Depends(get_db),
    _auth: User = Depends(require_role("admin")),
):
    """Import fault knowledge base from frontend/src/data/fault-kb.json into DB.

    Reads the structured fault knowledge JSON (symptoms, root_causes, solutions,
    spare_parts, related_faults) and inserts into fault_knowledge table.
    Skips existing entries by fault_type.
    """
    import json as _json
    kb_path = Path(__file__).resolve().parents[3] / "frontend" / "src" / "data" / "fault-kb.json"
    if not kb_path.exists():
        raise HTTPException(status_code=404, detail=f"Knowledge base file not found: {kb_path}")

    data = _json.loads(kb_path.read_text(encoding="utf-8"))
    nodes = data.get("nodes", [])
    if not nodes:
        raise HTTPException(status_code=400, detail="No nodes found in fault-kb.json")

    created = 0
    skipped = 0
    for node in nodes:
        ft = node.get("fault_type", "")
        if not ft:
            continue
        # Check duplicate
        existing = (await db.execute(
            select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == ft)
        )).scalar_one_or_none()
        if existing:
            skipped += 1
            continue

        fk = FaultKnowledgeNode(
            fault_type=ft,
            category=node.get("category", "other"),
            icon=node.get("icon", "⚠️"),
            severity=node.get("severity", "medium"),
            symptoms=node.get("symptoms", []),
            root_causes=node.get("root_causes", []),
            solutions=node.get("solutions", []),
            related_faults=node.get("related_faults", []),
            spare_parts=node.get("spare_parts", []),
            cases=node.get("cases", []),
            source="manual",
            confidence=1.0,
            verified=True,
        )
        db.add(fk)
        created += 1

    await db.commit()
    return {
        "success": True,
        "message": f"Seeded {created} knowledge nodes, skipped {skipped} existing",
    }
