# app/middleware/auth_middleware.py
"""
Authentication middleware for protected routes.

Flow:
    1. /auth/login verifies email/password → returns backend JWT
    2. Frontend stores backend JWT
    3. For subsequent requests (e.g. /auth/me), frontend sends backend JWT
    4. This middleware verifies the backend JWT and loads the user

Role-based dependencies:
    - get_current_user          → any authenticated user
    - get_current_active_user   → any authenticated + active user
    - require_admin             → admin only
    - require_role("broker")    → specific role
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_access_token
from app.services.user_service import get_user_by_email
import logging

logger = logging.getLogger(__name__)

# Use HTTPBearer so Swagger UI shows the 🔒 lock icon and sends "Authorization: Bearer <token>"
security = HTTPBearer()


# --------------------------------------------------------------------------
# Base dependency: extract user from backend JWT
# --------------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency: extracts and verifies the backend JWT from the
    Authorization header, then loads the user from MongoDB.

    Raises HTTP 401 if the token is invalid/expired or the user doesn't exist.
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    if payload is None:
        logger.warning("⚠️ Backend JWT decode failed or expired")
        raise credentials_exception

    email: str = payload.get("sub")
    if email is None:
        logger.warning("⚠️ Backend JWT missing 'sub' claim")
        raise credentials_exception

    user = await get_user_by_email(email)
    if user is None:
        logger.warning(f"⚠️ User not found for email={email}")
        raise credentials_exception

    # Attach the role from the JWT payload (in case DB is slightly behind)
    user["_jwt_role"] = payload.get("role", "user")

    logger.debug(f"🔓 Authenticated user: {user.get('email')} (role={user.get('role')})")
    return user


# --------------------------------------------------------------------------
# Active-user dependency
# --------------------------------------------------------------------------
async def get_current_active_user(
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Raises 403 if the user account is deactivated."""
    if not current_user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )
    return current_user


# --------------------------------------------------------------------------
# Role-based dependencies
# --------------------------------------------------------------------------
def require_role(*allowed_roles: str):
    """
    Factory that returns a dependency requiring one of the given roles.

    Usage:
        @router.get("/admin/dashboard")
        async def dashboard(user = Depends(require_role("admin"))):
            ...
    """
    async def _role_checker(
        current_user: dict = Depends(get_current_active_user),
    ) -> dict:
        user_role = current_user.get("role", "user")
        if user_role not in allowed_roles:
            logger.warning(
                f"⚠️ Role denied: {current_user.get('email')} has role "
                f"'{user_role}', needs one of {allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {', '.join(allowed_roles)}",
            )
        return current_user

    return _role_checker


# Convenience shortcuts
require_admin = require_role("admin")
require_broker = require_role("broker", "admin")
