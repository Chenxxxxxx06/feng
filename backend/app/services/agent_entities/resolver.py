"""Deterministic entity resolution for Agent task planning.

The Agent may use a model to understand the user's intent, but entity lookup is
kept in backend code so that fuzzy names resolve to real database rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Turbine, User, WorkOrder

T = TypeVar("T")


@dataclass
class EntityResolution(Generic[T]):
    entity: Optional[T]
    candidates: list[T]
    normalized_ref: Optional[str] = None
    reason: str = ""


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def normalize_turbine_ref(value: str | None) -> Optional[str]:
    """Normalize common turbine reference variants to names like YD-B-007."""
    if not value:
        return None
    text = str(value).strip().upper()
    text = re.sub(r"(号?风机|风机|机组|号)", "", text)
    match = re.search(r"([A-Z]{1,4})[-_\s]*([A-Z])[-_\s]*(\d{1,4})", text)
    if not match:
        return None
    prefix, group, number = match.groups()
    return f"{prefix}-{group}-{int(number):03d}"


def extract_turbine_ref(message: str) -> Optional[str]:
    """Extract and normalize the first turbine-like reference from text."""
    patterns = [
        r"([A-Za-z]{1,4}[-_\s]?[A-Za-z][-_]?\s*\d{1,4})\s*(?:号)?风机",
        r"(?<![A-Za-z0-9])([A-Za-z]{1,4}[-_\s]?[A-Za-z][-_]?\s*\d{1,4})(?![A-Za-z0-9])",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            normalized = normalize_turbine_ref(match.group(1))
            if normalized:
                return normalized
    return None


def _turbine_norm(turbine: Turbine) -> str:
    return _compact(normalize_turbine_ref(turbine.name) or turbine.name)


async def resolve_turbine_by_ref(db: AsyncSession, turbine_ref: str | None) -> EntityResolution[Turbine]:
    normalized = normalize_turbine_ref(turbine_ref) or (turbine_ref.strip().upper() if turbine_ref else None)
    if not normalized:
        return EntityResolution(entity=None, candidates=[], normalized_ref=None, reason="missing_turbine_ref")

    exact = await db.execute(
        select(Turbine).where(Turbine.name == normalized).order_by(Turbine.id.asc())
    )
    exact_matches = list(exact.scalars().all())
    if len(exact_matches) == 1:
        return EntityResolution(
            entity=exact_matches[0],
            candidates=exact_matches,
            normalized_ref=normalized,
            reason="exact",
        )
    if len(exact_matches) > 1:
        return EntityResolution(
            entity=None,
            candidates=exact_matches[:5],
            normalized_ref=normalized,
            reason="ambiguous",
        )

    all_result = await db.execute(select(Turbine).order_by(Turbine.name.asc()))
    turbines = list(all_result.scalars().all())
    target = _compact(normalized)
    normalized_matches = [item for item in turbines if _turbine_norm(item) == target]
    if len(normalized_matches) == 1:
        return EntityResolution(entity=normalized_matches[0], candidates=normalized_matches, normalized_ref=normalized, reason="normalized_exact")
    if len(normalized_matches) > 1:
        return EntityResolution(entity=None, candidates=normalized_matches[:5], normalized_ref=normalized, reason="ambiguous")

    fuzzy_matches = [
        item
        for item in turbines
        if target in _turbine_norm(item) or _turbine_norm(item) in target or normalized in item.name.upper()
    ][:5]
    if len(fuzzy_matches) == 1:
        return EntityResolution(entity=fuzzy_matches[0], candidates=fuzzy_matches, normalized_ref=normalized, reason="fuzzy")
    if fuzzy_matches:
        return EntityResolution(entity=None, candidates=fuzzy_matches, normalized_ref=normalized, reason="ambiguous")
    return EntityResolution(entity=None, candidates=[], normalized_ref=normalized, reason="not_found")


async def resolve_personnel_by_name(db: AsyncSession, name: str | None) -> EntityResolution[User]:
    value = (name or "").strip()
    if not value:
        return EntityResolution(entity=None, candidates=[], normalized_ref=None, reason="missing_personnel_name")

    exact = await db.execute(
        select(User).where(
            User.is_active.is_(True),
            User.role == "technician",
            User.username == value,
        )
    )
    found = exact.scalar_one_or_none()
    if found:
        return EntityResolution(entity=found, candidates=[found], normalized_ref=value, reason="exact")

    fuzzy = await db.execute(
        select(User)
        .where(
            User.is_active.is_(True),
            User.role == "technician",
            or_(User.username.ilike(f"%{value}%"), User.email.ilike(f"%{value}%")),
        )
        .order_by(User.username.asc())
        .limit(5)
    )
    candidates = list(fuzzy.scalars().all())
    if len(candidates) == 1:
        return EntityResolution(entity=candidates[0], candidates=candidates, normalized_ref=value, reason="fuzzy")
    if candidates:
        return EntityResolution(entity=None, candidates=candidates, normalized_ref=value, reason="ambiguous")
    return EntityResolution(entity=None, candidates=[], normalized_ref=value, reason="not_found")


async def resolve_workorder_by_ref(db: AsyncSession, workorder_id: int | None) -> EntityResolution[WorkOrder]:
    if not workorder_id:
        return EntityResolution(entity=None, candidates=[], normalized_ref=None, reason="missing_workorder_ref")
    result = await db.execute(select(WorkOrder).where(WorkOrder.id == workorder_id))
    found = result.scalar_one_or_none()
    if found:
        return EntityResolution(entity=found, candidates=[found], normalized_ref=f"WO-{workorder_id:04d}", reason="exact")
    return EntityResolution(entity=None, candidates=[], normalized_ref=f"WO-{workorder_id:04d}", reason="not_found")
