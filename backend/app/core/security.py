"""Security module for authentication and authorization.

Provides:
- Password hashing (bcrypt)
- JWT token creation and validation
- OAuth2 password bearer scheme
- API Key 静态加密（转发自 app.core.crypto，导入本模块即完成透明加密列挂载）
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings

# 导入即触发 API Key 透明加密列的挂载（写时加密 / 读时解密 / 明文向后兼容）。
# app.core.security 被 app.api.auth 引用，而几乎所有路由都依赖 auth，
# 因此挂载必然发生在任何 SQL 语句编译之前。
from app.core.crypto import (  # noqa: F401
    crypto_backend,
    decrypt_secret,
    encrypt_secret,
    install_encrypted_columns,
    is_encrypted,
    key_source,
    mark_secret_for_upgrade,
    mask_secret,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Hash a password using bcrypt.

    Args:
        password: Plain text password

    Returns:
        Hashed password string
    """
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against its hash.

    Args:
        plain: Plain text password
        hashed: Hashed password from database

    Returns:
        True if password matches, False otherwise
    """
    return pwd_context.verify(plain, hashed)


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create a JWT access token.

    Args:
        data: Payload data to encode (must include 'sub' key)
        expires_delta: Token expiration time (default: from settings)

    Returns:
        Encoded JWT token string
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )


def decode_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded payload dict if valid, None if invalid
    """
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
    except JWTError as e:
        logger.debug(f"Token decode failed: {e}")
        return None
