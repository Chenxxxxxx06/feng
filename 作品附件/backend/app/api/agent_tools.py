"""Agent data tool APIs.

These endpoints expose read-only context and draft-building tools for advanced
Agent workflows. They do not perform business mutations; writes still go
through `/api/agent-actions/*`.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import User
from app.services.agent_data_tools import (
    _serialize_turbine,
    _serialize_user,
    _serialize_workorder,
    draft_workorder_from_context,
    list_personnel_candidates,
    query_blade_image_context,
    query_fault_context,
    query_fleet_overview,
    query_knowledge_context,
    query_maintenance_plan_context,
    query_rul_context,
    query_settings_context,
    query_turbine_detail_context,
    query_vibration_context,
    query_workorder_context,
    resolve_batch_turbines,
    resolve_data_source,
    resolve_fault_by_context,
)
from app.services.agent_read_tasks import answer_read_task
from app.services.agent_entities import (
    resolve_personnel_by_name,
    resolve_turbine_by_ref,
    resolve_workorder_by_ref,
)
from app.services.agent_playbooks import load_agent_knowledge_base, retrieve_playbooks, validate_agent_knowledge_base

router = APIRouter(dependencies=[Depends(get_current_user)])


class WorkorderDraftRequest(BaseModel):
    turbine_ref: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=512)
    assignee_name: Optional[str] = Field(default=None, max_length=64)


class AgentReadTaskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    page_context: dict = Field(default_factory=dict)


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@router.get("/agent-tools/catalog")
async def get_agent_tool_catalog():
    kb = load_agent_knowledge_base()
    return {
        "validation_errors": validate_agent_knowledge_base(),
        "counts": {
            "entities": len(kb["entities"].get("entities", [])),
            "primitive_actions": len(kb["primitive_actions"].get("actions", [])),
            "read_tasks": len(kb["read_tasks"].get("tasks", [])),
            "advanced_workflows": len(kb["advanced_workflows"].get("workflows", [])),
        },
        "entities": kb["entities"].get("entities", []),
        "primitive_actions": kb["primitive_actions"].get("actions", []),
    }


@router.get("/agent-tools/playbooks/retrieve")
async def retrieve_agent_playbooks(query: str = Query(..., min_length=1), top_k: int = Query(3, ge=1, le=10)):
    return {"query": query, "matches": retrieve_playbooks(query, top_k=top_k)}


@router.post("/agent-tools/read/answer")
async def answer_agent_read_task(
    data: AgentReadTaskRequest,
    db: AsyncSession = Depends(get_db),
):
    return await answer_read_task(db, message=data.message, page_context=data.page_context)


@router.get("/agent-tools/entities/turbine/resolve")
async def resolve_turbine_entity(ref: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    result = await resolve_turbine_by_ref(db, ref)
    return {
        "entity": _serialize_turbine(result.entity),
        "candidates": [_serialize_turbine(item) for item in result.candidates],
        "normalized_ref": result.normalized_ref,
        "reason": result.reason,
    }


@router.get("/agent-tools/entities/workorder/resolve")
async def resolve_workorder_entity(ref: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    import re

    match = re.search(r"(?:WO[-_\s]*)?(\d{1,8})", ref, flags=re.IGNORECASE)
    workorder_id = int(match.group(1)) if match else None
    result = await resolve_workorder_by_ref(db, workorder_id)
    return {
        "entity": _serialize_workorder(result.entity),
        "candidates": [_serialize_workorder(item) for item in result.candidates],
        "normalized_ref": result.normalized_ref,
        "reason": result.reason,
    }


@router.get("/agent-tools/entities/personnel/resolve")
async def resolve_personnel_entity(name: str = Query(..., min_length=1), db: AsyncSession = Depends(get_db)):
    result = await resolve_personnel_by_name(db, name)
    return {
        "entity": _serialize_user(result.entity),
        "candidates": [_serialize_user(item) for item in result.candidates],
        "normalized_ref": result.normalized_ref,
        "reason": result.reason,
        "all_candidates": await list_personnel_candidates(db, name=name),
    }


@router.get("/agent-tools/entities/fault/resolve")
async def resolve_fault_entity(
    fault_id: int | None = Query(None),
    turbine_ref: str | None = Query(None),
    fault_keyword: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await resolve_fault_by_context(
        db,
        fault_id=fault_id,
        turbine_ref=turbine_ref,
        fault_keyword=fault_keyword,
        status=status,
    )


@router.get("/agent-tools/entities/data-source/resolve")
async def resolve_data_source_entity(
    source_type: str | None = Query(None),
    name: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await resolve_data_source(db, source_type=source_type, name=name)


@router.get("/agent-tools/entities/batch-turbines")
async def resolve_batch_turbine_entities(
    scope: str | None = Query(None),
    region: str | None = Query(None),
    status: str | None = Query(None),
    hi_min: float | None = Query(None),
    hi_max: float | None = Query(None),
    turbine_refs: str | None = Query(None, description="Comma-separated turbine refs"),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await resolve_batch_turbines(
        db,
        scope=scope,
        region=region,
        status=status,
        hi_min=hi_min,
        hi_max=hi_max,
        turbine_refs=_split_csv(turbine_refs),
        limit=limit,
    )


@router.get("/agent-tools/context/fleet")
async def get_fleet_context(
    region: str | None = Query(None),
    status: str | None = Query(None),
    model: str | None = Query(None),
    hi_min: float | None = Query(None),
    hi_max: float | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    return await query_fleet_overview(db, region=region, status=status, model=model, hi_min=hi_min, hi_max=hi_max, limit=limit)


@router.get("/agent-tools/context/turbine/{turbine_id}")
async def get_turbine_context(turbine_id: int, db: AsyncSession = Depends(get_db)):
    return await query_turbine_detail_context(db, turbine_id)


@router.get("/agent-tools/context/faults")
async def get_fault_context(
    turbine_id: int | None = Query(None),
    fault_id: int | None = Query(None),
    fault_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await query_fault_context(db, turbine_id=turbine_id, fault_id=fault_id, fault_type=fault_type, status=status, limit=limit)


@router.get("/agent-tools/context/vibration")
async def get_vibration_context(
    turbine_id: int = Query(..., gt=0),
    component: str | None = Query(None),
    limit: int = Query(24, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    return await query_vibration_context(db, turbine_id=turbine_id, component=component, limit=limit)


@router.get("/agent-tools/context/blade-images")
async def get_blade_image_context(
    turbine_id: int = Query(..., gt=0),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await query_blade_image_context(db, turbine_id=turbine_id, limit=limit)


@router.get("/agent-tools/context/rul")
async def get_rul_context(
    turbine_id: int | None = Query(None, gt=0),
    component: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    return await query_rul_context(db, turbine_id=turbine_id, component=component, limit=limit)


@router.get("/agent-tools/context/maintenance-plan")
async def get_maintenance_plan_context(
    top_n: int | None = Query(30, ge=1, le=200),
    region: str | None = Query(None),
    priority: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await query_maintenance_plan_context(db, top_n=top_n, region=region, priority=priority)


@router.get("/agent-tools/context/workorders")
async def get_workorder_context(
    workorder_ref: str | None = Query(None),
    turbine_id: int | None = Query(None, gt=0),
    status: str | None = Query(None),
    assignee: str | None = Query(None),
    priority: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await query_workorder_context(
        db,
        workorder_ref=workorder_ref,
        turbine_id=turbine_id,
        status=status,
        assignee=assignee,
        priority=priority,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.get("/agent-tools/context/knowledge")
async def get_knowledge_context(
    query: str | None = Query(None),
    fault_type: str | None = Query(None),
    category: str | None = Query(None),
    verified: bool | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await query_knowledge_context(db, query=query, fault_type=fault_type, category=category, verified=verified, limit=limit)


@router.get("/agent-tools/context/settings")
async def get_settings_context(
    include_data_sources: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await query_settings_context(db, user=user, include_data_sources=include_data_sources)


@router.post("/agent-tools/drafts/workorder")
async def draft_workorder(data: WorkorderDraftRequest, db: AsyncSession = Depends(get_db)):
    return await draft_workorder_from_context(
        db,
        turbine_ref=data.turbine_ref,
        message=data.message,
        assignee_name=data.assignee_name,
    )
