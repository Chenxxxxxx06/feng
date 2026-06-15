import logging
from datetime import datetime, timezone
from smtplib import SMTPRecipientsRefused

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import Fault, MaintenanceRecord, NotificationConfig, NotificationLog, User, WorkOrder
from app.schemas import (
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    NotificationLogResponse,
    WorkOrderCreate,
    WorkOrderDetailResponse,
    WorkOrderEmailRequest,
    WorkOrderResponse,
    WorkOrderUpdate,
)
from app.services.email_service import EmailConfigError, send_email

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

VALID_STATUS = {"pending", "assigned", "in_progress", "review", "completed", "closed", "cancelled"}
STATUS_ACTION = {
    "pending": "created",
    "assigned": "assigned",
    "in_progress": "started",
    "review": "reviewed",
    "completed": "repaired",
    "closed": "closed",
    "cancelled": "cancelled",
}


def _model_fields() -> set[str]:
    return {col.name for col in WorkOrder.__table__.columns}


def _filter_model_data(data: dict) -> dict:
    fields = _model_fields()
    return {key: val for key, val in data.items() if key in fields}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _workorder_email_body(wo: WorkOrder) -> str:
    return "\n".join(
        [
            f"Work order: WO-{wo.id:04d}",
            f"Title: {wo.title}",
            f"Turbine ID: {wo.turbine_id}",
            f"Priority: {wo.priority or 'medium'}",
            f"Fault type: {wo.fault_type or '-'}",
            f"Due date: {wo.due_date or '-'}",
            f"Status: {wo.status}",
            f"Assignee: {wo.assignee or 'unassigned'}",
            f"Estimated cost: {wo.cost_estimate}",
            "",
            "Please log in to the PHM system to view and process this work order.",
        ]
    )


async def _add_record(
    db: AsyncSession,
    wo: WorkOrder,
    user: User | None,
    action_type: str,
    content: str | None = None,
    before_status: str | None = None,
    after_status: str | None = None,
    extra: dict | None = None,
) -> MaintenanceRecord:
    record = MaintenanceRecord(
        work_order_id=wo.id,
        operator_id=user.id if user else None,
        action_type=action_type,
        content=content,
        before_status=before_status,
        after_status=after_status,
        extra=extra,
    )
    db.add(record)
    return record


async def _resolve_assignee_email(wo: WorkOrder, db: AsyncSession) -> str | None:
    if wo.assignee_email:
        return wo.assignee_email
    if wo.assignee_id:
        result = await db.execute(select(User).where(User.id == wo.assignee_id, User.is_active == True))
        user = result.scalar_one_or_none()
        if user:
            return user.email
    if not wo.assignee:
        return None

    result = await db.execute(select(User).where(User.username == wo.assignee, User.is_active == True))
    user = result.scalar_one_or_none()
    return user.email if user else None


async def _recipient_emails(data: WorkOrderEmailRequest, wo: WorkOrder, db: AsyncSession) -> list[str]:
    recipients = list(data.recipient_emails)
    assignee_email = await _resolve_assignee_email(wo, db)
    if assignee_email:
        recipients.append(assignee_email)

    if data.recipient_user_ids:
        result = await db.execute(select(User).where(User.id.in_(data.recipient_user_ids), User.is_active == True))
        recipients.extend(user.email for user in result.scalars().all())

    return list(dict.fromkeys(email for email in recipients if email))


@router.get("/", response_model=list[WorkOrderResponse])
async def list_workorders(
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    priority: str | None = Query(None),
    turbine_id: int | None = Query(None),
    fault_id: int | None = Query(None),
    include_deleted: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    q = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if not include_deleted:
        q = q.where(or_(WorkOrder.deleted_at.is_(None), WorkOrder.status == "cancelled"))
    if status:
        q = q.where(WorkOrder.status == status)
    if assignee:
        q = q.where(WorkOrder.assignee == assignee)
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if turbine_id:
        q = q.where(WorkOrder.turbine_id == turbine_id)
    if fault_id:
        q = q.where(WorkOrder.fault_id == fault_id)
    result = await db.execute(q)
    return [WorkOrderResponse.model_validate(wo) for wo in result.scalars().all()]


@router.get("/{workorder_id}", response_model=WorkOrderDetailResponse)
async def get_workorder(workorder_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    records_result = await db.execute(
        select(MaintenanceRecord)
        .where(MaintenanceRecord.work_order_id == workorder_id)
        .order_by(MaintenanceRecord.created_at.asc())
    )
    logs_result = await db.execute(
        select(NotificationLog)
        .where(NotificationLog.work_order_id == workorder_id)
        .order_by(NotificationLog.created_at.asc())
    )
    detail = WorkOrderDetailResponse.model_validate(wo)
    detail.records = [MaintenanceRecordResponse.model_validate(record) for record in records_result.scalars().all()]
    detail.notification_logs = [NotificationLogResponse.model_validate(log) for log in logs_result.scalars().all()]
    return detail


@router.post("/", response_model=WorkOrderResponse, status_code=201)
async def create_workorder(
    data: WorkOrderCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    payload = data.model_dump(exclude_none=True)
    if data.fault_id is not None:
        fault = await db.get(Fault, data.fault_id)
        if not fault:
            raise HTTPException(status_code=404, detail="Fault not found")
        if fault.turbine_id != data.turbine_id:
            raise HTTPException(status_code=400, detail="Work order turbine_id must match fault turbine_id")

    if payload.get("assignee") or payload.get("assignee_id"):
        payload.setdefault("status", "assigned")

    now = _utc_now()
    payload.setdefault("priority", "medium")
    payload.setdefault("created_at", now)
    payload.setdefault("updated_at", now)

    wo = WorkOrder(**_filter_model_data(payload))
    db.add(wo)
    await db.flush()
    await _add_record(db, wo, user, "created", "Work order created", after_status=wo.status)

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.put("/{workorder_id}", response_model=WorkOrderResponse)
async def update_workorder(
    workorder_id: int,
    data: WorkOrderUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    before_status = wo.status
    update_data = data.model_dump(exclude_none=True)
    if data.status and data.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="Invalid work order status")

    now = _utc_now()
    if data.status == "completed" and wo.status != "completed":
        update_data["completed_at"] = now
    if data.status == "cancelled":
        update_data["cancelled_at"] = now
    update_data["updated_at"] = now

    for key, val in _filter_model_data(update_data).items():
        setattr(wo, key, val)

    await _add_record(
        db,
        wo,
        user,
        STATUS_ACTION.get(data.status, "updated") if data.status and data.status != before_status else "updated",
        content="Work order updated",
        before_status=before_status,
        after_status=wo.status,
        extra={"updated_fields": sorted(update_data.keys())},
    )

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.delete("/{workorder_id}", response_model=WorkOrderResponse)
async def cancel_workorder(
    workorder_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    before_status = wo.status
    now = _utc_now()
    wo.status = "cancelled"
    wo.cancelled_at = now
    wo.updated_at = now
    await _add_record(
        db,
        wo,
        user,
        "cancelled",
        content="Work order cancelled",
        before_status=before_status,
        after_status=wo.status,
    )

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.post("/{workorder_id}/records", response_model=MaintenanceRecordResponse, status_code=201)
async def add_workorder_record(
    workorder_id: int,
    data: MaintenanceRecordCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    before_status = wo.status
    if data.status:
        if data.status not in VALID_STATUS:
            raise HTTPException(status_code=400, detail="Invalid work order status")
        wo.status = data.status
        wo.updated_at = _utc_now()
        if data.status == "completed" and not wo.completed_at:
            wo.completed_at = _utc_now()

    record = await _add_record(
        db,
        wo,
        user,
        data.action_type,
        content=data.content,
        before_status=before_status,
        after_status=wo.status,
    )
    await db.commit()
    await db.refresh(record)
    return MaintenanceRecordResponse.model_validate(record)


@router.post("/{workorder_id}/send-email")
async def send_workorder_email(
    workorder_id: int,
    data: WorkOrderEmailRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    config_result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    config = config_result.scalar_one_or_none()
    logger.info(
        "Workorder email setting: user_id=%s username=%s config_id=%s email_enabled=%s",
        user.id,
        user.username,
        getattr(config, "id", None),
        getattr(config, "email_enabled", None),
    )
    if not config or not config.email_enabled:
        raise HTTPException(status_code=400, detail="Email notification is disabled in settings")

    recipients = await _recipient_emails(data, wo, db)
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipient email found for work order assignee")

    subject = data.subject or f"[Fengdiao PHM] WO-{wo.id:04d} {wo.title}"
    body = data.content or _workorder_email_body(wo)
    logs = []
    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        try:
            await send_email(recipient, subject, body)
            logs.append({"recipient_email": recipient, "status": "sent", "error_message": None})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="sent",
                    sent_at=_utc_now(),
                )
            )
            sent_count += 1
        except EmailConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SMTPRecipientsRefused as exc:
            refused = exc.recipients or {}
            details = []
            for email, error in refused.items():
                code, message = error
                if isinstance(message, bytes):
                    message = message.decode("utf-8", errors="replace")
                details.append(f"{email}: {code} {message}")
            error_message = "Recipient mailbox unavailable or refused: " + "; ".join(details)
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": error_message})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="failed",
                    error_message=error_message,
                )
            )
            failed_count += 1
        except Exception as exc:
            error_message = str(exc)
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": error_message})
            db.add(
                NotificationLog(
                    work_order_id=workorder_id,
                    recipient_email=recipient,
                    subject=subject,
                    status="failed",
                    error_message=error_message,
                )
            )
            failed_count += 1

    if sent_count == 0 and failed_count > 0:
        await db.commit()
        first_error = logs[0]["error_message"] if logs else "Email send failed"
        raise HTTPException(status_code=502, detail=first_error)

    if sent_count:
        wo.notification_sent_at = _utc_now()
        wo.updated_at = _utc_now()
        await _add_record(
            db,
            wo,
            user,
            "email_sent",
            content=f"Sent email to {sent_count} recipient(s)",
            before_status=wo.status,
            after_status=wo.status,
        )
    await db.commit()

    return {
        "work_order_id": workorder_id,
        "sent": sent_count,
        "failed": failed_count,
        "logs": logs,
    }
