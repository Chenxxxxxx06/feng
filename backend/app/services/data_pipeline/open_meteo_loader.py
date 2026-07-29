"""Open-Meteo weather API access for turbine locations."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoWeatherError(RuntimeError):
    """Raised when Open-Meteo cannot provide current weather data."""


class OpenMeteoWeatherLoader:
    """Fetch current weather with a short in-process cache.

    Turbine detail pages are opened repeatedly during monitoring. Open-Meteo
    observations change much more slowly than those navigations, so avoiding a
    new external request for every page load makes the panel responsive and
    also protects the upstream service from request bursts.
    """

    def __init__(self, cache_ttl_seconds: float = 300.0) -> None:
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[tuple[float, float], tuple[float, dict[str, Any]]] = {}
        self._locks: dict[tuple[float, float], asyncio.Lock] = {}

    @staticmethod
    def _cache_key(lat: float, lng: float) -> tuple[float, float]:
        # Four decimal places are about 11 metres and are more precise than the
        # weather grid while still coalescing duplicate coordinates.
        return round(float(lat), 4), round(float(lng), 4)

    def clear_cache(self) -> None:
        """Clear cached observations (primarily useful for tests/maintenance)."""
        self._cache.clear()

    async def get_current_weather(self, lat: float, lng: float) -> dict[str, Any]:
        key = self._cache_key(lat, lng)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_ttl_seconds:
            return dict(cached[1])

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # A concurrent request may have populated the cache while this
            # caller was waiting for the per-location lock.
            now = time.monotonic()
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.cache_ttl_seconds:
                return dict(cached[1])

            try:
                weather = await self._fetch_current_weather(lat, lng)
            except OpenMeteoWeatherError:
                # Serving an expired real observation is preferable to making
                # an already-rendered monitoring panel disappear during a
                # transient upstream outage.
                if cached:
                    return dict(cached[1])
                raise

            self._cache[key] = (time.monotonic(), weather)
            return dict(weather)

    async def _fetch_current_weather(self, lat: float, lng: float) -> dict[str, Any]:
        params = {
            "latitude": lat,
            "longitude": lng,
            "current": ",".join(
                [
                    "temperature_2m",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                    "surface_pressure",
                ]
            ),
            "wind_speed_unit": "ms",
            "timezone": "Asia/Shanghai",
        }

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
                response = await client.get(OPEN_METEO_FORECAST_URL, params=params)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OpenMeteoWeatherError("Open-Meteo weather lookup failed.") from exc

        payload = response.json()
        current = payload.get("current")
        if not isinstance(current, dict):
            raise OpenMeteoWeatherError("Open-Meteo response did not include current weather.")

        return {
            "wind_speed_ms": current.get("wind_speed_10m"),
            "wind_gust_ms": current.get("wind_gusts_10m"),
            "wind_direction_deg": current.get("wind_direction_10m"),
            "turbulence_intensity": None,
            "air_temperature_c": current.get("temperature_2m"),
            "air_pressure_hpa": current.get("surface_pressure"),
            "data_source": "open_meteo",
            "observed_at": current.get("time"),
        }


open_meteo_loader = OpenMeteoWeatherLoader()
