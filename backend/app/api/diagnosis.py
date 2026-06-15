from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
import re
import shutil
from uuid import uuid4

from sqlalchemy import select

from app.database import get_db
from app.models import BladeImage, Fault, FaultSignal, Turbine, VibrationData
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
    AutoFaultDetectionRequest, AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest, BatchAutoFaultDetectionResponse,
)
from app.api.auth import get_current_user
from app.services.blade_yolo_service import BladeModelUnavailable, blade_yolo_service

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

@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    turbine_id: int | None = Query(None),
    status: str | None = Query(None),
    source_dataset: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Fault, Turbine.name, Turbine.region).join(Turbine, Turbine.id == Fault.turbine_id)
    if source_dataset:
        q = q.where(Turbine.source_dataset == source_dataset)
    if turbine_id:
        q = q.where(Fault.turbine_id == turbine_id)
    if status:
        q = q.where(Fault.status == status)
    q = q.order_by(Fault.detected_at.desc())
    result = await db.execute(q)
    return [
        FaultResponse(
            id=fault.id,
            turbine_id=fault.turbine_id,
            turbine_name=turbine_name or "",
            turbine_region=turbine_region or "",
            detected_at=fault.detected_at,
            discovered_at=fault.discovered_at,
            processing_started_at=fault.processing_started_at,
            closed_at=fault.closed_at,
            failed_at=fault.failed_at,
            handler=fault.handler,
            processing_status=fault.processing_status or "pending",
            priority=fault.priority or "medium",
            work_order_id=fault.work_order_id,
            work_order_title=fault.work_order_title,
            last_action_at=fault.last_action_at,
            maintenance_cost_estimate=fault.maintenance_cost_estimate,
            maintenance_cost_actual=fault.maintenance_cost_actual,
            status_note=fault.status_note or "",
            fault_type=fault.fault_type,
            confidence=fault.confidence,
            status=fault.status,
            details=fault.details,
        )
        for fault, turbine_name, turbine_region in result.all()
    ]


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
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

    return FaultDetailResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine_name or "",
        turbine_region=turbine_region or "",
        detected_at=fault.detected_at,
        discovered_at=fault.discovered_at,
        processing_started_at=fault.processing_started_at,
        closed_at=fault.closed_at,
        failed_at=fault.failed_at,
        handler=fault.handler,
        processing_status=fault.processing_status or "pending",
        priority=fault.priority or "medium",
        work_order_id=fault.work_order_id,
        work_order_title=fault.work_order_title,
        last_action_at=fault.last_action_at,
        maintenance_cost_estimate=fault.maintenance_cost_estimate,
        maintenance_cost_actual=fault.maintenance_cost_actual,
        status_note=fault.status_note or "",
        fault_type=fault.fault_type,
        confidence=fault.confidence,
        status=fault.status,
        details=fault.details,
        signals=[FaultSignalResponse.model_validate(s) for s in signals],
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


@router.get("/vibration-preview")
async def vibration_preview(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    q = select(VibrationData).where(VibrationData.turbine_id == turbine_id)
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


@router.post("/auto-detect", response_model=AutoFaultDetectionResponse)
async def auto_detect(
    request: AutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.diagnosis_orchestrator import run_auto_fault_identification
    return await run_auto_fault_identification(db, request)


@router.post("/auto-detect/batch", response_model=BatchAutoFaultDetectionResponse)
async def auto_detect_batch(
    request: BatchAutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.services.diagnosis_orchestrator import run_batch_auto_fault_identification
    return await run_batch_auto_fault_identification(db, request)

