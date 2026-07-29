"""生产计划域（风窗排产）数据模型 — 风电的"生产计划"即发电计划。

本域的核心业务命题是**机会性维护（Opportunistic Maintenance）**：
    用风功率预测找出未来的"低风窗口"，把必须做的检修塞进老天爷本来就不发电的时段，
    从而把检修造成的损失电量（lost kWh）压到最小。

包含两张新表（均为增量新增，不改动任何既有表）：
    - ``power_forecasts``    风功率预测曲线（含置信带）
    - ``production_plans``   版本化的排产方案（draft / committed / superseded）

表由 SQLAlchemy 模型 + 启动时 ``Base.metadata.create_all`` 自动创建。
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)

from app.database import Base


class PowerForecast(Base):
    """风功率预测点 — 一行代表某个时刻（整点）的场站/单机预测功率。

    ``turbine_id`` 为空表示**全场**预测（风窗排产默认使用全场曲线，
    单机损失电量按额定容量占比折算）。

    ``source`` 取值：
        - ``weather_forecast``  Open-Meteo 预报风速 → 功率曲线（精度最高，需联网）
        - ``history_analog``    历史类比法（从 SCADA 检索风况相近的历史时段外推）
        - ``persistence``       持续法（以最近实测风速为基准 + 日变化形态）
        - ``manual``            人工/演示种子写入
    """

    __tablename__ = "power_forecasts"
    __table_args__ = (
        Index("ix_power_forecast_slot", "turbine_id", "forecast_time", "horizon_hours"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # 空 = 全场预测；非空 = 指定机组
    turbine_id = Column(Integer, ForeignKey("turbines.id"), nullable=True, index=True)
    forecast_time = Column(DateTime(timezone=True), nullable=False, index=True)  # 被预测的时刻（整点）
    horizon_hours = Column(Integer, nullable=False, default=1)  # 相对预测发布时刻的提前量（小时）
    wind_speed_ms = Column(Float, nullable=True)  # 轮毂高度预测风速 m/s
    expected_power_kw = Column(Float, nullable=True)  # 期望出力 kW
    confidence_low = Column(Float, nullable=True)  # 置信下界 kW（类比样本 P10）
    confidence_high = Column(Float, nullable=True)  # 置信上界 kW（类比样本 P90）
    source = Column(String(32), default="persistence", index=True)
    created_at = Column(DateTime(timezone=True), default=func.now())


class ProductionPlan(Base):
    """版本化排产方案 — 一次"风窗排产"的完整结果快照。

    版本关系：``baseline_plan_id`` 指向被本版本取代/对照的旧版本。
    - 优化方案的 ``baseline_plan_id`` 指向 baseline（尽早排程）方案；
    - 事件触发重排产生的新版本，其 ``baseline_plan_id`` 指向被重排的旧版本。

    ``status``：``draft``（草稿）/ ``committed``（已提交执行）/ ``superseded``（已被新版本取代）。

    ``objective_json``（目标函数与对比指标）::

        {
          "strategy": "optimized",
          "total_lost_kwh": 12345.6,          # 本方案检修损失电量
          "total_revenue_loss": 6419.7,       # 折算收益损失 CNY
          "baseline_lost_kwh": 20130.2,       # 对照基线损失电量
          "improvement_pct": 38.7,            # 相对基线的改善率 %
          "constraint_hits": {...},           # 各类约束被触发的次数
          ...
        }

    ``schedule_json``（排程明细）::

        [{"work_order_id": 1, "turbine_id": 40, "slot_start": "...", "slot_end": "...",
          "est_lost_kwh": 812.4, "reason": "落在低风窗…", "moved_by": "supply_delay:PO-102"}]
    """

    __tablename__ = "production_plans"

    id = Column(Integer, primary_key=True, index=True)
    plan_no = Column(String(64), unique=True, nullable=False, index=True)  # PP-20260726-a1b2
    period_start = Column(DateTime(timezone=True), nullable=False, index=True)
    period_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(16), default="draft", index=True)  # draft/committed/superseded
    objective_json = Column(JSON, nullable=True)
    schedule_json = Column(JSON, nullable=True)
    baseline_plan_id = Column(Integer, ForeignKey("production_plans.id"), nullable=True, index=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by_name = Column(String(64), nullable=True)  # 冗余留痕，便于前端直接展示
    note = Column(Text, nullable=True)  # 生成原因/重排理由
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())
    committed_at = Column(DateTime(timezone=True), nullable=True)
    # 与证据链打通：可挂到 evidence_nodes，并对排程内容做 SHA-256 留痕
    evidence_id = Column(Integer, ForeignKey("evidence_nodes.id"), nullable=True)
    audit_hash = Column(String(64), nullable=True)
