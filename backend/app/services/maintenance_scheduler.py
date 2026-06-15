"""Maintenance Scheduler — auto-scheduling, conflict detection, weather windows.

Key algorithms:
  1. auto_schedule() — greedy deadline-aware slot assignment
  2. detect_conflicts() — same-turbine, crew-overload, weather-unsafe detection
  3. weather_window() — rate a date as safe/unsafe for outdoor maintenance
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MAX_FORECAST_DAYS = 16

# ── Crew and shift config ──
SHIFT_HOURS = 8  # hours per shift
AVAILABLE_CREWS = 3  # max parallel crews
MAX_DAILY_CAPACITY = AVAILABLE_CREWS * SHIFT_HOURS  # 24h


def auto_schedule(
    plan: list[dict],
    *,
    start_date: Optional[date] = None,
    max_days: int = 90,
    crew_limit: int = AVAILABLE_CREWS,
    top_n: Optional[int] = None,
) -> list[dict]:
    """Greedy auto-scheduler.

    Only schedules the top_n most urgent items (default: top 30).
    Enforces hard capacity: if a day is full, the task moves to the next day.
    Items that cannot fit within their RUL window are marked as `overflow`.
    """
    today = start_date or date.today()
    deadline = today + timedelta(days=max_days)
    capacity = crew_limit * SHIFT_HOURS

    # Take only top urgent items
    items = sorted(plan, key=lambda t: (
        0 if t["priority"] == "urgent" else 1 if t["priority"] == "high" else 2,
        -t["urgency_score"],
    ))
    if top_n:
        items = items[:top_n]

    # Daily capacity tracking
    daily_state: dict[str, dict] = {}

    def _key(d: date) -> str:
        return d.isoformat()

    def _can_schedule(d: date, item: dict) -> bool:
        if d > deadline:
            return False
        if item["priority"] not in ("urgent",) and d.weekday() >= 5:
            return False
        state = daily_state.get(_key(d))
        if not state:
            return True
        # Same turbine already on this day → block non-urgent
        if item["turbine_id"] in state["turbine_ids"] and item["priority"] != "urgent":
            return False
        # Hard capacity check — reject if over
        if state["crew_hours"] + item["downtime_hours"] > capacity:
            return False
        return True

    def _assign(d: date, item: dict):
        s = daily_state.setdefault(_key(d), {"turbine_ids": set(), "crew_hours": 0.0})
        s["turbine_ids"].add(item["turbine_id"])
        s["crew_hours"] += item["downtime_hours"]

    overflow_items = []
    for item in items:
        item_deadline = today + timedelta(days=max(1, int(item["rul_days"] * 0.7)))
        assigned = False

        cursor = today
        while cursor <= min(item_deadline, deadline):
            if _can_schedule(cursor, item):
                item["scheduled_date"] = cursor.isoformat()
                item["time_slot"] = _time_slot_for(cursor, item, daily_state)
                _assign(cursor, item)
                assigned = True
                break
            cursor += timedelta(days=1)

        if not assigned:
            item["scheduled_date"] = None
            item["time_slot"] = None
            item["overflow"] = True
            item["overflow_reason"] = f"无法在{item['rul_days']:.0f}天RUL窗口内安排，每日容量{capacity}h已满"
            overflow_items.append(item)

    # Return only scheduled items, plus overflow items at the end
    scheduled = [t for t in items if not t.get("overflow")]
    scheduled.sort(key=lambda t: t.get("scheduled_date", "9999"))
    return scheduled + overflow_items


def _time_slot_for(d: date, item: dict, daily_state: dict) -> str:
    """Determine morning/afternoon slot based on existing bookings."""
    key = d.isoformat()
    existing = daily_state.get(key, {}).get("crew_hours", 0)
    if existing < SHIFT_HOURS:
        return "08:00-12:00"
    elif existing < SHIFT_HOURS * 2:
        return "13:00-17:00"
    else:
        return "17:00+"


def detect_conflicts(scheduled: list[dict]) -> list[dict]:
    """Detect scheduling conflicts in a plan.

    Returns list of conflict descriptions.
    """
    conflicts: list[dict] = []

    # Index by date
    by_date: dict[str, list[dict]] = {}
    for item in scheduled:
        sd = item.get("scheduled_date", "")
        if sd:
            by_date.setdefault(sd, []).append(item)

    for sd, items in by_date.items():
        # Same turbine multiple tasks on same day
        turbine_counts: dict[int, list[dict]] = {}
        for item in items:
            turbine_counts.setdefault(item["turbine_id"], []).append(item)
        for tid, group in turbine_counts.items():
            if len(group) > 1:
                conflicts.append({
                    "date": sd,
                    "type": "same_turbine",
                    "severity": "warning",
                    "message": f"风机 {group[0]['turbine_name']} 同日排了{len(group)}项维修",
                    "items": [g["component"] for g in group],
                    "suggestion": "建议合并为一个停机窗口",
                })

        # Crew overload
        total_hours = sum(it.get("downtime_hours", 0) for it in items)
        total_crew = sum(it.get("crew_size", 0) for it in items)
        if total_hours > AVAILABLE_CREWS * SHIFT_HOURS:
            conflicts.append({
                "date": sd,
                "type": "crew_overload",
                "severity": "error",
                "message": f"{sd} 总工时 {total_hours}h 超出容量 ({AVAILABLE_CREWS * SHIFT_HOURS}h)",
                "suggestion": f"建议将部分任务分流至前后日期，或增加临时班组",
            })
        elif total_crew > AVAILABLE_CREWS * 4:
            conflicts.append({
                "date": sd,
                "type": "crew_high",
                "severity": "warning",
                "message": f"{sd} 需要 {total_crew} 人，接近班组上限",
                "suggestion": "考虑拆分到上下午或次日",
            })

        # RUL approaching without being scheduled
    for item in scheduled:
        if not item.get("scheduled_date"):
            conflicts.append({
                "date": None,
                "type": "unscheduled_urgent",
                "severity": "error" if item["priority"] == "urgent" else "warning",
                "message": f"{item['turbine_name']} {item['component']} (RUL {item['rul_days']:.0f}天) 未排程",
                "items": [item["component"]],
                "suggestion": "请尽快安排维修",
            })

    return conflicts


def _seasonal_fallback(d: date, lat: float) -> dict:
    """Seasonal approximation when forecast is unavailable."""
    month = d.month
    if month in (12, 1, 2):
        base_score, flags = 40, ["低温", "可能的冰雪"]
    elif month in (3, 4):
        base_score, flags = 65, (["风沙季"] if lat > 36 else [])
    elif month in (5, 6):
        base_score, flags = 80, (["偶有雷雨"] if month == 6 else [])
    elif month in (7, 8):
        base_score, flags = 70, ["高温", "可能有雷暴"]
    else:
        base_score, flags = 90, []
    variation = (d.day * 7 + month * 13) % 20 - 10
    score = max(0, min(100, base_score + variation))
    return {
        "date": d.isoformat(),
        "score": score,
        "safe": score >= 50,
        "flags": flags,
        "source": "seasonal_model",
    }


async def _fetch_open_meteo_forecast(lat: float, lng: float) -> dict[str, dict]:
    """Fetch daily forecast from Open-Meteo API. Returns {date_str: weather_data}."""
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": "wind_speed_10m_max,wind_gusts_10m_max,temperature_2m_max,precipitation_sum",
        "wind_speed_unit": "ms",
        "timezone": "Asia/Shanghai",
        "forecast_days": MAX_FORECAST_DAYS,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(OPEN_METEO_FORECAST_URL, params=params)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("Open-Meteo forecast lookup failed: %s", exc)
        return {}

    payload = response.json()
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        return {}

    dates = daily.get("time") or []
    wind_max = daily.get("wind_speed_10m_max") or []
    gusts_max = daily.get("wind_gusts_10m_max") or []
    precip = daily.get("precipitation_sum") or []
    temp_max = daily.get("temperature_2m_max") or []

    forecast: dict[str, dict] = {}
    for i, d_str in enumerate(dates):
        w = _safe_get(wind_max, i)
        g = _safe_get(gusts_max, i)
        p = _safe_get(precip, i)
        t = _safe_get(temp_max, i)
        forecast[d_str] = {
            "wind_speed_max_ms": w,
            "wind_gusts_max_ms": g,
            "precipitation_mm": p,
            "temperature_max_c": t,
        }
    return forecast


def _safe_get(lst: list, idx: int) -> float | None:
    try:
        return float(lst[idx]) if lst[idx] is not None else None
    except (IndexError, TypeError, ValueError):
        return None


def _score_from_forecast(fc: dict | None) -> dict:
    """Convert forecast data to a weather safety score (0-100)."""
    if not fc:
        return {"score": 50, "safe": True, "flags": ["无预报数据"], "source": "no_data"}

    score = 100
    flags: list[str] = []
    w = fc.get("wind_speed_max_ms")
    g = fc.get("wind_gusts_max_ms")
    p = fc.get("precipitation_mm")
    t = fc.get("temperature_max_c")

    # Wind > 15 m/s → unsafe for outdoor turbine work
    if w is not None and w > 15:
        score -= 40
        flags.append(f"强风 {w:.0f}m/s")
    elif w is not None and w > 10:
        score -= 15
        flags.append(f"大风 {w:.0f}m/s")
    # Gusts > 20 m/s → dangerous
    if g is not None and g > 20:
        score -= 30
        flags.append(f"阵风 {g:.0f}m/s")
    # Precipitation > 5mm → rain/snow interruption
    if p is not None and p > 5:
        score -= 25
        flags.append(f"降雨 {p:.0f}mm")
    elif p is not None and p > 1:
        score -= 10
        flags.append(f"小雨 {p:.0f}mm")
    # Extreme cold or heat
    if t is not None and t < -10:
        score -= 20
        flags.append(f"极寒 {t:.0f}°C")
    elif t is not None and t > 38:
        score -= 15
        flags.append(f"高温 {t:.0f}°C")

    score = max(0, min(100, score))
    return {
        "score": score,
        "safe": score >= 50,
        "flags": flags,
        "source": "open_meteo_forecast",
    }


async def get_weather_for_dates(
    dates: list[date],
    lat: float = 37.3,
    lng: float = 107.6,
) -> list[dict]:
    """Get weather safety windows for outdoor maintenance.

    Uses Open-Meteo daily forecast (up to 16 days ahead).
    Falls back to seasonal model for dates beyond forecast range.
    """
    if not dates:
        return []

    forecast = await _fetch_open_meteo_forecast(lat, lng)
    results: list[dict] = []
    for d in dates:
        d_str = d.isoformat()
        fc = forecast.get(d_str)
        if fc is not None:
            item = _score_from_forecast(fc)
        else:
            item = _seasonal_fallback(d, lat)
        item["date"] = d_str
        item["lat"] = lat
        item["lng"] = lng
        results.append(item)
    return results


def generate_ics(scheduled: list[dict], title: str = "风电运维计划") -> str:
    """Generate iCalendar (.ics) content from scheduled maintenance tasks.

    Args:
        scheduled: List of tasks with scheduled_date, time_slot, turbine_name, etc.
        title: Calendar name

    Returns:
        ICS file content as string
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//FengDiao PHM//Maintenance Scheduler//CN",
        f"X-WR-CALNAME:{title}",
        "X-WR-CALDESC:风调预顺 PHM 系统自动生成运维计划",
        "X-WR-TIMEZONE:Asia/Shanghai",
    ]

    for item in scheduled:
        if not item.get("scheduled_date"):
            continue

        sd = item["scheduled_date"]
        slot = item.get("time_slot", "08:00-12:00")
        start_hour = 8 if "08" in slot else 13 if "13" in slot else 17
        end_hour = start_hour + min(4, item.get("downtime_hours", 4))

        dt_start = f"{sd}T{start_hour:02d}:00:00"
        dt_end = f"{sd}T{end_hour:02d}:00:00"
        uid = f"fengdiao-{item['turbine_id']}-{item['component']}-{sd}@phm"
        summary = f"[{'急' if item['priority']=='urgent' else '高' if item['priority']=='high' else '中'}] {item['turbine_name']} {item['component']}: {item['action']}"
        description = (
            f"风机: {item['turbine_name']} ({item.get('region', '')})\\n"
            f"部件: {item['component']}\\n"
            f"RUL: {item['rul_days']:.0f}天\\n"
            f"措施: {item['action']}\\n"
            f"预估费用: ¥{item['cost_estimate']:,.0f}\\n"
            f"备件: {', '.join(item['parts_needed'][:3])}\\n"
            f"人员: {item['crew_size']}人\\n"
        )

        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTART:{dt_start}",
            f"DTEND:{dt_end}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            f"LOCATION:{item.get('region', '')} {item['turbine_name']}",
            "END:VEVENT",
        ])

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
