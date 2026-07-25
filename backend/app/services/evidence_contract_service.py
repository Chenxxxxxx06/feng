"""Evidence contract service — typed evidence management with completeness scoring.

Provides the service-layer API for creating, querying, and evaluating
evidence contracts. Uses the domain layer for pure logic and the database
for persistence.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain import (
    EvidenceCompletenessResult,
    EvidenceContract,
    EvidenceQuality,
    EvidenceType,
)
from app.domain.evidence_types import (
    SOURCE_RELIABILITY,
    check_evidence_completeness,
    compute_content_hash,
    detect_conflicts,
    freshness_decay,
)
from app.models import EvidenceEdge, EvidenceNode, Incident

logger = logging.getLogger(__name__)


class EvidenceContractService:
    """Manages typed evidence for incident investigations.

    Ensures every piece of evidence has:
    - source type and source ID
    - collection time and expiry
    - unit and value
    - confidence/quality level
    - content hash
    - support/contradict relationships to hypotheses
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Evidence CRUD ──

    async def add_evidence(
        self,
        incident_id: str,
        evidence_type: EvidenceType,
        source_type: str,
        source_id: str,
        label: str,
        description: str = "",
        value: Optional[float] = None,
        unit: str = "",
        confidence: float = 0.5,
        quality: EvidenceQuality = EvidenceQuality.MEDIUM,
        is_direct_observation: bool = False,
        supports_hypothesis: list[str] | None = None,
        contradicts_hypothesis: list[str] | None = None,
        expires_in_hours: Optional[float] = None,
        props: dict | None = None,
    ) -> EvidenceContract:
        """Add a typed evidence item to an incident."""
        inc = await self._get_incident_int_id(incident_id)

        content = {
            "source_type": source_type,
            "source_id": source_id,
            "label": label,
            "value": value,
            "unit": unit,
            "confidence": confidence,
        }
        content_hash = compute_content_hash(content)

        now = datetime.now(timezone.utc)
        expires_at = None
        if expires_in_hours is not None:
            from datetime import timedelta
            expires_at = now + timedelta(hours=expires_in_hours)

        node = EvidenceNode(
            incident_id=inc,
            node_type=evidence_type.value,
            label=label,
            description=description,
            source=source_type,
            confidence=confidence,
            props={
                "source_id": source_id,
                "value": value,
                "unit": unit,
                "quality": quality.value,
                "is_direct_observation": is_direct_observation,
                "content_hash": content_hash,
                "collected_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
                "supports": supports_hypothesis or [],
                "contradicts": contradicts_hypothesis or [],
                **(props or {}),
            },
            created_at=now,
        )
        self.db.add(node)
        await self.db.flush()

        return EvidenceContract(
            id=str(node.id),
            incident_id=incident_id,
            evidence_type=evidence_type,
            source_type=source_type,
            source_id=source_id,
            label=label,
            description=description,
            value=value,
            unit=unit,
            confidence=confidence,
            quality=quality,
            collected_at=now,
            expires_at=expires_at,
            content_hash=content_hash,
            is_direct_observation=is_direct_observation,
            supports_hypothesis=supports_hypothesis or [],
            contradicts_hypothesis=contradicts_hypothesis or [],
        )

    async def get_evidence(self, incident_id: str) -> list[EvidenceContract]:
        """Get all evidence for an incident."""
        inc = await self._get_incident_int_id(incident_id)

        nodes = await self.db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.incident_id == inc)
            .order_by(EvidenceNode.created_at.desc())
        )
        node_list = nodes.scalars().all()

        return [
            EvidenceContract(
                id=str(n.id),
                incident_id=incident_id,
                evidence_type=self._parse_evidence_type(n.node_type),
                source_type=n.source or "unknown",
                source_id=(n.props or {}).get("source_id", str(n.id)),
                label=n.label,
                description=n.description or "",
                value=(n.props or {}).get("value"),
                unit=(n.props or {}).get("unit", ""),
                confidence=n.confidence or 0.5,
                quality=EvidenceQuality((n.props or {}).get("quality", "medium")),
                collected_at=n.created_at or datetime.now(timezone.utc),
                expires_at=self._parse_datetime((n.props or {}).get("expires_at")),
                content_hash=(n.props or {}).get("content_hash", ""),
                is_direct_observation=(n.props or {}).get("is_direct_observation", False),
                supports_hypothesis=(n.props or {}).get("supports", []),
                contradicts_hypothesis=(n.props or {}).get("contradicts", []),
                props=n.props or {},
            )
            for n in node_list
        ]

    async def add_edge(
        self,
        incident_id: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,  # supports / contradicts / requires_check / caused_by / resolved_by
        confidence: float = 0.5,
        evidence_ref: str = "",
    ) -> EvidenceEdge:
        """Add an edge between two evidence nodes."""
        inc = await self._get_incident_int_id(incident_id)

        edge = EvidenceEdge(
            incident_id=inc,
            source_node_id=int(source_node_id),
            target_node_id=int(target_node_id),
            edge_type=edge_type,
            source="rule",
            confidence=confidence,
            evidence_ref=evidence_ref,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(edge)
        await self.db.flush()
        return edge

    # ── Completeness evaluation ──

    async def evaluate_completeness(
        self,
        incident_id: str,
        required_types: list[EvidenceType] | None = None,
    ) -> EvidenceCompletenessResult:
        """Evaluate evidence completeness for an incident.

        Returns actionable result: can diagnosis be confirmed?
        If not, what evidence is missing/expired/conflicting?
        """
        evidence_list = await self.get_evidence(incident_id)
        return check_evidence_completeness(evidence_list, required_types)

    async def get_missing_evidence(self, incident_id: str) -> list[str]:
        """Get list of missing evidence types."""
        result = await self.evaluate_completeness(incident_id)
        return result.missing_evidence

    async def can_confirm_diagnosis(self, incident_id: str) -> bool:
        """Check if evidence is sufficient to confirm a diagnosis."""
        result = await self.evaluate_completeness(incident_id)
        return result.can_confirm_diagnosis

    async def detect_conflicts_for_incident(
        self, incident_id: str
    ) -> list[tuple[str, str]]:
        """Detect conflicting evidence pairs in this incident."""
        evidence_list = await self.get_evidence(incident_id)
        return detect_conflicts(evidence_list)

    # ── Helpers ──

    async def _get_incident_int_id(self, incident_id: str) -> int:
        """Convert incident_id string to integer primary key."""
        result = await self.db.execute(
            select(Incident.id).where(Incident.incident_id == incident_id)
        )
        inc_id = result.scalar_one_or_none()
        if inc_id is None:
            raise ValueError(f"Incident not found: {incident_id}")
        return inc_id

    @staticmethod
    def _parse_evidence_type(raw: str) -> EvidenceType:
        try:
            return EvidenceType(raw)
        except ValueError:
            return EvidenceType.OBSERVATION

    @staticmethod
    def _parse_datetime(raw: str | None) -> datetime | None:
        if raw is None:
            return None
        try:
            return datetime.fromisoformat(raw)
        except (ValueError, TypeError):
            return None
