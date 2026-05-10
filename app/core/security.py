# app/core/security.py
"""
JWT token utilities and password hashing for email/password authentication.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# --------------------------------------------------------------------------
# Access Token
# --------------------------------------------------------------------------
def create_access_token(
    subject: Union[str, Any],
    role: str = "user",
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a short-lived access token (default: 24 h)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    )
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "role": role,
        "type": "access",
    }
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    logger.debug(f"🔐 Access token created for sub={subject}, role={role}")
    return encoded_jwt


from jose import jwt, JWTError, ExpiredSignatureError

def decode_access_token(token: str) -> dict:
    """
    Decode and validate an access token.
    Raises ExpiredSignatureError if the token is expired.
    Raises JWTError for other validation failures.
    """
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "access":
            logger.warning("⚠️ Token is not an access token")
            raise JWTError("Invalid token type")
        return payload
    except ExpiredSignatureError:
        logger.warning("🕒 Access token has expired")
        raise
    except JWTError as e:
        logger.warning(f"⚠️ Access token decode failed: {e}")
        raise


# --------------------------------------------------------------------------
# Refresh Token
# --------------------------------------------------------------------------
def create_refresh_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a long-lived refresh token (default: 30 days)."""
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)
    )
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "type": "refresh",
    }
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_REFRESH_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    logger.debug(f"🔐 Refresh token created for sub={subject}")
    return encoded_jwt


def decode_refresh_token(token: str) -> Optional[dict]:
    """Decode and validate a refresh token. Returns None on any failure."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_REFRESH_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "refresh":
            logger.warning("⚠️ Token is not a refresh token")
            return None
        return payload
    except JWTError as e:
        logger.warning(f"⚠️ Refresh token decode failed: {e}")
        return None


# --------------------------------------------------------------------------
# Password helpers
# --------------------------------------------------------------------------
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)
