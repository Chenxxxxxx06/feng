"""审计链篡改检测演示端点 —— Demo 第四幕「安全合规与可追溯」高光素材。

提供三个只读端点：
- ``GET  /api/audit-demo/status``       签名密钥状态（算法/来源/公钥，不含私钥）
- ``GET  /api/audit-demo/candidates``   可用于演示的事件列表（按审计环数排序）
- ``POST /api/audit-demo/tamper-check`` 篡改检测演示：篡改前全链通过 → 篡改后第 N 环失败

【安全边界】
所有篡改都发生在 ``AuditChainService.build_chain`` 生成的**内存副本**上
（额外做了 deepcopy），端点全程只对数据库做 SELECT，
**绝不修改数据库中的任何真实数据**。响应里的 ``database_mutated`` 恒为 False。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.database import get_db
from app.models import AgentSpan, AgentTrace, Incident
from app.services.audit_chain_service import AuditChainService

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


class TamperCheckRequest(BaseModel):
    """篡改检测演示请求。所有字段可选，全部留空即自动选取素材。"""

    incident_id: Optional[int] = Field(
        default=None, description="事件数据库主键。留空则自动挑选审计环最多的事件。"
    )
    tamper_seq: Optional[int] = Field(
        default=None, ge=1, description="要篡改的环序号（1 起）。留空则取链条中部。"
    )
    tamper_field: str = Field(
        default="decision",
        description="要篡改的字段：decision / output_hash / input_hash / action_type / agent",
    )
    tamper_value: str = Field(
        default="auto_approved_without_human",
        max_length=128,
        description="篡改后的取值（演示用，例如把「需人工确认」改成「已自动放行」）",
    )
    allow_synthetic: bool = Field(
        default=True,
        description="库中没有带 span 的事件时，是否允许使用合成演示链（明确标注 synthetic）",
    )


async def _pick_incident(db: AsyncSession) -> Optional[Incident]:
    """挑选审计环最多的事件作为演示素材。"""
    stmt = (
        select(Incident.id, func.count(AgentSpan.id).label("span_count"))
        .join(AgentTrace, AgentTrace.incident_id == Incident.id)
        .join(AgentSpan, AgentSpan.trace_id == AgentTrace.trace_id)
        .group_by(Incident.id)
        .order_by(func.count(AgentSpan.id).desc(), Incident.id.desc())
        .limit(1)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        return None
    return await db.get(Incident, row[0])


@router.get("/audit-demo/status")
async def audit_demo_status(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """返回审计链签名能力状态（不暴露私钥）。"""
    service = AuditChainService(db)
    info = service.key_info()
    incident = await _pick_incident(db)
    return {
        **info,
        "default_enabled": True,
        "demo_incident_available": incident is not None,
        "demo_incident_id": incident.incident_id if incident else None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/audit-demo/candidates")
async def audit_demo_candidates(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """列出可用于篡改演示的事件（按审计环数从多到少）。"""
    stmt = (
        select(
            Incident.id,
            Incident.incident_id,
            Incident.title,
            Incident.severity,
            func.count(AgentSpan.id).label("span_count"),
        )
        .join(AgentTrace, AgentTrace.incident_id == Incident.id)
        .join(AgentSpan, AgentSpan.trace_id == AgentTrace.trace_id)
        .group_by(Incident.id)
        .order_by(func.count(AgentSpan.id).desc(), Incident.id.desc())
        .limit(20)
    )
    rows = (await db.execute(stmt)).all()
    return {
        "total": len(rows),
        "candidates": [
            {
                "id": r[0],
                "incident_id": r[1],
                "title": r[2],
                "severity": r[3],
                "audit_links": r[4],
            }
            for r in rows
        ],
    }


@router.post("/audit-demo/tamper-check")
async def tamper_check(
    data: TamperCheckRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """篡改检测演示：同一条审计链，篡改前后逐环对比。

    返回结构（前端可视化直接消费）：

    - ``baseline``：篡改前的全链校验结果，含每一环的
      ``prev_hash / current_hash / recomputed_hash / link_ok / hash_ok / reason``
      以及 Ed25519 根签名。
    - ``scenarios``：两种攻击场景（只改内容 / 改内容并重算哈希）的对应结果，
      标出 ``first_broken_at``、``broken_entries``、``detected_by``。
    - ``summary.headline``：一句话结论，可直接投屏。
    """
    service = AuditChainService(db)

    incident: Optional[Incident] = None
    if data.incident_id is not None:
        incident = await db.get(Incident, data.incident_id)
        if not incident:
            raise HTTPException(status_code=404, detail="事件不存在")
    else:
        incident = await _pick_incident(db)

    chain = await service.build_chain(incident) if incident else []
    data_source = "real_incident"

    if not chain:
        if not data.allow_synthetic:
            raise HTTPException(
                status_code=404,
                detail="该事件没有可供演示的 Agent 审计记录；可将 allow_synthetic 设为 true 使用合成演示链。",
            )
        chain = service.build_demo_chain()
        data_source = "synthetic_demo"

    tamper_seq = data.tamper_seq or max(1, (len(chain) + 1) // 2)
    if tamper_seq > len(chain):
        tamper_seq = len(chain)

    report = service.tamper_scenarios(
        chain,
        tamper_seq=tamper_seq,
        tamper_field=data.tamper_field,
        tamper_value=data.tamper_value,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": data_source,
        "data_source_note": (
            "使用数据库中真实的 Agent 执行轨迹构建审计链（只读）。"
            if data_source == "real_incident"
            else "库中暂无带 Agent 轨迹的事件，使用**合成**演示链，不代表真实风场运行数据。"
        ),
        "incident_id": incident.incident_id if (incident and data_source == "real_incident") else None,
        "incident_title": incident.title if (incident and data_source == "real_incident") else None,
        "signing": service.key_info(),
        "tamperable_fields": list(service.TAMPERABLE_FIELDS),
        **report,
    }
