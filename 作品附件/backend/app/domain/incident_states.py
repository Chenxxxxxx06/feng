"""Incident state machine — pure domain logic.

Validates transitions and enforces stage rules without any database or HTTP
dependency. Used by both the API layer and the policy enforcement service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.domain import (
    IncidentStage,
    VALID_TRANSITIONS,
    can_transition,
)


@dataclass
class StageTransitionRequest:
    """Request to transition an incident to a new stage."""
    incident_id: str = ""
    from_stage: str = ""
    to_stage: str = ""
    requested_by: str = ""       # user_id or "system"
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class StageTransitionResult:
    """Result of a stage transition attempt."""
    allowed: bool = False
    from_stage: str = ""
    to_stage: str = ""
    blocked_by: list[str] = field(default_factory=list)  # Policy/evidence blocks
    requires_approval: bool = False
    message: str = ""


def validate_transition(request: StageTransitionRequest) -> StageTransitionResult:
    """Validate a stage transition against the state machine.

    Returns a StageTransitionResult indicating whether the transition is
    allowed by the state machine. Does NOT check policy rules — those are
    enforced by the policy enforcement service.
    """
    if not can_transition(request.from_stage, request.to_stage):
        valid_targets = VALID_TRANSITIONS.get(
            IncidentStage(request.from_stage), set()
        )
        return StageTransitionResult(
            allowed=False,
            from_stage=request.from_stage,
            to_stage=request.to_stage,
            blocked_by=[f"invalid_transition"],
            message=(
                f"Cannot transition from '{request.from_stage}' to "
                f"'{request.to_stage}'. Valid targets: "
                f"{[s.value for s in valid_targets]}"
            ),
        )

    return StageTransitionResult(
        allowed=True,
        from_stage=request.from_stage,
        to_stage=request.to_stage,
        message=f"Transition '{request.from_stage}' → '{request.to_stage}' is valid",
    )
