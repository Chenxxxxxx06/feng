from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models import WorkOrder
from app.schemas import WorkOrderCreate, WorkOrderUpdate, WorkOrderResponse
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[WorkOrderResponse])
async def list_workorders(
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    turbine_id: int | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if status:
        q = q.where(WorkOrder.status == status)
    if assignee:
        q = q.where(WorkOrder.assignee == assignee)
    if turbine_id:
        q = q.where(WorkOrder.turbine_id == turbine_id)
    result = await db.execute(q)
    return [WorkOrderResponse.model_validate(wo) for wo in result.scalars().all()]


@router.post("/", response_model=WorkOrderResponse, status_code=201)
async def create_workorder(data: WorkOrderCreate, db: AsyncSession = Depends(get_db)):
    wo = WorkOrder(**data.model_dump())
    db.add(wo)
    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.put("/{workorder_id}", response_model=WorkOrderResponse)
async def update_workorder(workorder_id: int, data: WorkOrderUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    update_data = data.model_dump(exclude_none=True)
    if data.status == "completed" and wo.status != "completed":
        update_data["completed_at"] = datetime.now(timezone.utc)
    for key, val in update_data.items():
        setattr(wo, key, val)

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)
