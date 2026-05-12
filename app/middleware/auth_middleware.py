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
from jose import JWTError, ExpiredSignatureError

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """
    FastAPI dependency: extracts and verifies the backend JWT from the
    Authorization header, then loads the user from MongoDB.

    Raises HTTP 401 with specific detail if the token is expired.
    """
    token = credentials.credentials

    try:
        payload = decode_access_token(token)
        email: str = payload.get("sub")
        if email is None:
            raise JWTError("Missing 'sub' claim")
            
        user = await get_user_by_email(email)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Attach the role from the JWT payload
        user["_jwt_role"] = payload.get("role", "user")
        if "role" not in user:
            user["role"] = user["_jwt_role"]
        
        # Internal compatibility: ensure _id exists (get_user_by_email returns 'id')
        if "_id" not in user and "id" in user:
            user["_id"] = user["id"]
            
        return user

    except ExpiredSignatureError:
        logger.warning("⚠️ Token expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        logger.warning(f"⚠️ Token invalid: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


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
require_traveler = require_role("traveler", "admin")
