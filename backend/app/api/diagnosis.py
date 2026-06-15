from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.models import Fault, FaultSignal, Turbine
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
    AutoFaultDetectionRequest, AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest, BatchAutoFaultDetectionResponse,
)
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.api.auth import get_current_user
from app.services.blade_yolo_service import BladeModelUnavailable, blade_yolo_service

router = APIRouter(dependencies=[Depends(get_current_user)])

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
    q = select(Fault, Turbine.name).join(Turbine, Turbine.id == Fault.turbine_id)
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
            turbine_name=turbine_name,
            detected_at=fault.detected_at,
            fault_type=fault.fault_type,
            confidence=fault.confidence,
            status=fault.status,
            details=fault.details,
        )
        for fault, turbine_name in result.all()
    ]


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
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


@router.post("/blade-diagnosis", response_model=BladeDiagnosisResponse)
async def diagnose_blade(
    data: BladeDiagnosisRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run blade image diagnosis using the simulation pipeline."""
    turbine = await db.get(Turbine, data.turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    results = blade_simulator.generate_inspection(data.turbine_id, num_images=1)
    r = results[0]
    return BladeDiagnosisResponse(
        turbine_id=data.turbine_id,
        damage_type=r["damage_type"] or "no_damage",
        confidence=r["confidence"],
        damage_bbox=r["damage_bbox"],
        image_path=r["image_path"],
    )


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

    from app.services.data_pipeline.vibration_loader import vibration_loader
    return vibration_loader.generate_waveform(
        turbine_id=turbine_id,
        component=component,
        fault_type=fault_type,
    )


@router.get("/blade-images")
async def list_blade_images(
    turbine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get blade inspection images for a turbine.

    Returns simulated results. In production, these come from the database.
    """
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        raise HTTPException(status_code=404, detail="Turbine not found")

    return blade_simulator.generate_inspection(turbine_id, num_images=3)
