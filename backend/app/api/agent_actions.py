"""Agent Action Gateway.

This route handles data-mutating Agent tasks through backend validation,
confirmation, execution, read-back verification, and audit logging.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import (
    AgentActionConfirmResponse,
    AgentActionPlanRequest,
    AgentActionPlanResponse,
)
from app.services.agent_actions.workorder import (
    cancel_agent_action,
    confirm_agent_action,
    plan_agent_action,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/agent-actions/plan", response_model=AgentActionPlanResponse)
async def plan_action(
    data: AgentActionPlanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await plan_agent_action(
        db,
        user=user,
        message=data.message,
        page_context=data.page_context,
    )


@router.post("/agent-actions/{request_id}/confirm", response_model=AgentActionConfirmResponse)
async def confirm_action(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await confirm_agent_action(db, user=user, request_id=request_id)


@router.post("/agent-actions/{request_id}/cancel", response_model=AgentActionConfirmResponse)
async def cancel_action(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await cancel_agent_action(db, user=user, request_id=request_id)
