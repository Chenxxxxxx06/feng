from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import re
import shutil
from uuid import uuid4

from sqlalchemy import select

from app.database import get_db
from app.models import BladeImage, Fault, FaultSignal, SCADARecord, Turbine, VibrationData
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
    AutoFaultDetectionRequest, AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest, BatchAutoFaultDetectionResponse, BatchAutoFaultRecord,
    DiagnosisSignalInsight, TroubleshootingStep, VibrationPreviewResponse,
)
from app.api.auth import get_current_user
from app.services.blade_yolo_service import BladeModelUnavailable, blade_yolo_service
from app.services.care_monitoring_metrics import ANOMALY_STATUS_IDS, CARE_DATASET_ID

router = APIRouter(dependencies=[Depends(get_current_user)])
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_BLADE_IMAGE_DIR = DATA_DIR / "curated_datasets" / "raw" / "blade_images"
UPLOAD_BLADE_IMAGE_DIR = DATA_DIR / "uploads" / "blade_diagnosis"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
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
        return "mendeley_blade_vibration_faults"

    source_dataset = quality.get("source_dataset")
    if source_dataset == "care_public_vibration_reference":
        return "mendeley_blade_vibration_faults"
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
    path = DATA_DIR / record.waveform_path
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _diagnosis_steps(fault_type: str, source_dataset: str | None) -> list[TroubleshootingStep]:
    if fault_type == "no_fault_detected":
        return [
            TroubleshootingStep(order=1, title="保持监测", action="继续观察 CARE SCADA 与振动窗口的变化。", expected_effect="确认当前窗口是否稳定。"),
            TroubleshootingStep(order=2, title="复核数据源", action=f"检查 {source_dataset or '当前数据集'} 的采样时间、通道和缺失情况。", expected_effect="排除数据质量导致的误判。"),
        ]
    return [
        TroubleshootingStep(order=1, title="复核数据窗口", action="分别核对振动波形、主频、RMS 与 CARE SCADA 异常窗口的来源和采样时间。", expected_effect="确认诊断输入来自已导入数据。"),
        TroubleshootingStep(order=2, title="现场复测", action="对同一部件重新采集振动或巡检图像，并与当前数据集样本对比。", expected_effect="判断异常是否持续存在。"),
        TroubleshootingStep(order=3, title="生成工单", action="如果复测仍异常，再进入工单流程并记录维修开始、完成和恢复运行时间。", expected_effect="形成可追溯的维修闭环数据。"),
    ]


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
        normal_range=">=80 正常，60-79 预警，<60 故障",
        contribution_score=0.9 if turbine.status == "fault" else 0.65 if turbine.status == "warning" else 0.28,
        priority="high" if turbine.status == "fault" else "medium" if turbine.status == "warning" else "low",
        finding=f"来自 {turbine.source_dataset or 'turbine table'} 的风机健康状态。",
    ))
    signals.append(DiagnosisSignalInsight(
        sensor_name="SCADA异常窗口",
        value=f"{scada_summary['anomaly']}/{scada_summary['total']}",
        normal_range="最近窗口内异常标记为0",
        contribution_score=round(min(0.9, 0.25 + scada_summary["ratio"]), 3),
        priority="high" if scada_summary["ratio"] > 0.3 else "medium" if scada_summary["anomaly"] else "low",
        finding="按 CARE SCADA event_label/status_type_id 统计最近窗口异常占比。",
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
        "troubleshooting_steps": _diagnosis_steps(fault_type if has_fault else "no_fault_detected", source_dataset),
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
    db_items = [
        FaultResponse(
            id=fault.id,
            turbine_id=fault.turbine_id,
            turbine_name=turbine_name,
            turbine_region=region or "",
            detected_at=fault.detected_at,
            fault_type=fault.fault_type,
            confidence=fault.confidence,
            status=fault.status,
            details=fault.details,
        )
        for fault, turbine_name, region, source_dataset in result.all()
    ]
    return care_items + db_items


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
    if fault_id < 0:
        return await _care_fault_detail(db, fault_id)

    result = await db.execute(
        select(Fault, Turbine.name)
        .join(Turbine, Turbine.id == Fault.turbine_id)
        .where(Fault.id == fault_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Fault not found")
    fault, turbine_name = row
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")

    sig_result = await db.execute(
        select(FaultSignal).where(FaultSignal.fault_id == fault_id).order_by(FaultSignal.contribution_score.desc())
    )
    signals = sig_result.scalars().all()

    return FaultDetailResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine_name,
        detected_at=fault.detected_at,
        fault_type=fault.fault_type,
        confidence=fault.confidence,
        status=fault.status,
        details=fault.details,
        signals=[FaultSignalResponse.model_validate(s) for s in signals],
    )


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

    UPLOAD_BLADE_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    save_path = UPLOAD_BLADE_IMAGE_DIR / f"{uuid4().hex}{suffix}"
    with save_path.open("wb") as output:
        shutil.copyfileobj(image.file, output)

    try:
        return BladeDiagnosisResponse(**blade_yolo_service.predict(save_path, turbine_id))
    except Exception as exc:
        raise _blade_model_error(exc) from exc


@router.get("/vibration")
async def get_vibration_data(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Get vibration waveform for a turbine component.

    Supports optional fault injection for demonstration.
    """
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    q = select(VibrationData).where(VibrationData.turbine_id == turbine_id)
    if component:
        q = q.where(VibrationData.component == component)
    q = q.order_by(VibrationData.timestamp.desc())
    result = await db.execute(q)
    record = result.scalars().first()
    if not record:
        raise HTTPException(status_code=404, detail="No imported vibration data for this turbine")

    payload = {}
    if record.waveform_path:
        path = DATA_DIR / record.waveform_path
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))

    return {
        "turbine_id": turbine_id,
        "component": record.component,
        "timestamp": record.timestamp.isoformat(),
        "duration_seconds": payload.get("duration_seconds"),
        "sample_rate_hz": payload.get("sample_rate_hz"),
        "sample_count": payload.get("sample_count"),
        "rms": payload.get("rms", record.rms),
        "waveform": payload.get("waveform", []),
        "peak_frequencies": payload.get("peak_frequencies", []),
        "fault_detected": payload.get("fault_detected", False),
        "fault_info": payload.get("fault_info"),
        "quality": {"display_mode": "wall_clock_24h_loop"} if payload else None,
        "source_dataset": _resolve_vibration_source_dataset(payload, record),
        "data_source": payload.get("data_source", "imported_dataset"),
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
