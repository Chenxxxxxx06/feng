import time

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Callable

from app.database import get_db
from app.models import User
from app.schemas import UserRegister, UserLogin, TokenResponse, UserResponse
from app.core.security import hash_password, verify_password, create_access_token, decode_token

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

# ── Role hierarchy (P0-03: server-side RBAC) ──
# Higher index = more privilege
ROLE_LEVEL: dict[str, int] = {
    "viewer": 0,
    "operator": 1,
    "technician": 1,
    "engineer": 2,
    "approver": 3,
    "admin": 4,
}


def require_role(min_role: str) -> Callable:
    """Factory: create a dependency that requires at least `min_role`.

    Usage:
        @router.post("/faults")
        async def create_fault(
            ...,
            user: User = Depends(require_role("engineer")),
        ):
    """
    async def _check(
        current_user: User = Depends(get_current_user),
    ) -> User:
        min_level = ROLE_LEVEL.get(min_role, 0)
        user_level = ROLE_LEVEL.get(current_user.role, 0)
        if user_level < min_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action requires at least role '{min_role}'",
            )
        return current_user
    return _check


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT token and return current user. Raises 401 if invalid."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exception
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        raise credentials_exception
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception
    # P0-04: inactive users cannot use the system
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )
    return user


# ── Simple in-process login rate limiting: 5 failures per username/IP → 5 min lock ──
_LOGIN_FAIL_MAX = 5
_LOGIN_LOCK_SECONDS = 300
_login_failures: dict[str, tuple[int, float]] = {}  # key -> (fail_count, last_fail_ts)


def _login_locked(key: str) -> bool:
    record = _login_failures.get(key)
    if not record:
        return False
    count, last_ts = record
    if count < _LOGIN_FAIL_MAX:
        return False
    if time.monotonic() - last_ts >= _LOGIN_LOCK_SECONDS:
        _login_failures.pop(key, None)
        return False
    return True


def _record_login_failure(key: str) -> None:
    count, _ = _login_failures.get(key, (0, 0.0))
    _login_failures[key] = (count + 1, time.monotonic())


# --- Public routes (no auth required) ---

@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.username == data.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already exists")
    # P0-02: public registration always creates viewer — role changes require admin
    user = User(
        username=data.username,
        email=data.email,
        password_hash=hash_password(data.password),
        role="viewer",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    keys = (f"user:{data.username}", f"ip:{client_ip}")
    if any(_login_locked(key) for key in keys):
        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts, please try again later",
        )
    result = await db.execute(select(User).where(User.username == data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        for key in keys:
            _record_login_failure(key)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")
    for key in keys:
        _login_failures.pop(key, None)
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token, user=UserResponse.model_validate(user))


# --- Protected routes (auth required) ---

@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    """Get current user info (requires valid token)."""
    return UserResponse.model_validate(current_user)
