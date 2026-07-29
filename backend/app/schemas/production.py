"""生产计划域（风窗排产）Pydantic v2 Schema。

覆盖三类对象：
    1. 风功率预测曲线（含置信带 + 低风窗口标注）
    2. 版本化排产方案（objective 对比 + schedule 明细）
    3. 甘特图 / 域概览等前端直接消费的聚合视图
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ══════════════════════════════════════════════════════════
# 风功率预测
# ══════════════════════════════════════════════════════════


class PowerForecastPoint(BaseModel):
    """单个整点的预测值。"""

    forecast_time: datetime
    horizon_hours: int = 1
    wind_speed_ms: Optional[float] = None
    expected_power_kw: Optional[float] = None
    confidence_low: Optional[float] = None
    confidence_high: Optional[float] = None
    source: str = "persistence"

    model_config = {"from_attributes": True}


class LowWindWindow(BaseModel):
    """低风窗口 — 机会性维护的"黄金时段"。"""

    start: datetime
    end: datetime
    hours: float
    avg_power_kw: float
    min_power_kw: float
    avg_wind_ms: float
    capacity_factor: float = Field(default=0.0, description="窗口内平均出力/额定容量")
    label: str = ""


class PowerForecastResponse(BaseModel):
    """未来 N 小时预测曲线。"""

    turbine_id: Optional[int] = None
    turbine_name: Optional[str] = None
    hours: int
    farm_rated_kw: float
    source: str
    method_note: str = ""
    generated_at: datetime
    points: list[PowerForecastPoint] = Field(default_factory=list)
    low_wind_windows: list[LowWindWindow] = Field(default_factory=list)
    total_expected_kwh: float = 0.0
    avg_capacity_factor: float = 0.0
    degraded: bool = False
    degraded_reason: Optional[str] = None


class PowerForecastRefreshRequest(BaseModel):
    """重算预测曲线。"""

    hours: int = Field(default=168, ge=1, le=384)
    turbine_id: Optional[int] = None
    method: Optional[str] = Field(
        default=None,
        description="auto/weather_forecast/history_analog/persistence，留空为 auto（按可用性降级）",
    )


# ══════════════════════════════════════════════════════════
# 排产方案
# ══════════════════════════════════════════════════════════


class ScheduleSlot(BaseModel):
    """排程明细中的一条工单安排。"""

    work_order_id: int
    turbine_id: int
    turbine_name: str = ""
    title: str = ""
    priority: str = "medium"
    slot_start: Optional[datetime] = None
    slot_end: Optional[datetime] = None
    duration_hours: float = 0.0
    crew_size: int = 2
    est_lost_kwh: float = 0.0
    worst_lost_kwh: float = 0.0
    baseline_lost_kwh: float = 0.0
    saving_kwh: float = 0.0
    saving_cny: float = 0.0
    avg_wind_ms: Optional[float] = None
    safety_score: float = 0.0
    rul_days: Optional[float] = None
    reason: str = ""
    moved_by: Optional[str] = None
    parts_note: Optional[str] = None
    constraints: list[str] = Field(default_factory=list)
    scheduled: bool = True
    unscheduled_reason: Optional[str] = None


class ProductionPlanSummary(BaseModel):
    """排产版本列表项。"""

    id: int
    plan_no: str
    period_start: datetime
    period_end: datetime
    status: str
    strategy: str = "optimized"
    total_lost_kwh: float = 0.0
    baseline_lost_kwh: float = 0.0
    improvement_pct: float = 0.0
    total_revenue_loss: float = 0.0
    scheduled_count: int = 0
    unscheduled_count: int = 0
    baseline_plan_id: Optional[int] = None
    baseline_plan_no: Optional[str] = None
    created_by_name: Optional[str] = None
    note: Optional[str] = None
    audit_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    committed_at: Optional[datetime] = None


class ProductionPlanDetail(ProductionPlanSummary):
    """排产版本详情 — 含排程明细与 baseline 对比。"""

    objective: dict[str, Any] = Field(default_factory=dict)
    schedule: list[ScheduleSlot] = Field(default_factory=list)
    comparison: dict[str, Any] = Field(default_factory=dict)
    moved_slots: list[ScheduleSlot] = Field(default_factory=list)


class OptimizeRequest(BaseModel):
    """生成优化排产。"""

    period_days: int = Field(default=7, ge=1, le=14)
    work_order_ids: Optional[list[int]] = None
    mode: str = Field(default="optimized", description="optimized（低风窗优化）/ baseline（尽早排程对照）")
    note: Optional[str] = None
    with_baseline: bool = Field(default=True, description="是否同时落库 baseline 对照版本")


class ReplanRequest(BaseModel):
    """事件触发的增量重排。"""

    reason: str = Field(min_length=1, max_length=128, description="如 supply_delay:PO-102 / weather_alert")
    affected_work_orders: list[int] = Field(
        default_factory=list, description="留空表示全部工单重排"
    )
    delay_hours: float = Field(
        default=0.0,
        ge=0,
        le=336,
        description="事件导致受影响工单的最早可开工时间推迟多少小时（如备件晚到 48h）",
    )
    note: Optional[str] = None


class CommitPlanResponse(BaseModel):
    plan_no: str
    status: str
    committed_at: Optional[datetime] = None
    superseded_plan_nos: list[str] = Field(default_factory=list)
    audit_hash: Optional[str] = None
    message: str = ""


# ══════════════════════════════════════════════════════════
# 甘特图 / 概览
# ══════════════════════════════════════════════════════════


class GanttBar(BaseModel):
    """甘特图上的一个工单块。"""

    work_order_id: int
    turbine_id: int
    turbine_name: str = ""
    label: str = ""
    priority: str = "medium"
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    est_lost_kwh: float = 0.0
    saving_kwh: float = 0.0
    moved_by: Optional[str] = None
    reason: str = ""
    row: int = 0


class GanttWindCell(BaseModel):
    """背景风功率热力带的一格（1 小时）。"""

    time: datetime
    wind_speed_ms: Optional[float] = None
    expected_power_kw: Optional[float] = None
    capacity_factor: float = 0.0
    is_low_wind: bool = False


class GanttResponse(BaseModel):
    plan_no: Optional[str] = None
    status: Optional[str] = None
    period_start: datetime
    period_end: datetime
    bars: list[GanttBar] = Field(default_factory=list)
    wind_band: list[GanttWindCell] = Field(default_factory=list)
    low_wind_windows: list[LowWindWindow] = Field(default_factory=list)
    farm_rated_kw: float = 0.0
    forecast_source: str = ""
    legend: dict[str, Any] = Field(default_factory=dict)


class ProductionSummaryResponse(BaseModel):
    """域概览。"""

    active_plan_no: Optional[str] = None
    active_plan_status: Optional[str] = None
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    week_lost_kwh: float = 0.0
    week_revenue_loss_cny: float = 0.0
    baseline_lost_kwh: float = 0.0
    improvement_pct: float = 0.0
    saved_kwh: float = 0.0
    saved_cny: float = 0.0
    pending_work_orders: int = 0
    scheduled_work_orders: int = 0
    unscheduled_work_orders: int = 0
    low_wind_hours: int = 0
    forecast_source: str = ""
    forecast_points: int = 0
    plan_versions: int = 0
    electricity_price_cny_per_kwh: float = 0.0
    highlights: list[str] = Field(default_factory=list)
