"""故障百科 API — 知识图谱数据查询"""

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from typing import Any, Optional

from app.database import get_db
from app.models import FaultKnowledgeNode, Turbine, Fault, WorkOrder
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


class KnowledgeNodeCreate(BaseModel):
    fault_type: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    icon: str = Field(default="⚠️", max_length=8)
    severity: str = Field(default="medium", pattern="^(low|medium|high|critical)$")
    symptoms: list[dict[str, Any]] = Field(default_factory=list)
    root_causes: list[str] = Field(default_factory=list)
    solutions: list[dict[str, Any]] = Field(default_factory=list)
    related_faults: list[dict[str, Any]] = Field(default_factory=list)
    spare_parts: list[dict[str, Any]] = Field(default_factory=list)
    cases: list[dict[str, Any]] = Field(default_factory=list)
    source: str = Field(default="manual", max_length=32)
    confidence: float = Field(default=1.0, ge=0, le=1)
    verified: bool = True
    extracted_from: Optional[str] = None


def _review_state(node: FaultKnowledgeNode) -> str:
    if getattr(node, "source", "manual") == "ai_extracted" and not getattr(node, "verified", True):
        return "pending"
    return "approved"


def _apply_review_filter(stmt, review_state: Optional[str]):
    if review_state == "pending":
        return stmt.where(FaultKnowledgeNode.source == "ai_extracted", FaultKnowledgeNode.verified.is_(False))
    if review_state == "approved":
        return stmt.where(FaultKnowledgeNode.verified.is_(True))
    if review_state == "ai":
        return stmt.where(FaultKnowledgeNode.source == "ai_extracted")
    return stmt


class KnowledgeNodeUpdate(BaseModel):
    fault_type: Optional[str] = Field(default=None, min_length=1, max_length=128)
    category: Optional[str] = Field(default=None, min_length=1, max_length=64)
    icon: Optional[str] = Field(default=None, max_length=8)
    severity: Optional[str] = Field(default=None, pattern="^(low|medium|high|critical)$")
    symptoms: Optional[list[dict[str, Any]]] = None
    root_causes: Optional[list[str]] = None
    solutions: Optional[list[dict[str, Any]]] = None
    related_faults: Optional[list[dict[str, Any]]] = None
    spare_parts: Optional[list[dict[str, Any]]] = None
    cases: Optional[list[dict[str, Any]]] = None
    source: Optional[str] = Field(default=None, max_length=32)
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    verified: Optional[bool] = None
    extracted_from: Optional[str] = None

# ─── helpers ───
SEVERITY_CN = {"low": "低", "medium": "中", "high": "高", "critical": "紧急"}
STATUS_CN = {"open": "待诊断", "diagnosing": "诊断中", "confirmed": "已确认", "resolved": "已解决"}
WO_STATUS_CN = {"pending": "待处理", "in_progress": "进行中", "completed": "已完成", "cancelled": "已取消"}

def _node_to_dict(n: FaultKnowledgeNode) -> dict:
    return {
        "id": n.id, "fault_type": n.fault_type, "category": n.category,
        "icon": n.icon, "severity": n.severity,
        "symptoms": n.symptoms or [], "root_causes": n.root_causes or [],
        "solutions": n.solutions or [], "related_faults": n.related_faults or [],
        "spare_parts": n.spare_parts or [], "cases": n.cases or [],
        "source": getattr(n, "source", "manual"),
        "confidence": getattr(n, "confidence", 1.0),
        "verified": getattr(n, "verified", True),
        "review_state": _review_state(n),
    }


# ═══════════════════════════════════════════════════
# Knowledge Base CRUD
# ═══════════════════════════════════════════════════

@router.get("/knowledge-base")
async def list_all(
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    review_state: Optional[str] = Query(None, description="all | pending | approved | ai"),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(FaultKnowledgeNode)
    if category:
        stmt = stmt.where(FaultKnowledgeNode.category == category)
    if severity:
        stmt = stmt.where(FaultKnowledgeNode.severity == severity)
    stmt = _apply_review_filter(stmt, review_state)
    result = await db.execute(stmt)
    return {"nodes": [_node_to_dict(n) for n in result.scalars().all()]}


@router.get("/knowledge-base/search")
async def search(q: str, db: AsyncSession = Depends(get_db)):
    stmt = select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type.ilike(f"%{q}%"))
    result = await db.execute(stmt)
    return {"nodes": [_node_to_dict(n) for n in result.scalars().all()]}


@router.post("/knowledge-base")
async def create_knowledge_node(data: KnowledgeNodeCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == data.fault_type)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Fault knowledge node already exists")

    node = FaultKnowledgeNode(**data.model_dump())
    db.add(node)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Fault knowledge node already exists")

    await db.refresh(node)
    return _node_to_dict(node)


@router.get("/knowledge-base/{node_id}")
async def get_detail(node_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FaultKnowledgeNode).where(FaultKnowledgeNode.id == node_id))
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(404, "故障知识节点不存在")
    return _node_to_dict(node)


@router.get("/knowledge-base/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FaultKnowledgeNode))
    cats: dict[str, int] = {}
    for n in result.scalars().all():
        cats[n.category] = cats.get(n.category, 0) + 1
    return {"categories": [{"name": k, "count": v} for k, v in cats.items()]}


@router.patch("/knowledge-base/{node_id}/verify")
async def verify_node(node_id: int, db: AsyncSession = Depends(get_db)):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "节点不存在")
    node.verified = True
    node.confidence = 1.0
    await db.commit()
    return {"status": "verified"}


@router.patch("/knowledge-base/{node_id}/reject")
async def reject_node(node_id: int, db: AsyncSession = Depends(get_db)):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "Knowledge node not found")
    await db.delete(node)
    await db.commit()
    return {"status": "rejected"}


@router.patch("/knowledge-base/{node_id}")
async def update_knowledge_node(
    node_id: int,
    data: KnowledgeNodeUpdate,
    db: AsyncSession = Depends(get_db),
):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "Knowledge node not found")

    payload = data.model_dump(exclude_unset=True)
    if "fault_type" in payload and payload["fault_type"] != node.fault_type:
        existing = await db.execute(
            select(FaultKnowledgeNode).where(FaultKnowledgeNode.fault_type == payload["fault_type"])
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "Fault knowledge node already exists")

    for key, value in payload.items():
        setattr(node, key, value)
    node.updated_at = datetime.now(timezone.utc)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Fault knowledge node already exists")

    await db.refresh(node)
    return _node_to_dict(node)


@router.delete("/knowledge-base/{node_id}")
async def delete_knowledge_node(node_id: int, db: AsyncSession = Depends(get_db)):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "节点不存在")
    await db.delete(node)
    await db.commit()
    return {"status": "deleted"}


# ═══════════════════════════════════════════════════
# Knowledge Graph — 双视图
# ═══════════════════════════════════════════════════

@router.get("/knowledge-graph")
async def get_knowledge_graph(
    include_unverified: bool = Query(False, description="Include pending AI-extracted knowledge"),
    view: str = Query("topology", description="topology | knowledge"),
    fault_type: Optional[str] = Query(None, description="知识视图: 聚焦故障类型"),
    region: Optional[str] = Query(None, description="拓扑视图: 区域筛选"),
    active_only: bool = Query(False, description="拓扑视图: 仅显示活跃"),
    db: AsyncSession = Depends(get_db),
):
    """
    知识图谱 — 两种视图:

    **topology** (运维拓扑): 风机在哪、出了什么事、谁在修、什么时候
      节点: turbine → fault_record → workorder → person
      筛选: region, active_only
      不含知识节点(症状/根因/方案等)

    **knowledge** (知识网络): 某个故障的原理 — 症状/根因/方案/备件/案例
      节点: fault → symptom / root_cause / solution / spare_part / case / related_fault
      参数: fault_type (必填)
      不含运维节点(风机/工单/人员)
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(id_: str, name: str, category: str, symbol: str, size: int = 30, extra: dict | None = None):
        if id_ in node_ids: return
        node_ids.add(id_)
        node = {"id": id_, "name": name, "category": category, "symbol": symbol, "symbolSize": size}
        if extra: node.update(extra)
        nodes.append(node)

    def add_edge(source: str, target: str, label: str = ""):
        edges.append({"source": source, "target": target, "label": label})

    # ─── Load data ───
    result = await db.execute(select(FaultKnowledgeNode))
    all_knowledge = result.scalars().all()
    all_knowledge_all_states = all_knowledge
    if not include_unverified:
        all_knowledge = [n for n in all_knowledge if getattr(n, "verified", True)]

    result = await db.execute(select(Turbine))
    all_turbines = result.scalars().all()

    stmt = select(Fault)
    if active_only:
        stmt = stmt.where(Fault.status.in_(["open", "diagnosing", "confirmed"]))
    result = await db.execute(stmt)
    all_faults = result.scalars().all()

    stmt = select(WorkOrder)
    if active_only:
        stmt = stmt.where(WorkOrder.status.in_(["pending", "in_progress"]))
    result = await db.execute(stmt)
    all_workorders = result.scalars().all()

    # Build WO lookup: fault_id → workorder
    wo_by_fault: dict[int, list[WorkOrder]] = {}
    for wo in all_workorders:
        if wo.fault_id:
            wo_by_fault.setdefault(wo.fault_id, []).append(wo)

    # ─── Stats ───
    stats = {
        "active_faults": sum(1 for f in all_faults if f.status in ("open", "diagnosing", "confirmed")),
        "warning_turbines": sum(1 for t in all_turbines if t.status in ("warning", "fault")),
        "pending_workorders": sum(1 for w in all_workorders if w.status in ("pending", "in_progress")),
        "personnel_count": len(set(w.assignee for w in all_workorders if w.assignee)),
        "total_turbines": len(all_turbines),
        "total_knowledge_nodes": len(all_knowledge),
        "pending_knowledge_nodes": sum(
            1 for n in all_knowledge_all_states
            if getattr(n, "source", "manual") == "ai_extracted" and not getattr(n, "verified", True)
        ),
        "regions": sorted(set(getattr(t, 'region', '') for t in all_turbines if getattr(t, 'region', ''))),
    }

    # ═══════════════════════════════════════════════
    # VIEW: topology — 运维拓扑
    # ═══════════════════════════════════════════════
    if view == "topology":
        # ── Turbines ──
        fault_counts: dict[int, int] = {}
        for f in all_faults:
            if f.status in ("open", "diagnosing", "confirmed"):
                fault_counts[f.turbine_id] = fault_counts.get(f.turbine_id, 0) + 1

        filtered_turbines = all_turbines
        if region:
            filtered_turbines = [t for t in all_turbines if getattr(t, 'region', '') == region]

        for t in filtered_turbines:
            fc = fault_counts.get(t.id, 0)
            status_icon = {"normal": "✅", "warning": "🟡", "fault": "🔴", "maintenance": "🔧"}.get(t.status, "⚪")
            add_node(f"turbine_{t.id}", t.name or f"风机{t.id}", "turbine", "🌀",
                     44 + fc * 12,
                     {"status": t.status, "region": getattr(t, 'region', ''),
                      "fault_count": fc, "status_icon": status_icon})

        # ── Fault records (事件层) ──
        for f in all_faults:
            fid = f"fault_record_{f.id}"
            is_active = f.status in ("open", "diagnosing", "confirmed")
            # Format time compactly
            ts = f.detected_at
            time_str = ts.strftime("%m/%d %H:%M") if ts else ""
            label = f.fault_type or "未知故障"

            add_node(fid, label, "fault_record", "⚠️",
                     30 if is_active else 22,
                     {"fault_type": f.fault_type, "status": f.status,
                      "status_cn": STATUS_CN.get(f.status, f.status),
                      "active": is_active, "detected_at": time_str,
                      "confidence": getattr(f, 'confidence', 0)})

            # Edge: turbine → fault_record
            edge_label = f"{time_str}"
            add_edge(f"turbine_{f.turbine_id}", fid, edge_label)

            # Edge: fault_record → workorder (if linked)
            wos = wo_by_fault.get(f.id, [])
            for wo in wos:
                add_edge(fid, f"workorder_{wo.id}", f"工单-{wo.id}")

        # ── Work orders ──
        for wo in all_workorders:
            wid = f"workorder_{wo.id}"
            icon = {"pending": "📝", "in_progress": "🔧", "completed": "✅", "cancelled": "❌"}.get(wo.status, "📋")
            add_node(wid, wo.title or f"WO-{wo.id}", "workorder", icon, 28,
                     {"status": wo.status, "status_cn": WO_STATUS_CN.get(wo.status, wo.status),
                      "assignee": wo.assignee})

            # Edge: turbine → workorder (all work orders link to a turbine)
            if wo.turbine_id:
                add_edge(f"turbine_{wo.turbine_id}", wid, "工单")

            # Edge: workorder → personnel
            if wo.assignee:
                pid = f"person_{wo.assignee}"
                add_node(pid, wo.assignee, "personnel", "👤", 32)
                add_edge(wid, pid, "负责人")

        return {"stats": stats, "nodes": nodes, "edges": edges}

    # ═══════════════════════════════════════════════
    # VIEW: knowledge — 故障知识网络
    # ═══════════════════════════════════════════════
    if view == "knowledge":
        # Find target fault — exact match first, then fuzzy
        target = None
        if fault_type:
            for fn in all_knowledge:
                if fn.fault_type == fault_type:
                    target = fn
                    break
            if not target:
                for fn in all_knowledge:
                    if fault_type in (fn.fault_type or ""):
                        target = fn
                        break

        # If no target specified, show all knowledge (filtered view)
        targets = [target] if target else all_knowledge

        # Build name→id map for cross-references
        name_to_id: dict[str, str] = {}
        for fn in all_knowledge:
            name_to_id[fn.fault_type] = f"fault_{fn.id}"

        for fn in targets:
            fid = f"fault_{fn.id}"
            sev = fn.severity or "medium"
            add_node(fid, fn.fault_type, "fault", fn.icon, 52,
                     {"severity": sev, "severity_cn": SEVERITY_CN.get(sev, sev),
                      "category": fn.category})

            # ── Symptoms ──
            for s in (fn.symptoms or []):
                sid = f"symptom_{fn.id}_{s['indicator'][:20]}"
                add_node(sid, s["indicator"], "symptom", "🔍", 24,
                         {"threshold": s.get("threshold", ""), "unit": s.get("unit", "")})
                add_edge(fid, sid, s.get("threshold", ""))

            # ── Root causes ──
            for rc in (fn.root_causes or []):
                rid = f"rootcause_{fn.id}_{rc[:20]}"
                add_node(rid, rc, "root_cause", "🎯", 24)
                add_edge(fid, rid, "导致")

            # ── Solutions ──
            for sol in (fn.solutions or []):
                sid2 = f"solution_{fn.id}_{sol['action'][:20]}"
                diff = sol.get("difficulty", "")
                add_node(sid2, sol["action"], "solution", "🔧", 26,
                         {"difficulty": diff, "downtime_hours": sol.get("downtime_hours", 0)})
                add_edge(fid, sid2, f"{diff} · {sol.get('downtime_hours', 0)}h")

            # ── Spare parts ──
            for sp in (fn.spare_parts or []):
                spid = f"part_{sp['name'][:24]}"
                add_node(spid, sp["name"], "spare_part", "📦", 24,
                         {"quantity": sp.get("quantity", 1), "est_cost": sp.get("est_cost", 0)})
                add_edge(fid, spid, f"x{sp.get('quantity', 1)}")

            # ── Related faults ──
            for rf in (fn.related_faults or []):
                target_id = name_to_id.get(rf.get("name", ""))
                if target_id and target_id != fid:
                    add_edge(fid, target_id, f"伴生{int(rf['probability'] * 100)}%")

            # ── Historical cases ──
            for c in (fn.cases or []):
                cid = f"case_{fn.id}_{c['turbine'][:12]}"
                add_node(cid, f"{c['turbine']}\n{c['date']}", "case_record", "📖", 24,
                         {"resolution": c.get("resolution", ""),
                          "total_cost": c.get("total_cost", 0),
                          "downtime_days": c.get("downtime_days", 0)})
                add_edge(fid, cid, "案例")

        return {"stats": stats, "nodes": nodes, "edges": edges, "fault_type": fault_type}


# ═══════════════════════════════════════════════════
# Stats endpoint
# ═══════════════════════════════════════════════════

@router.get("/knowledge-graph/stats")
async def get_graph_stats(include_unverified: bool = Query(False), db: AsyncSession = Depends(get_db)):
    knowledge_stmt = select(func.count(FaultKnowledgeNode.id))
    if not include_unverified:
        knowledge_stmt = knowledge_stmt.where(FaultKnowledgeNode.verified.is_(True))
    result = await db.execute(knowledge_stmt)
    knowledge_count = result.scalar() or 0
    result = await db.execute(
        select(func.count(FaultKnowledgeNode.id)).where(
            FaultKnowledgeNode.source == "ai_extracted",
            FaultKnowledgeNode.verified.is_(False),
        )
    )
    pending_knowledge_count = result.scalar() or 0
    result = await db.execute(select(func.count(Turbine.id)))
    turbine_count = result.scalar() or 0
    result = await db.execute(select(func.count(Fault.id)))
    fault_count = result.scalar() or 0
    result = await db.execute(select(func.count(Fault.id)).where(Fault.status.in_(["open", "diagnosing", "confirmed"])))
    active_fault_count = result.scalar() or 0
    result = await db.execute(select(func.count(WorkOrder.id)))
    wo_count = result.scalar() or 0
    result = await db.execute(select(func.count(WorkOrder.id)).where(WorkOrder.status.in_(["pending", "in_progress"])))
    pending_wo_count = result.scalar() or 0
    result = await db.execute(select(Turbine).where(Turbine.status.in_(["warning", "fault"])))
    warning_count = len(result.scalars().all())
    result = await db.execute(select(Turbine.region).where(Turbine.region.isnot(None)).distinct())
    regions = [r[0] for r in result.all() if r[0]]
    result = await db.execute(select(WorkOrder.assignee).where(WorkOrder.assignee.isnot(None)).distinct())
    personnel = [p[0] for p in result.all() if p[0]]

    return {
        "knowledge_nodes": knowledge_count, "turbines": turbine_count,
        "pending_knowledge_nodes": pending_knowledge_count,
        "total_faults": fault_count, "active_faults": active_fault_count,
        "total_workorders": wo_count, "pending_workorders": pending_wo_count,
        "warning_turbines": warning_count, "regions": regions, "personnel": personnel,
    }
