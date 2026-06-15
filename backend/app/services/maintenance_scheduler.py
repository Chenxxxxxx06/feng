"""Maintenance Scheduler — auto-scheduling, conflict detection, weather windows.

Key algorithms:
  1. auto_schedule() — greedy deadline-aware slot assignment
  2. detect_conflicts() — same-turbine, crew-overload, weather-unsafe detection
  3. weather_window() — rate a date as safe/unsafe for outdoor maintenance
     Uses Open-Meteo forecast API for days 1–16, seasonal model for days 17+.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Open-Meteo config ──
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_FORECAST_MAX_DAYS = 16  # free tier daily forecast horizon

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


# ── WMO weather-code → Chinese label ──
_WMO_LABELS: dict[int, str] = {
    0: "晴", 1: "大部晴", 2: "多云", 3: "阴",
    45: "雾", 48: "冰雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪",
    77: "雪粒",
    80: "阵雨", 81: "中阵雨", 82: "大阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷暴", 96: "冰雹雷暴", 99: "大冰雹雷暴",
}

# ── Weather codes that make outdoor turbine work dangerous ──
_UNSAFE_WEATHER_CODES = {55, 65, 66, 67, 75, 82, 86, 95, 96, 99}
_CAUTION_WEATHER_CODES = {51, 53, 61, 63, 71, 73, 80, 81, 85}


def _score_forecast_day(day_data: dict) -> tuple[int, list[str], bool]:
    """Score a single Open-Meteo daily forecast row for maintenance safety.

    Returns (score 0–100, flags list, safe boolean).
    """
    score = 100
    flags: list[str] = []

    wind_max = day_data.get("wind_speed_10m_max") or 0
    gust_max = day_data.get("wind_gusts_10m_max") or 0
    precip = day_data.get("precipitation_sum") or 0
    temp_max = day_data.get("temperature_2m_max")
    temp_min = day_data.get("temperature_2m_min")
    weather_code = day_data.get("weather_code") or 0

    # ── Wind (most critical for turbine work) ──
    max_wind = max(wind_max, gust_max)
    if max_wind > 15:
        score -= 50
        flags.append(f"强风 {max_wind:.0f}m/s")
    elif max_wind > 12:
        score -= 30
        flags.append(f"大风 {max_wind:.0f}m/s")
    elif max_wind > 8:
        score -= 10
        flags.append(f"微风 {max_wind:.0f}m/s")

    # ── Precipitation ──
    if precip > 20:
        score -= 40
        flags.append(f"暴雨 {precip:.0f}mm")
    elif precip > 10:
        score -= 25
        flags.append(f"大雨 {precip:.0f}mm")
    elif precip > 5:
        score -= 15
        flags.append(f"降雨 {precip:.0f}mm")
    elif precip > 1:
        score -= 5
        flags.append(f"小雨 {precip:.1f}mm")

    # ── Temperature extremes ──
    if temp_max is not None and temp_max > 38:
        score -= 15
        flags.append(f"高温 {temp_max:.0f}°C")
    elif temp_max is not None and temp_max > 35:
        score -= 8
        flags.append(f"炎热 {temp_max:.0f}°C")
    if temp_min is not None and temp_min < -15:
        score -= 20
        flags.append(f"严寒 {temp_min:.0f}°C")
    elif temp_min is not None and temp_min < -5:
        score -= 8
        flags.append(f"低温 {temp_min:.0f}°C")

    # ── Severe weather codes ──
    if weather_code in _UNSAFE_WEATHER_CODES:
        score -= 40
        flags.append(_WMO_LABELS.get(weather_code, f"恶劣天气"))
    elif weather_code in _CAUTION_WEATHER_CODES:
        score -= 10
        label = _WMO_LABELS.get(weather_code, "")
        if label and label not in flags:
            flags.append(label)

    score = max(0, min(100, score))
    safe = score >= 50
    return score, flags, safe


async def _fetch_open_meteo_forecast(
    lat: float, lng: float, days: int = 16
) -> dict[str, list]:
    """Fetch daily forecast from Open-Meteo API.

    Returns { "dates": [...], "rows": [{wind_speed_10m_max, ...}, ...] }
    or empty dict on failure.
    """
    params = {
        "latitude": lat,
        "longitude": lng,
        "daily": ",".join([
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_speed_10m_max",
            "wind_gusts_10m_max",
        ]),
        "wind_speed_unit": "ms",
        "timezone": "Asia/Shanghai",
        "forecast_days": min(days, OPEN_METEO_FORECAST_MAX_DAYS),
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(OPEN_METEO_FORECAST_URL, params=params)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("Open-Meteo forecast fetch failed: %s", exc)
        return {}

    body = resp.json()
    daily = body.get("daily")
    if not isinstance(daily, dict):
        return {}

    dates = daily.get("time") or []
    if not dates:
        return {}

    keys = [
        "weather_code", "temperature_2m_max", "temperature_2m_min",
        "precipitation_sum", "wind_speed_10m_max", "wind_gusts_10m_max",
    ]
    rows = []
    for i in range(len(dates)):
        row = {}
        for k in keys:
            arr = daily.get(k) or []
            row[k] = arr[i] if i < len(arr) else None
        rows.append(row)

    return {"dates": dates, "rows": rows, "lat": lat, "lng": lng}


def _seasonal_window(d: date, lat: float, lng: float) -> dict:
    """Fallback seasonal model for dates beyond the forecast horizon."""
    month = d.month
    day_of_month = d.day

    if month in (12, 1, 2):
        base_score = 40
        flags = ["低温", "可能的冰雪"]
    elif month in (3, 4):
        base_score = 65
        flags = ["风沙季"] if lat > 36 else []
    elif month in (5, 6):
        base_score = 80
        flags = ["偶有雷雨"] if month == 6 else []
    elif month in (7, 8):
        base_score = 70
        flags = ["高温", "可能有雷暴"]
    else:
        base_score = 90
        flags = []

    variation = (day_of_month * 7 + month * 13) % 20 - 10
    score = max(0, min(100, base_score + variation))

    return {
        "date": d.isoformat(),
        "score": score,
        "safe": score >= 50,
        "flags": flags,
        "lat": lat,
        "lng": lng,
        "source": "seasonal_model",
    }


async def get_weather_for_dates(
    dates: list[date],
    lat: float = 37.3,
    lng: float = 107.6,
) -> list[dict]:
    """Get weather windows for a list of dates at a given location.

    Uses Open-Meteo daily forecast for days within the free 16-day horizon,
    and the seasonal model for dates beyond that.
    """
    if not dates:
        return []

    today = date.today()
    horizon = today + timedelta(days=OPEN_METEO_FORECAST_MAX_DAYS - 1)

    forecast_dates = [d for d in dates if d <= horizon]
    seasonal_dates = [d for d in dates if d > horizon]

    windows: list[dict] = []

    # ── Real forecast for near-term dates ──
    if forecast_dates:
        fc = await _fetch_open_meteo_forecast(
            lat, lng, days=OPEN_METEO_FORECAST_MAX_DAYS
        )
        if fc and fc.get("dates"):
            fc_dates = fc["dates"]
            fc_rows = fc["rows"]
            fc_index: dict[str, dict] = {}
            for i, dstr in enumerate(fc_dates):
                if i < len(fc_rows):
                    fc_index[dstr] = fc_rows[i]

            for d in forecast_dates:
                dkey = d.isoformat()
                row = fc_index.get(dkey)
                if row:
                    score, flags, safe = _score_forecast_day(row)
                    windows.append({
                        "date": dkey,
                        "score": score,
                        "safe": safe,
                        "flags": flags,
                        "lat": lat,
                        "lng": lng,
                        "source": "open_meteo",
                    })
                else:
                    windows.append(_seasonal_window(d, lat, lng))
        else:
            # API failed — fall back to seasonal for all forecast dates
            for d in forecast_dates:
                windows.append(_seasonal_window(d, lat, lng))

    # ── Seasonal model for far-future dates ──
    for d in seasonal_dates:
        windows.append(_seasonal_window(d, lat, lng))

    # Sort by date
    windows.sort(key=lambda w: w["date"])
    return windows


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
