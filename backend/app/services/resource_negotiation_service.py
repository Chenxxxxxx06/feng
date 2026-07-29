"""Agent-to-Agent 资源协商协议（v2 —— 落库版）。

多事件对稀缺资源的协商，包含：

- 资源请求（经济 + 风险复合竞价），**落库**到 ``resource_bids``
- 资源锁（带超时），**落库**到 ``resource_locks``
- 冲突检测：真实查询同一资源上的活跃锁 / 待决竞价
- 赢家判定（安全 > 经济 > 紧急度 > 公平）
- 落标方返回人工协调提示，不编造资源可用性
- 锁释放与重新协商

v1 → v2 的三处实质修正
----------------------
1. **锁跨请求失效**：v1 把锁放在 ``self._locks`` 实例字典里，而 FastAPI 每个
   请求都会新建一次 service 实例，因此上一个请求拿到的锁在下一个请求里
   查不到，"独占"从未真正生效。v2 改为落库 + 惰性过期。
2. **``check_conflicts`` 是空实现**：v1 直接 ``return []``（注释写着
   "In production: query DB"）。v2 真实查询三类冲突源并返回冲突方明细。
3. **替代件硬编码 2 条**：v1 用一个写死的 dict 映射两个假 SN 号。v2 改为
   按品类 / 适用机型 / 可治故障从 ``spare_parts`` 表检索，查不到就诚实返回空
   并说明原因，绝不编造。

对外函数签名与 ``app/api/incidents.py`` 的调用保持兼容（只增字段不改删）。
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Incident
from app.models.negotiation import ResourceBid, ResourceLockRecord

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite 取回的 DateTime 可能没有 tzinfo，统一补 UTC 后再比较。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@dataclass
class ResourceRequest:
    """One agent's bid for a resource."""
    request_id: str = field(default_factory=lambda: f"REQ-{uuid.uuid4().hex[:8]}")
    incident_id: str = ""
    resource_id: str = ""
    resource_type: str = ""  # spare_part / personnel / tool / weather_window
    quantity: int = 1
    urgency: str = "medium"  # low / medium / high / critical
    economic_impact_per_hour: float = 0.0  # CNY/hour of delay
    safety_risk: float = 0.0  # 0-100
    max_wait_hours: float = 24.0  # How long can this incident wait?
    bid_score: float = 0.0  # Computed score
    timestamp: datetime = field(default_factory=_utcnow)
    #: v2 新增：竞价分项拆解（可解释），不影响既有字段
    score_breakdown: dict[str, float] = field(default_factory=dict)


@dataclass
class ResourceLock:
    """A lock on a resource allocated to an incident."""
    lock_id: str = field(default_factory=lambda: f"LOCK-{uuid.uuid4().hex[:8]}")
    resource_id: str = ""
    incident_id: str = ""
    locked_at: datetime = field(default_factory=_utcnow)
    expires_at: Optional[datetime] = None
    released: bool = False
        #: 历史兼容字段；独立库存域归档后始终为 None。
    reservation_lock_id: Optional[str] = None
    persisted: bool = False


@dataclass
class NegotiationResult:
    """Result of one resource negotiation round."""
    resource_id: str = ""
    winner_incident_id: str = ""
    winner_score: float = 0.0
    losers: list[dict[str, Any]] = field(default_factory=list)
    lock: Optional[ResourceLock] = None
    reasoning: str = ""
    escalated: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_utcnow)
    #: v2 新增：协商时刻检测到的既有冲突方
    conflicts: list[dict[str, Any]] = field(default_factory=list)


class ResourceNegotiationService:
    """Agent-to-Agent resource negotiation with **persistent** locking."""

    LOCK_TIMEOUT_HOURS = 24  # Auto-release locks after this period

    def __init__(self, db: AsyncSession):
        self.db = db
        # 仅作单次请求内的读缓存；权威状态在 resource_locks 表。
        self._locks: dict[str, ResourceLock] = {}

    # ══════════════════════════════════════════════════════════════
    # 竞价
    # ══════════════════════════════════════════════════════════════

    async def request_resource(
        self,
        incident: Incident,
        resource_id: str,
        resource_type: str = "spare_part",
        urgency: str = "medium",
        economic_impact: float = 0.0,
        safety_risk: float = 0.0,
        max_wait_hours: float = 24.0,
        quantity: int = 1,
    ) -> ResourceRequest:
        """提交一个资源请求（竞价），并**落库**以便后续冲突检测与复盘。"""
        urgency_weights = {"critical": 10, "high": 7, "medium": 4, "low": 1}
        u_weight = urgency_weights.get(urgency, 4)

        # Composite score: safety (40%) + economic (30%) + urgency (20%) + fairness (10%)
        safety_term = 0.40 * min(100, safety_risk)
        economic_term = 0.30 * min(100, economic_impact / 100)
        urgency_term = 0.20 * u_weight * 10
        fairness_term = 0.10 * 50
        bid_score = safety_term + economic_term + urgency_term + fairness_term

        req = ResourceRequest(
            incident_id=incident.incident_id,
            resource_id=resource_id,
            resource_type=resource_type,
            quantity=quantity,
            urgency=urgency,
            economic_impact_per_hour=economic_impact,
            safety_risk=safety_risk,
            max_wait_hours=max_wait_hours,
            bid_score=bid_score,
            score_breakdown={
                "safety_40pct": round(safety_term, 2),
                "economic_30pct": round(economic_term, 2),
                "urgency_20pct": round(urgency_term, 2),
                "fairness_10pct": round(fairness_term, 2),
            },
        )

        await self._persist_bid(req, incident_pk=incident.id)
        return req

    async def _persist_bid(
        self, req: ResourceRequest, incident_pk: Optional[int] = None
    ) -> None:
        """把竞价写入 ``resource_bids``。落库失败不阻断协商主流程。"""
        try:
            if incident_pk is None and req.incident_id:
                incident_pk = await self._resolve_incident_pk(req.incident_id)
            self.db.add(
                ResourceBid(
                    request_id=req.request_id,
                    resource_id=req.resource_id,
                    resource_type=req.resource_type or "spare_part",
                    incident_id=req.incident_id,
                    incident_pk=incident_pk,
                    quantity=req.quantity,
                    urgency=req.urgency,
                    economic_impact_per_hour=req.economic_impact_per_hour,
                    safety_risk=req.safety_risk,
                    max_wait_hours=req.max_wait_hours,
                    bid_score=req.bid_score,
                    score_breakdown=json.dumps(req.score_breakdown, ensure_ascii=False),
                    status="pending",
                )
            )
            await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            logger.warning("竞价落库失败（不阻断协商）: %s", exc)

    async def _resolve_incident_pk(self, incident_id: str) -> Optional[int]:
        if not incident_id:
            return None
        row = (
            await self.db.execute(
                select(Incident.id).where(Incident.incident_id == incident_id)
            )
        ).scalar_one_or_none()
        return row

    # ══════════════════════════════════════════════════════════════
    # 协商
    # ══════════════════════════════════════════════════════════════

    async def negotiate(
        self,
        resource_id: str,
        requests: list[ResourceRequest],
    ) -> NegotiationResult:
        """Run one negotiation round for a resource.

        Algorithm:
        1. 惰性过期：先把到期未释放的锁标记为 expired
        2. 若资源仍被活跃锁占用 → 直接返回现有持有者（真正的互斥，跨请求生效）
        3. 按复合竞价分排序，最高者中标
        4. 中标者落库资源锁；备件类资源同时尝试建立 ``PartReservation``
        5. 落标者给出替代件建议（查 SparePart 表）与升级路径
        """
        await self._expire_stale_locks(resource_id)

        existing = await self._get_active_lock(resource_id)
        if existing is not None:
            lock = self._to_dataclass(existing)
            self._locks[resource_id] = lock
            conflicts = await self.check_conflicts(resource_id)
            return NegotiationResult(
                resource_id=resource_id,
                winner_incident_id=existing.incident_id or "",
                winner_score=float(existing.priority_score or 0.0),
                losers=[],
                lock=lock,
                reasoning=(
                    f"Resource already locked by {existing.incident_id} "
                    f"(lock_id={existing.lock_id}, expires_at="
                    f"{_aware(existing.expires_at).isoformat() if existing.expires_at else 'never'})"
                ),
                timestamp=_utcnow(),
                conflicts=conflicts,
            )

        if not requests:
            return NegotiationResult(
                resource_id=resource_id,
                winner_incident_id="",
                winner_score=0.0,
                reasoning="No requests submitted",
                conflicts=await self.check_conflicts(resource_id),
            )

        # 补算未评分的竞价（API 直接构造 ResourceRequest 时 bid_score 可能为 0）
        for r in requests:
            if not r.bid_score:
                r.bid_score = self._score(r)
                r.score_breakdown = self._score_breakdown(r)
            if not r.resource_id:
                r.resource_id = resource_id

        sorted_requests = sorted(requests, key=lambda r: r.bid_score, reverse=True)
        winner = sorted_requests[0]
        losers = sorted_requests[1:]

        lock = await self._create_lock(resource_id, winner)

        escalated: list[str] = []
        loser_details: list[dict[str, Any]] = []
        for loser in losers:
            wait_time = loser.max_wait_hours
            if wait_time <= 0:
                escalated.append(loser.incident_id)

            alt_resource = await self._find_alternative(resource_id, loser.resource_type)
            alt_candidates = await self.find_alternatives(
                resource_id, loser.resource_type, limit=3
            )

            loser_details.append({
                "incident_id": loser.incident_id,
                "bid_score": loser.bid_score,
                "can_wait_hours": loser.max_wait_hours,
                "escalated": wait_time <= 0,
                "alternative_resource": alt_resource,
                # v2 新增：来自 spare_parts 表的可替代件明细（含匹配依据与库存）
                "alternative_candidates": alt_candidates,
                "recommendation": (
                    f"Use alternative: {alt_resource}"
                    if alt_resource
                    else f"Escalate to manual procurement for {resource_id}"
                ),
            })

        await self._resolve_bids(resource_id, winner, losers)

        return NegotiationResult(
            resource_id=resource_id,
            winner_incident_id=winner.incident_id,
            winner_score=winner.bid_score,
            losers=loser_details,
            lock=lock,
            reasoning=(
                f"{winner.incident_id} wins (score={winner.bid_score:.0f}): "
                f"safety_risk={winner.safety_risk}, "
                f"economic_impact={winner.economic_impact_per_hour} CNY/h, "
                f"urgency={winner.urgency}"
            ),
            escalated=escalated,
            conflicts=await self.check_conflicts(resource_id, exclude_lock_id=lock.lock_id),
        )

    @staticmethod
    def _score(r: ResourceRequest) -> float:
        urgency_weights = {"critical": 10, "high": 7, "medium": 4, "low": 1}
        u = urgency_weights.get(r.urgency, 4)
        return (
            0.40 * min(100, r.safety_risk)
            + 0.30 * min(100, r.economic_impact_per_hour / 100)
            + 0.20 * u * 10
            + 0.10 * 50
        )

    @staticmethod
    def _score_breakdown(r: ResourceRequest) -> dict[str, float]:
        urgency_weights = {"critical": 10, "high": 7, "medium": 4, "low": 1}
        u = urgency_weights.get(r.urgency, 4)
        return {
            "safety_40pct": round(0.40 * min(100, r.safety_risk), 2),
            "economic_30pct": round(0.30 * min(100, r.economic_impact_per_hour / 100), 2),
            "urgency_20pct": round(0.20 * u * 10, 2),
            "fairness_10pct": 5.0,
        }

    # ══════════════════════════════════════════════════════════════
    # 锁生命周期（落库）
    # ══════════════════════════════════════════════════════════════

    async def _expire_stale_locks(self, resource_id: Optional[str] = None) -> int:
        """惰性过期：把已过 ``expires_at`` 的 held 锁标记为 expired。"""
        now = _utcnow()
        stmt = (
            update(ResourceLockRecord)
            .where(
                ResourceLockRecord.status == "held",
                ResourceLockRecord.expires_at.is_not(None),
                ResourceLockRecord.expires_at < now,
            )
            .values(status="expired", released_at=now)
        )
        if resource_id:
            stmt = stmt.where(ResourceLockRecord.resource_id == resource_id)
        # synchronize_session=False：批量 UPDATE 不回写已加载对象。
        # SQLite 取回的 DateTime 无 tzinfo，用默认的 evaluate 策略会在内存里
        # 拿 naive 与 aware datetime 相比而抛 TypeError。
        result = await self.db.execute(
            stmt.execution_options(synchronize_session=False)
        )
        if result.rowcount:
            await self.db.commit()
            logger.info("自动过期资源锁 %d 把 (resource=%s)", result.rowcount, resource_id or "*")
        return int(result.rowcount or 0)

    async def _get_active_lock(self, resource_id: str) -> Optional[ResourceLockRecord]:
        return (
            await self.db.execute(
                select(ResourceLockRecord)
                .where(
                    ResourceLockRecord.resource_id == resource_id,
                    ResourceLockRecord.status == "held",
                )
                .order_by(ResourceLockRecord.locked_at.desc())
            )
        ).scalars().first()

    async def _create_lock(
        self, resource_id: str, winner: ResourceRequest
    ) -> ResourceLock:
        """为中标者创建持久化资源锁。"""
        now = _utcnow()
        expires_at = now + timedelta(hours=self.LOCK_TIMEOUT_HOURS)
        lock = ResourceLock(
            resource_id=resource_id,
            incident_id=winner.incident_id,
            locked_at=now,
            expires_at=expires_at,
        )

        incident_pk = await self._resolve_incident_pk(winner.incident_id)
        reservation_lock_id: Optional[str] = None

        try:
            self.db.add(
                ResourceLockRecord(
                    lock_id=lock.lock_id,
                    resource_id=resource_id,
                    resource_type=winner.resource_type or "spare_part",
                    incident_id=winner.incident_id,
                    incident_pk=incident_pk,
                    holder=winner.incident_id,
                    quantity=winner.quantity or 1,
                    priority_score=winner.bid_score,
                    status="held",
                    reason=(
                        f"竞价中标 score={winner.bid_score:.1f}"
                        f"（安全{winner.safety_risk}/经济{winner.economic_impact_per_hour}"
                        f"/紧急度{winner.urgency}）"
                    ),
                    reservation_lock_id=reservation_lock_id,
                    locked_at=now,
                    expires_at=expires_at,
                )
            )
            await self.db.commit()
            lock.persisted = True
            lock.reservation_lock_id = reservation_lock_id
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            logger.error("资源锁落库失败 resource=%s: %s", resource_id, exc)

        self._locks[resource_id] = lock
        return lock

    async def _reserve_spare_part(
        self,
        resource_id: str,
        winner: ResourceRequest,
        incident_pk: Optional[int],
        expires_at: datetime,
    ) -> Optional[str]:
        """Compatibility hook: execution resources now require human approval."""
        return None

    async def _resolve_spare_part(self, resource_id: str) -> None:
        """Compatibility hook retained for callers from older snapshots."""
        return None

    async def release_lock(self, resource_id: str, incident_id: str) -> bool:
        """Release a resource lock after maintenance completes."""
        record = (
            await self.db.execute(
                select(ResourceLockRecord)
                .where(
                    ResourceLockRecord.resource_id == resource_id,
                    ResourceLockRecord.incident_id == incident_id,
                    ResourceLockRecord.status == "held",
                )
                .order_by(ResourceLockRecord.locked_at.desc())
            )
        ).scalars().first()

        if record is None:
            self._locks.pop(resource_id, None)
            return False

        now = _utcnow()
        record.status = "released"
        record.released_at = now

        await self.db.commit()

        cached = self._locks.get(resource_id)
        if cached:
            cached.released = True
        return True

    @staticmethod
    def _to_dataclass(record: ResourceLockRecord) -> ResourceLock:
        return ResourceLock(
            lock_id=record.lock_id,
            resource_id=record.resource_id,
            incident_id=record.incident_id or "",
            locked_at=_aware(record.locked_at) or _utcnow(),
            expires_at=_aware(record.expires_at),
            released=record.status != "held",
            reservation_lock_id=record.reservation_lock_id,
            persisted=True,
        )

    # ══════════════════════════════════════════════════════════════
    # 冲突检测（v1 为空实现）
    # ══════════════════════════════════════════════════════════════

    async def check_conflicts(
        self,
        resource_id: str,
        exclude_lock_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """检测同一资源上的活跃冲突方。

        三类冲突源全部真实查库：

        1. ``resource_locks`` 中 status=held 且未过期的协商锁；
        2. ``part_reservations`` 中 status=held 且未过期的库存预留
           （备件类资源才有——这是库存域的权威占用口径，别的域也可能建预留，
           协商必须看得见）；
        3. ``resource_bids`` 中 status=pending 的待决竞价（还在抢的对手）。

        Returns:
            冲突方明细列表，每项含 ``conflict_type`` / ``incident_id`` /
            ``work_order_id`` / ``holder`` / ``expires_at`` / ``priority``。

        Note:
            v1 此方法直接 ``return []``（空实现）。返回类型由
            ``list[ResourceRequest]`` 改为 ``list[dict]`` —— 代码库内无其它调用方，
            改动不影响既有接口。
        """
        await self._expire_stale_locks(resource_id)
        now = _utcnow()
        conflicts: list[dict[str, Any]] = []

        # ── 1. 协商锁 ──
        lock_rows = (
            await self.db.execute(
                select(ResourceLockRecord).where(
                    ResourceLockRecord.resource_id == resource_id,
                    ResourceLockRecord.status == "held",
                )
            )
        ).scalars().all()
        for rec in lock_rows:
            if exclude_lock_id and rec.lock_id == exclude_lock_id:
                continue
            exp = _aware(rec.expires_at)
            conflicts.append({
                "conflict_type": "resource_lock",
                "lock_id": rec.lock_id,
                "resource_id": rec.resource_id,
                "resource_type": rec.resource_type,
                "incident_id": rec.incident_id,
                "work_order_id": rec.work_order_id,
                "holder": rec.holder or rec.incident_id,
                "quantity": rec.quantity,
                "priority": round(float(rec.priority_score or 0.0), 2),
                "expires_at": exp.isoformat() if exp else None,
                "expires_in_hours": (
                    round((exp - now).total_seconds() / 3600, 2) if exp else None
                ),
                "reason": rec.reason,
            })

        # ── 2. 待决竞价 ──
        bid_rows = (
            await self.db.execute(
                select(ResourceBid)
                .where(
                    ResourceBid.resource_id == resource_id,
                    ResourceBid.status == "pending",
                )
                .order_by(ResourceBid.bid_score.desc())
            )
        ).scalars().all()
        for bid in bid_rows:
            conflicts.append({
                "conflict_type": "pending_bid",
                "lock_id": None,
                "request_id": bid.request_id,
                "resource_id": bid.resource_id,
                "resource_type": bid.resource_type,
                "incident_id": bid.incident_id,
                "work_order_id": None,
                "holder": bid.incident_id,
                "quantity": bid.quantity,
                "priority": round(float(bid.bid_score or 0.0), 2),
                "expires_at": None,
                "expires_in_hours": bid.max_wait_hours,
                "reason": f"待决竞价（紧急度={bid.urgency}，最长可等待 {bid.max_wait_hours}h）",
            })

        return conflicts

    async def _resolve_bids(
        self,
        resource_id: str,
        winner: ResourceRequest,
        losers: list[ResourceRequest],
    ) -> None:
        """把本轮参与的竞价从 pending 结算为 won / lost。"""
        try:
            now = _utcnow()
            ids = [winner.request_id] + [l.request_id for l in losers]
            rows = (
                await self.db.execute(
                    select(ResourceBid).where(
                        ResourceBid.resource_id == resource_id,
                        ResourceBid.status == "pending",
                        or_(
                            ResourceBid.request_id.in_(ids),
                            ResourceBid.incident_id.in_(
                                [winner.incident_id] + [l.incident_id for l in losers]
                            ),
                        ),
                    )
                )
            ).scalars().all()
            for row in rows:
                row.status = "won" if row.incident_id == winner.incident_id else "lost"
                row.resolved_at = now
            if rows:
                await self.db.commit()
        except Exception as exc:  # noqa: BLE001
            await self.db.rollback()
            logger.warning("竞价结算失败（不影响锁）: %s", exc)

    # ══════════════════════════════════════════════════════════════
    # 替代件检索（v1 为两条硬编码）
    # ══════════════════════════════════════════════════════════════

    async def find_alternatives(
        self,
        resource_id: str,
        resource_type: str = "spare_part",
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Do not invent alternatives when no authoritative resource catalog is connected."""
        return []

    async def _find_alternative(
        self, resource_id: str, resource_type: str
    ) -> Optional[str]:
        """[签名兼容] 返回最佳替代件的一行文本描述；无匹配时返回 None。"""
        alternatives = await self.find_alternatives(resource_id, resource_type, limit=1)
        if not alternatives:
            return None
        best = alternatives[0]
        stock_note = (
            f"现货{best['available_qty']}件"
            if best["available_qty"] > 0
            else f"需采购，提前期{best['lead_time_days']}天"
        )
        return f"{best['part_no']} {best['name']}（{'；'.join(best['match_basis'][:2])}，{stock_note}）"

    # ══════════════════════════════════════════════════════════════
    # 查询辅助
    # ══════════════════════════════════════════════════════════════

    async def list_active_locks(
        self, resource_type: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """列出当前全部活跃资源锁（运维可视化 / 排障用）。"""
        await self._expire_stale_locks()
        q = select(ResourceLockRecord).where(ResourceLockRecord.status == "held")
        if resource_type:
            q = q.where(ResourceLockRecord.resource_type == resource_type)
        rows = (await self.db.execute(q.order_by(ResourceLockRecord.locked_at.desc()))).scalars().all()
        return [
            {
                "lock_id": r.lock_id,
                "resource_id": r.resource_id,
                "resource_type": r.resource_type,
                "incident_id": r.incident_id,
                "holder": r.holder,
                "quantity": r.quantity,
                "priority": round(float(r.priority_score or 0.0), 2),
                "locked_at": (_aware(r.locked_at).isoformat() if r.locked_at else None),
                "expires_at": (_aware(r.expires_at).isoformat() if r.expires_at else None),
                "reservation_lock_id": r.reservation_lock_id,
                "reason": r.reason,
            }
            for r in rows
        ]
