from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Fault, FaultSignal, Turbine, WorkOrder
from app.schemas import (
    AutoFaultDetectionRequest,
    AutoFaultDetectionResponse,
    BatchAutoFaultDetectionRequest,
    BatchAutoFaultDetectionResponse,
    BladeDiagnosisRequest,
    BladeDiagnosisResponse,
    FaultDetailResponse,
    FaultResponse,
    FaultSignalResponse,
    VibrationPreviewResponse,
)
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.services.diagnosis_orchestrator import (
    build_signal_insights,
    build_troubleshooting_steps,
    get_vibration_preview,
    run_auto_fault_identification,
    run_batch_auto_fault_identification,
    run_blade_image_diagnosis,
)
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


def _details_datetime(details: dict | None, key: str) -> datetime | None:
    value = (details or {}).get(key)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _processing_status(fault: Fault, work_order: WorkOrder | None, details: dict | None) -> str:
    explicit = (details or {}).get("processing_status")
    if explicit:
        return str(explicit)
    if _details_datetime(details, "failed_at") or (work_order and work_order.status == "failed"):
        return "failed"
    if fault.status == "closed" or (work_order and work_order.status == "completed"):
        return "closed"
    if work_order and work_order.status == "in_progress":
        return "processing"
    if work_order and work_order.status == "assigned":
        return "assigned"
    return "pending"


def _priority(fault: Fault, details: dict | None) -> str:
    explicit = (details or {}).get("priority")
    if explicit:
        return str(explicit)
    if fault.confidence >= 0.9:
        return "urgent"
    if fault.confidence >= 0.82:
        return "high"
    return "medium"


def _fallback_closed_at(fault: Fault) -> datetime | None:
    if fault.status != "closed":
        return None
    return fault.detected_at + timedelta(hours=18 + fault.id % 12)


def _fault_response(
    fault: Fault,
    turbine: Turbine | None,
    work_order: WorkOrder | None,
) -> FaultResponse:
    details = fault.details or {}
    processing_status = _processing_status(fault, work_order, details)
    processing_started_at = _details_datetime(details, "processing_started_at")
    if not processing_started_at and work_order and processing_status != "pending":
        processing_started_at = work_order.created_at

    closed_at = _details_datetime(details, "closed_at")
    if not closed_at and work_order and work_order.completed_at:
        closed_at = work_order.completed_at
    if not closed_at:
        closed_at = _fallback_closed_at(fault)
    if not closed_at and processing_status == "closed":
        closed_at = fault.detected_at + timedelta(hours=18 + fault.id % 12)

    failed_at = _details_datetime(details, "failed_at")
    last_action_at = failed_at or closed_at or processing_started_at or fault.detected_at

    handler = details.get("handler") or (work_order.assignee if work_order else None)
    return FaultResponse(
        id=fault.id,
        turbine_id=fault.turbine_id,
        turbine_name=turbine.name if turbine else "",
        turbine_region=turbine.region if turbine else "",
        detected_at=fault.detected_at,
        discovered_at=fault.detected_at,
        processing_started_at=processing_started_at,
        closed_at=closed_at,
        failed_at=failed_at,
        handler=handler,
        processing_status=processing_status,
        priority=_priority(fault, details),
        work_order_id=work_order.id if work_order else None,
        work_order_title=work_order.title if work_order else None,
        last_action_at=last_action_at,
        maintenance_cost_estimate=work_order.cost_estimate if work_order else None,
        maintenance_cost_actual=work_order.cost_actual if work_order else None,
        status_note=str(details.get("recommendation") or details.get("root_cause") or ""),
        fault_type=fault.fault_type,
        confidence=fault.confidence,
        status=fault.status,
        details=fault.details,
    )


@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    turbine_id: int | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Fault)
    if turbine_id:
        q = q.where(Fault.turbine_id == turbine_id)
    if status:
        q = q.where(Fault.status == status)
    q = q.order_by(Fault.detected_at.desc())
    result = await db.execute(q)
    faults = result.scalars().all()
    turbine_map: dict[int, Turbine] = {}
    work_order_map: dict[int, WorkOrder] = {}
    if faults:
        turbine_ids = {fault.turbine_id for fault in faults}
        turbine_result = await db.execute(select(Turbine).where(Turbine.id.in_(turbine_ids)))
        turbine_map = {turbine.id: turbine for turbine in turbine_result.scalars().all()}

        fault_ids = {fault.id for fault in faults}
        work_order_result = await db.execute(
            select(WorkOrder)
            .where(WorkOrder.fault_id.in_(fault_ids))
            .order_by(WorkOrder.created_at.asc())
        )
        work_order_map = {
            work_order.fault_id: work_order
            for work_order in work_order_result.scalars().all()
            if work_order.fault_id is not None
        }

    return [
        _fault_response(
            fault,
            turbine_map.get(fault.turbine_id),
            work_order_map.get(fault.id),
        )
        for fault in faults
    ]


@router.get("/faults/{fault_id}", response_model=FaultDetailResponse)
async def get_fault_detail(fault_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fault).where(Fault.id == fault_id))
    fault = result.scalar_one_or_none()
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")

    turbine_result = await db.execute(select(Turbine).where(Turbine.id == fault.turbine_id))
    turbine = turbine_result.scalar_one_or_none()
    work_order_result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.fault_id == fault.id)
        .order_by(WorkOrder.created_at.desc())
        .limit(1)
    )
    work_order = work_order_result.scalar_one_or_none()

    sig_result = await db.execute(
        select(FaultSignal)
        .where(FaultSignal.fault_id == fault_id)
        .order_by(FaultSignal.contribution_score.desc())
    )
    signals = sig_result.scalars().all()
    insights = build_signal_insights(signals, fault.fault_type, fault.turbine_id)
    fault_data = _fault_response(fault, turbine, work_order)

    return FaultDetailResponse(
        **fault_data.model_dump(),
        signals=[FaultSignalResponse.model_validate(s) for s in signals],
        signal_insights=insights,
        troubleshooting_steps=build_troubleshooting_steps(fault.fault_type, insights),
    )


@router.post("/auto-detect", response_model=AutoFaultDetectionResponse)
async def auto_detect_fault(
    data: AutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Orchestrate automatic fault identification.

    The real vibration/frequency algorithm can replace the adapter in
    diagnosis_orchestrator.py without changing this API contract.
    """
    return await run_auto_fault_identification(db, data)


@router.post("/auto-detect/batch", response_model=BatchAutoFaultDetectionResponse)
async def batch_auto_detect_faults(
    data: BatchAutoFaultDetectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Run automatic fault identification for a filtered turbine set."""
    return await run_batch_auto_fault_identification(db, data)


@router.post("/blade-diagnosis", response_model=BladeDiagnosisResponse)
async def diagnose_blade(data: BladeDiagnosisRequest):
    """Orchestrate blade diagnosis by image path."""
    return run_blade_image_diagnosis(data.turbine_id, data.image_path)


@router.post("/blade-diagnosis/upload", response_model=BladeDiagnosisResponse)
async def upload_blade_for_diagnosis(
    turbine_id: int = Form(...),
    image: UploadFile = File(...),
):
    """Accept a blade image upload and pass it through the diagnosis control layer."""
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=400, detail="Only JPG and PNG images are supported")
    image_path = f"uploaded://{image.filename}"
    return run_blade_image_diagnosis(turbine_id, image_path)


@router.get("/vibration-preview", response_model=VibrationPreviewResponse)
async def get_vibration_preview_data(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
):
    """Return demo waveform data for the diagnosis page visualization slot."""
    return get_vibration_preview(turbine_id, component, fault_type)


@router.get("/troubleshooting/{fault_id}")
async def get_troubleshooting(fault_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Fault).where(Fault.id == fault_id))
    fault = result.scalar_one_or_none()
    if not fault:
        raise HTTPException(status_code=404, detail="Fault not found")

    sig_result = await db.execute(
        select(FaultSignal)
        .where(FaultSignal.fault_id == fault_id)
        .order_by(FaultSignal.contribution_score.desc())
    )
    insights = build_signal_insights(sig_result.scalars().all(), fault.fault_type, fault.turbine_id)
    return {
        "fault_id": fault.id,
        "fault_type": fault.fault_type,
        "steps": build_troubleshooting_steps(fault.fault_type, insights),
    }


@router.get("/vibration")
async def get_vibration_data(
    turbine_id: int = Query(...),
    component: str = Query("gearbox_high_speed"),
    fault_type: str | None = Query(None),
):
    """Get vibration waveform for a turbine component.

    Kept for existing pages. It now uses the same diagnosis control layer as
    the diagnosis page preview.
    """
    preview = get_vibration_preview(turbine_id, component, fault_type)
    return preview.model_dump()


@router.get("/blade-images")
async def list_blade_images(
    turbine_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Get blade inspection images for a turbine.

    Returns simulated results until the real image dataset interface is ready.
    """
    return blade_simulator.generate_inspection(turbine_id, num_images=3)
