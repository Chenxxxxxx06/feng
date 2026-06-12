"""故障百科 API — 知识图谱数据查询"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.database import get_db
from app.models import FaultKnowledgeNode, Turbine, Fault, WorkOrder
from app.api.auth import get_current_user

from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/knowledge-base")
async def list_all(
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取全部故障知识节点"""
    stmt = select(FaultKnowledgeNode)
    if category:
        stmt = stmt.where(FaultKnowledgeNode.category == category)
    if severity:
        stmt = stmt.where(FaultKnowledgeNode.severity == severity)
    result = await db.execute(stmt)
    nodes = result.scalars().all()
    return {"nodes": [_node_to_dict(n) for n in nodes]}


@router.get("/knowledge-base/search")
async def search(q: str, db: AsyncSession = Depends(get_db)):
    """全文搜索故障知识"""
    stmt = select(FaultKnowledgeNode).where(
        FaultKnowledgeNode.fault_type.ilike(f"%{q}%")
    )
    result = await db.execute(stmt)
    return {"nodes": [_node_to_dict(n) for n in result.scalars().all()]}


@router.get("/knowledge-base/{node_id}")
async def get_detail(node_id: int, db: AsyncSession = Depends(get_db)):
    """获取单个故障详情"""
    result = await db.execute(
        select(FaultKnowledgeNode).where(FaultKnowledgeNode.id == node_id)
    )
    node = result.scalar_one_or_none()
    if not node:
        raise HTTPException(404, "故障知识节点不存在")
    return _node_to_dict(node)


@router.get("/knowledge-base/categories")
async def get_categories(db: AsyncSession = Depends(get_db)):
    """获取分类统计"""
    result = await db.execute(select(FaultKnowledgeNode))
    nodes = result.scalars().all()
    cats: dict[str, int] = {}
    for n in nodes:
        cats[n.category] = cats.get(n.category, 0) + 1
    return {"categories": [{"name": k, "count": v} for k, v in cats.items()]}


@router.get("/knowledge-graph")
async def get_knowledge_graph(db: AsyncSession = Depends(get_db)):
    """获取知识图谱数据 — 节点+边，供前端 ECharts 渲染

    图谱包含:
    - 故障节点 (从 fault_knowledge 表)
    - 症状/根因/方案/备件 (从故障节点 JSON 展开)
    - 风机节点 (从 turbines 表)
    - 工单节点 + 人员关联
    - 节点间关系边
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    def add_node(id_: str, name: str, category: str, symbol: str, size: int = 30, extra: dict | None = None):
        if id_ in node_ids:
            return
        node_ids.add(id_)
        node = {"id": id_, "name": name, "category": category, "symbol": symbol, "symbolSize": size}
        if extra:
            node.update(extra)
        nodes.append(node)

    def add_edge(source: str, target: str, label: str = ""):
        edges.append({"source": source, "target": target, "label": label})

    # 1. 故障知识节点 + 构建 name→id 查找表
    result = await db.execute(select(FaultKnowledgeNode))
    fault_nodes = result.scalars().all()
    fault_name_to_id: dict[str, str] = {}
    for fn in fault_nodes:
        fid = f"fault_{fn.id}"
        fault_name_to_id[fn.fault_type] = fid
        add_node(fid, fn.fault_type, "fault", fn.icon, 40,
                 {"severity": fn.severity, "category": fn.category})

    # 2. 故障 → 症状/根因/方案/备件/关联故障
    for fn in fault_nodes:
        fid = f"fault_{fn.id}"
        for s in (fn.symptoms or []):
            sid = f"symptom_{fn.id}_{s['indicator']}"
            add_node(sid, s["indicator"], "symptom", "🔍", 20)
            add_edge(fid, sid, f">{s.get('threshold','')}")
        for rc in (fn.root_causes or []):
            rid = f"rootcause_{fn.id}_{rc[:20]}"
            add_node(rid, rc, "root_cause", "🎯", 20)
            add_edge(fid, rid, "根因")
        for sol in (fn.solutions or []):
            sid2 = f"solution_{fn.id}_{sol['action'][:20]}"
            add_node(sid2, sol["action"], "solution", "🔧", 22)
            add_edge(fid, sid2, f"{sol.get('difficulty','')}")
        for rf in (fn.related_faults or []):
            target_id = fault_name_to_id.get(rf.get("name", ""))
            if target_id:
                add_edge(fid, target_id, f"伴生{int(rf['probability']*100)}%")
        for sp in (fn.spare_parts or []):
            spid = f"part_{sp['name'][:30]}"
            add_node(spid, sp["name"], "spare_part", "📦", 20)
            add_edge(fid, spid, f"x{sp.get('quantity',1)}")

    # 3. 风机节点
    result = await db.execute(select(Turbine))
    turbines = result.scalars().all()
    for t in turbines:
        tid = f"turbine_{t.id}"
        add_node(tid, t.name or f"风机{t.id}", "turbine", "🌀", 35,
                 {"status": t.status, "region": t.region})

    # 4. 故障记录 → 风机
    result = await db.execute(select(Fault))
    faults = result.scalars().all()
    for f in faults:
        fid_fault = f"fault_record_{f.id}"
        add_node(fid_fault, f.fault_type or "未知故障", "fault_record", "⚠️", 25,
                 {"status": f.status, "confidence": f.confidence})
        add_edge(f"turbine_{f.turbine_id}", fid_fault, "发生故障")
        # 连接故障记录→知识库故障
        for fn in fault_nodes:
            if fn.fault_type and f.fault_type and fn.fault_type in f.fault_type:
                add_edge(fid_fault, f"fault_{fn.id}", "匹配知识")

    # 5. 工单 → 风机 + 故障
    result = await db.execute(select(WorkOrder))
    wos = result.scalars().all()
    for wo in wos:
        wid = f"workorder_{wo.id}"
        add_node(wid, wo.title or f"工单{wo.id}", "workorder", "📋", 25,
                 {"status": wo.status, "assignee": wo.assignee})
        add_edge(f"turbine_{wo.turbine_id}", wid, "工单")
        if wo.assignee:
            add_node(f"person_{wo.assignee}", wo.assignee, "personnel", "👤", 28)
            add_edge(wid, f"person_{wo.assignee}", "负责人")

    return {"nodes": nodes, "edges": edges}


def _node_to_dict(n: FaultKnowledgeNode) -> dict:
    return {
        "id": n.id,
        "fault_type": n.fault_type,
        "category": n.category,
        "icon": n.icon,
        "severity": n.severity,
        "symptoms": n.symptoms or [],
        "root_causes": n.root_causes or [],
        "solutions": n.solutions or [],
        "related_faults": n.related_faults or [],
        "spare_parts": n.spare_parts or [],
        "cases": n.cases or [],
        "source": getattr(n, "source", "manual"),
        "confidence": getattr(n, "confidence", 1.0),
        "verified": getattr(n, "verified", True),
    }


@router.patch("/knowledge-base/{node_id}/verify")
async def verify_node(node_id: int, db: AsyncSession = Depends(get_db)):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "节点不存在")
    node.verified = True
    node.confidence = 1.0
    await db.commit()
    return {"status": "verified"}


@router.delete("/knowledge-base/{node_id}")
async def delete_knowledge_node(node_id: int, db: AsyncSession = Depends(get_db)):
    node = await db.get(FaultKnowledgeNode, node_id)
    if not node:
        raise HTTPException(404, "节点不存在")
    await db.delete(node)
    await db.commit()
    return {"status": "deleted"}
