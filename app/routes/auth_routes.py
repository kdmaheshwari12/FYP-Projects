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

from fastapi import APIRouter, HTTPException, status, Depends, Response
from fastapi.responses import JSONResponse
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
from app.core.validation import (
    validate_email,
    validate_password,
    validate_name,
    ValidationError,
    ValidationErrorResponse,
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


from jose import JWTError, ExpiredSignatureError

async def get_current_user_obj(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency that verifies the backend JWT and returns the
    MongoDB user document with ``_id`` converted to a string.
    """
    token = credentials.credentials

    try:
        payload = decode_access_token(token)
        email: str = payload.get("sub")
        if not email:
            raise JWTError("Missing 'sub' claim")

        user = await users_col.find_one({"email": email})
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        # Convert ObjectId → string
        user["_id"] = str(user["_id"])
        return user

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )


# --------------------------------------------------------------------------
# POST /auth/signup (alias for /register) — register a new user
# --------------------------------------------------------------------------
@router.post("/signup")
@router.post("/register")
async def register(user_data: UserSignup):
    """
    Register a new user with email, name, and password.
    """
    request_id = f"REG-{id(user_data)}"
    logger.info(f"[{request_id}] 📝 Signup attempt | Email: {user_data.email} | Role: {user_data.role}")
    
    try:
        errors = []
        
        # ========== VALIDATION ==========
        try:
            validated_email = validate_email(user_data.email, "email")
            logger.debug(f"[{request_id}] Email validation PASSED")
        except ValidationError as e:
            errors.append(e)
            validated_email = None
        
        try:
            validated_name = validate_name(user_data.full_name, "full_name", allow_spaces=True)
            logger.debug(f"[{request_id}] Name validation PASSED")
        except ValidationError as e:
            errors.append(e)
            validated_name = None
        
        try:
            validated_password = validate_password(user_data.password, "password")
            logger.debug(f"[{request_id}] Password validation PASSED")
        except ValidationError as e:
            errors.append(e)
            validated_password = None
        
        # Return validation errors
        if errors:
            error_response = ValidationErrorResponse.from_errors(errors)
            for err in errors:
                logger.warning(f"[{request_id}] ❌ Validation error on '{err.field}': {err.message}")
            
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "message": "Validation failed",
                    "errors": error_response.dict()["errors"]
                }
            )
        
        # ========== CHECK DUPLICATE EMAIL ==========
        logger.debug(f"[{request_id}] Checking database for existing user...")
        existing_user = await get_user_by_email(validated_email)
        if existing_user:
            logger.warning(f"[{request_id}] ⚠️ Signup failed — email already registered: {validated_email}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "message": "Email already registered"
                }
            )
        
        # ========== CREATE USER ==========
        logger.info(f"[{request_id}] Hashing password and saving to database...")
        hashed_password = get_password_hash(validated_password)
        user = await create_user(
            email=validated_email,
            name=validated_name,
            hashed_password=hashed_password,
            role=user_data.role
        )
        
        # Issue JWT pair
        logger.debug(f"[{request_id}] Generating JWT tokens...")
        access_token = create_access_token(subject=user["email"], role=user.get("role", "user"))
        refresh_token = create_refresh_token(subject=user["email"])
        
        logger.info(f"[{request_id}] ✅ User registered successfully: {validated_email}")
        
        return {
            "success": True,
            "message": "User registered successfully",
            "token": access_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role", "user"),
            },
        }

    except Exception as e:
        logger.error(f"[{request_id}] 💥 CRITICAL ERROR in register: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": f"Server error during registration: {str(e)}"
            }
        )


# --------------------------------------------------------------------------
# POST /auth/login — login with email and password
# --------------------------------------------------------------------------
@router.post("/login")
async def login(credentials: UserLogin):
    """
    Login with email and password.
    """
    request_id = f"LOG-{id(credentials)}"
    logger.info(f"[{request_id}] 🔐 Login attempt | Email: {credentials.email}")
    
    try:
        # ========== VALIDATION ==========
        try:
            validated_email = validate_email(credentials.email, "email")
        except ValidationError as e:
            logger.warning(f"[{request_id}] ❌ Login email validation error: {e.message}")
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "success": False,
                    "message": e.message
                }
            )
        
        # ========== AUTHENTICATE ==========
        logger.debug(f"[{request_id}] Fetching user from database...")
        user = await get_user_by_email(validated_email)
        if not user:
            logger.warning(f"[{request_id}] ⚠️ Login failed — user not found: {validated_email}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "message": "Invalid email or password"
                }
            )

        # Verify password
        logger.debug(f"[{request_id}] Verifying password...")
        if not verify_password(credentials.password, user.get("hashed_password", "")):
            logger.warning(f"[{request_id}] ⚠️ Login failed — invalid password for: {validated_email}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "success": False,
                    "message": "Invalid email or password"
                }
            )

        # Check if user is active
        if not user.get("is_active", True):
            logger.warning(f"[{request_id}] ⚠️ Login failed — account deactivated: {validated_email}")
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "success": False,
                    "message": "Account is deactivated"
                }
            )

        # Update last login timestamp
        await update_last_login(validated_email)

        # Issue JWT pair
        logger.debug(f"[{request_id}] Generating JWT tokens...")
        user_role = user.get("role", "user")
        access_token = create_access_token(subject=validated_email, role=user_role)
        refresh_token = create_refresh_token(subject=validated_email)

        logger.info(f"[{request_id}] ✅ Login successful for {validated_email}")

        return {
            "success": True,
            "message": "Login successful",
            "token": access_token,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "user": {
                "id": user.get("id"),
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user_role,
            },
        }

    except Exception as e:
        logger.error(f"[{request_id}] 💥 CRITICAL ERROR in login: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "message": f"Server error during login: {str(e)}"
            }
        )


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
        "id": str(current_user.get("_id")),
        "email": current_user.get("email"),
        "full_name": current_user.get("name"),
        "role": current_user.get("role", "traveler"),
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