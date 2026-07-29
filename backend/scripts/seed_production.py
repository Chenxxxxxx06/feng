"""生产计划域（风窗排产）种子数据 —— 幂等、只增不改。

产出两样东西：
    1. **未来 7 天的风功率预测曲线**（168 个整点），其中人为构造了 3 个明显的
       低风窗口，落在白班作业时段内，使优化器能演示出"把检修塞进低风窗"的效果。
       曲线本身用真实物理模型生成：合成风速 → 标准功率曲线 → 期望出力。
    2. **一对可对比的排产方案**：baseline（尽早排程，现行做法）+ optimized
       （风窗排产），optimized.baseline_plan_id 指向 baseline。

幂等策略：
    - 预测点：同 (turbine_id=NULL, forecast_time, horizon_hours) 已存在则覆盖更新，不新增重复行
    - 排产方案：plan_no 已存在则跳过（不覆盖既有方案，避免抹掉人工提交的版本）
    - 全程只操作本域新建的 power_forecasts / production_plans 两张表，
      绝不 delete/update 任何既有业务表的数据

用法::

    cd backend
    set PYTHONPATH=<project>/backend
    python -m scripts.seed_production
"""

from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.database import async_session  # noqa: E402
from app.models import WorkOrder  # noqa: E402
from app.models.production import PowerForecast, ProductionPlan  # noqa: E402
from app.services.power_forecast_service import (  # noqa: E402
    find_low_wind_windows,
    get_farm_profile,
    persist_forecast,
    power_curve,
)
from app.services.production_scheduler_service import (  # noqa: E402
    SCHEDULABLE_STATUSES,
    TERMINAL_STATUSES,
    optimize_schedule,
)

SEED_SOURCE = "manual"
SEED_HOURS = 168  # 7 天
LOCAL_UTC_OFFSET_HOURS = 8  # 场址位于 Asia/Shanghai，与排产器口径一致

# 人为构造的"静风天"（相对种子起点的**本地日历日**序号，0 = 第 1 天）。
# 用本地日而不是固定小时偏移，保证无论脚本几点运行，低风窗都落在
# 白班作业窗（08:00-18:00 当地时间）内，优化器才有窗可用。
LOW_WIND_LOCAL_DAYS = (1, 3, 5)   # 第 2 / 4 / 6 天：天气系统过境，全天小风
# 人为构造的"大风天"，风速 > 12 m/s 禁止登塔，用于演示天气窗约束真的会挡人
HIGH_WIND_LOCAL_DAYS = (2,)       # 第 3 天白班：大风禁作业


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _synthetic_wind(hour_offset: int, local_day: int, local_hour: int) -> float:
    """合成风速序列：日变化 + 天气尺度波动 + 人为静风天/大风天。

    基础公式（m/s）::

        v = 8.2 + 2.2*sin(2π*(h-6)/24)      日变化（午后偏大）
                + 3.0*sin(2π*h/54 + 0.7)     天气尺度（约 2.2 天周期的天气系统）

    静风天：整日风速压到 2.4~4.2 m/s（切入风速附近，基本不发电），
    正午最低 —— 这是一次真实天气系统过境的形态，也是检修的黄金窗口。
    大风天：白班 14~16 m/s，超过登塔风速上限。
    全程无随机数，结果可复现。
    """
    if local_day in LOW_WIND_LOCAL_DAYS:
        # 正午（12:00 当地）最低，日出/日落前后回升
        shape = math.sin(math.pi * min(1.0, max(0.0, (local_hour - 4) / 16.0)))
        return round(4.2 - 1.8 * shape, 2)
    if local_day in HIGH_WIND_LOCAL_DAYS and 7 <= local_hour < 19:
        return round(14.5 + 1.5 * math.sin(math.pi * (local_hour - 7) / 12.0), 2)

    base = 8.2
    diurnal = 2.2 * math.sin(2 * math.pi * (hour_offset - 6) / 24.0)
    synoptic = 3.0 * math.sin(2 * math.pi * hour_offset / 54.0 + 0.7)
    return round(max(0.0, base + diurnal + synoptic), 2)


def build_seed_forecast(start_hour: datetime, farm_rated_kw: float) -> list[dict[str, Any]]:
    """生成 168 小时的种子预测点（真实功率曲线驱动，置信带随时效放宽）。"""
    points: list[dict[str, Any]] = []
    day0 = (start_hour + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)).date()
    for h in range(SEED_HOURS):
        slot = start_hour + timedelta(hours=h)
        local = slot + timedelta(hours=LOCAL_UTC_OFFSET_HOURS)
        wind = _synthetic_wind(h, (local.date() - day0).days, local.hour)
        expected = power_curve(wind, farm_rated_kw)
        # 预报不确定度：±1.0 m/s 起，每 72h 再放宽 1 倍
        sigma = 1.0 * (1 + h / 72.0)
        points.append(
            {
                "forecast_time": slot,
                "horizon_hours": h + 1,
                "wind_speed_ms": wind,
                "expected_power_kw": round(expected, 1),
                "confidence_low": round(power_curve(max(0.0, wind - sigma), farm_rated_kw), 1),
                "confidence_high": round(power_curve(wind + sigma, farm_rated_kw), 1),
                "source": SEED_SOURCE,
            }
        )
    return points


async def _existing_seed_points(db: AsyncSession, start: datetime, end: datetime) -> int:
    rows = (
        await db.execute(
            select(PowerForecast.id).where(
                PowerForecast.turbine_id.is_(None),
                PowerForecast.forecast_time >= start,
                PowerForecast.forecast_time < end,
            )
        )
    ).all()
    return len(rows)


async def seed_production(db: AsyncSession, *, verbose: bool = True) -> dict[str, Any]:
    """写入生产计划域种子数据（幂等）。

    Returns:
        {"forecast_points": int, "forecast_skipped": bool,
         "baseline_plan_no": str|None, "optimized_plan_no": str|None,
         "messages": [...]}
    """
    messages: list[str] = []

    def _say(msg: str) -> None:
        messages.append(msg)
        if verbose:
            print(msg)

    start_hour = _floor_hour(_utc_now()) + timedelta(hours=1)
    end_hour = start_hour + timedelta(hours=SEED_HOURS)

    # ── 1. 风功率预测 ──
    profile = await get_farm_profile(db)
    farm_rated_kw = float(profile["rated_kw"])
    _say(
        f"   场站额定容量 {farm_rated_kw / 1000:.1f} MW / {profile['turbine_count']} 台机组"
    )

    before = await _existing_seed_points(db, start_hour, end_hour)
    points = build_seed_forecast(start_hour, farm_rated_kw)
    written = await persist_forecast(db, points, turbine_id=None, commit=True)
    windows = find_low_wind_windows(points, farm_rated_kw)
    _say(
        f"   ✅ 风功率预测: 写入/更新 {written} 个整点"
        f"（原有 {before} 个），识别出 {len(windows)} 个低风窗口"
    )
    for w in windows[:3]:
        local_start = w["start"] + timedelta(hours=8)
        _say(
            f"      · {local_start:%m-%d %H:%M} 起 {w['hours']:.0f}h，"
            f"均风 {w['avg_wind_ms']:.1f} m/s，出力仅 {w['capacity_factor'] * 100:.0f}% 额定"
        )

    # ── 2. 排产方案（baseline vs optimized） ──
    schedulable = (
        await db.execute(
            select(WorkOrder).where(
                WorkOrder.deleted_at.is_(None),
                WorkOrder.status.notin_(TERMINAL_STATUSES),
                WorkOrder.status.in_(SCHEDULABLE_STATUSES),
            )
        )
    ).scalars().all()

    if len(schedulable) < 2:
        _say(
            f"   ⚠️  可排产工单仅 {len(schedulable)} 张（需要 >=2 张才有对比意义），"
            f"跳过排产方案种子。请先创建待处理工单后重跑本脚本。"
        )
        return {
            "forecast_points": written,
            "forecast_skipped": False,
            "baseline_plan_no": None,
            "optimized_plan_no": None,
            "messages": messages,
        }

    seed_plan_no = f"PP-{start_hour:%Y%m%d}-SEED"
    existing = (
        await db.execute(
            select(ProductionPlan).where(ProductionPlan.plan_no == seed_plan_no)
        )
    ).scalar_one_or_none()
    if existing is not None:
        _say(f"   ⏭️  排产方案 {seed_plan_no} 已存在，跳过（幂等）")
        base = (
            await db.get(ProductionPlan, existing.baseline_plan_id)
            if existing.baseline_plan_id
            else None
        )
        return {
            "forecast_points": written,
            "forecast_skipped": False,
            "baseline_plan_no": base.plan_no if base else None,
            "optimized_plan_no": existing.plan_no,
            "messages": messages,
        }

    result = await optimize_schedule(
        db,
        period_days=7,
        mode="optimized",
        note="种子数据：风窗排产 vs 尽早排程对照",
        plan_no=seed_plan_no,
        with_baseline=True,
    )
    plan: Optional[ProductionPlan] = result.get("plan")
    baseline: Optional[ProductionPlan] = result.get("baseline_plan")
    obj = result.get("objective") or {}

    if plan is None:
        _say("   ⚠️  排产未生成（无可排工单）")
        return {
            "forecast_points": written,
            "forecast_skipped": False,
            "baseline_plan_no": None,
            "optimized_plan_no": None,
            "messages": messages,
        }

    _say(
        f"   ✅ 排产方案: {baseline.plan_no if baseline else '-'}(baseline) → "
        f"{plan.plan_no}(optimized)"
    )
    _say(
        f"      基线损失 {obj.get('baseline_lost_kwh', 0):,.0f} kWh → "
        f"优化后 {obj.get('total_lost_kwh', 0):,.0f} kWh，"
        f"少损失 {obj.get('saved_kwh', 0):,.0f} kWh"
        f"（≈¥{obj.get('saved_cny', 0):,.0f}），改善 {obj.get('improvement_pct', 0):.1f}%"
    )
    _say(
        f"      已排 {obj.get('scheduled_count', 0)} 张 / 挂起 {obj.get('unscheduled_count', 0)} 张，"
        f"局部交换改进 {obj.get('swap_improvements', 0)} 次"
    )

    return {
        "forecast_points": written,
        "forecast_skipped": False,
        "baseline_plan_no": baseline.plan_no if baseline else None,
        "optimized_plan_no": plan.plan_no,
        "messages": messages,
    }


async def _main() -> None:
    print("🌬️  生产计划域（风窗排产）种子数据")
    async with async_session() as db:
        await seed_production(db)
    print("✅ 完成")


if __name__ == "__main__":
    asyncio.run(_main())
