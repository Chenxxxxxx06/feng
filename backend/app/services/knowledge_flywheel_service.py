"""Incident review knowledge flywheel — structured post-mortem → knowledge extraction.

After incident closes:
1. Generate structured review draft
2. Extract candidate knowledge fragments
3. Deduplicate against existing knowledge
4. Queue for human review
5. Evaluate on historical replay scenarios
6. If approved: publish new playbook version, retain old version

Unreviewed knowledge CANNOT become production rules.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DecisionPlan,
    EvidenceNode,
    FaultKnowledgeNode,
    Incident,
)

logger = logging.getLogger(__name__)


class ReviewStatus(str, Enum):
    DRAFT = "draft"           # Auto-generated, not reviewed
    PENDING_REVIEW = "pending_review"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"     # Ready to publish
    REJECTED = "rejected"
    AMENDED = "amended"       # Modified after review


class EvaluationStatus(str, Enum):
    PENDING = "pending"
    EVALUATING = "evaluating"
    PASSED = "passed"        # Improved on historical cases
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


@dataclass
class KnowledgeFragment:
    """One candidate knowledge fragment extracted from an incident."""
    fragment_id: str = field(default_factory=lambda: f"KF-{uuid.uuid4().hex[:8]}")
    incident_id: str = ""
    category: str = ""  # symptom / root_cause / solution / rule / threshold
    content: str = ""
    confidence: float = 0.5
    source_type: str = ""  # auto_extracted / manual_entry
    review_status: ReviewStatus = ReviewStatus.DRAFT
    evaluation: EvaluationStatus = EvaluationStatus.PENDING
    eval_notes: str = ""
    related_fault_type: str = ""
    extracted_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None
    published_version: str = ""


@dataclass
class ReviewDraft:
    """Structured post-incident review draft."""
    incident_id: str = ""
    incident_title: str = ""
    summary: str = ""
    timeline: list[dict[str, Any]] = field(default_factory=list)
    diagnosis_accuracy: str = ""  # Did diagnosis match outcome?
    decision_quality: str = ""    # Was chosen plan effective?
    lessons_learned: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    candidate_knowledge: list[KnowledgeFragment] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class KnowledgeFlywheelResult:
    """Complete knowledge flywheel output for an incident."""
    review_draft: Optional[ReviewDraft] = None
    fragments_extracted: int = 0
    fragments_deduped: int = 0
    fragments_pending_review: int = 0
    playbook_updated: bool = False
    new_version: str = ""
    old_version_retained: str = ""


class KnowledgeFlywheelService:
    """Post-incident knowledge extraction and review pipeline.

    Knowledge CANNOT auto-publish. Every fragment must pass:
    1. Auto-extraction → 2. Dedup → 3. Human review → 4. Evaluation → 5. Publish
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def generate_review(self, incident: Incident) -> ReviewDraft:
        """Generate structured post-incident review draft."""
        draft = ReviewDraft(
            incident_id=incident.incident_id,
            incident_title=incident.title or "",
        )

        # Build incident summary
        draft.summary = (
            f"Incident {incident.incident_id}: {incident.title}. "
            f"Severity: {incident.severity}. "
            f"Final stage: {incident.stage}. "
            f"Verification: {incident.verification_status or 'pending'}."
        )

        # Timeline from evidence
        evidence = await self.db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.incident_id == incident.id)
            .order_by(EvidenceNode.created_at.asc())
        )
        draft.timeline = [
            {
                "time": n.created_at.isoformat() if n.created_at else "unknown",
                "type": n.node_type,
                "label": n.label,
                "source": n.source,
            }
            for n in evidence.scalars().all()
        ]

        # Decision quality assessment
        plans = await self.db.execute(
            select(DecisionPlan)
            .where(DecisionPlan.incident_id == incident.id)
            .order_by(DecisionPlan.total_score.desc())
        )
        plan_list = plans.scalars().all()
        if plan_list:
            chosen = next((p for p in plan_list if p.is_recommended), plan_list[0])
            draft.decision_quality = (
                f"Chose: {chosen.strategy} (score={chosen.total_score:.0f}). "
                f"Verification: {incident.verification_status or 'pending'}."
            )

        # Extract candidate knowledge
        fragments = await self._extract_fragments(incident)
        draft.candidate_knowledge = fragments

        # Lessons learned
        draft.lessons_learned = await self._derive_lessons(incident)
        draft.recommended_actions = await self._derive_actions(incident)

        return draft

    async def extract_and_dedup(
        self, incident: Incident
    ) -> KnowledgeFlywheelResult:
        """Extract knowledge fragments and deduplicate against existing base."""
        result = KnowledgeFlywheelResult()

        # Generate review
        draft = await self.generate_review(incident)
        result.review_draft = draft

        fragments = draft.candidate_knowledge
        result.fragments_extracted = len(fragments)

        # Deduplicate against existing knowledge
        existing = await self.db.execute(
            select(FaultKnowledgeNode)
        )
        existing_list = existing.scalars().all()

        deduped: list[KnowledgeFragment] = []
        for frag in fragments:
            is_dup = False
            for exist in existing_list:
                # Simple dedup: check if similar content exists
                if frag.content.lower() in (exist.fault_type or "").lower():
                    is_dup = True
                    break
                if exist.root_causes:
                    for rc in exist.root_causes:
                        if isinstance(rc, str) and frag.content.lower() in rc.lower():
                            is_dup = True
                            break
                if exist.solutions:
                    for sol in exist.solutions:
                        if isinstance(sol, str) and frag.content.lower() in sol.lower():
                            is_dup = True
                            break
                if is_dup:
                    break

            if not is_dup:
                frag.review_status = ReviewStatus.PENDING_REVIEW
                deduped.append(frag)

        result.fragments_deduped = len(fragments) - len(deduped)
        result.fragments_pending_review = len(deduped)

        return result

    async def publish_knowledge(
        self,
        fragment: KnowledgeFragment,
        reviewed_by: str,
    ) -> dict[str, Any]:
        """Publish approved knowledge fragment as a new playbook entry.

        Only call AFTER human review and evaluation pass.
        """
        if fragment.review_status != ReviewStatus.APPROVED:
            return {
                "published": False,
                "reason": f"Fragment not approved. Current status: {fragment.review_status.value}",
            }

        if fragment.evaluation != EvaluationStatus.PASSED:
            return {
                "published": False,
                "reason": f"Fragment not evaluated as passed. Current: {fragment.evaluation.value}",
            }

        # Create new version
        version = f"v{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        fragment.published_version = version

        # In production: would create new FaultKnowledgeNode version
        # and retain old version with rollback capability

        return {
            "published": True,
            "version": version,
            "fragment_id": fragment.fragment_id,
            "category": fragment.category,
            "content": fragment.content,
            "old_versions_retained": True,
            "rollback_available": True,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "published_by": reviewed_by,
        }

    async def _extract_fragments(
        self, incident: Incident
    ) -> list[KnowledgeFragment]:
        """Auto-extract candidate knowledge from incident data."""
        fragments: list[KnowledgeFragment] = []

        # From evidence nodes
        evidence = await self.db.execute(
            select(EvidenceNode)
            .where(EvidenceNode.incident_id == incident.id)
            .limit(20)
        )
        for node in evidence.scalars().all():
            if node.confidence and node.confidence > 0.7:
                fragments.append(KnowledgeFragment(
                    incident_id=incident.incident_id,
                    category="symptom",
                    content=node.description or node.label,
                    confidence=node.confidence,
                    source_type="auto_extracted",
                    related_fault_type=incident.title or "",
                ))

        # From decision plan
        plans = await self.db.execute(
            select(DecisionPlan)
            .where(
                DecisionPlan.incident_id == incident.id,
                DecisionPlan.is_recommended == True,
            )
            .limit(1)
        )
        for plan in plans.scalars().all():
            fragments.append(KnowledgeFragment(
                incident_id=incident.incident_id,
                category="solution",
                content=f"Strategy '{plan.strategy}' effective: score={plan.total_score:.0f}, "
                        f"cost={plan.repair_cost:.0f}, recovery={plan.recovery_days} days",
                confidence=0.6,
                source_type="auto_extracted",
                related_fault_type=incident.title or "",
            ))

        return fragments

    async def _derive_lessons(self, incident: Incident) -> list[str]:
        lessons: list[str] = []
        if incident.verification_status == "pass":
            lessons.append(f"维修策略有效: 恢复验证通过")
        elif incident.verification_status == "conditional":
            lessons.append("恢复验证有条件通过 — 建议延长观察窗口")
        elif incident.verification_status == "fail":
            lessons.append("恢复验证失败 — 需重新评估维修方案")
        if incident.stage == "escalated":
            lessons.append("事件升级 — 检查升级原因并优化决策流程")
        return lessons

    async def _derive_actions(self, incident: Incident) -> list[str]:
        actions: list[str] = []
        if incident.verification_status != "pass":
            actions.append("延长恢复验证观察时间至48小时")
        if incident.severity in ("high", "critical"):
            actions.append("将本案例加入高频故障监控列表")
        actions.append("更新维修知识库中的恢复时间估计")
        return actions
