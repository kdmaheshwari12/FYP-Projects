# app/routes/auth_routes.py
"""
Email/Password Authentication Routes.

Flow:
1. User signs up with email, name, and password
2. User logs in with email and password → receives JWT pair
3. Frontend stores backend JWT
4. For subsequent requests, frontend sends backend JWT in Authorization header

Endpoints:
    POST /auth/signup       — Register a new user
    POST /auth/login        — Login with email and password
    POST /auth/refresh      — Exchange a refresh token for a new access token
    GET  /auth/me           — Get current authenticated user (protected)
    GET  /auth/admin/users  — Admin-only: list all users
"""

from fastapi import APIRouter, HTTPException, status, Depends
from app.services.user_service import (
    get_user_by_email,
    create_user,
    update_last_login,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    verify_password,
    get_password_hash,
)
from app.schemas.user_schema import (
    UserSignup,
    UserLogin,
    RefreshTokenRequest,
)
from app.middleware.auth_middleware import (
    get_current_user,
    get_current_active_user,
    require_admin,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import decode_access_token
from app.db.mongodb import users_collection as users_col
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# --------------------------------------------------------------------------
# Legacy dependency: used by trip_routes, broker_routes, review_routes,
# chat_routes.  Returns the raw MongoDB user document with _id as a string.
# --------------------------------------------------------------------------
_bearer = HTTPBearer()


async def get_current_user_obj(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency that verifies the backend JWT and returns the
    MongoDB user document with ``_id`` converted to a string.

    This is the "raw doc" variant used by legacy route files that
    reference ``current_user["_id"]`` directly.
    """
    token = credentials.credentials

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email: str = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await users_col.find_one({"email": email})
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Convert ObjectId → string so downstream code can use it safely
    user["_id"] = str(user["_id"])
    return user


# --------------------------------------------------------------------------
# POST /auth/signup — register a new user
# --------------------------------------------------------------------------
@router.post("/register")
async def register(user_data: UserSignup):
    """
    Register a new user with email, name, and password.

    Body:
        {
            "email": "user@example.com",
            "name": "John Doe",
            "password": "securepassword123"
        }
    """
    logger.info(f"📝 Signup attempt for email: {user_data.email}")

    # Check if user already exists
    existing_user = await get_user_by_email(user_data.email)
    if existing_user:
        logger.warning(f"⚠️ Signup failed — email already registered: {user_data.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash the password and create user
    hashed_password = get_password_hash(user_data.password)
    user = await create_user(
        email=user_data.email,
        name=user_data.full_name,
        hashed_password=hashed_password,
        role=user_data.role
    )

    # Issue JWT pair
    access_token = create_access_token(subject=user["email"], role=user.get("role", "user"))
    refresh_token = create_refresh_token(subject=user["email"])

    logger.info(f"✅ User registered successfully: {user_data.email}")

    return {
        "message": "User registered successfully",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": user.get("role", "user"),
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role", "user"),
        },
    }


# --------------------------------------------------------------------------
# POST /auth/login — login with email and password
# --------------------------------------------------------------------------
@router.post("/login")
async def login(credentials: UserLogin):
    """
    Login with email and password.

    Body:
        {
            "email": "user@example.com",
            "password": "securepassword123"
        }

    Returns:
        JWT access + refresh token pair and user data
    """
    logger.info(f"🔐 Login attempt for email: {credentials.email}")

    user = await get_user_by_email(credentials.email)
    if not user:
        logger.warning(f"⚠️ Login failed — user not found: {credentials.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Verify password
    if not verify_password(credentials.password, user.get("hashed_password", "")):
        logger.warning(f"⚠️ Login failed — invalid password for: {credentials.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Check if user is active
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated. Contact support.",
        )

    # Update last login timestamp
    await update_last_login(user["email"])

    # Issue JWT pair
    user_role = user.get("role", "user")
    access_token = create_access_token(subject=user["email"], role=user_role)
    refresh_token = create_refresh_token(subject=user["email"])

    logger.info(f"✅ Login successful for {credentials.email}")

    return {
        "message": "Login successful",
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "role": user_role,
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user_role,
        },
    }


# --------------------------------------------------------------------------
# POST /auth/refresh — exchange refresh token for new access token
# --------------------------------------------------------------------------
@router.post("/refresh")
async def refresh_access_token(body: RefreshTokenRequest):
    """
    Exchange a valid refresh token for a new access token.

    Body:
        { "refresh_token": "<REFRESH_TOKEN>" }

    Returns:
        { "access_token": "...", "token_type": "bearer" }
    """
    payload = decode_refresh_token(body.refresh_token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("sub")
    user = await get_user_by_email(email)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found. Please login again.",
        )

    user_role = user.get("role", "user")
    new_access_token = create_access_token(subject=email, role=user_role)

    logger.info(f"🔄 Access token refreshed for {email}")

    return {
        "access_token": new_access_token,
        "token_type": "bearer",
    }


# --------------------------------------------------------------------------
# GET /auth/me — protected route
# --------------------------------------------------------------------------
@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_active_user)):
    """
    Returns the currently authenticated user.

    The frontend sends:
        GET /auth/me
        Authorization: Bearer <BACKEND_JWT_TOKEN>
    """
    return {
        "message": "User retrieved successfully",
        "user": {
            "id": current_user.get("id"),
            "email": current_user.get("email"),
            "name": current_user.get("name"),
            "role": current_user.get("role", "user"),
        },
    }


# --------------------------------------------------------------------------
# GET /auth/admin/users — admin-only route
# --------------------------------------------------------------------------
@router.get("/admin/users")
async def list_users(current_user: dict = Depends(require_admin)):
    """
    Admin-only endpoint: list all users.
    Requires role='admin' in the JWT.
    """
    from app.database.mongodb import users_collection, serialize_doc

    cursor = users_collection().find({}).limit(100)
    users = []
    async for doc in cursor:
        safe = serialize_doc(doc)
        users.append({
            "id": safe.get("id"),
            "email": safe.get("email"),
            "name": safe.get("name"),
            "role": safe.get("role", "user"),
            "is_active": safe.get("is_active", True),
            "created_at": safe.get("created_at"),
        })

    return {"total": len(users), "users": users}