import logging
from smtplib import SMTPRecipientsRefused

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models import NotificationConfig, User, WorkOrder
from app.schemas import WorkOrderCreate, WorkOrderUpdate, WorkOrderResponse, WorkOrderEmailRequest
from app.api.auth import get_current_user
from app.services.email_service import EmailConfigError, send_email

router = APIRouter(dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)

VALID_STATUS = {"pending", "assigned", "in_progress", "review", "completed", "closed", "cancelled"}


def _model_fields() -> set[str]:
    return {col.name for col in WorkOrder.__table__.columns}


def _filter_model_data(data: dict) -> dict:
    fields = _model_fields()
    return {key: val for key, val in data.items() if key in fields}


def _workorder_email_body(wo: WorkOrder) -> str:
    return "\n".join(
        [
            f"工单编号: WO-{wo.id:04d}",
            f"工单标题: {wo.title}",
            f"风机ID: {wo.turbine_id}",
            f"当前状态: {wo.status}",
            f"责任人: {wo.assignee or '待分配'}",
            f"预估成本: {wo.cost_estimate}",
            "",
            "请及时登录风调预顺 PHM 系统查看并处理该工单。",
        ]
    )


async def _resolve_assignee_email(wo: WorkOrder, db: AsyncSession) -> str | None:
    assignee_email = getattr(wo, "assignee_email", None)
    if assignee_email:
        return assignee_email
    if not wo.assignee:
        return None

    result = await db.execute(select(User).where(User.username == wo.assignee, User.is_active == True))
    user = result.scalar_one_or_none()
    return user.email if user else None


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
    payload = data.model_dump(exclude_none=True)
    if payload.get("assignee") and "status" in _model_fields():
        payload.setdefault("status", "assigned")
    wo = WorkOrder(**_filter_model_data(payload))
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
    if data.status and data.status not in VALID_STATUS:
        raise HTTPException(status_code=400, detail="Invalid work order status")
    if data.status == "completed" and wo.status != "completed":
        update_data["completed_at"] = datetime.now(timezone.utc)
    if data.status == "cancelled" and "cancelled_at" in _model_fields():
        update_data["cancelled_at"] = datetime.now(timezone.utc)
    for key, val in _filter_model_data(update_data).items():
        setattr(wo, key, val)

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


@router.delete("/{workorder_id}", response_model=WorkOrderResponse)
async def cancel_workorder(workorder_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    wo = result.scalar_one_or_none()
    if not wo:
        raise HTTPException(status_code=404, detail="WorkOrder not found")

    wo.status = "cancelled"
    fields = _model_fields()
    now = datetime.now(timezone.utc)
    if "cancelled_at" in fields:
        wo.cancelled_at = now
    if "deleted_at" in fields:
        wo.deleted_at = now

    await db.commit()
    await db.refresh(wo)
    return WorkOrderResponse.model_validate(wo)


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

    assignee_email = await _resolve_assignee_email(wo, db)
    recipients = [assignee_email] if assignee_email else []
    if not recipients:
        raise HTTPException(status_code=400, detail="No recipient email found for work order assignee")

    subject = data.subject or f"[风调预顺] WO-{wo.id:04d} {wo.title}"
    body = data.content or _workorder_email_body(wo)
    logs = []
    sent_count = 0
    failed_count = 0
    for recipient in recipients:
        try:
            await send_email(recipient, subject, body)
            logs.append({"recipient_email": recipient, "status": "sent", "error_message": None})
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
            error_message = "收件人邮箱不可用或被拒收：" + "; ".join(details)
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": error_message})
            failed_count += 1
        except Exception as exc:
            logs.append({"recipient_email": recipient, "status": "failed", "error_message": str(exc)})
            failed_count += 1

    if sent_count == 0 and failed_count > 0:
        first_error = logs[0]["error_message"] if logs else "Email send failed"
        raise HTTPException(status_code=502, detail=first_error)

    if sent_count:
        fields = _model_fields()
        if "notification_sent_at" in fields:
            wo.notification_sent_at = datetime.now(timezone.utc)
            await db.commit()

    return {
        "work_order_id": workorder_id,
        "sent": sent_count,
        "failed": failed_count,
        "logs": logs,
    }
