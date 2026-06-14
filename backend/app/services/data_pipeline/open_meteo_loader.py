"""Open-Meteo weather API access for turbine locations."""

from __future__ import annotations

from typing import Any

import httpx


OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


class OpenMeteoWeatherError(RuntimeError):
    """Raised when Open-Meteo cannot provide current weather data."""


class OpenMeteoWeatherLoader:
    async def get_current_weather(self, lat: float, lng: float) -> dict[str, Any]:
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
            async with httpx.AsyncClient(timeout=8.0) as client:
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
