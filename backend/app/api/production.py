"""生产计划域 API — 风窗排产（机会性维护）。

风电的"生产计划"就是发电计划。本域把**风功率预测**与**检修排程**打通：
先预测未来 7 天逐小时的发电能力，找出低风窗口，再把必须做的检修塞进
"老天爷本来就不发电"的时段，使检修损失电量最小。

路由清单：
    GET  /power-forecast          未来 N 小时预测曲线（含置信带 + 低风窗口）
    POST /power-forecast/refresh  重算预测（engineer+）
    GET  /plans                   排产版本列表
    POST /plans/optimize          生成优化排产（operator+）
    GET  /plans/{plan_no}         版本详情（排程明细 + baseline 对比）
    POST /plans/{plan_no}/commit  提交排产版本（approver+）
    POST /plans/{plan_no}/replan  事件触发增量重排（operator+）
    GET  /gantt                   甘特图数据（工单块 + 风功率热力带背景）
    GET  /summary                 域概览
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, require_role
from app.database import get_db
from app.models import User
from app.models.production import ProductionPlan
from app.schemas.production import (
    CommitPlanResponse,
    GanttBar,
    GanttResponse,
    GanttWindCell,
    LowWindWindow,
    OptimizeRequest,
    PowerForecastPoint,
    PowerForecastRefreshRequest,
    PowerForecastResponse,
    ProductionPlanDetail,
    ProductionPlanSummary,
    ProductionSummaryResponse,
    ReplanRequest,
    ScheduleSlot,
)
from app.services import power_forecast_service as pfs
from app.services import production_scheduler_service as pss

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _as_utc(value)
    try:
        return _as_utc(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


# ══════════════════════════════════════════════════════════
# 风功率预测
# ══════════════════════════════════════════════════════════


def _build_forecast_response(result: dict[str, Any], hours: int, turbine_id: Optional[int]):
    points = result["points"]
    farm_rated_kw = float(result.get("farm_rated_kw") or 0.0)
    windows = pfs.find_low_wind_windows(points, farm_rated_kw)
    total_kwh = sum(float(p.get("expected_power_kw") or 0.0) for p in points)
    avg_cf = (total_kwh / len(points) / farm_rated_kw) if points and farm_rated_kw > 0 else 0.0
    return PowerForecastResponse(
        turbine_id=turbine_id,
        turbine_name=result.get("turbine_name"),
        hours=hours,
        farm_rated_kw=round(farm_rated_kw, 1),
        source=result.get("source", "persistence"),
        method_note=result.get("method_note", ""),
        generated_at=result.get("generated_at") or datetime.now(timezone.utc),
        points=[PowerForecastPoint(**p) for p in points],
        low_wind_windows=[LowWindWindow(**w) for w in windows],
        total_expected_kwh=round(total_kwh, 1),
        avg_capacity_factor=round(avg_cf, 4),
        degraded=bool(result.get("degraded")),
        degraded_reason=result.get("degraded_reason"),
    )


@router.get("/power-forecast", response_model=PowerForecastResponse)
async def get_power_forecast(
    hours: int = Query(168, ge=1, le=384, description="预测时长（小时），默认 168=7 天"),
    turbine_id: Optional[int] = Query(None, description="留空为全场预测"),
    db: AsyncSession = Depends(get_db),
):
    """获取未来 N 小时的风功率预测曲线（含 P10/P90 置信带与低风窗口标注）。

    优先读取已落库的预测；覆盖率不足时自动重算（天气预报 → 历史类比 → 持续法）。
    """
    result = await pfs.get_or_build_forecast(db, hours, turbine_id=turbine_id)
    return _build_forecast_response(result, hours, turbine_id)


@router.post("/power-forecast/refresh", response_model=PowerForecastResponse)
async def refresh_power_forecast(
    data: PowerForecastRefreshRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("engineer")),
):
    """强制重算风功率预测并覆盖落库（幂等：同 forecast_time + horizon 覆盖更新）。"""
    result = await pfs.forecast_farm_power(
        db,
        data.hours,
        turbine_id=data.turbine_id,
        method=data.method,
        persist=True,
    )
    logger.info(
        "Power forecast refreshed by %s: hours=%s source=%s",
        user.username,
        data.hours,
        result.get("source"),
    )
    return _build_forecast_response(result, data.hours, data.turbine_id)


# ══════════════════════════════════════════════════════════
# 排产方案
# ══════════════════════════════════════════════════════════


def _slot_models(schedule: list[dict[str, Any]]) -> list[ScheduleSlot]:
    slots: list[ScheduleSlot] = []
    for s in schedule or []:
        data = dict(s)
        data["slot_start"] = _parse_dt(data.get("slot_start"))
        data["slot_end"] = _parse_dt(data.get("slot_end"))
        data["constraints"] = [c for c in (data.get("constraints") or []) if c]
        slots.append(ScheduleSlot(**data))
    return slots


async def _summary_model(
    db: AsyncSession, plan: ProductionPlan
) -> ProductionPlanSummary:
    obj = plan.objective_json or {}
    baseline_plan_no = None
    if plan.baseline_plan_id:
        base = await db.get(ProductionPlan, plan.baseline_plan_id)
        baseline_plan_no = base.plan_no if base else None
    return ProductionPlanSummary(
        id=plan.id,
        plan_no=plan.plan_no,
        period_start=_as_utc(plan.period_start),
        period_end=_as_utc(plan.period_end),
        status=plan.status or "draft",
        strategy=obj.get("strategy", "optimized"),
        total_lost_kwh=float(obj.get("total_lost_kwh") or 0.0),
        baseline_lost_kwh=float(obj.get("baseline_lost_kwh") or 0.0),
        improvement_pct=float(obj.get("improvement_pct") or 0.0),
        total_revenue_loss=float(obj.get("total_revenue_loss") or 0.0),
        scheduled_count=int(obj.get("scheduled_count") or 0),
        unscheduled_count=int(obj.get("unscheduled_count") or 0),
        baseline_plan_id=plan.baseline_plan_id,
        baseline_plan_no=baseline_plan_no,
        created_by_name=plan.created_by_name,
        note=plan.note,
        audit_hash=plan.audit_hash,
        created_at=_as_utc(plan.created_at),
        committed_at=_as_utc(plan.committed_at),
    )


@router.get("/plans", response_model=list[ProductionPlanSummary])
async def list_production_plans(
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="draft/committed/superseded"),
    db: AsyncSession = Depends(get_db),
):
    """排产版本列表（按创建时间倒序）。"""
    plans = await pss.list_plans(db, limit=limit)
    if status:
        plans = [p for p in plans if (p.status or "draft") == status]
    return [await _summary_model(db, p) for p in plans]


@router.post("/plans/optimize", response_model=ProductionPlanDetail, status_code=201)
async def optimize_production_plan(
    data: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """生成以**损失电量最小**为目标的风窗排产方案（贪心 + 局部交换启发式）。

    同时落库一个"尽早排程"的 baseline 对照版本，用于展示优化收益。
    """
    result = await pss.optimize_schedule(
        db,
        period_days=data.period_days,
        work_order_ids=data.work_order_ids,
        mode=data.mode,
        user=user,
        note=data.note,
        with_baseline=data.with_baseline,
    )
    plan = result.get("plan")
    if plan is None:
        raise HTTPException(
            status_code=409,
            detail="没有可排产的工单（pending/assigned/in_progress 状态为空）",
        )
    return await _detail_model(db, plan)


@router.get("/plans/{plan_no}", response_model=ProductionPlanDetail)
async def get_production_plan(plan_no: str, db: AsyncSession = Depends(get_db)):
    """排产版本详情：排程明细 + 与 baseline 的对比。"""
    plan = await pss.get_plan(db, plan_no)
    if plan is None:
        raise HTTPException(status_code=404, detail=f"排产方案 {plan_no} 不存在")
    return await _detail_model(db, plan)


async def _detail_model(db: AsyncSession, plan: ProductionPlan) -> ProductionPlanDetail:
    summary = await _summary_model(db, plan)
    obj = plan.objective_json or {}
    slots = _slot_models(plan.schedule_json or [])

    baseline_total = float(obj.get("baseline_lost_kwh") or 0.0)
    total = float(obj.get("total_lost_kwh") or 0.0)
    price = float(obj.get("electricity_price_cny_per_kwh") or 0.0)
    comparison = {
        "baseline_lost_kwh": round(baseline_total, 1),
        "optimized_lost_kwh": round(total, 1),
        "saved_kwh": round(max(0.0, baseline_total - total), 1),
        "saved_cny": round(max(0.0, baseline_total - total) * price, 2),
        "improvement_pct": float(obj.get("improvement_pct") or 0.0),
        "baseline_label": "尽早排程（现行做法，不看风）",
        "optimized_label": "维护窗口推荐方案",
        "algorithm": obj.get("algorithm", ""),
        "swap_improvements": obj.get("swap_improvements", 0),
        "constraint_hits": obj.get("constraint_hits", {}),
        "constraint_labels": obj.get("constraint_labels", {}),
        "capacity": obj.get("capacity", {}),
        "low_wind_windows": obj.get("low_wind_windows", []),
        "forecast_source": obj.get("forecast_source", ""),
    }
    return ProductionPlanDetail(
        **summary.model_dump(),
        objective=obj,
        schedule=slots,
        comparison=comparison,
        moved_slots=[s for s in slots if s.moved_by],
    )


@router.post("/plans/{plan_no}/commit", response_model=CommitPlanResponse)
async def commit_production_plan(
    plan_no: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("approver")),
):
    """提交排产版本执行（approver+）。同周期内其它已提交版本自动置为 superseded。"""
    try:
        result = await pss.commit_plan(db, plan_no, user=user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    plan = result["plan"]
    return CommitPlanResponse(
        plan_no=plan.plan_no,
        status=plan.status,
        committed_at=_as_utc(plan.committed_at),
        superseded_plan_nos=result["superseded"],
        audit_hash=plan.audit_hash,
        message=result["message"],
    )


@router.post("/plans/{plan_no}/replan", response_model=ProductionPlanDetail, status_code=201)
async def replan_production_plan(
    plan_no: str,
    data: ReplanRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("operator")),
):
    """事件触发的增量重排：只动受影响的工单，其余时段冻结。

    生成新版本（``baseline_plan_id`` 指向旧版本），被挪动的工单在
    ``schedule_json`` 中带 ``moved_by``（如 ``supply_delay:PO-102``）。
    """
    try:
        result = await pss.replan_on_event(
            db,
            plan_no,
            reason=data.reason,
            affected_work_orders=data.affected_work_orders,
            delay_hours=data.delay_hours,
            user=user,
            note=data.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return await _detail_model(db, result["plan"])


# ══════════════════════════════════════════════════════════
# 甘特图 / 概览
# ══════════════════════════════════════════════════════════


@router.get("/gantt", response_model=GanttResponse)
async def get_gantt(
    plan_no: Optional[str] = Query(None, description="留空取当前生效方案"),
    db: AsyncSession = Depends(get_db),
):
    """甘特图数据：工单块 + 风功率热力带背景，前端可直接渲染。

    - ``bars``      每张工单的时段块（含损失电量、省电量、moved_by 标记）
    - ``wind_band`` 逐小时的风速/出力/容量系数，用于绘制背景热力带
    - ``row``       工单块的泳道号（按机组分组，同机组同一行）
    """
    plan = await pss.get_plan(db, plan_no) if plan_no else await pss.get_active_plan(db)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    period_start = _as_utc(plan.period_start) if plan else now + timedelta(hours=1)
    period_end = _as_utc(plan.period_end) if plan else period_start + timedelta(days=7)
    hours = max(1, int((period_end - period_start).total_seconds() // 3600))

    forecast = await pfs.get_or_build_forecast(db, hours, turbine_id=None)
    points = forecast["points"]
    farm_rated_kw = float(forecast.get("farm_rated_kw") or 0.0)
    windows = pfs.find_low_wind_windows(points, farm_rated_kw)
    low_hours: set[datetime] = set()
    for w in windows:
        cursor = w["start"]
        while cursor < w["end"]:
            low_hours.add(cursor)
            cursor += timedelta(hours=1)

    wind_band = [
        GanttWindCell(
            time=_as_utc(p["forecast_time"]),
            wind_speed_ms=p.get("wind_speed_ms"),
            expected_power_kw=p.get("expected_power_kw"),
            capacity_factor=(
                round(float(p.get("expected_power_kw") or 0.0) / farm_rated_kw, 4)
                if farm_rated_kw > 0
                else 0.0
            ),
            is_low_wind=_as_utc(p["forecast_time"]) in low_hours,
        )
        for p in points
    ]

    bars: list[GanttBar] = []
    if plan:
        schedule = plan.schedule_json or []
        turbine_rows: dict[int, int] = {}
        for tid in sorted({int(s["turbine_id"]) for s in schedule if s.get("turbine_id")}):
            turbine_rows[tid] = len(turbine_rows)
        for s in schedule:
            if not s.get("slot_start"):
                continue
            bars.append(
                GanttBar(
                    work_order_id=int(s["work_order_id"]),
                    turbine_id=int(s["turbine_id"]),
                    turbine_name=s.get("turbine_name", ""),
                    label=s.get("title", ""),
                    priority=s.get("priority", "medium"),
                    start=_parse_dt(s.get("slot_start")),
                    end=_parse_dt(s.get("slot_end")),
                    est_lost_kwh=float(s.get("est_lost_kwh") or 0.0),
                    saving_kwh=float(s.get("saving_kwh") or 0.0),
                    moved_by=s.get("moved_by"),
                    reason=s.get("reason", ""),
                    row=turbine_rows.get(int(s["turbine_id"]), 0),
                )
            )

    return GanttResponse(
        plan_no=plan.plan_no if plan else None,
        status=plan.status if plan else None,
        period_start=period_start,
        period_end=period_end,
        bars=bars,
        wind_band=wind_band,
        low_wind_windows=[LowWindWindow(**w) for w in windows],
        farm_rated_kw=round(farm_rated_kw, 1),
        forecast_source=forecast.get("source", ""),
        legend={
            "low_wind_hint": "浅色/低饱和区段为低风窗口，是安排停机检修的最佳时机",
            "moved_hint": "带 moved_by 标记的工单块是本次事件重排中被挪动的",
            "max_work_wind_ms": pss.MAX_WORK_WIND_MS,
            "work_window_local": f"{pss.WORK_HOUR_START:02d}:00-{pss.WORK_HOUR_END:02d}:00 (UTC+8)",
        },
    )


@router.get("/summary", response_model=ProductionSummaryResponse)
async def get_production_summary(db: AsyncSession = Depends(get_db)):
    """域概览：本周计划损失电量 / 优化改善率 / 待排工单数。"""
    plan = await pss.get_active_plan(db)
    obj = (plan.objective_json or {}) if plan else {}
    price = float(obj.get("electricity_price_cny_per_kwh") or pss.get_electricity_price())

    points = await pfs.load_forecast_points(db, 168, turbine_id=None)
    farm = await pfs.get_farm_profile(db)
    windows = pfs.find_low_wind_windows(points, float(farm["rated_kw"])) if points else []
    low_hours = int(sum(w["hours"] for w in windows))

    pending = await pss.count_pending_work_orders(db)
    plans = await pss.list_plans(db, limit=200)

    total_lost = float(obj.get("total_lost_kwh") or 0.0)
    baseline_lost = float(obj.get("baseline_lost_kwh") or 0.0)
    saved = max(0.0, baseline_lost - total_lost)

    highlights: list[str] = []
    if plan:
        highlights.append(
            f"当前方案 {plan.plan_no}（{plan.status}）计划损失电量 {total_lost:,.0f} kWh"
        )
        if saved > 0:
            highlights.append(
                f"相比「尽早排程」基线少损失 {saved:,.0f} kWh（≈¥{saved * price:,.0f}），"
                f"改善 {float(obj.get('improvement_pct') or 0.0):.1f}%"
            )
    else:
        highlights.append("尚未生成排产方案，可调用 POST /plans/optimize 生成")
    if windows:
        best = windows[0]
        highlights.append(
            f"未来 7 天最佳检修窗：{best['label']}，平均出力仅 "
            f"{best['capacity_factor'] * 100:.0f}% 额定"
        )
    if pending:
        highlights.append(f"待排工单 {pending} 张")

    return ProductionSummaryResponse(
        active_plan_no=plan.plan_no if plan else None,
        active_plan_status=plan.status if plan else None,
        period_start=_as_utc(plan.period_start) if plan else None,
        period_end=_as_utc(plan.period_end) if plan else None,
        week_lost_kwh=round(total_lost, 1),
        week_revenue_loss_cny=round(total_lost * price, 2),
        baseline_lost_kwh=round(baseline_lost, 1),
        improvement_pct=float(obj.get("improvement_pct") or 0.0),
        saved_kwh=round(saved, 1),
        saved_cny=round(saved * price, 2),
        pending_work_orders=pending,
        scheduled_work_orders=int(obj.get("scheduled_count") or 0),
        unscheduled_work_orders=int(obj.get("unscheduled_count") or 0),
        low_wind_hours=low_hours,
        forecast_source=(points[0].get("source", "") if points else ""),
        forecast_points=len(points),
        plan_versions=len(plans),
        electricity_price_cny_per_kwh=price,
        highlights=highlights,
    )
