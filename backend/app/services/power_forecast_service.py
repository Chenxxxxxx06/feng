"""风功率预测服务 — 为"风窗排产"提供未来 N 小时的发电能力曲线。

风电的生产计划本质是发电计划，而发电能力完全由风决定。本服务给出未来
逐小时的期望出力与置信带，排产器据此寻找**低风窗口**（老天爷本来就不发电的
时段），把检修塞进去，使检修损失电量最小。

三级预测方法（按可用性自动降级，全部为确定性算法，不依赖 LLM）：

    1. ``weather_forecast``  Open-Meteo 数值天气预报的逐小时风速 → 功率曲线。
       精度最高，需要联网；离线时自动降级。
    2. ``history_analog``    历史类比法（Analog Ensemble）：从 SCADA 历史中检索
       风况与当前相近的历史日，用这些"类比日"的逐小时功率形态外推，
       置信区间取类比样本的 P10/P90 分位数。
    3. ``persistence``       持续法：以最近实测风速为基准，叠加由历史数据统计
       出的日变化（diurnal）形态。作为最后兜底。

关于 SCADA 查询：``scada_records`` 是百万行级大表，本模块所有历史查询都
**同时限定时间范围 + 单机组 + LIMIT**，避免全表扫描。

单位约定：``scada_records.power_kw`` 在本项目的数据集中是**归一化功率（标幺值，
0~1）**。本模块会自动探测量纲（样本最大值 <= 2.0 视为标幺值），并按机组额定
容量还原为 kW，避免把 0.7 当成 0.7kW。
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import SCADARecord, Turbine
from app.models.production import PowerForecast

logger = logging.getLogger(__name__)

# ── 标准风机功率曲线参数（IEC 61400-12 典型陆上机组） ──
CUT_IN_MS = 3.0      # 切入风速
RATED_MS = 12.0      # 额定风速
CUT_OUT_MS = 25.0    # 切出风速（超过则停机保护）

# ── 风切变（power law）：10m 测风外推到 ~100m 轮毂高度 ──
HUB_HEIGHT_M = 100.0
ANEMOMETER_HEIGHT_M = 10.0
WIND_SHEAR_ALPHA = 0.14  # 开阔地典型值

# ── 历史类比法参数 ──
ANALOG_LOOKBACK_DAYS = 120   # 从最近多少天的历史里找类比日
ANALOG_SAMPLE_LIMIT = 20000  # 单次 SCADA 查询硬上限（保护大表）
ANALOG_TOP_K = 8             # 取风况最接近的 K 个历史日组成类比集合

# ── 低风窗口判定 ──
LOW_WIND_QUANTILE = 0.35     # 出力低于全期 P35 视为低风
LOW_WIND_MIN_HOURS = 3       # 至少连续 3 小时才算一个窗口

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_FARM_LAT = 37.3   # 与 maintenance_scheduler 默认场址一致（陕北定边）
DEFAULT_FARM_LNG = 107.6
DEFAULT_CLIMATOLOGY_WIND_MS = 7.5  # 无任何数据时的兜底年均风速


# ══════════════════════════════════════════════════════════
# 基础工具
# ══════════════════════════════════════════════════════════


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """把（可能是 naive 的）数据库时间统一成 UTC aware。"""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _quantile(values: list[float], q: float) -> float:
    """线性插值分位数（纯 Python，避免为一个分位数拉 numpy）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * max(0.0, min(1.0, q))
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def power_curve(wind_speed: Optional[float], rated_kw: float) -> float:
    """标准风机功率曲线：风速 → 出力（kW）。

    分段公式（v = 轮毂高度风速 m/s）::

        v < 3            → P = 0                                   切入前不发电
        3 <= v < 12      → P = P_rated * (v³ - v_in³)/(v_r³ - v_in³)  贝茨定律：风功率 ∝ v³
        12 <= v <= 25    → P = P_rated                             变桨限功率，恒定额定出力
        v > 25           → P = 0                                   切出保护停机

    立方段用"减去切入立方"的归一化形式，保证在 v=3 处连续为 0、在 v=12 处
    连续到额定，不会出现常见的台阶跳变。

    Args:
        wind_speed: 轮毂高度风速 m/s（None 或负值按 0 处理）
        rated_kw: 额定容量 kW

    Returns:
        期望出力 kW（0 ~ rated_kw）
    """
    if wind_speed is None or rated_kw <= 0:
        return 0.0
    v = float(wind_speed)
    if v <= 0:
        return 0.0
    if v < CUT_IN_MS or v > CUT_OUT_MS:
        return 0.0
    if v >= RATED_MS:
        return float(rated_kw)
    numerator = v ** 3 - CUT_IN_MS ** 3
    denominator = RATED_MS ** 3 - CUT_IN_MS ** 3
    return float(rated_kw) * max(0.0, numerator / denominator)


def extrapolate_to_hub(wind_speed_10m: Optional[float]) -> Optional[float]:
    """10m 测风按幂律外推到轮毂高度：v_hub = v_10 * (h_hub/h_10)^α。"""
    if wind_speed_10m is None:
        return None
    return float(wind_speed_10m) * (HUB_HEIGHT_M / ANEMOMETER_HEIGHT_M) ** WIND_SHEAR_ALPHA


# ══════════════════════════════════════════════════════════
# 场站元数据
# ══════════════════════════════════════════════════════════


async def get_farm_profile(
    db: AsyncSession, turbine_id: Optional[int] = None
) -> dict[str, Any]:
    """读取场站（或单机）的额定容量与地理中心。"""
    q = select(Turbine)
    if turbine_id is not None:
        q = q.where(Turbine.id == turbine_id)
    result = await db.execute(q)
    turbines = list(result.scalars().all())

    rated_kw = 0.0
    lats: list[float] = []
    lngs: list[float] = []
    for t in turbines:
        rated_kw += float(t.power_mw or 0.0) * 1000.0
        if t.lat is not None and t.lng is not None:
            lats.append(float(t.lat))
            lngs.append(float(t.lng))

    if rated_kw <= 0:
        # 数据库里没有额定容量信息 → 用单机 3MW × 机组数兜底（并在日志中说明）
        rated_kw = max(1, len(turbines)) * 3000.0
        logger.warning("Turbine power_mw missing — falling back to 3MW/unit for forecast scaling")

    return {
        "rated_kw": rated_kw,
        "turbine_count": len(turbines),
        "lat": _mean(lats) if lats else DEFAULT_FARM_LAT,
        "lng": _mean(lngs) if lngs else DEFAULT_FARM_LNG,
        "turbine_name": turbines[0].name if (turbine_id is not None and turbines) else None,
    }


# ══════════════════════════════════════════════════════════
# 方法 1：数值天气预报驱动（Open-Meteo）
# ══════════════════════════════════════════════════════════


async def _fetch_open_meteo_hourly(lat: float, lng: float, hours: int) -> dict[datetime, float]:
    """拉取 Open-Meteo 逐小时风速预报，返回 {整点UTC: 轮毂高度风速 m/s}。

    优先使用 100m 风速（接近轮毂高度）；只有 10m 时按幂律外推。
    网络不可用直接返回空 dict，由上层降级 —— 绝不让离线环境挂掉。
    """
    try:
        import httpx  # 复用 maintenance_scheduler 已引入的依赖
    except ImportError:  # pragma: no cover - httpx 是既有依赖
        return {}

    forecast_days = max(1, min(16, math.ceil(hours / 24) + 1))
    params = {
        "latitude": lat,
        "longitude": lng,
        "hourly": "wind_speed_10m,wind_speed_100m",
        "wind_speed_unit": "ms",
        "timezone": "UTC",
        "forecast_days": forecast_days,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(OPEN_METEO_FORECAST_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # 离线/超时/限流一律降级
        logger.info("Open-Meteo hourly forecast unavailable, degrading: %s", exc)
        return {}

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict):
        return {}
    times = hourly.get("time") or []
    ws100 = hourly.get("wind_speed_100m") or []
    ws10 = hourly.get("wind_speed_10m") or []

    out: dict[datetime, float] = {}
    for i, t_str in enumerate(times):
        try:
            ts = datetime.fromisoformat(str(t_str)).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        v: Optional[float] = None
        if i < len(ws100) and ws100[i] is not None:
            v = float(ws100[i])
        elif i < len(ws10) and ws10[i] is not None:
            v = extrapolate_to_hub(float(ws10[i]))
        if v is not None:
            out[_floor_hour(ts)] = v
    return out


# ══════════════════════════════════════════════════════════
# 方法 2：历史类比法（Analog Ensemble）
# ══════════════════════════════════════════════════════════


async def _load_scada_window(
    db: AsyncSession, turbine_id: Optional[int], lookback_days: int
) -> tuple[list[tuple[datetime, float, Optional[float]]], Optional[int]]:
    """安全地加载一段 SCADA 历史（限定机组 + 时间范围 + LIMIT）。

    Returns: ([(timestamp, wind_speed_ms, power_kw)], ref_turbine_id)
    """
    # 1) 最新一条记录（利用 timestamp 索引，避免全表扫描）
    latest_q = (
        select(SCADARecord.timestamp, SCADARecord.turbine_id)
        .order_by(SCADARecord.timestamp.desc())
        .limit(1)
    )
    if turbine_id is not None:
        latest_q = latest_q.where(SCADARecord.turbine_id == turbine_id)
    latest_row = (await db.execute(latest_q)).first()
    if latest_row is None:
        return [], None

    latest_ts = _as_utc(latest_row[0])
    ref_turbine_id = turbine_id if turbine_id is not None else int(latest_row[1])
    if latest_ts is None:
        return [], ref_turbine_id

    start_ts = latest_ts - timedelta(days=lookback_days)

    # 2) 单机组 + 时间范围 + LIMIT 的有界查询
    rows = (
        await db.execute(
            select(
                SCADARecord.timestamp,
                SCADARecord.wind_speed_ms,
                SCADARecord.power_kw,
            )
            .where(
                SCADARecord.turbine_id == ref_turbine_id,
                SCADARecord.timestamp >= start_ts,
                SCADARecord.timestamp <= latest_ts,
                SCADARecord.wind_speed_ms.isnot(None),
            )
            .order_by(SCADARecord.timestamp.asc())
            .limit(ANALOG_SAMPLE_LIMIT)
        )
    ).all()

    samples: list[tuple[datetime, float, Optional[float]]] = []
    for ts, ws, p in rows:
        ts_utc = _as_utc(ts)
        if ts_utc is None or ws is None:
            continue
        ws_f = float(ws)
        if ws_f < 0 or ws_f > 60:  # 明显异常的传感器读数直接剔除
            continue
        samples.append((ts_utc, ws_f, float(p) if p is not None else None))
    return samples, ref_turbine_id


def _hourly_profiles(
    samples: list[tuple[datetime, float, Optional[float]]]
) -> dict[Any, dict[int, tuple[float, Optional[float]]]]:
    """把原始 10 分钟级 SCADA 聚合成 {日期: {小时: (平均风速, 平均功率)}}。"""
    buckets: dict[tuple[Any, int], list[tuple[float, Optional[float]]]] = {}
    for ts, ws, p in samples:
        key = (ts.date(), ts.hour)
        buckets.setdefault(key, []).append((ws, p))

    profiles: dict[Any, dict[int, tuple[float, Optional[float]]]] = {}
    for (day, hour), vals in buckets.items():
        ws_avg = _mean([v[0] for v in vals])
        powers = [v[1] for v in vals if v[1] is not None]
        p_avg = _mean(powers) if powers else None
        profiles.setdefault(day, {})[hour] = (ws_avg, p_avg)
    return profiles


def _detect_power_scale(samples: list[tuple[datetime, float, Optional[float]]]) -> str:
    """探测 power_kw 的量纲：标幺值（per_unit）还是真实千瓦（kw）。"""
    powers = [abs(p) for _, _, p in samples if p is not None]
    if not powers:
        return "unknown"
    return "per_unit" if max(powers) <= 2.0 else "kw"


async def _history_analog_forecast(
    db: AsyncSession,
    hours: int,
    rated_kw: float,
    turbine_id: Optional[int],
    start_hour: datetime,
) -> Optional[list[dict[str, Any]]]:
    """历史类比法：找风况相近的历史日，用其逐小时形态外推 + 分位数置信带。

    步骤：
      1. 取参考机组最近 ANALOG_LOOKBACK_DAYS 天的 SCADA（有界查询）
      2. 聚合成"日 × 小时"的风速/功率剖面
      3. 以最近 2 天的日均风速为"当前风况指纹"，按 |日均风速差| 排序取 Top-K 类比日
      4. 未来第 h 小时 → 取类比日在同一 hour-of-day 的样本：
         中位数=期望值，P10/P90=置信带（体现类比样本的离散度）
    """
    samples, _ = await _load_scada_window(db, turbine_id, ANALOG_LOOKBACK_DAYS)
    if len(samples) < 200:
        return None

    scale_mode = _detect_power_scale(samples)
    profiles = _hourly_profiles(samples)
    if len(profiles) < ANALOG_TOP_K + 2:
        return None

    days = sorted(profiles.keys())
    recent_days = days[-2:]
    recent_wind = [
        ws for d in recent_days for ws, _ in profiles[d].values()
    ]
    if not recent_wind:
        return None
    recent_mean = _mean(recent_wind)

    # 候选类比日（排除用于构造指纹的最近 2 天）
    candidates: list[tuple[float, Any]] = []
    for d in days[:-2]:
        day_wind = [ws for ws, _ in profiles[d].values()]
        if len(day_wind) < 12:  # 当天有效小时数太少，形态不可信
            continue
        candidates.append((abs(_mean(day_wind) - recent_mean), d))
    if len(candidates) < 3:
        return None
    candidates.sort(key=lambda x: x[0])
    analog_days = [d for _, d in candidates[:ANALOG_TOP_K]]

    points: list[dict[str, Any]] = []
    for h in range(hours):
        slot = start_hour + timedelta(hours=h)
        hh = slot.hour
        winds: list[float] = []
        powers: list[float] = []
        for d in analog_days:
            entry = profiles[d].get(hh)
            if entry is None:
                continue
            winds.append(entry[0])
            if entry[1] is not None:
                powers.append(entry[1])

        if not winds:
            winds = [recent_mean]

        wind_median = _quantile(winds, 0.5)

        if powers and scale_mode != "unknown":
            # 有实测功率 → 直接用类比样本的功率分布（已隐含真实功率曲线与可用率）
            if scale_mode == "per_unit":
                conv = lambda x: max(0.0, min(1.0, x)) * rated_kw
            else:
                conv = lambda x: max(0.0, x)
            expected = conv(_quantile(powers, 0.5))
            low = conv(_quantile(powers, 0.10))
            high = conv(_quantile(powers, 0.90))
        else:
            # 无实测功率 → 用风速分位数过功率曲线
            expected = power_curve(wind_median, rated_kw)
            low = power_curve(_quantile(winds, 0.10), rated_kw)
            high = power_curve(_quantile(winds, 0.90), rated_kw)

        points.append(
            {
                "forecast_time": slot,
                "horizon_hours": h + 1,
                "wind_speed_ms": round(wind_median, 2),
                "expected_power_kw": round(expected, 1),
                "confidence_low": round(min(low, expected), 1),
                "confidence_high": round(max(high, expected), 1),
                "source": "history_analog",
            }
        )
    return points


# ══════════════════════════════════════════════════════════
# 方法 3：持续法（兜底）
# ══════════════════════════════════════════════════════════


async def _persistence_forecast(
    db: AsyncSession,
    hours: int,
    rated_kw: float,
    turbine_id: Optional[int],
    start_hour: datetime,
) -> list[dict[str, Any]]:
    """持续法：以最近实测风速为基准 + 历史统计的日变化形态。

    置信带随预报时效线性放宽（±15% 起，每 24h 再放宽 10%，上限 ±60%），
    体现"预报越远越不确定"这一物理常识。
    """
    samples, _ = await _load_scada_window(db, turbine_id, 14)

    if samples:
        base_wind = _mean([ws for _, ws, _ in samples[-144:]])  # 最近约 24h
        # 日变化形态：hour-of-day 平均风速 / 全期平均
        by_hour: dict[int, list[float]] = {}
        for ts, ws, _ in samples:
            by_hour.setdefault(ts.hour, []).append(ws)
        overall = _mean([ws for _, ws, _ in samples]) or base_wind or 1.0
        diurnal = {
            h: (_mean(v) / overall if overall > 0 else 1.0) for h, v in by_hour.items()
        }
        note_source = "scada_recent"
    else:
        base_wind = DEFAULT_CLIMATOLOGY_WIND_MS
        diurnal = {}
        note_source = "climatology"

    if base_wind <= 0:
        base_wind = DEFAULT_CLIMATOLOGY_WIND_MS

    points: list[dict[str, Any]] = []
    for h in range(hours):
        slot = start_hour + timedelta(hours=h)
        factor = diurnal.get(slot.hour, 1.0)
        wind = max(0.0, base_wind * factor)
        expected = power_curve(wind, rated_kw)
        spread = min(0.60, 0.15 + 0.10 * (h / 24.0))
        points.append(
            {
                "forecast_time": slot,
                "horizon_hours": h + 1,
                "wind_speed_ms": round(wind, 2),
                "expected_power_kw": round(expected, 1),
                "confidence_low": round(power_curve(wind * (1 - spread), rated_kw), 1),
                "confidence_high": round(power_curve(wind * (1 + spread), rated_kw), 1),
                "source": "persistence",
                "_note_source": note_source,
            }
        )
    return points


# ══════════════════════════════════════════════════════════
# 主入口
# ══════════════════════════════════════════════════════════


async def forecast_farm_power(
    db: AsyncSession,
    hours: int = 168,
    *,
    turbine_id: Optional[int] = None,
    method: Optional[str] = None,
    persist: bool = True,
) -> dict[str, Any]:
    """生成未来 ``hours`` 小时的风功率预测曲线。

    Args:
        db: 异步会话
        hours: 预测时长（小时），默认 168（7 天）
        turbine_id: 指定机组；None 表示全场
        method: ``auto``/``weather_forecast``/``history_analog``/``persistence``
        persist: 是否落 ``power_forecasts`` 表（幂等：同 forecast_time+horizon 覆盖更新）

    Returns:
        {"points": [...], "source": str, "farm_rated_kw": float,
         "method_note": str, "degraded": bool, "degraded_reason": str|None}
    """
    hours = max(1, min(384, int(hours)))
    method = (method or "auto").strip().lower()
    profile = await get_farm_profile(db, turbine_id)
    rated_kw = profile["rated_kw"]
    start_hour = _floor_hour(_utc_now()) + timedelta(hours=1)

    points: Optional[list[dict[str, Any]]] = None
    source = "persistence"
    note = ""
    degraded = False
    degraded_reason: Optional[str] = None

    # ① 数值天气预报
    if method in ("auto", "weather_forecast"):
        wind_map = await _fetch_open_meteo_hourly(profile["lat"], profile["lng"], hours)
        if wind_map:
            built: list[dict[str, Any]] = []
            missing = 0
            for h in range(hours):
                slot = start_hour + timedelta(hours=h)
                v = wind_map.get(slot)
                if v is None:
                    missing += 1
                    continue
                expected = power_curve(v, rated_kw)
                # 预报风速误差随时效增长（MAE 经验值 ~1.2m/s @24h，线性外推）
                sigma = 1.2 * (1 + h / 72.0)
                built.append(
                    {
                        "forecast_time": slot,
                        "horizon_hours": h + 1,
                        "wind_speed_ms": round(v, 2),
                        "expected_power_kw": round(expected, 1),
                        "confidence_low": round(power_curve(max(0.0, v - sigma), rated_kw), 1),
                        "confidence_high": round(power_curve(v + sigma, rated_kw), 1),
                        "source": "weather_forecast",
                    }
                )
            if len(built) >= hours * 0.6:
                points = built
                source = "weather_forecast"
                note = (
                    f"Open-Meteo 逐小时 100m 风速预报 → IEC 标准功率曲线"
                    f"（切入{CUT_IN_MS:g}/额定{RATED_MS:g}/切出{CUT_OUT_MS:g} m/s）"
                    + (f"，{missing} 个时次超出预报范围已跳过" if missing else "")
                )
        elif method == "weather_forecast":
            degraded = True
            degraded_reason = "Open-Meteo 不可用（离线或超时），已降级"

    # ② 历史类比法
    if points is None and method in ("auto", "history_analog", "weather_forecast"):
        analog = await _history_analog_forecast(db, hours, rated_kw, turbine_id, start_hour)
        if analog:
            points = analog
            source = "history_analog"
            note = (
                f"历史类比法：从最近 {ANALOG_LOOKBACK_DAYS} 天 SCADA 中检索风况最接近的 "
                f"{ANALOG_TOP_K} 个历史日，取同 hour-of-day 样本的中位数为期望值、"
                f"P10/P90 为置信带"
            )
            if method != "history_analog":
                degraded = True
                degraded_reason = degraded_reason or "天气预报不可用，已降级为历史类比法"
        elif method == "history_analog":
            degraded = True
            degraded_reason = "SCADA 历史样本不足，无法构建类比集合"

    # ③ 持续法兜底
    if points is None:
        raw = await _persistence_forecast(db, hours, rated_kw, turbine_id, start_hour)
        note_source = raw[0].get("_note_source") if raw else "climatology"
        for p in raw:
            p.pop("_note_source", None)
        points = raw
        source = "persistence"
        note = (
            "持续法：以最近 24h 实测平均风速为基准，叠加历史日变化形态"
            if note_source == "scada_recent"
            else f"无可用 SCADA，采用气候态兜底风速 {DEFAULT_CLIMATOLOGY_WIND_MS} m/s"
        )
        if method != "persistence":
            degraded = True
            degraded_reason = degraded_reason or "天气预报与历史类比均不可用，已降级为持续法"

    if persist:
        await persist_forecast(db, points, turbine_id=turbine_id)

    return {
        "points": points,
        "source": source,
        "method_note": note,
        "farm_rated_kw": rated_kw,
        "turbine_name": profile.get("turbine_name"),
        "generated_at": _utc_now(),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


async def persist_forecast(
    db: AsyncSession,
    points: list[dict[str, Any]],
    *,
    turbine_id: Optional[int] = None,
    commit: bool = True,
) -> int:
    """幂等落库：同 (turbine_id, forecast_time, horizon_hours) 存在则覆盖更新，否则新增。

    只写本域自建的 ``power_forecasts`` 表，不触碰任何既有表。
    """
    if not points:
        return 0

    times = [p["forecast_time"] for p in points]
    q = select(PowerForecast).where(
        PowerForecast.forecast_time >= min(times),
        PowerForecast.forecast_time <= max(times),
    )
    q = (
        q.where(PowerForecast.turbine_id.is_(None))
        if turbine_id is None
        else q.where(PowerForecast.turbine_id == turbine_id)
    )
    existing_rows = (await db.execute(q)).scalars().all()
    index = {
        (_as_utc(r.forecast_time), r.horizon_hours): r for r in existing_rows
    }

    written = 0
    for p in points:
        key = (_as_utc(p["forecast_time"]), int(p.get("horizon_hours") or 1))
        row = index.get(key)
        if row is None:
            db.add(
                PowerForecast(
                    turbine_id=turbine_id,
                    forecast_time=p["forecast_time"],
                    horizon_hours=int(p.get("horizon_hours") or 1),
                    wind_speed_ms=p.get("wind_speed_ms"),
                    expected_power_kw=p.get("expected_power_kw"),
                    confidence_low=p.get("confidence_low"),
                    confidence_high=p.get("confidence_high"),
                    source=p.get("source", "persistence"),
                )
            )
        else:
            row.wind_speed_ms = p.get("wind_speed_ms")
            row.expected_power_kw = p.get("expected_power_kw")
            row.confidence_low = p.get("confidence_low")
            row.confidence_high = p.get("confidence_high")
            row.source = p.get("source", row.source)
        written += 1

    if commit:
        await db.commit()
    else:
        await db.flush()
    return written


async def load_forecast_points(
    db: AsyncSession,
    hours: int = 168,
    *,
    turbine_id: Optional[int] = None,
    since: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """从 ``power_forecasts`` 读取已有预测点（不触发重算）。"""
    hours = max(1, int(hours))
    start = _floor_hour(since or _utc_now())
    # 预测点从"下一个整点"开始，窗口多留 1 小时才能取满 hours 个点
    end = start + timedelta(hours=hours + 1)
    q = select(PowerForecast).where(
        PowerForecast.forecast_time >= start,
        PowerForecast.forecast_time < end,
    )
    q = (
        q.where(PowerForecast.turbine_id.is_(None))
        if turbine_id is None
        else q.where(PowerForecast.turbine_id == turbine_id)
    )
    rows = (await db.execute(q.order_by(PowerForecast.forecast_time.asc()))).scalars().all()

    # 同一时刻可能有多条（不同 horizon）→ 取 horizon 最小（最新最准）的一条
    best: dict[datetime, PowerForecast] = {}
    for r in rows:
        ts = _as_utc(r.forecast_time)
        if ts is None:
            continue
        cur = best.get(ts)
        if cur is None or (r.horizon_hours or 1) < (cur.horizon_hours or 1):
            best[ts] = r

    return [
        {
            "forecast_time": _as_utc(r.forecast_time),
            "horizon_hours": r.horizon_hours or 1,
            "wind_speed_ms": r.wind_speed_ms,
            "expected_power_kw": r.expected_power_kw,
            "confidence_low": r.confidence_low,
            "confidence_high": r.confidence_high,
            "source": r.source or "persistence",
        }
        for _, r in sorted(best.items())
    ][:hours]


async def get_or_build_forecast(
    db: AsyncSession,
    hours: int = 168,
    *,
    turbine_id: Optional[int] = None,
    min_coverage: float = 0.8,
) -> dict[str, Any]:
    """优先读库，覆盖率不足时才重算 —— 避免每次请求都打 SCADA/外网。"""
    points = await load_forecast_points(db, hours, turbine_id=turbine_id)
    if len(points) >= hours * min_coverage:
        profile = await get_farm_profile(db, turbine_id)
        sources = {p.get("source") for p in points if p.get("source")}
        return {
            "points": points,
            "source": sources.pop() if len(sources) == 1 else "mixed",
            "method_note": "读取已落库的预测曲线（如需更新请调用 /power-forecast/refresh）",
            "farm_rated_kw": profile["rated_kw"],
            "turbine_name": profile.get("turbine_name"),
            "generated_at": _utc_now(),
            "degraded": False,
            "degraded_reason": None,
        }
    return await forecast_farm_power(db, hours, turbine_id=turbine_id, persist=True)


# ══════════════════════════════════════════════════════════
# 低风窗口识别（机会性维护的核心输入）
# ══════════════════════════════════════════════════════════


def find_low_wind_windows(
    points: list[dict[str, Any]],
    farm_rated_kw: float,
    *,
    quantile: float = LOW_WIND_QUANTILE,
    min_hours: int = LOW_WIND_MIN_HOURS,
) -> list[dict[str, Any]]:
    """识别连续的低风窗口 —— "老天爷本来就不发电"的时段。

    判据：期望出力低于全期 P{quantile} 分位数，且连续时长 >= ``min_hours``。
    用分位数而非绝对阈值，保证在大风季/小风季都能给出相对最优的窗口。
    """
    if not points:
        return []
    powers = [float(p.get("expected_power_kw") or 0.0) for p in points]
    threshold = _quantile(powers, quantile)

    windows: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []

    def _close_run() -> None:
        if len(run) >= min_hours:
            ps = [float(x.get("expected_power_kw") or 0.0) for x in run]
            ws = [float(x.get("wind_speed_ms") or 0.0) for x in run]
            start = run[0]["forecast_time"]
            end = run[-1]["forecast_time"] + timedelta(hours=1)
            avg_p = _mean(ps)
            windows.append(
                {
                    "start": start,
                    "end": end,
                    "hours": float(len(run)),
                    "avg_power_kw": round(avg_p, 1),
                    "min_power_kw": round(min(ps), 1),
                    "avg_wind_ms": round(_mean(ws), 2),
                    "capacity_factor": round(avg_p / farm_rated_kw, 4) if farm_rated_kw > 0 else 0.0,
                    "label": f"{len(run)}h 低风窗（均风 {_mean(ws):.1f} m/s）",
                }
            )
        run.clear()

    for p in points:
        if float(p.get("expected_power_kw") or 0.0) <= threshold:
            run.append(p)
        else:
            _close_run()
    _close_run()

    windows.sort(key=lambda w: w["avg_power_kw"])
    return windows
