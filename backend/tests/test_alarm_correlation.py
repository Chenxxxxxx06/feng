"""Tests for weighted graph alarm correlation service.

Covers: edge weight computation, Union-Find clustering, primary alarm
selection, compression ratio, empty/single input, and idempotency.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.services.alarm_correlation_service import (
    AlarmCorrelationService,
    AlarmNode,
    AlarmCluster,
    AlarmCorrelationResult,
)


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def make_alarm(
    alarm_id: int = 1,
    turbine_id: int = 1,
    component: str = "gearbox",
    alarm_type: str = "vibration_high",
    severity: str = "high",
    fired_at: datetime | None = None,
    value: float | None = None,
) -> dict:
    return {
        "id": alarm_id,
        "turbine_id": turbine_id,
        "component": component,
        "alarm_type": alarm_type,
        "severity": severity,
        "fired_at": (fired_at or NOW).isoformat(),
        "value": value,
        "source": "scada",
    }


# ── Edge weight tests ──


def test_time_proximity_same_time():
    svc = AlarmCorrelationService(window_minutes=60)
    a = AlarmNode(alarm_id=1, turbine_id=1, component="g", fired_at=NOW)
    b = AlarmNode(alarm_id=2, turbine_id=1, component="g", fired_at=NOW)
    w = svc._time_proximity(a, b)
    assert w == pytest.approx(1.0)


def test_time_proximity_30min_apart():
    svc = AlarmCorrelationService(window_minutes=60)
    a = AlarmNode(alarm_id=1, turbine_id=1, fired_at=NOW)
    b = AlarmNode(alarm_id=2, turbine_id=1, fired_at=NOW - timedelta(minutes=30))
    w = svc._time_proximity(a, b)
    # exp(-30/60) ≈ 0.6065
    assert 0.5 < w < 0.7


def test_time_proximity_beyond_window_returns_zero():
    svc = AlarmCorrelationService(window_minutes=60)
    a = AlarmNode(alarm_id=1, turbine_id=1, fired_at=NOW)
    b = AlarmNode(alarm_id=2, turbine_id=1, fired_at=NOW - timedelta(minutes=120))
    w = svc._time_proximity(a, b)
    assert w == 0.0


def test_same_component_weight_is_1():
    svc = AlarmCorrelationService()
    w = svc._component_proximity("gearbox", "gearbox")
    assert w == 1.0


def test_component_substring_match():
    svc = AlarmCorrelationService()
    w = svc._component_proximity("gearbox_bearing", "gearbox")
    assert w == 0.6


def test_different_component_weight_is_0():
    svc = AlarmCorrelationService()
    w = svc._component_proximity("gearbox", "blade")
    assert w == 0.0


def test_topology_same_group():
    svc = AlarmCorrelationService()
    w = svc._topology_proximity("gearbox_wear", "bearing_fault")
    # Both in "drivetrain" group
    assert w == 0.5


def test_causal_relationship():
    svc = AlarmCorrelationService()
    w = svc._causal_proximity("vibration_high", "bearing_wear")
    # Known causal: vibration_high → bearing_wear
    assert w == 0.3


# ── Clustering tests ──


@pytest.mark.asyncio
async def test_empty_input_returns_zero():
    svc = AlarmCorrelationService()
    result = await svc.correlate([])
    assert result.original_count == 0
    assert result.compressed_count == 0


@pytest.mark.asyncio
async def test_single_alarm_no_compression():
    svc = AlarmCorrelationService()
    alarms = [make_alarm(alarm_id=1)]
    result = await svc.correlate(alarms)
    assert result.original_count == 1
    assert result.compressed_count == 1
    assert result.compression_ratio == 0.0


@pytest.mark.asyncio
async def test_identical_alarms_merge():
    """Alarms with same turbine, component, type at same time should merge."""
    svc = AlarmCorrelationService(window_minutes=60, threshold=0.35)
    alarms = [
        make_alarm(alarm_id=1, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="high", fired_at=NOW),
        make_alarm(alarm_id=2, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="medium", fired_at=NOW),
    ]
    result = await svc.correlate(alarms)
    assert result.compressed_count == 1
    assert result.compression_ratio == 0.5  # 2→1, ratio = (2-1)/2


@pytest.mark.asyncio
async def test_different_components_dont_merge():
    """Alarms on different components at same turbine don't merge."""
    svc = AlarmCorrelationService(window_minutes=60, threshold=0.55)
    alarms = [
        make_alarm(alarm_id=1, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", fired_at=NOW),
        make_alarm(alarm_id=2, turbine_id=1, component="blade",
                   alarm_type="surface_damage", fired_at=NOW),
    ]
    result = await svc.correlate(alarms)
    # Different components + no causal link → should NOT merge
    # Edge weight: time(1.0*0.30) + turbine(1.0*0.20) = 0.50 < threshold 0.55
    assert result.compressed_count == 2


@pytest.mark.asyncio
async def test_primary_alarm_has_highest_severity():
    """Primary alarm in cluster should be the one with highest severity."""
    svc = AlarmCorrelationService(window_minutes=60, threshold=0.35)
    alarms = [
        make_alarm(alarm_id=1, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="low", fired_at=NOW),
        make_alarm(alarm_id=2, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="critical", fired_at=NOW),
        make_alarm(alarm_id=3, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="medium", fired_at=NOW),
    ]
    result = await svc.correlate(alarms)
    assert result.compressed_count == 1
    cluster = result.clusters[0]
    assert cluster.primary_alarm_id == 2  # critical severity


@pytest.mark.asyncio
async def test_filter_by_turbine():
    svc = AlarmCorrelationService()
    alarms = [
        make_alarm(alarm_id=1, turbine_id=1, component="gearbox"),
        make_alarm(alarm_id=2, turbine_id=2, component="blade"),
    ]
    result = await svc.correlate(alarms, turbine_id=1)
    assert result.original_count == 1


@pytest.mark.asyncio
async def test_repeat_correlation_is_idempotent():
    """Running correlation twice on same input produces same output."""
    svc = AlarmCorrelationService(window_minutes=60, threshold=0.35)
    alarms = [
        make_alarm(alarm_id=i, turbine_id=1, component="gearbox",
                   alarm_type="vibration_high", severity="high", fired_at=NOW)
        for i in range(10)
    ]
    r1 = await svc.correlate(alarms)
    r2 = await svc.correlate(alarms)
    assert r1.compressed_count == r2.compressed_count
    assert r1.compression_ratio == r2.compression_ratio


# ── Severity selection tests ──


def test_highest_severity():
    svc = AlarmCorrelationService()
    alarms = [
        {"severity": "low"},
        {"severity": "critical"},
        {"severity": "medium"},
    ]
    assert svc._highest_severity(alarms) == "critical"


def test_primary_selection_severity_then_recency():
    """Primary selection: severity × recency. Critical+recent beats high+old."""
    svc = AlarmCorrelationService()
    # Both in the past relative to real "now" inside _select_primary
    recent = datetime.now(timezone.utc) - timedelta(hours=1)
    old = datetime.now(timezone.utc) - timedelta(hours=48)
    nodes = [
        AlarmNode(alarm_id=1, turbine_id=1, severity="critical", fired_at=recent),
        AlarmNode(alarm_id=2, turbine_id=1, severity="high", fired_at=old),
    ]
    primary = svc._select_primary(nodes)
    # critical (weight 10) × recent → highest score
    assert primary.alarm_id == 1
    assert primary.severity == "critical"
