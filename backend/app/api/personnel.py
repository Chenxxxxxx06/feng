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


async def _active_workorder_count(db: AsyncSession, assignee: str) -> int:
    result = await db.execute(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assignee == assignee,
            WorkOrder.status.notin_(["completed", "closed"]),
        )
    )
    return int(result.scalar_one())


async def _to_personnel_response(
    user: User,
    db: AsyncSession,
    skills: list[str] | None = None,
    region: str | None = None,
) -> PersonnelResponse:
    return PersonnelResponse(
        id=user.id,
        name=user.username,
        skills=skills or DEFAULT_SKILLS,
        region=region or DEFAULT_REGION,
        load=await _active_workorder_count(db, user.username),
        email=user.email,
    )


@router.get("/", response_model=list[PersonnelResponse])
async def list_personnel(
    region: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all personnel with optional region filter."""
    if region and region != DEFAULT_REGION:
        return []

    q = (
        select(User)
        .where(User.is_active == True, User.role == "technician")
        .order_by(User.username.asc())
    )

    result = await db.execute(q)
    users = result.scalars().all()

    personnel = []
    for user in users:
        personnel.append(await _to_personnel_response(user, db))

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
    db.add(user)
    await db.commit()
    await db.refresh(user)

    return await _to_personnel_response(user, db, skills=data.skills, region=data.region)


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

    await db.commit()
    await db.refresh(user)

    return await _to_personnel_response(
        user,
        db,
        skills=data.skills,
        region=data.region,
    )


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
