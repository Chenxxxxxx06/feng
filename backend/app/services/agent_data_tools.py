"""Read-only Agent data tools.

These helpers back the `/api/agent-tools/*` routes. They provide deterministic
data access for advanced Agent workflows without calling business page code and
without performing data mutations.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AIProviderConfig,
    BladeImage,
    DataImportBatch,
    DataSource,
    Fault,
    FaultKnowledgeNode,
    FaultSignal,
    MaintenancePersonnel,
    MaintenanceRecord,
    NotificationConfig,
    NotificationLog,
    RULPrediction,
    SCADARecord,
    Turbine,
    User,
    VibrationData,
    WorkOrder,
)
from app.services.agent_entities import (
    extract_turbine_ref,
    resolve_personnel_by_name,
    resolve_turbine_by_ref,
    resolve_workorder_by_ref,
)
from app.services.agent_workflows.workorder import (
    draft_create_workorder_fields,
    fault_context_state,
    query_turbine_fault_context,
)
from app.services.maintenance_planner import generate_maintenance_plan

ACTIVE_WORKORDER_STATUSES = {"pending", "assigned", "in_progress", "review"}
ACTIVE_FAULT_STATUSES = {"open", "active", "pending", "processing", "assigned"}


def _dt(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _workorder_id_from_ref(ref: str | None) -> int | None:
    if not ref:
        return None
    match = re.search(r"(?:WO[-_\s]*)?(\d{1,8})", ref, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _serialize_turbine(turbine: Turbine | None) -> dict[str, Any] | None:
    if not turbine:
        return None
    return {
        "id": turbine.id,
        "name": turbine.name,
        "model": turbine.model,
        "power_mw": turbine.power_mw,
        "region": turbine.region,
        "status": turbine.status,
        "hi_value": turbine.hi_value,
        "lat": turbine.lat,
        "lng": turbine.lng,
        "last_maintenance": _dt(turbine.last_maintenance),
        "commissioned_at": _dt(getattr(turbine, "commissioned_at", None)),
        "source_dataset": turbine.source_dataset,
        "source_asset_id": turbine.source_asset_id,
        "asset_scope": turbine.asset_scope,
        "geo_scope": turbine.geo_scope,
    }


def _serialize_fault(fault: Fault | None, turbine: Turbine | None = None) -> dict[str, Any] | None:
    if not fault:
        return None
    return {
        "id": fault.id,
        "turbine_id": fault.turbine_id,
        "turbine_name": turbine.name if turbine else None,
        "fault_type": fault.fault_type,
        "confidence": fault.confidence,
        "status": fault.status,
        "priority": getattr(fault, "priority", None),
        "processing_status": getattr(fault, "processing_status", None),
        "work_order_id": getattr(fault, "work_order_id", None),
        "detected_at": _dt(fault.detected_at),
        "details": fault.details,
    }


def _serialize_workorder(order: WorkOrder | None, turbine: Turbine | None = None) -> dict[str, Any] | None:
    if not order:
        return None
    return {
        "id": order.id,
        "ref": f"WO-{order.id:04d}",
        "turbine_id": order.turbine_id,
        "turbine_name": turbine.name if turbine else None,
        "fault_id": order.fault_id,
        "incident_id": order.incident_id,
        "title": order.title,
        "description": order.description,
        "status": order.status,
        "priority": order.priority,
        "fault_type": order.fault_type,
        "assignee": order.assignee,
        "assignee_id": order.assignee_id,
        "assignee_email": order.assignee_email,
        "due_date": _dt(order.due_date),
        "cost_estimate": order.cost_estimate,
        "cost_actual": order.cost_actual,
        "downtime_hours": order.downtime_hours,
        "created_at": _dt(order.created_at),
        "updated_at": _dt(order.updated_at),
        "completed_at": _dt(order.completed_at),
        "cancelled_at": _dt(order.cancelled_at),
        "deleted_at": _dt(order.deleted_at),
    }


def _serialize_user(user: User | None) -> dict[str, Any] | None:
    if not user:
        return None
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
    }


def _serialize_personnel(row: MaintenancePersonnel | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row.id,
        "user_id": row.user_id,
        "name": row.name,
        "email": row.email,
        "skills": row.skills or [],
        "region": row.region,
        "is_available": row.is_available,
        "max_load": row.max_load,
    }


def _serialize_ai_provider(config: AIProviderConfig | None) -> dict[str, Any] | None:
    if not config:
        return None
    return {
        "id": config.id,
        "provider": config.provider,
        "display_name": config.display_name,
        "base_url": config.base_url,
        "api_style": config.api_style,
        "default_model": config.default_model,
        "model_options": config.model_options or [],
        "enabled": config.enabled,
        "has_api_key": bool(config.api_key),
        "last_test_status": config.last_test_status,
        "last_test_message": config.last_test_message,
        "last_test_at": _dt(config.last_test_at),
    }


def _serialize_data_source(source: DataSource | None) -> dict[str, Any] | None:
    if not source:
        return None
    params = source.connection_params or {}
    safe_params = {
        key: ("***" if any(token in key.lower() for token in ("key", "token", "password", "secret")) else value)
        for key, value in params.items()
    }
    return {
        "id": source.id,
        "source_type": source.source_type,
        "name": source.name,
        "status": source.status,
        "connection_params": safe_params,
        "last_connected_at": _dt(source.last_connected_at),
        "last_data_at": _dt(source.last_data_at),
    }


async def resolve_fault_by_context(
    db: AsyncSession,
    *,
    fault_id: int | None = None,
    turbine_ref: str | None = None,
    fault_keyword: str | None = None,
    status: str | None = None,
    latest: bool = True,
    limit: int = 5,
) -> dict[str, Any]:
    turbine: Turbine | None = None
    if turbine_ref:
        turbine_resolution = await resolve_turbine_by_ref(db, turbine_ref)
        turbine = turbine_resolution.entity
        if not turbine:
            return {
                "entity": None,
                "candidates": [_serialize_turbine(item) for item in turbine_resolution.candidates],
                "reason": turbine_resolution.reason,
            }

    q = select(Fault).order_by(Fault.detected_at.desc()).limit(limit)
    if fault_id:
        q = select(Fault).where(Fault.id == fault_id).limit(1)
    if turbine:
        q = q.where(Fault.turbine_id == turbine.id)
    if fault_keyword:
        q = q.where(Fault.fault_type.ilike(f"%{fault_keyword}%"))
    if status:
        if status in ("active", "open"):
            q = q.where(Fault.status.in_(list(ACTIVE_FAULT_STATUSES)))
        else:
            q = q.where(Fault.status == status)

    result = await db.execute(q)
    faults = list(result.scalars().all())
    turbines: dict[int, Turbine] = {}
    if faults:
        ids = sorted({item.turbine_id for item in faults})
        tr = await db.execute(select(Turbine).where(Turbine.id.in_(ids)))
        turbines = {item.id: item for item in tr.scalars().all()}

    if fault_id and not faults:
        return {"entity": None, "candidates": [], "reason": "fault_not_found"}
    if len(faults) == 1 or (latest and faults):
        selected = faults[0]
        return {
            "entity": _serialize_fault(selected, turbines.get(selected.turbine_id)),
            "candidates": [_serialize_fault(item, turbines.get(item.turbine_id)) for item in faults],
            "reason": "exact" if fault_id else "latest",
        }
    return {
        "entity": None,
        "candidates": [_serialize_fault(item, turbines.get(item.turbine_id)) for item in faults],
        "reason": "ambiguous" if faults else "not_found",
    }


async def resolve_data_source(db: AsyncSession, *, source_type: str | None = None, name: str | None = None) -> dict[str, Any]:
    q = select(DataSource).order_by(DataSource.source_type.asc(), DataSource.name.asc())
    if source_type:
        q = q.where(DataSource.source_type.ilike(f"%{source_type}%"))
    if name:
        q = q.where(DataSource.name.ilike(f"%{name}%"))
    result = await db.execute(q)
    rows = list(result.scalars().all())
    return {
        "entity": _serialize_data_source(rows[0]) if len(rows) == 1 else None,
        "candidates": [_serialize_data_source(row) for row in rows[:10]],
        "reason": "exact" if len(rows) == 1 else "ambiguous" if rows else "not_found",
    }


async def resolve_batch_turbines(
    db: AsyncSession,
    *,
    scope: str | None = None,
    region: str | None = None,
    status: str | None = None,
    hi_min: float | None = None,
    hi_max: float | None = None,
    turbine_refs: list[str] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    resolved_ids: set[int] = set()
    unresolved_refs: list[str] = []
    for ref in turbine_refs or []:
        item = await resolve_turbine_by_ref(db, ref)
        if item.entity:
            resolved_ids.add(item.entity.id)
        else:
            unresolved_refs.append(ref)

    scope_text = (scope or "").strip()
    inferred_region = region
    inferred_status = status
    if scope_text:
        extracted = extract_turbine_ref(scope_text)
        if extracted:
            item = await resolve_turbine_by_ref(db, extracted)
            if item.entity:
                resolved_ids.add(item.entity.id)
        if "预警" in scope_text or "告警" in scope_text:
            inferred_status = inferred_status or "warning"
        if "故障" in scope_text:
            inferred_status = inferred_status or "fault"
        if "健康" in scope_text or "正常" in scope_text:
            inferred_status = inferred_status or "normal"
        region_match = re.search(r"(?:风场|区域|分组|组)?\s*([A-Za-z]|陕北)", scope_text)
        if region_match and not inferred_region:
            inferred_region = region_match.group(1)

    q = select(Turbine).order_by(Turbine.region.asc(), Turbine.name.asc()).limit(limit)
    if resolved_ids:
        q = q.where(Turbine.id.in_(resolved_ids))
    if inferred_region:
        q = q.where(Turbine.region.ilike(f"%{inferred_region}%"))
    if inferred_status:
        q = q.where(Turbine.status == inferred_status)
    if hi_min is not None:
        q = q.where(Turbine.hi_value >= hi_min)
    if hi_max is not None:
        q = q.where(Turbine.hi_value <= hi_max)

    result = await db.execute(q)
    turbines = list(result.scalars().all())
    return {
        "scope": scope,
        "filters": {
            "region": inferred_region,
            "status": inferred_status,
            "hi_min": hi_min,
            "hi_max": hi_max,
            "turbine_refs": turbine_refs or [],
        },
        "affected_count": len(turbines),
        "unresolved_refs": unresolved_refs,
        "turbines": [_serialize_turbine(item) for item in turbines],
        "warnings": ["影响范围为空，请重新指定筛选条件。"] if not turbines else [],
    }


async def query_fleet_overview(
    db: AsyncSession,
    *,
    region: str | None = None,
    status: str | None = None,
    model: str | None = None,
    hi_min: float | None = None,
    hi_max: float | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    q = select(Turbine).order_by(Turbine.region.asc(), Turbine.name.asc()).limit(limit)
    if region:
        q = q.where(Turbine.region.ilike(f"%{region}%"))
    if status:
        q = q.where(Turbine.status == status)
    if model:
        q = q.where(Turbine.model.ilike(f"%{model}%"))
    if hi_min is not None:
        q = q.where(Turbine.hi_value >= hi_min)
    if hi_max is not None:
        q = q.where(Turbine.hi_value <= hi_max)
    result = await db.execute(q)
    turbines = list(result.scalars().all())
    status_counts: dict[str, int] = {}
    region_counts: dict[str, int] = {}
    for turbine in turbines:
        status_counts[turbine.status] = status_counts.get(turbine.status, 0) + 1
        key = turbine.region or "未分组"
        region_counts[key] = region_counts.get(key, 0) + 1
    fault_count_result = await db.execute(select(func.count(Fault.id)).where(Fault.status.in_(list(ACTIVE_FAULT_STATUSES))))
    active_fault_count = int(fault_count_result.scalar() or 0)
    active_wo_result = await db.execute(select(func.count(WorkOrder.id)).where(WorkOrder.status.in_(list(ACTIVE_WORKORDER_STATUSES))))
    active_workorder_count = int(active_wo_result.scalar() or 0)
    hi_values = [float(item.hi_value or 0) for item in turbines]
    return {
        "summary": {
            "total": len(turbines),
            "status_counts": status_counts,
            "region_counts": region_counts,
            "active_fault_count": active_fault_count,
            "active_workorder_count": active_workorder_count,
            "avg_hi": round(sum(hi_values) / len(hi_values), 2) if hi_values else None,
            "min_hi": min(hi_values) if hi_values else None,
        },
        "turbines": [_serialize_turbine(item) for item in turbines],
    }


async def query_turbine_detail_context(db: AsyncSession, turbine_id: int) -> dict[str, Any]:
    turbine = await db.get(Turbine, turbine_id)
    if not turbine:
        return {"turbine": None, "error_code": "turbine_not_found"}
    scada_result = await db.execute(
        select(SCADARecord)
        .where(SCADARecord.turbine_id == turbine_id)
        .order_by(SCADARecord.timestamp.desc())
        .limit(5)
    )
    latest_scada = [
        {
            "timestamp": _dt(row.timestamp),
            "power_kw": row.power_kw,
            "wind_speed_ms": row.wind_speed_ms,
            "rotor_rpm": row.rotor_rpm,
            "gen_temperature_c": row.gen_temperature_c,
            "gearbox_temperature_c": row.gearbox_temperature_c,
            "bearing_temperature_c": row.bearing_temperature_c,
        }
        for row in scada_result.scalars().all()
    ]
    faults = await query_turbine_fault_context(db, turbine_id)
    wo_result = await db.execute(
        select(WorkOrder)
        .where(WorkOrder.turbine_id == turbine_id)
        .order_by(WorkOrder.created_at.desc())
        .limit(10)
    )
    rul_result = await db.execute(
        select(RULPrediction)
        .where(RULPrediction.turbine_id == turbine_id)
        .order_by(RULPrediction.predicted_at.desc())
        .limit(10)
    )
    return {
        "turbine": _serialize_turbine(turbine),
        "latest_scada": latest_scada,
        "fault_context": fault_context_state(faults),
        "workorders": [_serialize_workorder(item, turbine) for item in wo_result.scalars().all()],
        "rul_predictions": [
            {
                "id": row.id,
                "component": row.component,
                "remaining_life_days": row.remaining_life_days,
                "confidence_lower": row.confidence_lower,
                "confidence_upper": row.confidence_upper,
                "predicted_at": _dt(row.predicted_at),
            }
            for row in rul_result.scalars().all()
        ],
    }


async def query_fault_context(
    db: AsyncSession,
    *,
    turbine_id: int | None = None,
    fault_id: int | None = None,
    fault_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    q = select(Fault).order_by(Fault.detected_at.desc()).limit(limit)
    if fault_id:
        q = q.where(Fault.id == fault_id)
    if turbine_id:
        q = q.where(Fault.turbine_id == turbine_id)
    if fault_type:
        q = q.where(Fault.fault_type.ilike(f"%{fault_type}%"))
    if status:
        q = q.where(Fault.status.in_(list(ACTIVE_FAULT_STATUSES)) if status == "active" else Fault.status == status)
    result = await db.execute(q)
    faults = list(result.scalars().all())
    turbines: dict[int, Turbine] = {}
    if faults:
        ids = sorted({row.turbine_id for row in faults})
        tr = await db.execute(select(Turbine).where(Turbine.id.in_(ids)))
        turbines = {item.id: item for item in tr.scalars().all()}
    signals_by_fault: dict[int, list[dict[str, Any]]] = {}
    if faults:
        sr = await db.execute(select(FaultSignal).where(FaultSignal.fault_id.in_([item.id for item in faults])))
        for signal in sr.scalars().all():
            signals_by_fault.setdefault(signal.fault_id, []).append(
                {
                    "id": signal.id,
                    "sensor_name": signal.sensor_name,
                    "contribution_score": signal.contribution_score,
                    "priority": signal.priority,
                }
            )
    items = []
    for fault in faults:
        payload = _serialize_fault(fault, turbines.get(fault.turbine_id)) or {}
        payload["signals"] = signals_by_fault.get(fault.id, [])
        items.append(payload)
    return {
        "total": len(items),
        "active": sum(1 for item in items if item.get("status") in ACTIVE_FAULT_STATUSES),
        "items": items,
        "latest": items[0] if items else None,
    }


async def query_vibration_context(
    db: AsyncSession,
    *,
    turbine_id: int,
    component: str | None = None,
    limit: int = 24,
) -> dict[str, Any]:
    q = select(VibrationData).where(VibrationData.turbine_id == turbine_id).order_by(VibrationData.timestamp.desc()).limit(limit)
    if component:
        q = q.where(VibrationData.component == component)
    result = await db.execute(q)
    rows = list(result.scalars().all())
    rms_values = [float(row.rms or 0) for row in rows]
    peak_values = [float(row.peak_freq_hz or 0) for row in rows]
    return {
        "turbine_id": turbine_id,
        "component": component,
        "total": len(rows),
        "summary": {
            "latest_rms": rms_values[0] if rms_values else None,
            "max_rms": max(rms_values) if rms_values else None,
            "latest_peak_freq_hz": peak_values[0] if peak_values else None,
            "max_peak_freq_hz": max(peak_values) if peak_values else None,
        },
        "records": [
            {
                "id": row.id,
                "timestamp": _dt(row.timestamp),
                "component": row.component,
                "rms": row.rms,
                "peak_freq_hz": row.peak_freq_hz,
                "waveform_path": row.waveform_path,
            }
            for row in rows
        ],
    }


async def query_blade_image_context(db: AsyncSession, *, turbine_id: int, limit: int = 20) -> dict[str, Any]:
    result = await db.execute(
        select(BladeImage)
        .where(BladeImage.turbine_id == turbine_id)
        .order_by(BladeImage.timestamp.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return {
        "turbine_id": turbine_id,
        "total": len(rows),
        "images": [
            {
                "id": row.id,
                "timestamp": _dt(row.timestamp),
                "image_path": row.image_path,
                "diagnosis_type": row.diagnosis_type,
                "diagnosis_confidence": row.diagnosis_confidence,
                "damage_bbox": row.damage_bbox,
            }
            for row in rows
        ],
    }


async def query_rul_context(
    db: AsyncSession,
    *,
    turbine_id: int | None = None,
    component: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    q = select(RULPrediction).order_by(RULPrediction.remaining_life_days.asc(), RULPrediction.predicted_at.desc()).limit(limit)
    if turbine_id:
        q = q.where(RULPrediction.turbine_id == turbine_id)
    if component:
        q = q.where(RULPrediction.component == component)
    result = await db.execute(q)
    rows = list(result.scalars().all())
    turbines: dict[int, Turbine] = {}
    if rows:
        tr = await db.execute(select(Turbine).where(Turbine.id.in_(sorted({row.turbine_id for row in rows}))))
        turbines = {item.id: item for item in tr.scalars().all()}
    return {
        "total": len(rows),
        "urgent_count": sum(1 for row in rows if row.remaining_life_days <= 30),
        "high_count": sum(1 for row in rows if 30 < row.remaining_life_days <= 90),
        "items": [
            {
                "id": row.id,
                "turbine_id": row.turbine_id,
                "turbine_name": turbines.get(row.turbine_id).name if turbines.get(row.turbine_id) else None,
                "component": row.component,
                "remaining_life_days": row.remaining_life_days,
                "confidence_lower": row.confidence_lower,
                "confidence_upper": row.confidence_upper,
                "predicted_at": _dt(row.predicted_at),
            }
            for row in rows
        ],
    }


async def query_maintenance_plan_context(
    db: AsyncSession,
    *,
    top_n: int | None = 30,
    region: str | None = None,
    priority: str | None = None,
) -> dict[str, Any]:
    plan = await generate_maintenance_plan(db=db, top_n=top_n, region=region)
    if priority:
        plan = [item for item in plan if item.get("priority") == priority]
    return {
        "total": len(plan),
        "urgent_count": sum(1 for item in plan if item.get("priority") == "urgent"),
        "high_count": sum(1 for item in plan if item.get("priority") == "high"),
        "items": plan,
        "total_cost_estimate": round(sum(float(item.get("cost_estimate") or 0) for item in plan), 2),
    }


async def query_workorder_context(
    db: AsyncSession,
    *,
    workorder_ref: str | None = None,
    turbine_id: int | None = None,
    status: str | None = None,
    assignee: str | None = None,
    priority: str | None = None,
    include_deleted: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    workorder_id = _workorder_id_from_ref(workorder_ref)
    q = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(limit)
    if workorder_id:
        q = q.where(WorkOrder.id == workorder_id)
    if turbine_id:
        q = q.where(WorkOrder.turbine_id == turbine_id)
    if status:
        q = q.where(WorkOrder.status == status)
    if assignee:
        q = q.where(WorkOrder.assignee.ilike(f"%{assignee}%"))
    if priority:
        q = q.where(WorkOrder.priority == priority)
    if not include_deleted:
        q = q.where(or_(WorkOrder.deleted_at.is_(None), WorkOrder.status == "cancelled"))
    result = await db.execute(q)
    orders = list(result.scalars().all())
    turbines: dict[int, Turbine] = {}
    if orders:
        tr = await db.execute(select(Turbine).where(Turbine.id.in_(sorted({row.turbine_id for row in orders}))))
        turbines = {item.id: item for item in tr.scalars().all()}
    detail: dict[str, Any] | None = None
    if workorder_id and orders:
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
        detail = {
            "records": [
                {
                    "id": row.id,
                    "action_type": row.action_type,
                    "content": row.content,
                    "before_status": row.before_status,
                    "after_status": row.after_status,
                    "extra": row.extra,
                    "created_at": _dt(row.created_at),
                }
                for row in records_result.scalars().all()
            ],
            "notification_logs": [
                {
                    "id": row.id,
                    "recipient_email": row.recipient_email,
                    "subject": row.subject,
                    "channel": row.channel,
                    "status": row.status,
                    "error_message": row.error_message,
                    "sent_at": _dt(row.sent_at),
                    "created_at": _dt(row.created_at),
                }
                for row in logs_result.scalars().all()
            ],
        }
    return {
        "total": len(orders),
        "items": [_serialize_workorder(item, turbines.get(item.turbine_id)) for item in orders],
        "detail": detail,
    }


async def query_knowledge_context(
    db: AsyncSession,
    *,
    query: str | None = None,
    fault_type: str | None = None,
    category: str | None = None,
    verified: bool | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    q = select(FaultKnowledgeNode).order_by(FaultKnowledgeNode.updated_at.desc().nullslast(), FaultKnowledgeNode.id.asc()).limit(limit)
    if fault_type:
        q = q.where(FaultKnowledgeNode.fault_type.ilike(f"%{fault_type}%"))
    if category:
        q = q.where(FaultKnowledgeNode.category.ilike(f"%{category}%"))
    if query:
        pattern = f"%{query}%"
        q = q.where(or_(FaultKnowledgeNode.fault_type.ilike(pattern), FaultKnowledgeNode.category.ilike(pattern)))
    if verified is not None:
        q = q.where(FaultKnowledgeNode.verified.is_(verified))
    result = await db.execute(q)
    rows = list(result.scalars().all())
    return {
        "total": len(rows),
        "items": [
            {
                "id": row.id,
                "fault_type": row.fault_type,
                "category": row.category,
                "severity": row.severity,
                "symptoms": row.symptoms or [],
                "root_causes": row.root_causes or [],
                "solutions": row.solutions or [],
                "related_faults": row.related_faults or [],
                "spare_parts": row.spare_parts or [],
                "cases": row.cases or [],
                "source": row.source,
                "confidence": row.confidence,
                "verified": row.verified,
                "updated_at": _dt(row.updated_at),
            }
            for row in rows
        ],
    }


async def query_settings_context(db: AsyncSession, *, user: User, include_data_sources: bool = True) -> dict[str, Any]:
    provider_result = await db.execute(
        select(AIProviderConfig)
        .where(AIProviderConfig.user_id == user.id)
        .order_by(AIProviderConfig.created_at.asc(), AIProviderConfig.id.asc())
    )
    threshold_result = await db.execute(select(NotificationConfig).where(NotificationConfig.user_id == user.id))
    threshold = threshold_result.scalar_one_or_none()
    data_sources: list[dict[str, Any]] = []
    pipeline: dict[str, Any] = {}
    if include_data_sources:
        ds_result = await db.execute(select(DataSource).order_by(DataSource.source_type.asc()))
        data_sources = [_serialize_data_source(row) for row in ds_result.scalars().all()]
        counts = {}
        for label, model in (("scada", SCADARecord), ("vibration", VibrationData), ("blade_image", BladeImage)):
            counts[label] = int((await db.execute(select(func.count(model.id)))).scalar() or 0)
        latest_batch = await db.execute(select(DataImportBatch).order_by(DataImportBatch.started_at.desc()).limit(5))
        pipeline = {
            "record_counts": counts,
            "latest_batches": [
                {
                    "id": row.id,
                    "dataset_id": row.dataset_id,
                    "source_type": row.source_type,
                    "status": row.status,
                    "started_at": _dt(row.started_at),
                    "completed_at": _dt(row.completed_at),
                    "rows_imported": row.rows_imported,
                    "rows_skipped": row.rows_skipped,
                }
                for row in latest_batch.scalars().all()
            ],
        }
    return {
        "ai_providers": [_serialize_ai_provider(row) for row in provider_result.scalars().all()],
        "thresholds": {
            "id": threshold.id,
            "hi_threshold": threshold.hi_threshold,
            "email_enabled": threshold.email_enabled,
            "email_address": threshold.email_address,
            "wechat_enabled": threshold.wechat_enabled,
        }
        if threshold
        else {
            "id": None,
            "hi_threshold": 70.0,
            "email_enabled": False,
            "email_address": user.email,
            "wechat_enabled": False,
            "virtual_default": True,
        },
        "data_sources": data_sources,
        "pipeline": pipeline,
    }


async def draft_workorder_from_context(
    db: AsyncSession,
    *,
    turbine_ref: str,
    message: str,
    assignee_name: str | None = None,
) -> dict[str, Any]:
    turbine_resolution = await resolve_turbine_by_ref(db, turbine_ref)
    if not turbine_resolution.entity:
        return {
            "draft": None,
            "error_code": "turbine_not_found",
            "candidates": [_serialize_turbine(item) for item in turbine_resolution.candidates],
        }
    assignee: User | None = None
    if assignee_name:
        assignee_resolution = await resolve_personnel_by_name(db, assignee_name)
        if assignee_resolution.entity:
            assignee = assignee_resolution.entity
        else:
            return {
                "draft": None,
                "error_code": "assignee_not_found",
                "candidates": [_serialize_user(item) for item in assignee_resolution.candidates],
            }
    faults = await query_turbine_fault_context(db, turbine_resolution.entity.id)
    draft = draft_create_workorder_fields(
        turbine=turbine_resolution.entity,
        faults=faults,
        message=message,
        assignee_name=assignee.username if assignee else None,
        assignee_id=assignee.id if assignee else None,
        assignee_email=assignee.email if assignee else None,
    )
    return {
        "draft": draft,
        "turbine": _serialize_turbine(turbine_resolution.entity),
        "fault_context": fault_context_state(faults),
        "warnings": ["未查询到明确活跃故障，草稿按待诊断处理。"] if draft.get("fault_type") == "待诊断" else [],
    }


async def list_personnel_candidates(db: AsyncSession, *, name: str | None = None, limit: int = 20) -> dict[str, Any]:
    user_q = (
        select(User)
        .where(User.is_active.is_(True), User.role == "technician")
        .order_by(User.username.asc())
        .limit(limit)
    )
    personnel_q = select(MaintenancePersonnel).order_by(MaintenancePersonnel.name.asc()).limit(limit)
    if name:
        user_q = user_q.where(or_(User.username.ilike(f"%{name}%"), User.email.ilike(f"%{name}%")))
        personnel_q = personnel_q.where(or_(MaintenancePersonnel.name.ilike(f"%{name}%"), MaintenancePersonnel.email.ilike(f"%{name}%")))
    users = list((await db.execute(user_q)).scalars().all())
    rows = list((await db.execute(personnel_q)).scalars().all())
    return {
        "technician_users": [_serialize_user(item) for item in users],
        "maintenance_personnel": [_serialize_personnel(item) for item in rows],
    }

