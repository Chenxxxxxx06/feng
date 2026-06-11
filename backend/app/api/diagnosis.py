from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Fault, FaultSignal, Turbine
from app.schemas import (
    FaultResponse, FaultDetailResponse, FaultSignalResponse,
    BladeDiagnosisRequest, BladeDiagnosisResponse,
)
from app.services.data_pipeline.blade_simulator import blade_simulator
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/faults", response_model=list[FaultResponse])
async def list_faults(
    turbine_id: int | None = Query(None),
    status: str | None = Query(None),
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
