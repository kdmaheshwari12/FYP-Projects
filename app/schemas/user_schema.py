# app/schemas/user_schema.py
"""
Pydantic schemas for API request / response validation.
"""

from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


# --------------------------------------------------------------------------
# Auth Request Schemas
# --------------------------------------------------------------------------
class UserSignup(BaseModel):
    """Body for POST /auth/signup."""
    email: EmailStr
    name: str
    password: str


class UserLogin(BaseModel):
    """Body for POST /auth/login."""
    email: EmailStr
    password: str


# --------------------------------------------------------------------------
# User Response Schemas
# --------------------------------------------------------------------------
class UserResponse(BaseModel):
    id: str
    email: EmailStr
    name: str
    role: str = "user"
    is_active: bool = True
    last_login: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# --------------------------------------------------------------------------
# Token Schemas
# --------------------------------------------------------------------------
class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class TokenPair(BaseModel):
    """Returned on login — includes both access and refresh tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict


class RefreshTokenRequest(BaseModel):
    """Body for POST /auth/refresh."""
    refresh_token: str


# --------------------------------------------------------------------------
# Misc
# --------------------------------------------------------------------------
class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    user: Optional[dict] = None
