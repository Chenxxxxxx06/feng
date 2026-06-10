"""Personnel management API endpoints.

Provides CRUD operations for maintenance personnel.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import User
from app.schemas import PersonnelCreate, PersonnelUpdate, PersonnelResponse
from app.api.auth import get_current_user

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[PersonnelResponse])
async def list_personnel(
    region: str = None,
    db: AsyncSession = Depends(get_db),
):
    """List all personnel with optional region filter."""
    q = select(User).where(User.is_active == True)
    if region:
        q = q.where(User.role == "technician")  # Filter by role for now

    result = await db.execute(q)
    users = result.scalars().all()

    # Transform to personnel format
    personnel = []
    for user in users:
        personnel.append(PersonnelResponse(
            id=user.id,
            name=user.username,
            skills=["风机维护", "电气检修"],  # Default skills
            region="陕北",  # Default region
            load=0,  # TODO: Calculate from work orders
            email=user.email,
        ))

    return personnel


@router.post("/", response_model=PersonnelResponse, status_code=201)
async def create_personnel(
    data: PersonnelCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create new personnel (user with technician role)."""
    # Check if username exists
    existing = await db.execute(
        select(User).where(User.username == data.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")

    # Create user with technician role
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

    return PersonnelResponse(
        id=user.id,
        name=user.username,
        skills=data.skills,
        region=data.region,
        load=0,
        email=user.email,
    )


@router.put("/{personnel_id}", response_model=PersonnelResponse)
async def update_personnel(
    personnel_id: int,
    data: PersonnelUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update personnel information."""
    result = await db.execute(
        select(User).where(User.id == personnel_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Personnel not found")

    # Update user fields
    if data.name:
        user.username = data.name
    if data.email:
        user.email = data.email

    await db.commit()
    await db.refresh(user)

    return PersonnelResponse(
        id=user.id,
        name=user.username,
        skills=data.skills or ["风机维护"],
        region=data.region or "陕北",
        load=0,
        email=user.email,
    )


@router.delete("/{personnel_id}")
async def delete_personnel(
    personnel_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Deactivate personnel (soft delete)."""
    result = await db.execute(
        select(User).where(User.id == personnel_id)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Personnel not found")

    user.is_active = False
    await db.commit()

    return {"message": "Personnel deactivated successfully"}
