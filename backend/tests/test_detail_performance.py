"""Regression tests for turbine-detail performance safeguards."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.api import ai as ai_api
from app.api.diagnosis import _downsample_series
from app.models import SCADARecord
from app.services.data_pipeline.open_meteo_loader import OpenMeteoWeatherLoader


@pytest.mark.asyncio
async def test_open_meteo_cache_coalesces_concurrent_requests(monkeypatch):
    loader = OpenMeteoWeatherLoader(cache_ttl_seconds=300)
    calls = 0

    async def fake_fetch(lat: float, lng: float):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {
            "wind_speed_ms": 7.2,
            "wind_gust_ms": 9.1,
            "wind_direction_deg": 120,
            "turbulence_intensity": None,
            "air_temperature_c": 18.5,
            "air_pressure_hpa": 921.0,
            "data_source": "open_meteo",
            "observed_at": "2026-07-29T12:00",
        }

    monkeypatch.setattr(loader, "_fetch_current_weather", fake_fetch)
    first, second = await asyncio.gather(
        loader.get_current_weather(37.325, 107.598),
        loader.get_current_weather(37.325, 107.598),
    )
    third = await loader.get_current_weather(37.325, 107.598)

    assert calls == 1
    assert first == second == third
    assert first is not second


def test_vibration_downsample_preserves_endpoints_and_limit():
    source = list(range(10_000))
    sampled = _downsample_series(source, 1024)

    assert len(sampled) == 1024
    assert sampled[0] == 0.0
    assert sampled[-1] == 9999.0
    assert sampled == sorted(sampled)


@pytest.mark.asyncio
async def test_scada_compact_response_respects_point_limit(
    client,
    auth_headers,
    db_session,
    test_turbine,
):
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db_session.add_all([
        SCADARecord(
            turbine_id=test_turbine.id,
            timestamp=base + timedelta(minutes=10 * index),
            power_kw=float(index),
            wind_speed_ms=6.5,
            ambient_temp_c=18.0,
            extra={
                "source_dataset": "care_to_compare_v6",
                "source_file": "large-import.csv",
                "source_row": index,
            },
        )
        for index in range(200)
    ])
    await db_session.commit()

    response = await client.get(
        f"/api/turbines/{test_turbine.id}/scada"
        "?hours=72&max_points=144&compact=true",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 144
    assert payload[0]["dataset_window"] == "historical_latest"
    assert payload[0]["source_dataset"] == "care_to_compare_v6"
    assert "source_file" not in payload[0]
    assert "source_row" not in payload[0]


@pytest.mark.asyncio
async def test_ai_summary_reuses_identical_result(
    client,
    auth_headers,
    monkeypatch,
):
    ai_api._summary_cache.clear()
    ai_api._summary_locks.clear()
    calls = 0

    def fake_summary(*args, **kwargs):
        nonlocal calls
        calls += 1
        return {
            "conclusions": ["风机运行状态稳定"],
            "suggestions": ["继续按计划巡检"],
        }

    monkeypatch.setattr(ai_api, "summarize_page", fake_summary)
    request = {"page_type": "turbine_detail", "page_data": {"hiValue": 95}}

    first = await client.post("/api/ai/summary", headers=auth_headers, json=request)
    second = await client.post("/api/ai/summary", headers=auth_headers, json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "success"
    assert second.json()["conclusions"] == first.json()["conclusions"]
    assert calls == 1


@pytest.mark.asyncio
async def test_ai_summary_returns_visible_local_fallback(
    client,
    auth_headers,
    monkeypatch,
):
    ai_api._summary_cache.clear()
    ai_api._summary_locks.clear()

    def unavailable_summary(*args, **kwargs):
        raise ValueError("API key not configured")

    monkeypatch.setattr(ai_api, "summarize_page", unavailable_summary)
    response = await client.post(
        "/api/ai/summary",
        headers=auth_headers,
        json={"page_type": "turbine_detail", "page_data": {"status": "normal"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "fallback"
    assert payload["conclusions"]
    assert payload["suggestions"]
    assert "summary_ai_failed_local_fallback" in payload["warnings"]
