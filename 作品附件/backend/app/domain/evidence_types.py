"""Evidence types — domain definitions for the evidence contract system.

No database or HTTP dependencies. Pure domain logic for evidence quality,
completeness scoring, freshness decay, and conflict detection.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.domain import (
    EvidenceContract,
    EvidenceCompletenessResult,
    EvidenceQuality,
    EvidenceType,
)

# ── Source reliability baseline weights ──
# Higher = more trustworthy. Normalized across sources in completeness scoring.
SOURCE_RELIABILITY: dict[str, float] = {
    "scada": 0.90,
    "vibration": 0.85,
    "oil_analysis": 0.80,
    "yolo": 0.75,
    "model": 0.70,
    "rule_engine": 0.75,
    "knowledge_base": 0.65,
    "llm": 0.40,
    "human": 0.85,
    "manual": 0.50,
    "unknown": 0.30,
}

# ── Required evidence types for diagnosis confirmation ──
# A confirmed diagnosis needs at least one piece of evidence from each
# of these categories (or an explicit exception).
REQUIRED_EVIDENCE_FOR_CONFIRMATION: list[EvidenceType] = [
    EvidenceType.OBSERVATION,       # At least one direct sensor reading
    EvidenceType.MODEL_PREDICTION,  # At least one model-based assessment
    EvidenceType.RULE_INFERENCE,    # At least one rule-based check
]


def compute_content_hash(data: dict | str) -> str:
    """SHA-256 hash of evidence content for audit trail."""
    if isinstance(data, dict):
        payload = json.dumps(data, sort_keys=True, default=str)
    else:
        payload = str(data)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def source_reliability(source_type: str) -> float:
    """Get baseline reliability weight for a source type.

    Returns 0.30 for unknown sources (conservative default).
    """
    return SOURCE_RELIABILITY.get(source_type.lower(), 0.30)


def freshness_decay(
    collected_at: datetime,
    expires_at: Optional[datetime] = None,
    now: Optional[datetime] = None,
    half_life_hours: float = 24.0,
) -> float:
    """Calculate freshness decay factor (0.0–1.0).

    1.0 = freshly collected.
    0.0 = fully expired (beyond expires_at or many half-lives old).

    Uses exponential decay: weight = 2^(-age/half_life).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    age_hours = (now - collected_at).total_seconds() / 3600.0

    if expires_at is not None and now > expires_at:
        return 0.0

    if age_hours <= 0:
        return 1.0

    return 2.0 ** (-age_hours / half_life_hours)


def evidence_weight(evidence: EvidenceContract, now: Optional[datetime] = None) -> float:
    """Composite evidence weight combining reliability and freshness.

    weight = source_reliability × freshness_decay × confidence
    """
    reliability = source_reliability(evidence.source_type)
    freshness = freshness_decay(evidence.collected_at, evidence.expires_at, now)
    return reliability * freshness * evidence.confidence


def detect_conflicts(
    evidence_list: list[EvidenceContract],
    time_window_hours: float = 1.0,
) -> list[tuple[str, str]]:
    """Detect conflicting evidence for the same variable within a time window.

    Two pieces of evidence conflict if:
    - They reference the same source_type and label (same variable)
    - Their values are incompatible (differ by >3σ or have opposite signs)
    - They were collected within the time window

    Returns list of (evidence_id_a, evidence_id_b) pairs.
    """
    conflicts: list[tuple[str, str]] = []

    for i, ev_a in enumerate(evidence_list):
        for ev_b in evidence_list[i + 1 :]:
            # Same variable?
            if ev_a.source_type != ev_b.source_type or ev_a.label != ev_b.label:
                continue
            # Within time window?
            time_diff = abs(
                (ev_a.collected_at - ev_b.collected_at).total_seconds() / 3600.0
            )
            if time_diff > time_window_hours:
                continue
            # Both have numeric values?
            if ev_a.value is None or ev_b.value is None:
                continue
            # Conflict: values differ by more than 50% relative or opposite signs
            if ev_a.value == 0 and ev_b.value == 0:
                continue
            if ev_a.value == 0 or ev_b.value == 0:
                if abs(ev_a.value - ev_b.value) > 1.0:
                    conflicts.append((ev_a.id, ev_b.id))
            else:
                relative_diff = abs(ev_a.value - ev_b.value) / max(
                    abs(ev_a.value), abs(ev_b.value)
                )
                if relative_diff >= 0.5:
                    conflicts.append((ev_a.id, ev_b.id))

    return conflicts


def check_evidence_completeness(
    evidence_list: list[EvidenceContract],
    required_types: list[EvidenceType] | None = None,
    now: Optional[datetime] = None,
) -> EvidenceCompletenessResult:
    """Check if evidence is complete enough for confirmed diagnosis.

    Computes:
    1. How many required evidence types are satisfied
    2. Whether any evidence has expired
    3. Whether there are conflicts
    4. Minimum confirmation threshold

    Returns EvidenceCompletenessResult with diagnosis recommendation.
    """
    if required_types is None:
        required_types = REQUIRED_EVIDENCE_FOR_CONFIRMATION

    if now is None:
        now = datetime.now(timezone.utc)

    # Count satisfied required types
    present_types = {e.evidence_type for e in evidence_list}
    satisfied = [t for t in required_types if t in present_types]
    missing = [t.value for t in required_types if t not in present_types]

    # Find expired evidence
    expired = [
        e.id
        for e in evidence_list
        if e.expires_at is not None and now > e.expires_at
    ]

    # Detect conflicts
    conflicts = detect_conflicts(evidence_list)

    # Calculate completeness ratio
    total_required = len(required_types)
    satisfied_count = len(satisfied)
    completeness = satisfied_count / total_required if total_required > 0 else 0.0

    # Minimum threshold: ALL required types must have at least one piece of evidence
    can_confirm = (
        completeness >= 1.0
        and len(expired) == 0
        and len(conflicts) == 0
    )

    recommendation = ""
    if not can_confirm:
        reasons = []
        if missing:
            reasons.append(f"Missing evidence types: {missing}")
        if expired:
            reasons.append(f"{len(expired)} evidence items expired")
        if conflicts:
            reasons.append(f"{len(conflicts)} conflicting evidence pairs detected")
        recommendation = (
            "Cannot confirm diagnosis. " + "; ".join(reasons) + "."
        )
    else:
        recommendation = "Evidence complete. Diagnosis can be confirmed."

    return EvidenceCompletenessResult(
        required_count=total_required,
        satisfied_count=satisfied_count,
        completeness_ratio=completeness,
        missing_evidence=missing,
        expired_evidence=expired,
        conflicting_pairs=conflicts,
        can_confirm_diagnosis=can_confirm,
        recommendation=recommendation,
    )
