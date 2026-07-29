"""风窗排产服务 — 以"损失电量最小"为目标的机会性维护排程。

════════════════════════════════════════════════════════════
算法性质声明（重要，避免过度包装）
════════════════════════════════════════════════════════════
本模块是**启发式（heuristic）**求解器，不是 MILP / 精确最优化：

    阶段一  贪心构造：按 [安全风险 > RUL紧迫度 > 可省电量] 排序，
            逐一把工单放进"当前可行窗口中损失电量最小"的那一个。
    阶段二  局部改进：对已排工单做 pairwise swap（两两交换时段），
            只要总损失电量下降就接受，最多迭代 MAX_SWAP_PASSES 轮。

贪心 + 局部搜索**不保证全局最优**，但在 7 天 × 小时粒度 × 十余张工单的规模下
可秒级给出高质量解，且每一步都可解释、可复现（无随机数）。真正的最优解需要
MILP/CP-SAT 求解器，本项目不引入额外第三方依赖，故明确不作此宣称。

════════════════════════════════════════════════════════════
业务约束（硬约束，任一不满足即该时段不可行）
════════════════════════════════════════════════════════════
    ① 人力容量   并行班组数 <= AVAILABLE_CREWS，单日人时 <= MAX_DAILY_CAPACITY
                （常量复用 ``maintenance_scheduler``，不修改该模块）
    ② 备件 ETA   开工时间 >= 备件可用时间（查库存域/供应链域，未接入则降级为无约束）
    ③ 天气窗     作业时段内每小时风速 <= MAX_WORK_WIND_MS（超过禁止登塔），
                且必须落在白班作业窗口内
    ④ 停机并发   同一时段停机机组数 <= MAX_CONCURRENT_OUTAGES；同一机组不重叠

目标函数：min Σ 损失电量(kWh) = Σ_工单 Σ_小时 期望出力 × 机组容量占比 × 重叠时长
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FaultKnowledgeNode, RULPrediction, Turbine, User, WorkOrder
from app.models.production import ProductionPlan
from app.services.power_forecast_service import (
    find_low_wind_windows,
    get_or_build_forecast,
)

# 复用既有运维排程模块的人力配置常量（只读引用，不修改该文件）
from app.services.maintenance_scheduler import AVAILABLE_CREWS, SHIFT_HOURS

logger = logging.getLogger(__name__)

MAX_DAILY_CAPACITY = AVAILABLE_CREWS * SHIFT_HOURS  # 24 人时/天

# ── 作业窗口（登塔作业只能白天） ──
LOCAL_UTC_OFFSET_HOURS = 8   # 场址位于 Asia/Shanghai
WORK_HOUR_START = 8          # 本地 08:00 开工
WORK_HOUR_END = 18           # 本地 18:00 收工
MAX_TASK_HOURS = float(WORK_HOUR_END - WORK_HOUR_START)  # 单段作业上限 10h

# ── 天气 / 停机并发 ──
MAX_WORK_WIND_MS = 12.0      # 风速超过 12 m/s 禁止登塔（GB 及厂家作业规程通行值）
MAX_CONCURRENT_OUTAGES = 3   # 同一时段最多停 3 台，保障场站出力

# ── 优先级 → 安全风险分 / 默认工期 / 默认班组人数 ──
SAFETY_BY_PRIORITY = {"urgent": 1.0, "high": 0.75, "medium": 0.45, "low": 0.2}
DEFAULT_HOURS_BY_PRIORITY = {"urgent": 8.0, "high": 6.0, "medium": 4.0, "low": 3.0}
DEFAULT_CREW_BY_PRIORITY = {"urgent": 3, "high": 2, "medium": 2, "low": 1}
HIGH_RISK_KEYWORDS = ("blade", "叶片", "tower", "塔筒", "fire", "起火", "brake", "刹车", "structural")
MEDIUM_RISK_KEYWORDS = ("gearbox", "齿轮箱", "main_shaft", "主轴", "bearing", "轴承")

SCHEDULABLE_STATUSES = ("pending", "assigned", "in_progress")
TERMINAL_STATUSES = ("completed", "cancelled", "closed")
MAX_SWAP_PASSES = 3
RUL_URGENT_DAYS = 90.0  # RUL 小于该值开始计紧迫度


def get_electricity_price() -> float:
    """上网电价（CNY/kWh）—— 复用经济影响服务的统一口径。"""
    try:
        from app.services.economic_impact_service import DEFAULT_ELECTRICITY_PRICE_CNY

        return float(DEFAULT_ELECTRICITY_PRICE_CNY)
    except Exception:  # pragma: no cover
        return 0.52


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _local_hour(dt: datetime) -> int:
    """UTC 时刻对应的本地小时（场址 UTC+8）。"""
    return (dt.hour + LOCAL_UTC_OFFSET_HOURS) % 24


def _local_date(dt: datetime) -> date:
    return (dt + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)).date()


# ══════════════════════════════════════════════════════════
# 任务与占用状态
# ══════════════════════════════════════════════════════════


@dataclass
class SchedulableTask:
    """一张待排工单在排产器中的表示。"""

    work_order_id: int
    turbine_id: int
    turbine_name: str
    title: str
    priority: str
    duration_hours: float
    crew_size: int
    safety_score: float
    rul_days: Optional[float]
    rul_urgency: float
    capacity_share: float          # 该机组额定容量 / 全场额定容量
    earliest_start: datetime
    parts_note: Optional[str] = None
    duration_note: Optional[str] = None

    # 排程结果
    slot_start: Optional[datetime] = None
    est_lost_kwh: float = 0.0
    worst_lost_kwh: float = 0.0
    best_alt_lost_kwh: float = 0.0
    feasible_slots: int = 0
    avg_wind_ms: Optional[float] = None
    moved_by: Optional[str] = None
    unscheduled_reason: Optional[str] = None
    constraints: list[str] = field(default_factory=list)

    @property
    def priority_key(self) -> tuple:
        """任务优先级：安全风险 > RUL 紧迫度 > 可省电量（越大越先排）。"""
        return (-self.safety_score, -self.rul_urgency, -self.capacity_share, self.work_order_id)


@dataclass
class _Occupancy:
    """排程占用状态（资源日历）。"""

    crew_per_hour: dict[datetime, int] = field(default_factory=dict)
    person_hours_per_day: dict[date, float] = field(default_factory=dict)
    outage_per_hour: dict[datetime, set] = field(default_factory=dict)
    turbine_hours: dict[int, set] = field(default_factory=dict)

    def apply(self, task: SchedulableTask, start: datetime, sign: int = 1) -> None:
        for hour, frac in _slot_hours(start, task.duration_hours):
            self.crew_per_hour[hour] = self.crew_per_hour.get(hour, 0) + sign
            if self.crew_per_hour[hour] <= 0:
                self.crew_per_hour.pop(hour, None)
            bucket = self.outage_per_hour.setdefault(hour, set())
            if sign > 0:
                bucket.add(task.turbine_id)
            else:
                bucket.discard(task.turbine_id)
            t_hours = self.turbine_hours.setdefault(task.turbine_id, set())
            if sign > 0:
                t_hours.add(hour)
            else:
                t_hours.discard(hour)
            d = _local_date(hour)
            self.person_hours_per_day[d] = (
                self.person_hours_per_day.get(d, 0.0) + sign * task.crew_size * frac
            )


def _slot_hours(start: datetime, duration_hours: float) -> list[tuple[datetime, float]]:
    """把 [start, start+duration) 拆成 (整点, 该小时内占用比例) 列表。"""
    out: list[tuple[datetime, float]] = []
    remaining = float(duration_hours)
    cursor = start
    guard = 0
    while remaining > 1e-6 and guard < 96:
        hour = _floor_hour(cursor)
        to_next = (hour + timedelta(hours=1) - cursor).total_seconds() / 3600.0
        frac = min(remaining, to_next if to_next > 0 else 1.0)
        out.append((hour, frac))
        remaining -= frac
        cursor = cursor + timedelta(hours=frac)
        guard += 1
    return out


# ══════════════════════════════════════════════════════════
# 数据装载
# ══════════════════════════════════════════════════════════


async def build_parts_context(db: AsyncSession) -> dict[str, Any]:
    """Load required-part names from the fault knowledge base.

    Stock and supplier systems are outside the competition demo scope. The
    scheduler therefore never invents availability or an ETA: it keeps the
    time constraint open and records that execution resources require review.
    """
    ctx: dict[str, Any] = {
        "available": False,
        "reason": "执行资源未接入自动校验，备件与工具须在工单审核时人工确认",
        "parts_by_fault": {},
        "kb_names_by_fault": {},
    }
    try:
        kb_rows = (
            await db.execute(
                select(FaultKnowledgeNode.fault_type, FaultKnowledgeNode.spare_parts)
            )
        ).all()
        for fault_type, parts in kb_rows:
            names: list[str] = []
            for item in parts or []:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
                elif isinstance(item, str):
                    names.append(item)
            if names:
                ctx["kb_names_by_fault"][fault_type] = names
    except Exception as exc:  # pragma: no cover
        logger.debug("Fault knowledge spare parts unavailable: %s", exc)
    return ctx


def resolve_parts_eta(
    ctx: dict[str, Any], fault_type: Optional[str], floor_time: datetime
) -> tuple[datetime, Optional[str]]:
    """Return an open time constraint and an explicit human-review note."""
    if not ctx.get("available"):
        kb_names = ctx.get("kb_names_by_fault", {}).get(fault_type or "", [])
        if kb_names:
            return (
                floor_time,
                f"知识库建议 {('、'.join(kb_names[:3]))}；库存可用性须在工单审核时确认",
            )
        return floor_time, ctx.get("reason") or None
    if not fault_type:
        return floor_time, "工单未标注故障类型，按无备件约束处理"

    parts = ctx["parts_by_fault"].get(fault_type) or []
    if not parts:
        kb_names = ctx["kb_names_by_fault"].get(fault_type)
        if kb_names:
            return floor_time, f"知识库建议备件 {('、'.join(kb_names[:2]))}，库存域无对应主数据"
        return floor_time, "该故障类型无备件需求记录，按无备件约束处理"

    eta = floor_time
    notes: list[str] = []
    for p in parts:
        if p["available_qty"] >= 1:
            continue
        if p["po"]:
            part_eta, po_no = p["po"]
            notes.append(f"{p['name']} 缺货，在途采购单 {po_no} 预计 {part_eta:%m-%d} 到货")
        else:
            part_eta = floor_time + timedelta(days=p["lead_time_days"])
            notes.append(f"{p['name']} 缺货，按采购提前期 {p['lead_time_days']:.0f} 天计")
        if part_eta > eta:
            eta = part_eta

    return eta, ("；".join(notes[:3]) if notes else "备件齐套，可立即开工")


def _safety_score(priority: str, fault_type: Optional[str], title: str) -> float:
    """安全风险分（0~1）：优先级为基线，高危部件关键词加权。"""
    score = SAFETY_BY_PRIORITY.get((priority or "medium").lower(), 0.45)
    text = f"{fault_type or ''} {title or ''}".lower()
    if any(k in text for k in HIGH_RISK_KEYWORDS):
        score += 0.15
    elif any(k in text for k in MEDIUM_RISK_KEYWORDS):
        score += 0.08
    return round(min(1.0, score), 3)


async def _load_tasks(
    db: AsyncSession,
    *,
    work_order_ids: Optional[list[int]],
    period_start: datetime,
    farm_rated_kw: float,
    parts_ctx: dict[str, Any],
) -> list[SchedulableTask]:
    """把待排工单装载成排产任务（含安全分、RUL 紧迫度、容量占比、备件 ETA）。"""
    q = select(WorkOrder).where(
        WorkOrder.deleted_at.is_(None),
        WorkOrder.status.notin_(TERMINAL_STATUSES),  # 已完成/已取消的工单不再排产
    )
    if work_order_ids:
        q = q.where(WorkOrder.id.in_(work_order_ids))
    else:
        q = q.where(WorkOrder.status.in_(SCHEDULABLE_STATUSES))
    work_orders = list((await db.execute(q.order_by(WorkOrder.id.asc()))).scalars().all())
    if not work_orders:
        return []

    turbine_ids = sorted({wo.turbine_id for wo in work_orders if wo.turbine_id})
    turbines = {
        t.id: t
        for t in (
            await db.execute(select(Turbine).where(Turbine.id.in_(turbine_ids)))
        ).scalars().all()
    }

    rul_rows = (
        await db.execute(
            select(
                RULPrediction.turbine_id,
                func.min(RULPrediction.remaining_life_days),
            )
            .where(RULPrediction.turbine_id.in_(turbine_ids))
            .group_by(RULPrediction.turbine_id)
        )
    ).all()
    rul_by_turbine = {int(tid): float(days) for tid, days in rul_rows if days is not None}

    tasks: list[SchedulableTask] = []
    for wo in work_orders:
        turbine = turbines.get(wo.turbine_id)
        if turbine is None:
            continue
        priority = (wo.priority or "medium").lower()

        raw_hours = float(wo.downtime_hours or 0) or DEFAULT_HOURS_BY_PRIORITY.get(priority, 4.0)
        duration_note = None
        if raw_hours > MAX_TASK_HOURS:
            duration_note = (
                f"工期 {raw_hours:.0f}h 超出单日作业窗 {MAX_TASK_HOURS:.0f}h，"
                f"本次仅排首段，剩余需拆分工单"
            )
            raw_hours = MAX_TASK_HOURS
        duration = max(1.0, round(raw_hours, 1))

        rated_kw = float(turbine.power_mw or 0.0) * 1000.0
        share = (rated_kw / farm_rated_kw) if farm_rated_kw > 0 else 0.0

        rul_days = rul_by_turbine.get(wo.turbine_id)
        rul_urgency = (
            round(max(0.0, min(1.0, 1.0 - rul_days / RUL_URGENT_DAYS)), 3)
            if rul_days is not None
            else 0.0
        )

        eta, parts_note = resolve_parts_eta(parts_ctx, wo.fault_type, period_start)

        tasks.append(
            SchedulableTask(
                work_order_id=wo.id,
                turbine_id=wo.turbine_id,
                turbine_name=turbine.name,
                title=wo.title or f"工单#{wo.id}",
                priority=priority,
                duration_hours=duration,
                crew_size=DEFAULT_CREW_BY_PRIORITY.get(priority, 2),
                safety_score=_safety_score(priority, wo.fault_type, wo.title or ""),
                rul_days=rul_days,
                rul_urgency=rul_urgency,
                capacity_share=share,
                earliest_start=max(period_start, _floor_hour(eta)),
                parts_note=parts_note,
                duration_note=duration_note,
            )
        )
    return tasks


# ══════════════════════════════════════════════════════════
# 可行性判定与损失电量
# ══════════════════════════════════════════════════════════


def _slot_lost_kwh(
    power_by_hour: dict[datetime, float], task: SchedulableTask, start: datetime
) -> float:
    """损失电量 = Σ_小时 全场期望出力 × 机组容量占比 × 该小时占用比例。"""
    total = 0.0
    for hour, frac in _slot_hours(start, task.duration_hours):
        total += power_by_hour.get(hour, 0.0) * task.capacity_share * frac
    return total


def _slot_avg_wind(
    wind_by_hour: dict[datetime, float], task: SchedulableTask, start: datetime
) -> Optional[float]:
    vals = [
        wind_by_hour[h] for h, _ in _slot_hours(start, task.duration_hours) if h in wind_by_hour
    ]
    return round(sum(vals) / len(vals), 2) if vals else None


def _check_slot(
    task: SchedulableTask,
    start: datetime,
    *,
    occ: _Occupancy,
    wind_by_hour: dict[datetime, float],
    period_end: datetime,
) -> Optional[str]:
    """返回 None 表示可行，否则返回违反的约束标识。"""
    end = start + timedelta(hours=task.duration_hours)
    if end > period_end:
        return "period_bound"
    if start < task.earliest_start:
        return "parts_eta"

    hours = _slot_hours(start, task.duration_hours)

    # ③ 作业窗口 + 天气窗
    for hour, _frac in hours:
        lh = _local_hour(hour)
        if lh < WORK_HOUR_START or lh >= WORK_HOUR_END:
            return "work_hours"
        wind = wind_by_hour.get(hour)
        if wind is not None and wind > MAX_WORK_WIND_MS:
            return "weather_wind"
    # 跨自然日的作业也不允许（本地日历日必须一致）
    if _local_date(hours[0][0]) != _local_date(hours[-1][0]):
        return "work_hours"

    # ① 人力容量
    for hour, _frac in hours:
        if occ.crew_per_hour.get(hour, 0) + 1 > AVAILABLE_CREWS:
            return "crew_capacity"
    day_add: dict[date, float] = {}
    for hour, frac in hours:
        day_add[_local_date(hour)] = day_add.get(_local_date(hour), 0.0) + task.crew_size * frac
    for d, add in day_add.items():
        if occ.person_hours_per_day.get(d, 0.0) + add > MAX_DAILY_CAPACITY + 1e-6:
            return "crew_capacity"

    # ④ 同机组不重叠 + 同时段停机机组数上限
    busy = occ.turbine_hours.get(task.turbine_id, set())
    for hour, _frac in hours:
        if hour in busy:
            return "same_turbine"
        outage = occ.outage_per_hour.get(hour, set())
        if task.turbine_id not in outage and len(outage) + 1 > MAX_CONCURRENT_OUTAGES:
            return "max_outage"
    return None


def _candidate_starts(period_start: datetime, period_end: datetime) -> list[datetime]:
    """候选开工时刻 = 排产周期内所有落在白班作业窗的整点。"""
    starts: list[datetime] = []
    cursor = _floor_hour(period_start)
    while cursor < period_end:
        lh = _local_hour(cursor)
        if WORK_HOUR_START <= lh < WORK_HOUR_END:
            starts.append(cursor)
        cursor += timedelta(hours=1)
    return starts


def _place(
    task: SchedulableTask,
    *,
    occ: _Occupancy,
    starts: list[datetime],
    power_by_hour: dict[datetime, float],
    wind_by_hour: dict[datetime, float],
    period_end: datetime,
    mode: str,
    constraint_hits: dict[str, int],
) -> bool:
    """把单个任务放到"损失电量最小"（optimized）或"最早可行"（baseline）的窗口。"""
    best_start: Optional[datetime] = None
    best_lost = float("inf")
    worst_lost = 0.0
    feasible = 0
    hit_reasons: dict[str, int] = {}

    for start in starts:
        reason = _check_slot(
            task, start, occ=occ, wind_by_hour=wind_by_hour, period_end=period_end
        )
        if reason:
            hit_reasons[reason] = hit_reasons.get(reason, 0) + 1
            continue
        feasible += 1
        lost = _slot_lost_kwh(power_by_hour, task, start)
        worst_lost = max(worst_lost, lost)
        if mode == "baseline":
            if best_start is None:  # 尽早排程：第一个可行窗口即采纳
                best_start, best_lost = start, lost
        elif lost < best_lost - 1e-9:
            best_start, best_lost = start, lost

    for k, v in hit_reasons.items():
        constraint_hits[k] = constraint_hits.get(k, 0) + v

    task.feasible_slots = feasible
    if best_start is None:
        task.slot_start = None
        task.unscheduled_reason = _describe_blockers(hit_reasons)
        task.constraints = [CONSTRAINT_LABELS.get(k, k) for k in sorted(hit_reasons)]
        return False

    if mode == "baseline":
        # baseline 需要记录"若按最优放置能省多少"，这里补算一次全窗口最小值
        worst_lost = max(worst_lost, best_lost)

    task.slot_start = best_start
    task.est_lost_kwh = round(best_lost, 1)
    task.worst_lost_kwh = round(worst_lost, 1)
    task.avg_wind_ms = _slot_avg_wind(wind_by_hour, task, best_start)
    task.constraints = [CONSTRAINT_LABELS.get(k, k) for k in sorted(hit_reasons)]
    occ.apply(task, best_start, sign=1)
    return True


# 未排入原因的展示优先级：越靠前越有解释力（结构性约束排最后）
CONSTRAINT_PRIORITY = (
    "parts_eta",
    "weather_wind",
    "crew_capacity",
    "max_outage",
    "same_turbine",
    "work_hours",
    "period_bound",
)

CONSTRAINT_LABELS = {
    "period_bound": "超出排产周期",
    "parts_eta": "备件未到货",
    "work_hours": "非白班作业窗",
    "weather_wind": f"风速超过 {MAX_WORK_WIND_MS:g} m/s 禁止登塔",
    "crew_capacity": "人力容量已满",
    "same_turbine": "同机组时段冲突",
    "max_outage": f"同时段停机机组已达上限 {MAX_CONCURRENT_OUTAGES}",
    "unknown": "无可行窗口",
}


STRUCTURAL_CONSTRAINTS = ("work_hours", "period_bound")


def _describe_blockers(hit_reasons: dict[str, int]) -> str:
    """描述"为什么排不进去"。

    不宣称单一主因（``_check_slot`` 短路返回首个违反项，计数本身带顺序偏差），
    而是如实列出受阻时段数最多的业务约束；白班窗口/周期边界属于结构性约束，
    几乎每个任务都会大量命中，只在没有业务约束触发时才展示。
    """
    if not hit_reasons:
        return "无可行窗口"
    ranked = sorted(
        hit_reasons.items(),
        key=lambda kv: (
            CONSTRAINT_PRIORITY.index(kv[0]) if kv[0] in CONSTRAINT_PRIORITY else 99
        ),
    )
    business = [kv for kv in ranked if kv[0] not in STRUCTURAL_CONSTRAINTS]
    chosen = business[:2] or ranked[:1]
    detail = "、".join(f"{CONSTRAINT_LABELS.get(k, k)} {v} 个时段" for k, v in chosen)
    return f"无可行窗口（受阻：{detail}）"


def _pairwise_swap(
    tasks: list[SchedulableTask],
    *,
    occ: _Occupancy,
    power_by_hour: dict[datetime, float],
    wind_by_hour: dict[datetime, float],
    period_end: datetime,
) -> int:
    """局部改进：两两交换时段，只接受总损失电量下降的交换。

    这是标准的 2-exchange 局部搜索，只能保证**局部最优**。
    """
    improvements = 0
    scheduled = [t for t in tasks if t.slot_start is not None]
    for _pass in range(MAX_SWAP_PASSES):
        changed = False
        for a, b in combinations(scheduled, 2):
            if a.slot_start is None or b.slot_start is None:
                continue
            sa, sb = a.slot_start, b.slot_start
            if sa == sb:
                continue
            before = a.est_lost_kwh + b.est_lost_kwh

            occ.apply(a, sa, sign=-1)
            occ.apply(b, sb, sign=-1)

            ok_a = _check_slot(a, sb, occ=occ, wind_by_hour=wind_by_hour, period_end=period_end)
            ok_b = None
            if ok_a is None:
                occ.apply(a, sb, sign=1)
                ok_b = _check_slot(
                    b, sa, occ=occ, wind_by_hour=wind_by_hour, period_end=period_end
                )
                occ.apply(a, sb, sign=-1)

            after = float("inf")
            if ok_a is None and ok_b is None:
                after = _slot_lost_kwh(power_by_hour, a, sb) + _slot_lost_kwh(
                    power_by_hour, b, sa
                )

            if after < before - 1e-6:
                a.slot_start, b.slot_start = sb, sa
                a.est_lost_kwh = round(_slot_lost_kwh(power_by_hour, a, sb), 1)
                b.est_lost_kwh = round(_slot_lost_kwh(power_by_hour, b, sa), 1)
                a.avg_wind_ms = _slot_avg_wind(wind_by_hour, a, sb)
                b.avg_wind_ms = _slot_avg_wind(wind_by_hour, b, sa)
                occ.apply(a, sb, sign=1)
                occ.apply(b, sa, sign=1)
                improvements += 1
                changed = True
            else:
                occ.apply(a, sa, sign=1)
                occ.apply(b, sb, sign=1)
        if not changed:
            break
    return improvements


# ══════════════════════════════════════════════════════════
# 排程构建
# ══════════════════════════════════════════════════════════


def _build_reason(task: SchedulableTask, price: float) -> str:
    """生成"为什么放这里"的中文解释 —— Demo 讲解与审计都靠它。"""
    if task.slot_start is None:
        return f"未能排入：{task.unscheduled_reason or '无可行窗口'}"
    end = task.slot_start + timedelta(hours=task.duration_hours)
    local_start = task.slot_start + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    local_end = end + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
    saving = max(0.0, task.worst_lost_kwh - task.est_lost_kwh)
    wind_txt = f"，窗口均风 {task.avg_wind_ms:.1f} m/s" if task.avg_wind_ms is not None else ""
    return (
        f"排在 {local_start:%m-%d %H:%M}-{local_end:%H:%M}（当地时间）"
        f"{wind_txt}，预计损失电量 {task.est_lost_kwh:,.0f} kWh；"
        f"较同周期最差窗口（{task.worst_lost_kwh:,.0f} kWh）少损失 {saving:,.0f} kWh"
        f"（≈¥{saving * price:,.0f}）"
    )


def _slot_dict(task: SchedulableTask, price: float) -> dict[str, Any]:
    end = (
        task.slot_start + timedelta(hours=task.duration_hours)
        if task.slot_start is not None
        else None
    )
    saving = max(0.0, task.worst_lost_kwh - task.est_lost_kwh)
    return {
        "work_order_id": task.work_order_id,
        "turbine_id": task.turbine_id,
        "turbine_name": task.turbine_name,
        "title": task.title,
        "priority": task.priority,
        "slot_start": task.slot_start.isoformat() if task.slot_start else None,
        "slot_end": end.isoformat() if end else None,
        "duration_hours": task.duration_hours,
        "crew_size": task.crew_size,
        "est_lost_kwh": round(task.est_lost_kwh, 1),
        "worst_lost_kwh": round(task.worst_lost_kwh, 1),
        "baseline_lost_kwh": round(task.best_alt_lost_kwh, 1),
        "saving_kwh": round(saving, 1),
        "saving_cny": round(saving * price, 2),
        "avg_wind_ms": task.avg_wind_ms,
        "safety_score": task.safety_score,
        "rul_days": round(task.rul_days, 1) if task.rul_days is not None else None,
        "reason": _build_reason(task, price),
        "moved_by": task.moved_by,
        "parts_note": task.parts_note,
        "constraints": task.constraints
        + ([task.duration_note] if task.duration_note else []),
        "scheduled": task.slot_start is not None,
        "unscheduled_reason": task.unscheduled_reason,
    }


def _run_schedule(
    tasks: list[SchedulableTask],
    *,
    power_by_hour: dict[datetime, float],
    wind_by_hour: dict[datetime, float],
    period_start: datetime,
    period_end: datetime,
    mode: str,
    occ: Optional[_Occupancy] = None,
) -> tuple[_Occupancy, dict[str, int], int]:
    """执行"贪心构造 + pairwise swap"，就地写回 tasks 的排程结果。"""
    occ = occ or _Occupancy()
    starts = _candidate_starts(period_start, period_end)
    constraint_hits: dict[str, int] = {}

    for task in sorted(tasks, key=lambda t: t.priority_key):
        _place(
            task,
            occ=occ,
            starts=starts,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_end=period_end,
            mode=mode,
            constraint_hits=constraint_hits,
        )

    swaps = 0
    if mode != "baseline":
        swaps = _pairwise_swap(
            tasks,
            occ=occ,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_end=period_end,
        )
        _retry_unscheduled(
            tasks,
            occ=occ,
            starts=starts,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_end=period_end,
            constraint_hits=constraint_hits,
        )
    return occ, constraint_hits, swaps


def _retry_unscheduled(
    tasks: list[SchedulableTask],
    *,
    occ: _Occupancy,
    starts: list[datetime],
    power_by_hour: dict[datetime, float],
    wind_by_hour: dict[datetime, float],
    period_end: datetime,
    constraint_hits: dict[str, int],
) -> int:
    """局部交换会腾出新的空档 —— 给未排入的工单再试一次，能救一张是一张。"""
    placed = 0
    pending = sorted(
        (t for t in tasks if t.slot_start is None), key=lambda t: t.priority_key
    )
    for task in pending:
        if _place(
            task,
            occ=occ,
            starts=starts,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_end=period_end,
            mode="optimized",
            constraint_hits=constraint_hits,
        ):
            task.unscheduled_reason = None
            placed += 1
    return placed


def _clone_tasks(tasks: list[SchedulableTask]) -> list[SchedulableTask]:
    """深拷贝任务列表（用于 baseline 对照，避免污染优化解）。"""
    out: list[SchedulableTask] = []
    for t in tasks:
        out.append(
            SchedulableTask(
                work_order_id=t.work_order_id,
                turbine_id=t.turbine_id,
                turbine_name=t.turbine_name,
                title=t.title,
                priority=t.priority,
                duration_hours=t.duration_hours,
                crew_size=t.crew_size,
                safety_score=t.safety_score,
                rul_days=t.rul_days,
                rul_urgency=t.rul_urgency,
                capacity_share=t.capacity_share,
                earliest_start=t.earliest_start,
                parts_note=t.parts_note,
                duration_note=t.duration_note,
            )
        )
    return out


def compute_audit_hash(payload: dict[str, Any]) -> str:
    """对排程内容做 SHA-256 留痕（可篡改检测，与审计链同口径）。"""
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _next_plan_no(period_start: datetime, suffix: str = "") -> str:
    tail = f"-{suffix}" if suffix else ""
    return f"PP-{period_start:%Y%m%d}{tail}-{uuid.uuid4().hex[:4]}"


# ══════════════════════════════════════════════════════════
# 对外主入口
# ══════════════════════════════════════════════════════════


async def optimize_schedule(
    db: AsyncSession,
    period_days: int = 7,
    work_order_ids: Optional[list[int]] = None,
    *,
    mode: str = "optimized",
    user: Optional[User] = None,
    note: Optional[str] = None,
    plan_no: Optional[str] = None,
    with_baseline: bool = True,
    persist: bool = True,
) -> dict[str, Any]:
    """**核心**：生成以损失电量最小为目标的风窗排产方案。

    Args:
        db: 异步会话
        period_days: 排产周期（天），默认 7
        work_order_ids: 指定工单；None 则取所有 pending/assigned/in_progress 工单
        mode: ``optimized``（低风窗优化）/ ``baseline``（尽早排程对照）
        user: 创建人
        note: 备注/生成原因
        plan_no: 指定计划编号（种子脚本用于保证幂等），留空自动生成
        with_baseline: optimized 模式下是否同时落库 baseline 对照版本
        persist: 是否写入 ``production_plans`` 表

    Returns:
        {"plan": ProductionPlan|None, "baseline_plan": ..., "objective": {...},
         "schedule": [...], "tasks": [...]}
    """
    price = get_electricity_price()
    period_start = _floor_hour(_utc_now()) + timedelta(hours=1)
    period_end = period_start + timedelta(days=max(1, int(period_days)))
    hours = int((period_end - period_start).total_seconds() // 3600)

    forecast = await get_or_build_forecast(db, hours, turbine_id=None)
    points = forecast["points"]
    farm_rated_kw = float(forecast["farm_rated_kw"] or 0.0)
    power_by_hour = {
        _as_utc(p["forecast_time"]): float(p.get("expected_power_kw") or 0.0) for p in points
    }
    wind_by_hour = {
        _as_utc(p["forecast_time"]): float(p["wind_speed_ms"])
        for p in points
        if p.get("wind_speed_ms") is not None
    }

    parts_ctx = await build_parts_context(db)
    tasks = await _load_tasks(
        db,
        work_order_ids=work_order_ids,
        period_start=period_start,
        farm_rated_kw=farm_rated_kw,
        parts_ctx=parts_ctx,
    )
    if not tasks:
        return {
            "plan": None,
            "baseline_plan": None,
            "objective": {"message": "没有待排工单", "total_lost_kwh": 0.0},
            "schedule": [],
            "tasks": [],
            "forecast": forecast,
        }

    # ── baseline：尽早排程（现行做法：来一个排一个，不看风） ──
    baseline_tasks = _clone_tasks(tasks)
    _, baseline_hits, _ = _run_schedule(
        baseline_tasks,
        power_by_hour=power_by_hour,
        wind_by_hour=wind_by_hour,
        period_start=period_start,
        period_end=period_end,
        mode="baseline",
    )
    baseline_lost = sum(t.est_lost_kwh for t in baseline_tasks if t.slot_start)
    baseline_by_wo = {t.work_order_id: t for t in baseline_tasks}

    if mode == "baseline":
        target_tasks = baseline_tasks
        constraint_hits = baseline_hits
        swaps = 0
    else:
        _, constraint_hits, swaps = _run_schedule(
            tasks,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_start=period_start,
            period_end=period_end,
            mode="optimized",
        )
        target_tasks = tasks

    for t in target_tasks:
        ref = baseline_by_wo.get(t.work_order_id)
        t.best_alt_lost_kwh = ref.est_lost_kwh if ref else t.est_lost_kwh

    total_lost = sum(t.est_lost_kwh for t in target_tasks if t.slot_start)
    scheduled = [t for t in target_tasks if t.slot_start is not None]
    unscheduled = [t for t in target_tasks if t.slot_start is None]
    improvement = (
        round((baseline_lost - total_lost) / baseline_lost * 100, 2)
        if baseline_lost > 0
        else 0.0
    )

    low_windows = find_low_wind_windows(points, farm_rated_kw)
    schedule_json = [
        _slot_dict(t, price)
        for t in sorted(
            target_tasks,
            key=lambda x: (x.slot_start is None, x.slot_start or period_end, x.work_order_id),
        )
    ]

    objective_json: dict[str, Any] = {
        "strategy": "baseline" if mode == "baseline" else "optimized",
        "algorithm": "greedy(safety>RUL>savings) + pairwise-swap local search (heuristic, NOT MILP)",
        "algorithm_version": "1.0",
        "total_lost_kwh": round(total_lost, 1),
        "total_revenue_loss": round(total_lost * price, 2),
        "baseline_lost_kwh": round(baseline_lost, 1),
        "baseline_revenue_loss": round(baseline_lost * price, 2),
        "saved_kwh": round(max(0.0, baseline_lost - total_lost), 1),
        "saved_cny": round(max(0.0, baseline_lost - total_lost) * price, 2),
        "improvement_pct": improvement if mode != "baseline" else 0.0,
        "constraint_hits": constraint_hits,
        "constraint_labels": CONSTRAINT_LABELS,
        "scheduled_count": len(scheduled),
        "unscheduled_count": len(unscheduled),
        "swap_improvements": swaps,
        "electricity_price_cny_per_kwh": price,
        "farm_rated_kw": farm_rated_kw,
        "forecast_source": forecast.get("source"),
        "forecast_note": forecast.get("method_note"),
        "forecast_degraded": forecast.get("degraded", False),
        "low_wind_windows": [
            {
                "start": w["start"].isoformat(),
                "end": w["end"].isoformat(),
                "hours": w["hours"],
                "avg_power_kw": w["avg_power_kw"],
                "avg_wind_ms": w["avg_wind_ms"],
                "label": w["label"],
            }
            for w in low_windows[:8]
        ],
        "capacity": {
            "available_crews": AVAILABLE_CREWS,
            "shift_hours": SHIFT_HOURS,
            "max_daily_person_hours": MAX_DAILY_CAPACITY,
            "max_concurrent_outages": MAX_CONCURRENT_OUTAGES,
            "max_work_wind_ms": MAX_WORK_WIND_MS,
            "work_window_local": f"{WORK_HOUR_START:02d}:00-{WORK_HOUR_END:02d}:00 (UTC+8)",
        },
        "parts_domain": parts_ctx.get("reason", ""),
    }

    result: dict[str, Any] = {
        "plan": None,
        "baseline_plan": None,
        "objective": objective_json,
        "schedule": schedule_json,
        "tasks": target_tasks,
        "forecast": forecast,
    }
    if not persist:
        return result

    baseline_plan: Optional[ProductionPlan] = None
    if mode != "baseline" and with_baseline:
        baseline_schedule = [
            _slot_dict(t, price)
            for t in sorted(
                baseline_tasks,
                key=lambda x: (x.slot_start is None, x.slot_start or period_end, x.work_order_id),
            )
        ]
        baseline_obj = dict(objective_json)
        baseline_obj.update(
            {
                "strategy": "baseline",
                "algorithm": "earliest-feasible-slot (现行做法：来一个排一个，不看风)",
                "total_lost_kwh": round(baseline_lost, 1),
                "total_revenue_loss": round(baseline_lost * price, 2),
                "saved_kwh": 0.0,
                "saved_cny": 0.0,
                "improvement_pct": 0.0,
                "swap_improvements": 0,
                "scheduled_count": len([t for t in baseline_tasks if t.slot_start]),
                "unscheduled_count": len([t for t in baseline_tasks if not t.slot_start]),
            }
        )
        baseline_plan = await _persist_plan(
            db,
            plan_no=(f"{plan_no}-BASE" if plan_no else _next_plan_no(period_start, "BASE")),
            period_start=period_start,
            period_end=period_end,
            objective=baseline_obj,
            schedule=baseline_schedule,
            user=user,
            note="对照基线：尽早排程（不考虑风功率）",
            baseline_plan_id=None,
            commit=False,
        )
        await db.flush()

    plan = await _persist_plan(
        db,
        plan_no=plan_no or _next_plan_no(period_start),
        period_start=period_start,
        period_end=period_end,
        objective=objective_json,
        schedule=schedule_json,
        user=user,
        note=note,
        baseline_plan_id=baseline_plan.id if baseline_plan else None,
        commit=True,
    )

    result["plan"] = plan
    result["baseline_plan"] = baseline_plan
    return result


async def _persist_plan(
    db: AsyncSession,
    *,
    plan_no: str,
    period_start: datetime,
    period_end: datetime,
    objective: dict[str, Any],
    schedule: list[dict[str, Any]],
    user: Optional[User],
    note: Optional[str],
    baseline_plan_id: Optional[int],
    commit: bool = True,
) -> ProductionPlan:
    """写入一个排产版本（新建；已存在同 plan_no 则更新其内容，保持幂等）。"""
    existing = (
        await db.execute(select(ProductionPlan).where(ProductionPlan.plan_no == plan_no))
    ).scalar_one_or_none()

    audit_hash = compute_audit_hash(
        {
            "plan_no": plan_no,
            "period_start": period_start,
            "period_end": period_end,
            "objective": objective,
            "schedule": schedule,
        }
    )

    if existing is not None:
        existing.period_start = period_start
        existing.period_end = period_end
        existing.objective_json = objective
        existing.schedule_json = schedule
        existing.baseline_plan_id = baseline_plan_id
        existing.note = note or existing.note
        existing.audit_hash = audit_hash
        plan = existing
    else:
        plan = ProductionPlan(
            plan_no=plan_no,
            period_start=period_start,
            period_end=period_end,
            status="draft",
            objective_json=objective,
            schedule_json=schedule,
            baseline_plan_id=baseline_plan_id,
            created_by=user.id if user else None,
            created_by_name=user.username if user else None,
            note=note,
            audit_hash=audit_hash,
        )
        db.add(plan)

    if commit:
        await db.commit()
        await db.refresh(plan)
    else:
        await db.flush()
    return plan


async def replan_on_event(
    db: AsyncSession,
    plan_no: str,
    reason: str,
    affected_work_orders: Optional[list[int]] = None,
    *,
    delay_hours: float = 0.0,
    user: Optional[User] = None,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """事件触发的**增量重排** —— 只动受影响的工单，其余保持原时段冻结。

    典型事件：备件延误（``supply_delay:PO-102``）、大风预警、人员请假。
    每个真正被挪动的工单会在 ``schedule_json`` 中带上 ``moved_by``，
    这是 Demo 的高光时刻："一条供应链消息进来，排产自己动了，并且说得清为什么动"。

    生成的新版本 ``baseline_plan_id`` 指向旧版本，状态为 ``draft``（提交后旧版才 superseded）。
    """
    old = (
        await db.execute(select(ProductionPlan).where(ProductionPlan.plan_no == plan_no))
    ).scalar_one_or_none()
    if old is None:
        raise ValueError(f"排产方案 {plan_no} 不存在")

    price = get_electricity_price()
    old_schedule = list(old.schedule_json or [])
    old_slot_by_wo = {
        int(s["work_order_id"]): s.get("slot_start") for s in old_schedule if s.get("work_order_id")
    }
    all_wo_ids = [int(s["work_order_id"]) for s in old_schedule if s.get("work_order_id")]
    affected = set(affected_work_orders or []) or set(all_wo_ids)

    period_start = max(_floor_hour(_utc_now()) + timedelta(hours=1), _as_utc(old.period_start))
    period_end = _as_utc(old.period_end)
    if period_end <= period_start:
        period_end = period_start + timedelta(days=7)
    hours = max(1, int((period_end - period_start).total_seconds() // 3600))

    forecast = await get_or_build_forecast(db, hours, turbine_id=None)
    points = forecast["points"]
    farm_rated_kw = float(forecast["farm_rated_kw"] or 0.0)
    power_by_hour = {
        _as_utc(p["forecast_time"]): float(p.get("expected_power_kw") or 0.0) for p in points
    }
    wind_by_hour = {
        _as_utc(p["forecast_time"]): float(p["wind_speed_ms"])
        for p in points
        if p.get("wind_speed_ms") is not None
    }

    parts_ctx = await build_parts_context(db)
    tasks = await _load_tasks(
        db,
        work_order_ids=all_wo_ids or None,
        period_start=period_start,
        farm_rated_kw=farm_rated_kw,
        parts_ctx=parts_ctx,
    )

    occ = _Occupancy()
    frozen: list[SchedulableTask] = []
    to_replan: list[SchedulableTask] = []

    for t in tasks:
        old_slot = old_slot_by_wo.get(t.work_order_id)
        if t.work_order_id in affected or not old_slot:
            if t.work_order_id in affected and delay_hours > 0:
                # 事件导致最早可开工时间推迟（如备件晚到）
                t.earliest_start = max(
                    t.earliest_start, _floor_hour(period_start + timedelta(hours=delay_hours))
                )
            to_replan.append(t)
            continue
        try:
            start = _as_utc(datetime.fromisoformat(str(old_slot)))
        except ValueError:
            to_replan.append(t)
            continue
        if start is None or start < period_start:
            to_replan.append(t)
            continue
        # 冻结：原样占用资源日历
        t.slot_start = start
        t.est_lost_kwh = round(_slot_lost_kwh(power_by_hour, t, start), 1)
        t.avg_wind_ms = _slot_avg_wind(wind_by_hour, t, start)
        occ.apply(t, start, sign=1)
        frozen.append(t)

    starts = _candidate_starts(period_start, period_end)
    constraint_hits: dict[str, int] = {}
    for t in sorted(to_replan, key=lambda x: x.priority_key):
        _place(
            t,
            occ=occ,
            starts=starts,
            power_by_hour=power_by_hour,
            wind_by_hour=wind_by_hour,
            period_end=period_end,
            mode="optimized",
            constraint_hits=constraint_hits,
        )

    swaps = _pairwise_swap(
        to_replan,
        occ=occ,
        power_by_hour=power_by_hour,
        wind_by_hour=wind_by_hour,
        period_end=period_end,
    )
    _retry_unscheduled(
        to_replan,
        occ=occ,
        starts=starts,
        power_by_hour=power_by_hour,
        wind_by_hour=wind_by_hour,
        period_end=period_end,
        constraint_hits=constraint_hits,
    )

    # 标注真正被挪动的工单
    for t in frozen + to_replan:
        old_slot = old_slot_by_wo.get(t.work_order_id)
        new_slot = t.slot_start.isoformat() if t.slot_start else None
        if old_slot and new_slot and str(old_slot) != new_slot:
            t.moved_by = reason
        elif old_slot and not new_slot:
            t.moved_by = f"{reason}(无可行窗口，已挂起)"
        elif not old_slot and new_slot:
            t.moved_by = f"{reason}(新增排程)"

    all_tasks = frozen + to_replan
    for t in all_tasks:
        old_entry = next(
            (s for s in old_schedule if int(s.get("work_order_id", -1)) == t.work_order_id), None
        )
        t.best_alt_lost_kwh = float(old_entry.get("est_lost_kwh") or 0.0) if old_entry else 0.0
        if t.worst_lost_kwh <= 0:
            t.worst_lost_kwh = max(t.est_lost_kwh, t.best_alt_lost_kwh)

    total_lost = sum(t.est_lost_kwh for t in all_tasks if t.slot_start)
    old_obj = old.objective_json or {}
    old_total = float(old_obj.get("total_lost_kwh") or 0.0)
    # baseline 口径必须保持不变（始终是"尽早排程"），否则改善率会因为
    # 工单被挂起而虚高 —— 少排一张工单不是优化，是欠账。
    inherited_baseline = float(old_obj.get("baseline_lost_kwh") or 0.0) or old_total
    old_unscheduled = int(old_obj.get("unscheduled_count") or 0)
    unscheduled_now = [t for t in all_tasks if not t.slot_start]
    # 原本排上了、这次却没窗口的工单 —— 必须显式暴露，不能被"总损失下降"掩盖
    newly_unscheduled = [
        t for t in unscheduled_now if old_slot_by_wo.get(t.work_order_id)
    ]
    schedule_json = [
        _slot_dict(t, price)
        for t in sorted(
            all_tasks,
            key=lambda x: (x.slot_start is None, x.slot_start or period_end, x.work_order_id),
        )
    ]
    moved = [s for s in schedule_json if s.get("moved_by")]

    objective_json = dict(old.objective_json or {})
    objective_json.update(
        {
            "strategy": "replan",
            "algorithm": "incremental greedy + pairwise-swap over frozen occupancy (heuristic)",
            "replan_reason": reason,
            "replan_delay_hours": delay_hours,
            "affected_work_orders": sorted(affected),
            "moved_count": len(moved),
            "frozen_count": len(frozen),
            "total_lost_kwh": round(total_lost, 1),
            "total_revenue_loss": round(total_lost * price, 2),
            "baseline_lost_kwh": round(inherited_baseline, 1),
            "baseline_revenue_loss": round(inherited_baseline * price, 2),
            "saved_kwh": round(max(0.0, inherited_baseline - total_lost), 1),
            "saved_cny": round(max(0.0, inherited_baseline - total_lost) * price, 2),
            "improvement_pct": (
                round((inherited_baseline - total_lost) / inherited_baseline * 100, 2)
                if inherited_baseline > 0
                else 0.0
            ),
            "previous_plan_lost_kwh": round(old_total, 1),
            "delta_kwh": round(total_lost - old_total, 1),
            "constraint_hits": constraint_hits,
            "scheduled_count": len([t for t in all_tasks if t.slot_start]),
            "unscheduled_count": len(unscheduled_now),
            "newly_unscheduled": [t.work_order_id for t in newly_unscheduled],
            "replan_warning": (
                f"{len(newly_unscheduled)} 张工单在新约束下已无可行窗口，"
                f"需人工延长周期或增派班组"
                if newly_unscheduled
                else None
            ),
            "swap_improvements": swaps,
            "previous_plan_no": old.plan_no,
            "previous_unscheduled_count": old_unscheduled,
            "forecast_source": forecast.get("source"),
        }
    )

    plan = await _persist_plan(
        db,
        plan_no=_next_plan_no(period_start, "R"),
        period_start=period_start,
        period_end=period_end,
        objective=objective_json,
        schedule=schedule_json,
        user=user,
        note=note or f"事件重排：{reason}",
        baseline_plan_id=old.id,
        commit=True,
    )
    return {
        "plan": plan,
        "previous_plan": old,
        "objective": objective_json,
        "schedule": schedule_json,
        "moved": moved,
    }


async def commit_plan(
    db: AsyncSession, plan_no: str, user: Optional[User] = None
) -> dict[str, Any]:
    """提交排产版本：本版本 ``committed``，同周期其它已提交版本置为 ``superseded``。"""
    plan = (
        await db.execute(select(ProductionPlan).where(ProductionPlan.plan_no == plan_no))
    ).scalar_one_or_none()
    if plan is None:
        raise ValueError(f"排产方案 {plan_no} 不存在")
    if plan.status == "committed":
        return {"plan": plan, "superseded": [], "message": "该版本已处于已提交状态"}

    superseded: list[str] = []
    others = (
        await db.execute(
            select(ProductionPlan).where(
                ProductionPlan.status == "committed",
                ProductionPlan.id != plan.id,
            )
        )
    ).scalars().all()
    for other in others:
        # 时间区间有重叠的旧版本才作废，历史周期的记录保持原状
        if _as_utc(other.period_start) < _as_utc(plan.period_end) and _as_utc(
            other.period_end
        ) > _as_utc(plan.period_start):
            other.status = "superseded"
            superseded.append(other.plan_no)

    plan.status = "committed"
    plan.committed_at = _utc_now()
    if user is not None and not plan.created_by_name:
        plan.created_by_name = user.username
    # 重新计算 audit_hash，把"已提交"这一状态一并纳入留痕
    plan.audit_hash = compute_audit_hash(
        {
            "plan_no": plan.plan_no,
            "period_start": plan.period_start,
            "period_end": plan.period_end,
            "objective": plan.objective_json,
            "schedule": plan.schedule_json,
            "status": "committed",
            "committed_by": user.username if user else None,
        }
    )
    await db.commit()
    await db.refresh(plan)
    return {
        "plan": plan,
        "superseded": superseded,
        "message": f"排产方案 {plan_no} 已提交执行"
        + (f"，{len(superseded)} 个旧版本已作废" if superseded else ""),
    }


# ══════════════════════════════════════════════════════════
# 查询辅助（供 API 层复用）
# ══════════════════════════════════════════════════════════


async def list_plans(db: AsyncSession, limit: int = 50) -> list[ProductionPlan]:
    rows = (
        await db.execute(
            select(ProductionPlan).order_by(ProductionPlan.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return list(rows)


async def get_plan(db: AsyncSession, plan_no: str) -> Optional[ProductionPlan]:
    return (
        await db.execute(select(ProductionPlan).where(ProductionPlan.plan_no == plan_no))
    ).scalar_one_or_none()


async def get_active_plan(db: AsyncSession) -> Optional[ProductionPlan]:
    """当前生效方案：优先最新 committed，其次最新 draft。"""
    plan = (
        await db.execute(
            select(ProductionPlan)
            .where(ProductionPlan.status == "committed")
            .order_by(ProductionPlan.committed_at.desc(), ProductionPlan.id.desc())
            .limit(1)
        )
    ).scalars().first()
    if plan is not None:
        return plan
    return (
        await db.execute(
            select(ProductionPlan)
            .where(ProductionPlan.status == "draft")
            .order_by(ProductionPlan.id.desc())
            .limit(1)
        )
    ).scalars().first()


async def count_pending_work_orders(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count(WorkOrder.id)).where(
                    WorkOrder.status.in_(SCHEDULABLE_STATUSES),
                    WorkOrder.deleted_at.is_(None),
                )
            )
        ).scalar()
        or 0
    )
