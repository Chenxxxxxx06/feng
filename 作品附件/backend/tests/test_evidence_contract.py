"""Tests for evidence contract domain logic.

Covers: evidence weight, freshness decay, conflict detection,
completeness scoring, and minimum diagnosis threshold.
"""
import pytest
from datetime import datetime, timedelta, timezone

from app.domain import (
    EvidenceContract,
    EvidenceCompletenessResult,
    EvidenceQuality,
    EvidenceType,
)
from app.domain.evidence_types import (
    SOURCE_RELIABILITY,
    check_evidence_completeness,
    compute_content_hash,
    detect_conflicts,
    evidence_weight,
    freshness_decay,
    source_reliability,
)


NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=timezone.utc)


def make_evidence(
    evidence_type: EvidenceType = EvidenceType.OBSERVATION,
    source_type: str = "scada",
    label: str = "vibration_rms",
    value: float = 7.5,
    confidence: float = 0.9,
    collected_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> EvidenceContract:
    return EvidenceContract(
        evidence_type=evidence_type,
        source_type=source_type,
        source_id="test_sensor_001",
        label=label,
        description=f"Test evidence: {label}",
        value=value,
        unit="mm/s",
        confidence=confidence,
        quality=EvidenceQuality.HIGH,
        collected_at=collected_at or NOW,
        expires_at=expires_at,
        content_hash=compute_content_hash({"value": value}),
        is_direct_observation=(evidence_type == EvidenceType.OBSERVATION),
    )


# ── Source reliability ──


def test_source_reliability_known():
    assert source_reliability("scada") == 0.90
    assert source_reliability("vibration") == 0.85
    assert source_reliability("llm") == 0.40
    assert source_reliability("human") == 0.85


def test_source_reliability_unknown_defaults_to_conservative():
    assert source_reliability("_made_up_source_") == 0.30


def test_source_reliability_case_insensitive():
    assert source_reliability("SCADA") == 0.90
    assert source_reliability("Llm") == 0.40


# ── Freshness decay ──


def test_freshness_fresh_is_one():
    decay = freshness_decay(NOW, now=NOW)
    assert decay == 1.0


def test_freshness_one_half_life():
    decay = freshness_decay(
        NOW - timedelta(hours=24), now=NOW, half_life_hours=24.0
    )
    assert decay == pytest.approx(0.5)


def test_freshness_expired_returns_zero():
    decay = freshness_decay(
        NOW,
        expires_at=NOW - timedelta(hours=1),
        now=NOW,
    )
    assert decay == 0.0


def test_freshness_not_yet_expired():
    decay = freshness_decay(
        NOW - timedelta(hours=23),
        expires_at=NOW + timedelta(hours=1),
        now=NOW,
    )
    assert decay > 0.0


# ── Evidence weight ──


def test_evidence_weight_combines_factors():
    ev = make_evidence(confidence=0.9)
    weight = evidence_weight(ev, now=NOW)
    # reliability(0.90) × freshness(1.0) × confidence(0.9) = 0.81
    assert weight == pytest.approx(0.81)


def test_evidence_weight_llm_low():
    ev = make_evidence(
        evidence_type=EvidenceType.LLM_HYPOTHESIS,
        source_type="llm",
        confidence=0.7,
    )
    weight = evidence_weight(ev, now=NOW)
    # reliability(0.40) × freshness(1.0) × confidence(0.7) = 0.28
    assert weight == pytest.approx(0.28)


# ── Conflict detection ──


def test_no_conflicts_when_values_close():
    ev1 = make_evidence(value=7.5)
    ev2 = make_evidence(value=7.8)
    conflicts = detect_conflicts([ev1, ev2])
    assert len(conflicts) == 0


def test_conflict_when_values_diverge():
    ev1 = make_evidence(value=7.5)
    ev2 = make_evidence(value=15.0)  # >50% relative diff
    conflicts = detect_conflicts([ev1, ev2])
    assert len(conflicts) == 1
    assert ev1.id in conflicts[0]
    assert ev2.id in conflicts[0]


def test_conflict_opposite_signs():
    ev1 = make_evidence(value=1.0)
    ev2 = make_evidence(value=-1.0)
    conflicts = detect_conflicts([ev1, ev2])
    assert len(conflicts) == 1


def test_no_conflict_different_variables():
    ev1 = make_evidence(label="vibration_rms", value=7.5)
    ev2 = make_evidence(label="temperature", value=90.0)
    conflicts = detect_conflicts([ev1, ev2])
    assert len(conflicts) == 0


# ── Evidence completeness ──


def test_completeness_all_required_satisfied():
    evidence = [
        make_evidence(EvidenceType.OBSERVATION, source_type="scada"),
        make_evidence(EvidenceType.MODEL_PREDICTION, source_type="model"),
        make_evidence(EvidenceType.RULE_INFERENCE, source_type="rule_engine"),
    ]
    result = check_evidence_completeness(evidence, now=NOW)
    assert result.completeness_ratio == 1.0
    assert result.can_confirm_diagnosis is True


def test_completeness_missing_observation_cannot_confirm():
    evidence = [
        make_evidence(EvidenceType.MODEL_PREDICTION, source_type="model"),
        make_evidence(EvidenceType.RULE_INFERENCE, source_type="rule_engine"),
    ]
    result = check_evidence_completeness(evidence, now=NOW)
    assert result.completeness_ratio < 1.0
    assert result.can_confirm_diagnosis is False
    assert "observation" in result.missing_evidence


def test_completeness_expired_blocks_confirmation():
    evidence = [
        make_evidence(EvidenceType.OBSERVATION, source_type="scada",
                      expires_at=NOW - timedelta(hours=1)),
        make_evidence(EvidenceType.MODEL_PREDICTION, source_type="model"),
        make_evidence(EvidenceType.RULE_INFERENCE, source_type="rule_engine"),
    ]
    result = check_evidence_completeness(evidence, now=NOW)
    assert result.can_confirm_diagnosis is False
    assert len(result.expired_evidence) >= 1


def test_completeness_conflict_blocks_confirmation():
    evidence = [
        make_evidence(EvidenceType.OBSERVATION, value=7.5),
        make_evidence(EvidenceType.OBSERVATION, value=30.0),  # conflicts
        make_evidence(EvidenceType.MODEL_PREDICTION),
        make_evidence(EvidenceType.RULE_INFERENCE),
    ]
    result = check_evidence_completeness(evidence, now=NOW)
    assert result.can_confirm_diagnosis is False
    assert len(result.conflicting_pairs) >= 1


def test_completeness_empty_evidence_list():
    result = check_evidence_completeness([], now=NOW)
    assert result.completeness_ratio == 0.0
    assert result.can_confirm_diagnosis is False
    assert len(result.missing_evidence) == 3


def test_completeness_only_llm_hypothesis_cannot_confirm():
    """LLM alone cannot confirm diagnosis — must have observation or model."""
    evidence = [
        make_evidence(EvidenceType.LLM_HYPOTHESIS, source_type="llm", confidence=0.95),
    ]
    result = check_evidence_completeness(evidence, now=NOW)
    assert result.can_confirm_diagnosis is False


# ── Minimum diagnosis threshold ──


def test_missing_critical_evidence_cannot_upgrade_to_confirmed(tmp_path):
    """Integration-style: missing required evidence → candidate diagnosis only."""
    evidence = [
        make_evidence(EvidenceType.OBSERVATION, source_type="scada", value=8.0),
        # MODEL_PREDICTION missing
        # RULE_INFERENCE missing
    ]
    result = check_evidence_completeness(evidence)
    assert result.can_confirm_diagnosis is False
    assert result.completeness_ratio < 1.0
