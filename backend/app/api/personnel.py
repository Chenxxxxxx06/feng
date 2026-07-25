"""Personnel management API endpoints.

Provides CRUD operations for maintenance personnel.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, or_, select

from app.database import get_db
from app.models import User, WorkOrder
from app.schemas import PersonnelCreate, PersonnelUpdate, PersonnelResponse
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])

DEFAULT_REGION = "陕北"
DEFAULT_SKILLS = ["风机维护", "电气检修"]
PERSONNEL_PREF_KEY = "personnel_profile"


def _clean_skills(skills: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for skill in skills or []:
        value = skill.strip()
        if value and value not in cleaned:
            cleaned.append(value)
    return cleaned or DEFAULT_SKILLS


def _personnel_profile(user: User) -> tuple[list[str], str]:
    preferences = user.preferences if isinstance(user.preferences, dict) else {}
    profile = preferences.get(PERSONNEL_PREF_KEY) if isinstance(preferences, dict) else None
    if not isinstance(profile, dict):
        return DEFAULT_SKILLS, DEFAULT_REGION

    raw_skills = profile.get("skills")
    skills = _clean_skills(raw_skills if isinstance(raw_skills, list) else None)
    region = str(profile.get("region") or DEFAULT_REGION).strip() or DEFAULT_REGION
    return skills, region


def _set_personnel_profile(
    user: User,
    *,
    skills: list[str] | None = None,
    region: str | None = None,
) -> None:
    preferences = dict(user.preferences or {}) if isinstance(user.preferences, dict) else {}
    profile = dict(preferences.get(PERSONNEL_PREF_KEY) or {})
    if skills is not None:
        profile["skills"] = _clean_skills(skills)
    if region is not None:
        profile["region"] = region.strip() or DEFAULT_REGION
    preferences[PERSONNEL_PREF_KEY] = profile
    user.preferences = preferences


async def _active_workorder_count(db: AsyncSession, assignee: str) -> int:
    result = await db.execute(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assignee == assignee,
            WorkOrder.status.notin_(["completed", "closed"]),
            WorkOrder.deleted_at.is_(None),
        )
    )
    return int(result.scalar_one())


async def _to_personnel_response(
    user: User,
    db: AsyncSession,
) -> PersonnelResponse:
    skills, region = _personnel_profile(user)
    return PersonnelResponse(
        id=user.id,
        name=user.username,
        skills=skills,
        region=region,
        load=await _active_workorder_count(db, user.username),
        email=user.email,
    )


@router.get("/", response_model=list[PersonnelResponse])
async def list_personnel(
    region: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all personnel with optional region filter."""
    q = (
        select(User)
        .where(User.is_active == True, User.role == "technician")
        .order_by(User.username.asc())
    )

    result = await db.execute(q)
    users = result.scalars().all()

    personnel = []
    for user in users:
        item = await _to_personnel_response(user, db)
        if region and item.region != region:
            continue
        personnel.append(item)

    return personnel


@router.post("/", response_model=PersonnelResponse, status_code=201)
async def create_personnel(
    data: PersonnelCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create new personnel (user with technician role)."""
    existing = await db.execute(
        select(User).where(or_(User.username == data.name, User.email == data.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Personnel name or email already exists")

    from app.core.security import hash_password
    user = User(
        username=data.name,
        email=data.email,
        password_hash=hash_password("temp123"),  # Default password
        role="technician",
    )
    _set_personnel_profile(user, skills=data.skills, region=data.region)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return await _to_personnel_response(user, db)


@router.put("/{personnel_id}", response_model=PersonnelResponse)
async def update_personnel(
    personnel_id: int,
    data: PersonnelUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update personnel information."""
    result = await db.execute(
        select(User).where(User.id == personnel_id, User.role == "technician")
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Personnel not found")

    if data.name and data.name != user.username:
        existing = await db.execute(select(User).where(User.username == data.name))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Personnel name already exists")
        user.username = data.name

    if data.email and data.email != user.email:
        existing = await db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Email already exists")
        user.email = data.email

    if data.skills is not None or data.region is not None:
        current_skills, current_region = _personnel_profile(user)
        _set_personnel_profile(
            user,
            skills=data.skills if data.skills is not None else current_skills,
            region=data.region if data.region is not None else current_region,
        )

    await db.commit()
    await db.refresh(user)

    return await _to_personnel_response(user, db)


@router.delete("/{personnel_id}")
async def delete_personnel(
    personnel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate personnel (soft delete)."""
    result = await db.execute(
        select(User).where(User.id == personnel_id, User.role == "technician")
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Personnel not found")

    user.is_active = False
    await db.commit()

    return {"message": "Personnel deactivated successfully"}
