"""Unified Agent task planning API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import AgentTaskCancelResponse, AgentTaskPlanRequest, AgentTaskPlanResponse
from app.services.agent_task_planner import cancel_agent_task_plan, plan_agent_task

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.post("/agent-tasks/plan", response_model=AgentTaskPlanResponse)
async def plan_task(
    data: AgentTaskPlanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await plan_agent_task(
        db,
        user=user,
        message=data.message,
        page_context=data.page_context,
        plan_id=data.plan_id,
        provider_config_id=data.provider_config_id,
        model=data.model,
    )


@router.post("/agent-tasks/{plan_id}/cancel", response_model=AgentTaskCancelResponse)
async def cancel_task_plan(
    plan_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await cancel_agent_task_plan(db, user=user, plan_id=plan_id)
