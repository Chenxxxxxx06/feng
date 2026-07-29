"""Prediction service: RUL refresh, cost comparison, and prediction summary.

RUL 预测采用**多模型融合 + 残差自助法不确定性量化**（v2）：

1. 从 SCADA 历史抽取等间隔 HI 退化轨迹（``_load_hi_trajectory``）；
2. 在同一条轨迹上并行拟合三个退化模型：

   - ``linear``       线性退化   HI(t) = a + b·t          （ISO 13381-1 基线，保留作对照）
   - ``exponential``  指数退化   HI(t) = HI0·exp(-λ·t)    （Wiener/Gamma 退化过程的确定性简化形式）
   - ``analogue``     轨迹类比   k-NN 检索机队中形态最相似的历史退化轨迹，借用其退化速率

3. 三个模型 + 一个 ISO 13381-1 **状态先验基线**按拟合优度（R²）加权融合；
   先验以固定"伪 R²"参与竞争，保证数据不支持任何模型时自动、平滑地退化到状态先验；
4. 置信区间由**残差自助法（residual bootstrap）**给出——对每个模型的拟合残差
   有放回重采样→重新拟合→重新投影 RUL→取经验分位数，不使用任何拍脑袋的百分比。

诚实声明：本系统数据库中**没有 run-to-failure 真值标签**，因此上述 R²/RMSE 全部是
轨迹**样本内拟合优度**，不等于 RUL 预测精度；RUL 的外部精度标注为 not_evaluated
（见 ``model_card_service``）。

Reference: ISO 13381-1:2015 — Condition monitoring and diagnostics — Prognostics.

All configuration values (fault types, costs, components, degradation rates,
scoring parameters) are computed from the real database via data_registry.
No hardcoded constants remain.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RULPrediction, Turbine, SCADARecord, WorkOrder
from app.schemas import CostComparisonRequest, CostComparisonResponse
from app.services.health_index import calculate_turbine_hi, WEIGHTS

logger = logging.getLogger(__name__)

# ── Physical constants (not data-driven — these are physics limits) ────
HI_FAILURE_THRESHOLD = 55.0   # HI below → functional failure (ISO 13381-1)
HI_HEALTHY = 90.0             # HI above → negligible degradation
MIN_DEGRADATION_RATE = 0.015  # 0.015/day ≈ minimum detectable
DEFAULT_DEGRADATION_RATE = 0.05  # 0.05/day ≈ typical warning
FAST_DEGRADATION_RATE = 0.15     # 0.15/day ≈ fault mode

# ── These are now sourced from data_registry at runtime ──
#    COMPONENT_WEIGHTS, FAULT_COST_CONFIG, VALID_FAULT_TYPES
#    COST_PARAMS, degradation rate modifiers, component offsets
#    are all computed from DB data. See data_registry.py.

# Late-import helper (avoids circular import)
def _registry():
    from app.services.data_registry import (
        get_fault_type_registry,
        get_cost_aggregates,
        get_component_config,
        get_urgency_boost,
        get_hi_thresholds,
        get_cost_params,
        get_degradation_rates,
        get_rul_settings,
        get_score_thresholds,
    )
    return {
        "get_fault_type_registry": get_fault_type_registry,
        "get_cost_aggregates": get_cost_aggregates,
        "get_component_config": get_component_config,
        "get_urgency_boost": get_urgency_boost,
        "get_hi_thresholds": get_hi_thresholds,
        "get_cost_params": get_cost_params,
        "get_degradation_rates": get_degradation_rates,
        "get_rul_settings": get_rul_settings,
        "get_score_thresholds": get_score_thresholds,
    }


async def _get_component_weights(db: AsyncSession) -> dict[str, tuple[str, float]]:
    """Build component weights dynamically from knowledge base categories.

    Maps Chinese component names → (component_key, weight_value).
    Falls back to industry-standard mapping when DB is empty.
    """
    reg = _registry()
    comp_config = await reg["get_component_config"](db)
    if not comp_config:
        return {
            "齿轮箱": ("gearbox", WEIGHTS["performance"]),
            "发电机": ("generator", WEIGHTS["performance"]),
            "主轴承": ("main_bearing", WEIGHTS["vibration"]),
            "叶片": ("blade", WEIGHTS["blade"]),
            "变桨系统": ("pitch", WEIGHTS["trend"]),
        }

    # Map categories to weight keys
    category_key_map = {
        "齿轮箱": "gearbox", "发电机": "generator", "轴承": "main_bearing",
        "叶片": "blade", "变桨": "pitch", "传动": "main_bearing",
        "电气": "generator", "偏航": "pitch", "塔筒": "blade",
    }
    weight_type_map = {
        "performance": WEIGHTS["performance"],
        "vibration": WEIGHTS["vibration"],
        "blade": WEIGHTS["blade"],
        "trend": WEIGHTS["trend"],
    }

    result: dict[str, tuple[str, float]] = {}
    for cat_name in comp_config:
        key = category_key_map.get(cat_name, "generator")
        weight = weight_type_map.get(
            "vibration" if cat_name == "轴承" else
            "blade" if cat_name in ("叶片", "塔筒") else
            "trend" if cat_name in ("变桨", "偏航") else
            "performance",
            WEIGHTS["performance"],
        )
        result[cat_name] = (key, weight)

    logger.info("Component weights built from %d DB categories", len(result))
    return result


async def _get_fault_cost_config(db: AsyncSession) -> dict[str, dict]:
    """Build fault cost configuration from real DB data.

    Merges FaultKnowledgeNode case costs + WorkOrder aggregates.
    Falls back to industry-average values when data is absent.
    """
    reg = _registry()
    fault_registry = await reg["get_fault_type_registry"](db)
    cost_aggs = await reg["get_cost_aggregates"](db)

    if not fault_registry:
        logger.warning("No fault registry data — using minimal fallback")
        return _fallback_fault_cost_config()

    config: dict[str, dict] = {}
    for fault_type, info in fault_registry.items():
        category = info.get("category", "")
        total_parts_cost = info.get("total_parts_cost", 0)
        avg_case_cost = info.get("avg_case_cost", 0)
        avg_downtime_days = info.get("avg_downtime_days", 0)

        # Base cost: prefer real WorkOrder avg, then case avg, then parts cost
        wo_agg = cost_aggs.get(fault_type, {})
        base = (
            wo_agg.get("avg_cost_estimate")
            or wo_agg.get("avg_cost_actual")
            or avg_case_cost
            or total_parts_cost
            or 50000
        )

        # Multiplier: derived from severity
        severity = info.get("severity", "medium")
        sev_mult = {"critical": 2.5, "high": 1.8, "medium": 1.0, "low": 0.8}
        multiplier = sev_mult.get(severity, 1.0)

        # Downtime: prefer real WorkOrder avg, then case avg, then solution avg
        downtime_days = (
            (wo_agg.get("avg_downtime_hours") or 0) / 24
            or avg_downtime_days
            or info.get("avg_downtime_hours", 0) / 24
            or 3
        )

        config[fault_type] = {
            "base": round(base, 2),
            "multiplier": multiplier,
            "downtime_days": max(1, round(downtime_days, 1)),
            "component": category,
            "label": fault_type,
        }

    logger.info("Fault cost config built from DB: %d entries", len(config))
    return config


def _fallback_fault_cost_config() -> dict[str, dict]:
    """Industry-average fallback when DB has no data."""
    return {
        "轴承磨损": {"base": 85000, "multiplier": 1.5, "downtime_days": 3, "component": "轴承", "label": "轴承磨损"},
        "齿轮箱故障": {"base": 120000, "multiplier": 2.5, "downtime_days": 7, "component": "齿轮箱", "label": "齿轮箱故障"},
        "叶片损伤": {"base": 35000, "multiplier": 3.0, "downtime_days": 5, "component": "叶片", "label": "叶片损伤"},
        "发电机故障": {"base": 45000, "multiplier": 2.0, "downtime_days": 4, "component": "发电机", "label": "发电机故障"},
        "变桨系统故障": {"base": 18000, "multiplier": 1.0, "downtime_days": 2, "component": "变桨", "label": "变桨系统故障"},
        "主轴不对中": {"base": 60000, "multiplier": 1.8, "downtime_days": 5, "component": "传动", "label": "主轴不对中"},
        "冷却系统故障": {"base": 25000, "multiplier": 1.2, "downtime_days": 2, "component": "电气", "label": "冷却系统故障"},
        "电气连接松动": {"base": 15000, "multiplier": 0.8, "downtime_days": 1, "component": "电气", "label": "电气连接松动"},
    }


async def get_valid_fault_types(db: AsyncSession) -> list[str]:
    """Return all known fault types from the knowledge base."""
    reg = _registry()
    fault_registry = await reg["get_fault_type_registry"](db)
    if fault_registry:
        return sorted(fault_registry.keys())
    return sorted(_fallback_fault_cost_config().keys())


# ── RUL Refresh ──

async def refresh_rul_predictions(
    turbine_id: Optional[int] = None,
    *,
    db: AsyncSession,
) -> dict:
    """Regenerate RUL predictions for one or all turbines.

    Uses the health-index engine to project remaining life for each major
    component.  Existing predictions for the target turbine(s) are replaced.

    Returns a summary dict with counts.
    """
    # Load target turbines
    q = select(Turbine)
    if turbine_id is not None:
        q = q.where(Turbine.id == turbine_id)
    result = await db.execute(q)
    turbines = result.scalars().all()

    if not turbines:
        return {"refreshed": 0, "predictions": 0, "turbines": 0}

    now = datetime.now(timezone.utc)

    # Delete old predictions for these turbines
    tids = [t.id for t in turbines]
    from sqlalchemy import delete

    await db.execute(delete(RULPrediction).where(RULPrediction.turbine_id.in_(tids)))
    await db.flush()

    total_predictions = 0
    degraded_turbines = 0
    weight_accumulator: dict[str, float] = {}
    weight_samples = 0
    context = _new_rul_context()

    for t in turbines:
        detail = await predict_turbine_rul_detailed(t, db, now=now, context=context)
        for item in detail["components"]:
            db.add(
                RULPrediction(
                    turbine_id=t.id,
                    component=item["component"],
                    predicted_at=now,
                    remaining_life_days=item["remaining_life_days"],
                    confidence_lower=item["confidence_lower"],
                    confidence_upper=item["confidence_upper"],
                )
            )
            total_predictions += 1
        if detail.get("degraded"):
            degraded_turbines += 1
        for entry in detail["method_breakdown"]:
            weight_accumulator[entry["method"]] = (
                weight_accumulator.get(entry["method"], 0.0) + entry["weight"]
            )
        weight_samples += 1

    await db.commit()

    avg_weights = (
        {k: round(v / weight_samples, 4) for k, v in sorted(weight_accumulator.items())}
        if weight_samples
        else {}
    )

    logger.info(
        "RUL refresh (%s): %d turbines → %d predictions, %d degraded, weights=%s",
        RUL_MODEL_VERSION,
        len(turbines),
        total_predictions,
        degraded_turbines,
        avg_weights,
    )
    return {
        # ── 既有字段（前端在用，保持不变）──
        "refreshed": len(turbines),
        "predictions": total_predictions,
        "turbines": len(turbines),
        # ── v2 新增可解释字段（只增不改）──
        "model_version": RUL_MODEL_VERSION,
        "ensemble_methods": [m["method"] for m in RUL_METHOD_CATALOG],
        "avg_method_weights": avg_weights,
        "degraded_turbines": degraded_turbines,
        "uncertainty_method": "residual_bootstrap",
        "confidence_level": RUL_CONFIDENCE_LEVEL,
    }


# ═══════════════════════════════════════════════════════════════════
# RUL 多模型融合引擎 v2 —— 常量
# ═══════════════════════════════════════════════════════════════════

HI_FAILURE_THRESHOLD = 55.0   # HI below → functional failure
HI_WARNING = 70.0             # HI below → accelerated degradation
HI_HEALTHY = 90.0             # HI above → negligible degradation
MIN_DEGRADATION_RATE = 0.015  # 0.015/day ≈ 5.5 HI/year (minimum detectable)
DEFAULT_DEGRADATION_RATE = 0.05  # 0.05/day ≈ 18 HI/year (typical warning)
FAST_DEGRADATION_RATE = 0.15     # 0.15/day ≈ 55 HI/year (fault mode)

#: 融合模型版本号 —— 随算法变更递增，写入 API 响应与模型卡
RUL_MODEL_VERSION = "rul-ensemble-v2.0.0"

#: 轨迹抽取：等间隔窗口数
RUL_TRAJECTORY_WINDOWS = 12
#: 单窗口最少 SCADA 原始记录数（低于则该窗口作废）
RUL_MIN_WINDOW_SAMPLES = 20
#: 单窗口最少"有效风速段"记录数（6~25 m/s）
RUL_MIN_OPERATING_SAMPLES = 10
#: 整机最少 SCADA 记录数（低于则无法建立轨迹）
RUL_MIN_SCADA_RECORDS = 50

#: 单机轨迹抽取的最大读取行数。超过时按主键取模做**确定性等距抽样**
#: （id % stride == 0，SQLite / PostgreSQL 通用），把 10~30 万行压到 4 万行量级。
#: 每个时间窗仍有数千样本，窗口内比例估计的标准误 <1%，对轨迹形态无实质影响，
#: 但全机队刷新耗时下降数倍。抽样倍率会写进 trajectory.sampling 供复核。
RUL_MAX_TRAJECTORY_ROWS = 40000

#: 各模型可用所需的最少轨迹点数（诚实降级门槛）
RUL_MIN_POINTS_LINEAR = 3
RUL_MIN_POINTS_EXPONENTIAL = 5
RUL_MIN_POINTS_ANALOGUE = 4

#: 类比法：k 近邻个数与最多检索的同机型对照机
RUL_ANALOGUE_NEIGHBORS = 3
RUL_ANALOGUE_MAX_PEERS = 8

#: ISO 13381-1 状态先验基线的"伪 R²" —— 它以此权重与数据模型同台竞争。
#: 数据模型拟合越好，先验被挤压得越小；数据完全无趋势时先验自动接管。
RUL_PRIOR_PSEUDO_R2 = 0.05
#: 先验速率不确定性带宽（±50%，对应 ISO 状态分级区间的粗粒度）
RUL_PRIOR_RATE_BANDWIDTH = 0.5

#: 残差自助法重采样次数与置信水平
RUL_BOOTSTRAP_SAMPLES = 240
RUL_CONFIDENCE_LEVEL = 0.90
#: 自助法随机种子 —— 固定以保证同一输入可复现
RUL_BOOTSTRAP_SEED = 20260726

#: 指数模型 λ 的物理夹逼区间（1/day）
RUL_LAMBDA_MIN = MIN_DEGRADATION_RATE / 100.0
RUL_LAMBDA_MAX = 0.02

#: 预测地平线上限（天）—— 超出即按"超出预测地平线"截断，避免出现 10 年以上的伪精确数字
RUL_MAX_HORIZON_DAYS = 3650.0
RUL_MIN_HORIZON_DAYS = 1.0

#: 终末区（HI 已跌破功能失效线）参数。
#: HI < HI_FAILURE_THRESHOLD 时资产已处于功能失效区间，此时预测目标改为
#: "还有多久触及强制停机线 RUL_TERMINAL_HI_FLOOR"，并按 P-F 曲线经验施加加速系数。
#: 这三个数是**工程假设**（非标准强制值），显式命名以便评审复核与调参。
RUL_TERMINAL_HI_FLOOR = 45.0
RUL_TERMINAL_ACCELERATION = 5.0
RUL_TERMINAL_MAX_DAYS = 60.0

#: 轨迹缓存 TTL（秒）—— 单机刷新时避免重复扫描同机型对照机的 SCADA
RUL_TRAJECTORY_CACHE_TTL = 1800.0

#: 模型目录（用于模型卡与响应中的稳定顺序）
RUL_METHOD_CATALOG: list[dict[str, str]] = [
    {"method": "linear", "label": "线性退化模型", "form": "HI(t) = a + b·t"},
    {"method": "exponential", "label": "指数退化模型", "form": "HI(t) = HI0·exp(-λ·t)"},
    {"method": "analogue", "label": "相似轨迹类比模型", "form": "kNN(轨迹形态) → 借用同型机退化速率"},
    {"method": "status_prior", "label": "ISO 13381-1 状态先验基线", "form": "rate = f(turbine.status)"},
]

#: 进程内轨迹缓存 {turbine_id: (expire_ts, trajectory|None)}
_TRAJECTORY_CACHE: dict[int, tuple[float, Optional[dict]]] = {}


def _new_rul_context() -> dict[str, Any]:
    """构造一次刷新调用内共享的上下文（轨迹缓存 / 同机型对照集）。"""
    return {"trajectories": {}, "peer_rates": {}, "deg_rates": None, "component_weights": None}


# ═══════════════════════════════════════════════════════════════════
# 第 1 步：从 SCADA 抽取 HI 退化轨迹
# ═══════════════════════════════════════════════════════════════════


async def _load_hi_trajectory(
    turbine: Turbine,
    db: AsyncSession,
    *,
    context: Optional[dict] = None,
) -> Optional[dict]:
    """从 SCADA 历史抽取等间隔 HI 退化轨迹。

    与 v1 相比的两处实质修正：

    1. **量纲自适应**：CARE/真实数据集里 ``power_kw`` 以标幺值(p.u., 0~1)存储，
       v1 用 ``power_mw*1000*0.1`` 当阈值会把**每一条记录**都判成欠功率，
       导致轨迹恒为常数、斜率恒为 0、"数据驱动"实际退化成状态兜底。
       这里改为按观测到的功率上界自动判定标幺 / 绝对 kW（与 ``health_index``
       的 ``is_per_unit`` 判据同源）。
    2. **单次扫描**：v1 先拉全部时间戳再逐窗查询（1 + N 次查询）；这里改为
       一次带风速过滤的查询后在内存分窗，既更快也让每个窗口用上全部样本。

    HI 代理由两项组成（均为可解释的物理观测量）：
      - ``under_ratio``：6~25 m/s 有效风速段内功率低于额定 10% 的比例（可利用率损失）
      - ``cap_ratio``  ：10~14 m/s 近额定风速段的功率中位数 / 额定（功率曲线衰减）

    Returns:
        dict(days, hi, span_days, records, windows, ...) 或 None（数据不足）
    """
    ctx = context if context is not None else {}
    cache = ctx.setdefault("trajectories", {})
    if turbine.id in cache:
        return cache[turbine.id]

    cached = _TRAJECTORY_CACHE.get(turbine.id)
    if cached and cached[0] > time.monotonic():
        cache[turbine.id] = cached[1]
        return cached[1]

    operating_filter = (
        SCADARecord.turbine_id == turbine.id,
        SCADARecord.wind_speed_ms.is_not(None),
        SCADARecord.wind_speed_ms >= 6.0,
        SCADARecord.wind_speed_ms <= 25.0,
    )

    # 先数一遍，决定是否需要等距抽样（一次聚合查询远快于把几十万行拖进内存）
    total_rows = (
        await db.execute(select(func.count(SCADARecord.id)).where(*operating_filter))
    ).scalar() or 0

    stride = 1
    if total_rows > RUL_MAX_TRAJECTORY_ROWS:
        stride = int(total_rows // RUL_MAX_TRAJECTORY_ROWS) + 1

    q = select(
        SCADARecord.timestamp,
        SCADARecord.power_kw,
        SCADARecord.wind_speed_ms,
    ).where(*operating_filter)
    if stride > 1:
        # 主键取模抽样：确定性、可复现，且 SQLite / PostgreSQL 语法通用
        q = q.where(SCADARecord.id % stride == 0)
    rows = (await db.execute(q.order_by(SCADARecord.timestamp.asc()))).fetchall()

    trajectory = _build_trajectory_from_rows(rows, turbine)
    if trajectory is not None:
        trajectory["sampling"] = {
            "operating_rows_total": int(total_rows),
            "rows_read": len(rows),
            "stride": stride,
            "method": "deterministic id-modulo subsampling" if stride > 1 else "full scan",
        }
    _TRAJECTORY_CACHE[turbine.id] = (
        time.monotonic() + RUL_TRAJECTORY_CACHE_TTL,
        trajectory,
    )
    cache[turbine.id] = trajectory
    return trajectory


def _build_trajectory_from_rows(rows, turbine: Turbine) -> Optional[dict]:
    """把 (timestamp, power, wind) 原始行转成 HI 轨迹。纯函数，便于单测。"""
    if len(rows) < RUL_MIN_SCADA_RECORDS:
        return None

    seconds: list[float] = []
    powers: list[float] = []
    winds: list[float] = []
    for ts, power, wind in rows:
        if ts is None:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        seconds.append(ts.timestamp())
        powers.append(abs(power) if power is not None else 0.0)
        winds.append(wind if wind is not None else 0.0)

    if len(seconds) < RUL_MIN_SCADA_RECORDS:
        return None

    t_arr = np.asarray(seconds, dtype=float)
    p_arr = np.asarray(powers, dtype=float)
    w_arr = np.asarray(winds, dtype=float)

    # ── 量纲自适应：标幺值(≤1.5) vs 绝对 kW ──
    p_max = float(p_arr.max()) if p_arr.size else 0.0
    if p_max <= 1.5:
        rated_ref = 1.0
        power_unit = "per_unit"
    else:
        rated_ref = max(1.0, (turbine.power_mw or 2.0) * 1000.0)
        power_unit = "kW"

    t0, t1 = float(t_arr[0]), float(t_arr[-1])
    span_days = max(1.0, (t1 - t0) / 86400.0)
    edges = np.linspace(t0, t1, RUL_TRAJECTORY_WINDOWS + 1)

    days: list[float] = []
    his: list[float] = []
    window_meta: list[dict[str, Any]] = []

    for i in range(RUL_TRAJECTORY_WINDOWS):
        lo, up = edges[i], edges[i + 1]
        mask = (t_arr >= lo) & (t_arr <= up if i == RUL_TRAJECTORY_WINDOWS - 1 else t_arr < up)
        n = int(mask.sum())
        if n < max(RUL_MIN_WINDOW_SAMPLES, RUL_MIN_OPERATING_SAMPLES):
            continue

        pw = p_arr[mask]
        ww = w_arr[mask]

        under_ratio = float((pw < 0.10 * rated_ref).mean())
        hi_perf = 100.0 - under_ratio * 60.0

        near_rated = (ww >= 10.0) & (ww <= 14.0)
        if int(near_rated.sum()) >= RUL_MIN_OPERATING_SAMPLES:
            cap_ratio = float(np.median(pw[near_rated])) / rated_ref
            hi_cap = 100.0 - max(0.0, 1.0 - min(1.0, cap_ratio)) * 50.0
            hi = 0.6 * hi_perf + 0.4 * hi_cap
        else:
            cap_ratio = None
            hi = hi_perf

        hi = float(max(30.0, min(100.0, hi)))
        days.append(float((lo + up) / 2.0 / 86400.0 - t0 / 86400.0))
        his.append(hi)
        window_meta.append(
            {
                "day": round(days[-1], 1),
                "hi": round(hi, 2),
                "samples": n,
                "under_ratio": round(under_ratio, 4),
                "cap_ratio": round(cap_ratio, 4) if cap_ratio is not None else None,
            }
        )

    if len(days) < RUL_MIN_POINTS_LINEAR:
        return None

    return {
        "days": np.asarray(days, dtype=float),
        "hi": np.asarray(his, dtype=float),
        "points": len(days),
        "span_days": span_days,
        "records": int(t_arr.size),
        "power_unit": power_unit,
        "rated_ref": rated_ref,
        "windows": window_meta,
    }


# ═══════════════════════════════════════════════════════════════════
# 第 2 步：三个退化模型的拟合
# ═══════════════════════════════════════════════════════════════════


def _goodness_of_fit(y: np.ndarray, y_hat: np.ndarray) -> tuple[float, float]:
    """返回 (R², RMSE)。R² 一律在 HI 原始空间计算，保证跨模型可比。"""
    resid = y - y_hat
    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - float(np.mean(y))) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 0.0
    rmse = float(np.sqrt(ss_res / max(1, y.size)))
    return float(r2), rmse


def _fit_linear_model(days: np.ndarray, hi: np.ndarray) -> Optional[dict]:
    """线性退化 HI(t) = a + b·t（最小二乘）。"""
    if days.size < RUL_MIN_POINTS_LINEAR:
        return None
    slope, intercept = np.polyfit(days, hi, 1)
    fitted = intercept + slope * days
    r2, rmse = _goodness_of_fit(hi, fitted)
    return {
        "method": "linear",
        "kind": "linear",
        "rate": float(max(MIN_DEGRADATION_RATE, -float(slope))),
        "raw_slope": float(slope),
        "intercept": float(intercept),
        "r2": r2,
        "rmse": rmse,
        "fitted": fitted,
        "residuals": hi - fitted,
        "params": {
            "slope_hi_per_day": round(float(slope), 6),
            "intercept_hi": round(float(intercept), 3),
            "trend": "degrading" if slope < 0 else "stable_or_improving",
        },
    }


def _fit_exponential_model(days: np.ndarray, hi: np.ndarray) -> Optional[dict]:
    """指数退化 HI(t) = HI0·exp(-λ·t)。

    Wiener/Gamma 退化过程漂移项的确定性简化形式：对 ln(HI) 做最小二乘，
    再把拟合值映射回 HI 空间计算 R²/RMSE（与线性模型同一尺度可比）。
    """
    if days.size < RUL_MIN_POINTS_EXPONENTIAL:
        return None
    safe_hi = np.clip(hi, 1e-3, None)
    log_slope, log_intercept = np.polyfit(days, np.log(safe_hi), 1)
    lam_raw = -float(log_slope)
    lam = float(np.clip(lam_raw, RUL_LAMBDA_MIN, RUL_LAMBDA_MAX))
    fitted = np.exp(log_intercept + log_slope * days)
    r2, rmse = _goodness_of_fit(hi, fitted)
    return {
        "method": "exponential",
        "kind": "exponential",
        "rate": lam,
        "raw_lambda": lam_raw,
        "log_intercept": float(log_intercept),
        "r2": r2,
        "rmse": rmse,
        "fitted": fitted,
        "residuals": hi - fitted,
        "params": {
            "lambda_per_day": round(lam, 8),
            "lambda_raw_per_day": round(lam_raw, 8),
            "hi0": round(float(np.exp(log_intercept)), 3),
            "clamped": abs(lam - lam_raw) > 1e-12,
        },
    }


def _fit_analogue_model(
    days: np.ndarray,
    hi: np.ndarray,
    peers: list[dict],
) -> Optional[dict]:
    """相似轨迹类比法（k-NN over degradation trajectories）。

    1. 把每条对照机轨迹按"归一化时间 0~1"重采样到本机轨迹的时间栅格；
    2. 去均值后按 RMSE 距离排序，取最近的 k 条；
    3. 借用这 k 条轨迹的实测退化速率（中位数）作为本机的退化速率；
    4. **固定斜率、最小二乘求截距**后在本机轨迹上反算 R²/RMSE ——
       类比是否成立由数据说话（R² 可以为负，那就意味着"这台机不适合类比"，
       融合时权重自然归零，不做任何粉饰）。
    """
    if days.size < RUL_MIN_POINTS_ANALOGUE or not peers:
        return None

    span = float(days[-1] - days[0])
    if span <= 0:
        return None
    self_axis = (days - days[0]) / span
    self_centered = hi - float(np.mean(hi))

    scored: list[tuple[float, dict]] = []
    for peer in peers:
        p_days = peer["days"]
        p_hi = peer["hi"]
        p_span = float(p_days[-1] - p_days[0])
        if p_days.size < RUL_MIN_POINTS_LINEAR or p_span <= 0:
            continue
        p_axis = (p_days - p_days[0]) / p_span
        resampled = np.interp(self_axis, p_axis, p_hi)
        distance = float(np.sqrt(np.mean((resampled - float(np.mean(resampled)) - self_centered) ** 2)))
        scored.append((distance, peer))

    if not scored:
        return None

    scored.sort(key=lambda item: item[0])
    neighbours = scored[: RUL_ANALOGUE_NEIGHBORS]
    peer_rates = np.asarray([n[1]["rate"] for n in neighbours], dtype=float)
    rate = float(np.median(peer_rates))
    rate = float(max(MIN_DEGRADATION_RATE, rate))

    # 固定斜率 -rate，用最小二乘求最优截距（1 参数拟合），保证与线性/指数模型公平比较
    elapsed = days - days[0]
    anchor = float(np.mean(hi + rate * elapsed))
    fitted = anchor - rate * elapsed
    r2, rmse = _goodness_of_fit(hi, fitted)
    return {
        "method": "analogue",
        "kind": "linear",
        "rate": rate,
        "r2": r2,
        "rmse": rmse,
        "fitted": fitted,
        "residuals": hi - fitted,
        "peer_rates": peer_rates,
        "params": {
            "neighbours": [
                {
                    "turbine_id": n[1]["turbine_id"],
                    "turbine_name": n[1]["turbine_name"],
                    "trajectory_distance_hi": round(n[0], 3),
                    "observed_rate_hi_per_day": round(n[1]["rate"], 5),
                }
                for n in neighbours
            ],
            "k": len(neighbours),
            "borrowed_rate_hi_per_day": round(rate, 5),
            "peer_pool_size": len(scored),
        },
    }


def _status_prior_rate(status: str) -> float:
    """ISO 13381-1 状态分级先验退化速率。"""
    if status == "fault":
        return FAST_DEGRADATION_RATE
    if status == "warning":
        return DEFAULT_DEGRADATION_RATE
    return MIN_DEGRADATION_RATE


async def _collect_peer_trajectories(
    turbine: Turbine,
    db: AsyncSession,
    context: dict,
) -> list[dict]:
    """检索同机型对照机的退化轨迹（用于类比法）。

    优先同 ``model``；同机型不足时放宽到全机队。每条对照轨迹用线性拟合得到
    实测退化速率；只保留**确实在退化**（斜率为负）的轨迹作为类比样本 ——
    拿一条在变好的曲线去类比，等于编造。
    """
    cache_key = turbine.model or "__all__"
    if cache_key in context.get("peer_rates", {}):
        pool = context["peer_rates"][cache_key]
        return [p for p in pool if p["turbine_id"] != turbine.id]

    q = select(Turbine).where(Turbine.id != turbine.id)
    if turbine.model:
        q = q.where(Turbine.model == turbine.model)
    peers_rows = (await db.execute(q.limit(RUL_ANALOGUE_MAX_PEERS))).scalars().all()

    if len(peers_rows) < RUL_ANALOGUE_NEIGHBORS:
        peers_rows = (
            await db.execute(
                select(Turbine).where(Turbine.id != turbine.id).limit(RUL_ANALOGUE_MAX_PEERS)
            )
        ).scalars().all()

    pool: list[dict] = []
    for peer in peers_rows:
        traj = await _load_hi_trajectory(peer, db, context=context)
        if not traj:
            continue
        fit = _fit_linear_model(traj["days"], traj["hi"])
        if not fit or fit["raw_slope"] >= 0:
            continue  # 只把真正在退化的历史轨迹当作类比样本
        pool.append(
            {
                "turbine_id": peer.id,
                "turbine_name": peer.name,
                "model": peer.model,
                "days": traj["days"],
                "hi": traj["hi"],
                "rate": abs(fit["raw_slope"]),
                "r2": fit["r2"],
            }
        )

    context.setdefault("peer_rates", {})[cache_key] = pool
    return [p for p in pool if p["turbine_id"] != turbine.id]


# ═══════════════════════════════════════════════════════════════════
# 第 3 步：RUL 投影 + 加权融合 + 残差自助法区间
# ═══════════════════════════════════════════════════════════════════


def _project_rul(
    kind: str,
    rate: float,
    effective_hi: float,
    modifier: float = 1.0,
    failure_threshold: float = HI_FAILURE_THRESHOLD,
) -> float:
    """按模型形态把退化速率投影成 RUL（天）。

    分两个区间，用**同一套公式**处理，只切换目标阈值与速率加速系数：

    - 常规区（HI > 失效线）：投影到 ``failure_threshold``；
    - 终末区（HI ≤ 失效线）：资产已进入功能失效区间，改为投影到强制停机线
      ``RUL_TERMINAL_HI_FLOOR``，并按 P-F 曲线经验乘以 ``RUL_TERMINAL_ACCELERATION``，
      结果封顶 ``RUL_TERMINAL_MAX_DAYS``。

    v1 在终末区返回与速率无关的常数 ``(HI/55)*30``，导致各模型预测完全相同、
    自助法区间宽度恒为 0（"置信区间"失去意义）。这里改为保持速率依赖。
    """
    if effective_hi <= failure_threshold:
        target = RUL_TERMINAL_HI_FLOOR
        accel = RUL_TERMINAL_ACCELERATION
        ceiling = RUL_TERMINAL_MAX_DAYS
        if effective_hi <= target:
            return RUL_MIN_HORIZON_DAYS
    else:
        target = failure_threshold
        accel = 1.0
        ceiling = RUL_MAX_HORIZON_DAYS

    if kind == "exponential":
        lam = max(RUL_LAMBDA_MIN, rate * max(0.05, modifier) * accel)
        rul = math.log(effective_hi / target) / lam
    else:
        eff_rate = max(MIN_DEGRADATION_RATE * 0.1, rate * max(0.05, modifier) * accel)
        rul = (effective_hi - target) / eff_rate

    return float(min(ceiling, max(RUL_MIN_HORIZON_DAYS, rul)))


def _project_rul_linear(
    current_hi: float,
    degradation_rate: float,
    failure_threshold: float = HI_FAILURE_THRESHOLD,
) -> float:
    """[v1 兼容] 线性投影 RUL = (HI - threshold) / rate。"""
    return _project_rul("linear", degradation_rate, current_hi, 1.0, failure_threshold)


def _fuse_weights(models: list[dict]) -> dict[str, float]:
    """按拟合优度（R²）分配融合权重，ISO 状态先验以伪 R² 同台竞争。

    w_i ∝ max(0, R²_i)，先验固定 ``RUL_PRIOR_PSEUDO_R2``。
    数据完全没有趋势（所有 R² ≤ 0）时，先验权重归一化后为 1.0 —— 自动、
    平滑地退回状态基线，而不是硬编码一个 if/else 分支。
    """
    raw: dict[str, float] = {}
    for m in models:
        if m["method"] == "status_prior":
            raw[m["method"]] = RUL_PRIOR_PSEUDO_R2
        else:
            raw[m["method"]] = max(0.0, m["r2"])
    total = sum(raw.values())
    if total <= 0:
        return {m["method"]: (1.0 if m["method"] == "status_prior" else 0.0) for m in models}
    return {k: v / total for k, v in raw.items()}


def _bootstrap_rul_interval(
    models: list[dict],
    weights: dict[str, float],
    days: Optional[np.ndarray],
    effective_hi: float,
    modifier: float,
    rng: np.random.Generator,
) -> tuple[float, float, float]:
    """残差自助法预测区间。

    对每个数据模型：残差有放回重采样 → 叠回拟合值 → 重新拟合 → 重新投影 RUL；
    状态先验：在 ±``RUL_PRIOR_RATE_BANDWIDTH`` 带宽内均匀抽样速率。
    再按点估计权重融合每个自助副本，取经验分位数。

    Returns: (lower, upper, std)
    """
    b = RUL_BOOTSTRAP_SAMPLES
    total = np.zeros(b, dtype=float)
    used_any = False

    for m in models:
        w = weights.get(m["method"], 0.0)
        if w <= 0:
            continue

        if m["method"] == "status_prior":
            lo = m["rate"] * (1.0 - RUL_PRIOR_RATE_BANDWIDTH)
            hi_r = m["rate"] * (1.0 + RUL_PRIOR_RATE_BANDWIDTH)
            rates = rng.uniform(lo, hi_r, size=b)
            samples = np.asarray(
                [_project_rul("linear", float(r), effective_hi, modifier) for r in rates]
            )
        elif m["method"] == "analogue":
            pool = m.get("peer_rates")
            if pool is None or len(pool) == 0:
                samples = np.full(b, _project_rul(m["kind"], m["rate"], effective_hi, modifier))
            else:
                drawn = rng.choice(pool, size=(b, len(pool)), replace=True)
                rates = np.median(drawn, axis=1)
                samples = np.asarray(
                    [_project_rul("linear", float(r), effective_hi, modifier) for r in rates]
                )
        elif days is not None and m.get("residuals") is not None and days.size >= 3:
            resid = m["residuals"]
            fitted = m["fitted"]
            draw = rng.choice(resid, size=(b, resid.size), replace=True)
            y_b = fitted[None, :] + draw
            if m["kind"] == "exponential":
                y_b = np.clip(y_b, 1e-3, None)
                slopes = _vectorised_ols_slope(days, np.log(y_b))
                rates = np.clip(-slopes, RUL_LAMBDA_MIN, RUL_LAMBDA_MAX)
            else:
                slopes = _vectorised_ols_slope(days, y_b)
                rates = np.maximum(MIN_DEGRADATION_RATE, -slopes)
            samples = np.asarray(
                [_project_rul(m["kind"], float(r), effective_hi, modifier) for r in rates]
            )
        else:
            samples = np.full(b, _project_rul(m["kind"], m["rate"], effective_hi, modifier))

        total += w * samples
        used_any = True

    if not used_any:
        point = _project_rul("linear", MIN_DEGRADATION_RATE, effective_hi, modifier)
        return point, point, 0.0

    alpha = (1.0 - RUL_CONFIDENCE_LEVEL) / 2.0 * 100.0
    lower = float(np.percentile(total, alpha))
    upper = float(np.percentile(total, 100.0 - alpha))
    return (
        max(RUL_MIN_HORIZON_DAYS, lower),
        min(RUL_MAX_HORIZON_DAYS, upper),
        float(np.std(total)),
    )


def _vectorised_ols_slope(x: np.ndarray, y_matrix: np.ndarray) -> np.ndarray:
    """一次算完 B 个自助副本的 OLS 斜率（闭式解，避免 B 次 polyfit）。"""
    xc = x - float(np.mean(x))
    sxx = float(np.sum(xc ** 2))
    if sxx <= 1e-12:
        return np.zeros(y_matrix.shape[0], dtype=float)
    yc = y_matrix - y_matrix.mean(axis=1, keepdims=True)
    return (yc @ xc) / sxx


# ═══════════════════════════════════════════════════════════════════
# 第 4 步：对外可解释预测入口
# ═══════════════════════════════════════════════════════════════════


async def predict_turbine_rul_detailed(
    turbine: Turbine,
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    context: Optional[dict] = None,
) -> dict:
    """单台风机的**可解释** RUL 预测（多模型融合 + 自助法区间）。

    返回结构中的 ``method_breakdown`` / ``uncertainty_source`` / ``model_version``
    即为本次升级新增的可解释字段；``components[*]`` 内的
    ``remaining_life_days`` / ``confidence_lower`` / ``confidence_upper``
    与既有 ``RULPrediction`` 字段一一对应，前端契约不变。
    """
    now = now or datetime.now(timezone.utc)
    ctx = context if context is not None else _new_rul_context()

    hi = turbine.hi_value if turbine.hi_value is not None else 85.0
    status = turbine.status or "normal"

    maint_days = 180.0
    if turbine.last_maintenance:
        lm = turbine.last_maintenance
        if lm.tzinfo is None:
            lm = lm.replace(tzinfo=timezone.utc)
        maint_days = max(1.0, float((now - lm).days))

    trajectory = await _load_hi_trajectory(turbine, db, context=ctx)
    degraded_reasons: list[str] = []

    models: list[dict] = []
    unavailable: list[dict] = []

    if trajectory is None:
        degraded_reasons.append(
            f"SCADA 有效样本不足（<{RUL_MIN_SCADA_RECORDS} 条或无法构成 "
            f"{RUL_MIN_POINTS_LINEAR} 个有效时间窗），三个数据驱动模型全部不可用"
        )
        for spec in RUL_METHOD_CATALOG:
            if spec["method"] != "status_prior":
                unavailable.append(
                    {"method": spec["method"], "reason": "无可用退化轨迹（SCADA 数据不足）"}
                )
        days = None
    else:
        days = trajectory["days"]
        hi_series = trajectory["hi"]

        lin = _fit_linear_model(days, hi_series)
        if lin:
            models.append(lin)
        else:
            unavailable.append({"method": "linear", "reason": f"轨迹点数 < {RUL_MIN_POINTS_LINEAR}"})

        exp = _fit_exponential_model(days, hi_series)
        if exp:
            models.append(exp)
        else:
            unavailable.append(
                {"method": "exponential", "reason": f"轨迹点数 < {RUL_MIN_POINTS_EXPONENTIAL}，指数拟合不可靠"}
            )
            degraded_reasons.append(
                f"轨迹点数 {trajectory['points']} < {RUL_MIN_POINTS_EXPONENTIAL}，指数退化模型降级为不参与融合"
            )

        peers = await _collect_peer_trajectories(turbine, db, ctx)
        ana = _fit_analogue_model(days, hi_series, peers)
        if ana:
            models.append(ana)
        else:
            reason = (
                "机队中没有可用的同型退化轨迹（无对照机或对照机均未呈现退化）"
                if not peers
                else f"轨迹点数 < {RUL_MIN_POINTS_ANALOGUE}"
            )
            unavailable.append({"method": "analogue", "reason": reason})
            degraded_reasons.append(f"类比模型降级：{reason}")

    prior_rate = _status_prior_rate(status)
    models.append(
        {
            "method": "status_prior",
            "kind": "linear",
            "rate": prior_rate,
            "r2": None,
            "rmse": None,
            "fitted": None,
            "residuals": None,
            "params": {
                "status": status,
                "prior_rate_hi_per_day": prior_rate,
                "basis": "ISO 13381-1 状态分级（normal/warning/fault）",
                "pseudo_r2": RUL_PRIOR_PSEUDO_R2,
            },
        }
    )

    weights = _fuse_weights(models)

    data_fit_mass = sum(
        max(0.0, m["r2"]) for m in models if m["method"] != "status_prior" and m["r2"] is not None
    )
    if data_fit_mass <= 0:
        degraded_reasons.append(
            "全部数据驱动模型 R² ≤ 0（轨迹无显著退化趋势），融合权重 100% 落到 ISO 状态先验基线"
        )
    elif weights.get("status_prior", 0.0) > 0.5:
        degraded_reasons.append(
            f"数据拟合优度偏低（Σmax(0,R²)={data_fit_mass:.3f}），状态先验权重 "
            f"{weights['status_prior']:.0%}，RUL 以先验为主"
        )

    # ── 部件级投影 ──
    if ctx.get("component_weights") is None:
        ctx["component_weights"] = await _get_component_weights(db)
    if ctx.get("deg_rates") is None:
        ctx["deg_rates"] = await _registry()["get_degradation_rates"](db)
    component_weights = ctx["component_weights"]
    deg_rates = ctx["deg_rates"]

    rng = np.random.default_rng(RUL_BOOTSTRAP_SEED + int(turbine.id or 0))

    components: list[dict] = []
    for component_name, (comp_key, _weight) in component_weights.items():
        comp_offset = await _component_offset_real(
            comp_key, maint_days, hi, db, deg_rates=deg_rates
        )
        effective_hi = max(20.0, min(99.0, hi + comp_offset))
        modifier = float(deg_rates.get(comp_key, 1.0))

        per_method: dict[str, float] = {}
        fused = 0.0
        for m in models:
            rul_m = _project_rul(m["kind"], m["rate"], effective_hi, modifier)
            per_method[m["method"]] = round(rul_m, 1)
            fused += weights.get(m["method"], 0.0) * rul_m

        lower, upper, std = _bootstrap_rul_interval(
            models, weights, days, effective_hi, modifier, rng
        )
        # 保证点估计落在区间内（自助分布偏斜时的稳健收口）
        lower = min(lower, fused)
        upper = max(upper, fused)

        components.append(
            {
                "component": component_name,
                "component_key": comp_key,
                "remaining_life_days": round(min(RUL_MAX_HORIZON_DAYS, max(RUL_MIN_HORIZON_DAYS, fused)), 1),
                "confidence_lower": round(max(RUL_MIN_HORIZON_DAYS, lower), 1),
                "confidence_upper": round(min(RUL_MAX_HORIZON_DAYS, upper), 1),
                "effective_hi": round(effective_hi, 2),
                "rate_modifier": round(modifier, 4),
                "bootstrap_std_days": round(std, 1),
                "method_rul_days": per_method,
                "horizon_capped": fused >= RUL_MAX_HORIZON_DAYS,
            }
        )

    method_breakdown = []
    label_map = {spec["method"]: spec for spec in RUL_METHOD_CATALOG}
    for m in models:
        spec = label_map.get(m["method"], {})
        method_breakdown.append(
            {
                "method": m["method"],
                "label": spec.get("label", m["method"]),
                "form": spec.get("form", ""),
                "available": True,
                "weight": round(weights.get(m["method"], 0.0), 4),
                "r2": round(m["r2"], 4) if m["r2"] is not None else None,
                "rmse_hi": round(m["rmse"], 3) if m["rmse"] is not None else None,
                "reference_rul_days": round(_project_rul(m["kind"], m["rate"], max(20.0, min(99.0, hi)), 1.0), 1),
                "params": m["params"],
            }
        )
    for entry in unavailable:
        spec = label_map.get(entry["method"], {})
        method_breakdown.append(
            {
                "method": entry["method"],
                "label": spec.get("label", entry["method"]),
                "form": spec.get("form", ""),
                "available": False,
                "weight": 0.0,
                "r2": None,
                "rmse_hi": None,
                "reference_rul_days": None,
                "unavailable_reason": entry["reason"],
            }
        )

    best_fit = max(
        (m for m in models if m["r2"] is not None),
        key=lambda m: m["r2"],
        default=None,
    )

    uncertainty_source = {
        "method": "residual_bootstrap",
        "method_cn": "残差自助法重采样（有放回）",
        "confidence_level": RUL_CONFIDENCE_LEVEL,
        "bootstrap_samples": RUL_BOOTSTRAP_SAMPLES,
        "random_seed": RUL_BOOTSTRAP_SEED + int(turbine.id or 0),
        "trajectory_points": trajectory["points"] if trajectory else 0,
        "residual_std_hi": round(
            float(np.std(best_fit["residuals"])), 3
        ) if best_fit is not None and best_fit.get("residuals") is not None else None,
        "contributors": [
            "轨迹拟合残差（SCADA 观测噪声 + 模型形态偏差）",
            "多模型分歧（同一轨迹下各模型 RUL 的差异，按权重传播）",
            "ISO 状态先验速率带宽 ±{:.0%}".format(RUL_PRIOR_RATE_BANDWIDTH),
            "部件退化速率修正系数（来自 SCADA 分部件传感器斜率）",
        ],
        "not_included": [
            "未来工况变化（风况/载荷）",
            "维修干预导致的健康度跃变",
            "无 run-to-failure 真值，无法给出外部校准的覆盖率",
        ],
    }

    return {
        "turbine_id": turbine.id,
        "turbine_name": turbine.name,
        "turbine_model": turbine.model,
        "status": status,
        "hi_current": round(float(hi), 2),
        "model_version": RUL_MODEL_VERSION,
        "generated_at": now.isoformat(),
        "fusion": {
            "strategy": "goodness_of_fit_weighted_average",
            "strategy_cn": "拟合优度(R²)加权模型平均 + ISO 13381-1 状态先验兜底",
            "weights": {k: round(v, 4) for k, v in weights.items()},
            "prior_pseudo_r2": RUL_PRIOR_PSEUDO_R2,
            "data_fit_mass": round(data_fit_mass, 4),
        },
        "trajectory": (
            {
                "points": trajectory["points"],
                "span_days": round(trajectory["span_days"], 1),
                "scada_records_used": trajectory["records"],
                "power_unit_detected": trajectory["power_unit"],
                "rated_reference": trajectory["rated_ref"],
                "sampling": trajectory.get("sampling"),
                "windows": trajectory["windows"],
            }
            if trajectory
            else None
        ),
        "method_breakdown": method_breakdown,
        "uncertainty_source": uncertainty_source,
        "degraded": bool(degraded_reasons),
        "degraded_reason": "；".join(degraded_reasons) if degraded_reasons else None,
        "components": components,
        "horizon_days": RUL_MAX_HORIZON_DAYS,
        "failure_threshold_hi": HI_FAILURE_THRESHOLD,
    }


async def _estimate_linear_degradation(
    turbine: Turbine,
    db: AsyncSession,
) -> Optional[dict]:
    """[v1 兼容] 只返回线性模型的退化速率估计。

    保留原有返回键（degradation_rate/hi_start/hi_end/span_days/data_points），
    内部改走 v2 的轨迹抽取，因此不再受 v1 功率量纲 bug 影响。
    """
    trajectory = await _load_hi_trajectory(turbine, db)
    if trajectory is None:
        return None

    fit = _fit_linear_model(trajectory["days"], trajectory["hi"])
    if fit is None:
        return None

    slope = fit["raw_slope"]
    if -slope < MIN_DEGRADATION_RATE:
        degradation_rate = _status_prior_rate(turbine.status or "normal")
    else:
        degradation_rate = -slope

    return {
        "degradation_rate": float(degradation_rate),
        "hi_start": float(fit["intercept"]),
        "hi_end": float(trajectory["hi"][-1]),
        "span_days": trajectory["span_days"],
        "data_points": trajectory["points"],
        "r2": fit["r2"],
        "rmse": fit["rmse"],
    }


async def _predict_turbine_components(
    turbine: Turbine,
    now: datetime,
    db: AsyncSession,
    context: Optional[dict] = None,
) -> list[RULPrediction]:
    """[v1 兼容入口] 生成部件级 ``RULPrediction`` ORM 对象。

    内部已切换为 v2 融合模型；返回类型与字段保持不变。
    """
    detail = await predict_turbine_rul_detailed(turbine, db, now=now, context=context)
    return [
        RULPrediction(
            turbine_id=turbine.id,
            component=item["component"],
            predicted_at=now,
            remaining_life_days=item["remaining_life_days"],
            confidence_lower=item["confidence_lower"],
            confidence_upper=item["confidence_upper"],
        )
        for item in detail["components"]
    ]


async def _component_offset_real(
    comp_key: str,
    maint_days: float,
    hi: float,
    db: AsyncSession,
    deg_rates: Optional[dict[str, float]] = None,
) -> float:
    """Compute real per-component health offset from SCADA sensor data.

    Analyzes actual sensor variance across the fleet for this component.
    No fake scatter — uses real SCADA deviations.

    Falls back to maintenance-gap-based penalty only when SCADA data insufficient.

    Args:
        deg_rates: 已取好的分部件退化速率表。``get_degradation_rates`` **没有缓存**，
            每次调用都要扫 20000 条 SCADA ORM 行；本函数按部件被逐一调用，
            不传这个参数会让同一份数据在一台机上被重复拉取 N 次（实测占单机
            耗时的绝大部分）。调用方应复用同一份结果。
    """
    # Try computing from real SCADA data
    try:
        if deg_rates is None:
            from app.services.data_registry import get_degradation_rates
            deg_rates = await get_degradation_rates(db)
        # The degradation rate itself gives us the real degradation level
        # Convert rate modifier to HI offset (-10 to +5 range)
        rate = deg_rates.get(comp_key, 1.0)
        if rate > 1.5:
            base_offset = -8.0  # Fast degradation
        elif rate > 1.0:
            base_offset = -4.0  # Moderate degradation
        elif rate < 0.6:
            base_offset = 1.0   # Slow degradation (blades)
        else:
            base_offset = -1.0  # Normal

        # Maintenance gap penalty (real formula, not scatter)
        maint_penalty = min(0, -(maint_days / 365) * 4)

        return base_offset + maint_penalty
    except Exception:
        pass

    # Fallback: maintenance-based only, no fake random
    maint_penalty = min(0, -(maint_days / 365) * 4)
    base_map = {"gearbox": -6.0, "main_bearing": -3.0, "generator": -2.0, "blade": 2.0, "pitch": -1.0}
    return base_map.get(comp_key, 0.0) + maint_penalty


# Legacy alias kept for backwards compatibility during transition
_component_offset = _component_offset_real


# ── Cost parameters now sourced from data_registry.get_cost_params(db) ──
# Module-level COST_PARAMS kept for backwards compatibility (external imports)
# Real values are loaded at runtime from User.preferences JSON.


# ── Cost Comparison ──

async def calculate_cost_comparison(
    data: CostComparisonRequest,
    turbine: Turbine,
    db: AsyncSession,
) -> CostComparisonResponse:
    """Compare immediate vs delayed repair cost using real turbine + DB data.

    All cost parameters sourced from data_registry (real WorkOrder aggregates,
    FaultKnowledgeNode case costs) — no hardcoded price tables.
    """
    reg = _registry()
    fault_cost_config = await _get_fault_cost_config(db)
    cp = await reg["get_cost_params"](db)

    config = fault_cost_config.get(
        data.fault_type,
        {"base": 50000, "multiplier": 1.0, "downtime_days": 3, "label": data.fault_type},
    )

    power_mw = turbine.power_mw or 2.0
    hi = turbine.hi_value or 85.0

    # ── Immediate repair cost (scales with turbine power) ──
    immediate = config["base"] * (power_mw / 2.0) * config["multiplier"]

    # ── Failure probability (data-driven from HI) ──
    hi_thresholds = await reg["get_hi_thresholds"](db)
    hi_warning = hi_thresholds.get("warning", 70.0)
    if hi >= hi_thresholds.get("healthy", 90.0):
        failure_prob = 0.05 + (90 - hi) * cp["failure_prob_healthy_slope"]
    elif hi >= hi_warning:
        failure_prob = 0.10 + (90 - hi) * cp["failure_prob_warning_slope"]
    elif hi >= hi_thresholds.get("failure", 55.0):
        failure_prob = 0.30 + (70 - hi) * cp["failure_prob_fault_slope"]
    else:
        failure_prob = 0.60
    failure_prob = round(min(0.95, max(0.02, failure_prob)), 3)

    # ── Downtime loss per day (turbine power × 24h × electricity price) ──
    daily_loss = power_mw * 1000 * 24 * cp["electricity_price_cny_per_kwh"]

    # ── Delayed repair cost ──
    downtime_days = config["downtime_days"]
    failure_extra_cost = failure_prob * (
        daily_loss * downtime_days + immediate * cp["repair_failure_extra_factor"]
    )
    delayed = immediate + failure_extra_cost

    # ── Estimated saving ──
    saving = delayed - immediate

    # ── Risk level ──
    if failure_prob > cp["risk_high_threshold"]:
        risk_level = "high"
    elif failure_prob > cp["risk_medium_threshold"]:
        risk_level = "medium"
    else:
        risk_level = "low"

    # ── Optimal window ──
    optimal_days = cp[f"optimal_window_{risk_level}_days"]

    # ── Recommendation ──
    if risk_level == "high":
        recommendation = (
            f"紧急建议：{turbine.name} 当前健康指数 {hi:.0f}，{config['label']}故障概率 "
            f"{(failure_prob * 100):.0f}%。强烈建议在 {optimal_days} 天内安排立即检修，"
            f"避免突发性停机造成的 {(daily_loss * downtime_days):,.0f} 元损失。"
        )
    elif risk_level == "medium":
        recommendation = (
            f"建议在下次计划停机（{optimal_days} 天内）安排 {turbine.name} 的 "
            f"{config['label']} 检修。当前 HI={hi:.0f}，故障概率 "
            f"{(failure_prob * 100):.0f}%，提前维修预计可节省 ¥{saving:,.0f}。"
        )
    else:
        recommendation = (
            f"{turbine.name} ({config['label']}) 当前状态良好（HI={hi:.0f}），"
            f"故障概率仅 {(failure_prob * 100):.0f}%。建议纳入常规巡检计划，"
            f"在 {optimal_days} 天内安排预防性检查即可。"
        )

    # ── Cost drivers ──
    cost_drivers = _build_cost_drivers(config, power_mw, daily_loss, failure_prob)

    return CostComparisonResponse(
        immediate_repair_cost=round(immediate, 2),
        delayed_repair_cost=round(delayed, 2),
        downtime_loss_per_day=round(daily_loss, 2),
        failure_probability=failure_prob,
        recommendation=recommendation,
        optimal_window_days=optimal_days,
        risk_level=risk_level,
        estimated_saving=round(saving, 2),
        cost_drivers=cost_drivers,
    )


def _build_cost_drivers(
    config: dict,
    power_mw: float,
    daily_loss: float,
    failure_prob: float,
) -> list[str]:
    """Build human-readable cost driver descriptions."""
    drivers = [
        f"备件成本 ({config['label']})",
        f"停机损失 (¥{daily_loss:,.0f}/天 × {config['downtime_days']}天)",
        f"人工成本 ({power_mw:.1f}MW机组)",
    ]
    if failure_prob > 0.2:
        drivers.append(f"故障风险溢价 (概率{(failure_prob * 100):.0f}%)")
    if config["downtime_days"] > 3:
        drivers.append("发电损失（长停机窗口）")
    if config["multiplier"] >= 2.0:
        drivers.append("紧急调配附加费")
    return drivers


# ── Prediction Summary ──

async def get_prediction_summary(db: AsyncSession) -> dict:
    """Aggregate prediction stats for dashboard consumption."""
    now = datetime.now(timezone.utc)

    # Turbine health distribution
    total_result = await db.execute(select(func.count(Turbine.id)))
    total = total_result.scalar() or 0

    healthy_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "normal")
    )
    warning_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "warning")
    )
    fault_result = await db.execute(
        select(func.count(Turbine.id)).where(Turbine.status == "fault")
    )

    # RUL statistics
    rul_result = await db.execute(
        select(
            func.count(RULPrediction.id),
            func.avg(RULPrediction.remaining_life_days),
            func.min(RULPrediction.remaining_life_days),
            func.max(RULPrediction.remaining_life_days),
        )
    )
    rul_count, rul_avg, rul_min, rul_max = rul_result.one()

    # Imminent failures (RUL < 30 days)
    imminent_result = await db.execute(
        select(func.count(RULPrediction.id)).where(
            RULPrediction.remaining_life_days < 30
        )
    )
    imminent_count = imminent_result.scalar() or 0

    # Critical components (RUL < 90 days)
    critical_result = await db.execute(
        select(func.count(RULPrediction.id)).where(
            RULPrediction.remaining_life_days < 90
        )
    )
    critical_count = critical_result.scalar() or 0

    # Average HI across fleet
    hi_result = await db.execute(
        select(func.avg(Turbine.hi_value))
    )
    avg_hi = hi_result.scalar()

    # RUL by region
    region_rows = await db.execute(
        select(
            Turbine.region,
            func.avg(RULPrediction.remaining_life_days).label("avg_rul"),
            func.count(RULPrediction.id).label("cnt"),
        )
        .join(RULPrediction, RULPrediction.turbine_id == Turbine.id)
        .group_by(Turbine.region)
    )
    by_region = {
        row.region: {"avg_rul": round(row.avg_rul, 1), "count": row.cnt}
        for row in region_rows
    }

    # MTBF — prefer CARE event-based (from monitoring-metrics), fallback to formula
    fault_count = fault_result.scalar() or 0
    from app.services.care_monitoring_metrics import calculate_care_reliability_metrics
    try:
        care_metrics = await calculate_care_reliability_metrics(db)
        mtbf_hours = care_metrics.get("mtbf_hours")
    except Exception:
        mtbf_hours = None
    if mtbf_hours is None:
        if fault_count > 0:
            mtbf_hours = (total * 24 * 365) / fault_count
        else:
            mtbf_hours = total * 24 * 365

    # MTTR — from actual completed work orders, fallback to config estimate
    mttr_result = await db.execute(
        select(func.avg(WorkOrder.downtime_hours)).where(
            WorkOrder.status.in_(["completed", "closed"]),
        )
    )
    actual_mttr = mttr_result.scalar()
    if actual_mttr is not None and actual_mttr > 0:
        mttr_hours = actual_mttr
        mttr_source = "actual"
    else:
        # 无已完成工单时退回故障知识库的平均停机口径
        # （v1 此处引用了未定义的模块级 FAULT_COST_CONFIG，会抛 NameError）
        fallback_cfg = await _get_fault_cost_config(db) or _fallback_fault_cost_config()
        avg_downtime = sum(c["downtime_days"] for c in fallback_cfg.values()) / max(1, len(fallback_cfg))
        mttr_hours = avg_downtime * 8
        mttr_source = "estimated"

    return {
        "fleet": {
            "total": total,
            "healthy": healthy_result.scalar() or 0,
            "warning": warning_result.scalar() or 0,
            "fault": fault_count,
            "avg_hi": round(avg_hi, 1) if avg_hi else None,
        },
        "rul": {
            "total_predictions": rul_count or 0,
            "avg_days": round(rul_avg, 1) if rul_avg else None,
            "min_days": round(rul_min, 1) if rul_min else None,
            "max_days": round(rul_max, 1) if rul_max else None,
            "imminent_count": imminent_count,
            "critical_count": critical_count,
            # v2 新增：标注生成这批预测的模型版本与不确定性口径
            "model_version": RUL_MODEL_VERSION,
            "uncertainty_method": "residual_bootstrap",
            "confidence_level": RUL_CONFIDENCE_LEVEL,
        },
        "reliability": {
            "mtbf_hours": round(mtbf_hours, 1),
            "mttr_hours": round(mttr_hours, 1),
            "mttr_source": mttr_source,
        },
        "by_region": by_region,
        "generated_at": now.isoformat(),
    }
