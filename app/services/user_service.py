# app/services/user_service.py
"""
User CRUD operations against the MongoDB `users` collection.
"""

from app.database.mongodb import users_collection, serialize_doc
from app.core.config import settings
from datetime import datetime, timezone
from bson import ObjectId
import logging

logger = logging.getLogger(__name__)


async def get_user_by_email(email: str):
    """Find a user by their email address."""
    user = await users_collection().find_one({"email": email})
    return serialize_doc(user)


async def get_user_by_id(user_id: str):
    """Find a user by their MongoDB _id."""
    user = await users_collection().find_one({"_id": ObjectId(user_id)})
    return serialize_doc(user)


async def create_user(email: str, name: str, hashed_password: str, role: str = settings.DEFAULT_USER_ROLE):
    """Create a new user with email, name, hashed password, and role."""
    now = datetime.now(timezone.utc)
    new_user = {
        "email": email,
        "name": name,
        "hashed_password": hashed_password,
        "role": role,
        "is_active": True,
        "last_login": now,
        "created_at": now,
        "updated_at": now,
    }

    result = await users_collection().insert_one(new_user)
    created_user = await users_collection().find_one({"_id": result.inserted_id})
    logger.info(f"👤 New user created: {email}")
    return serialize_doc(created_user)


async def update_user_profile(user_id: str, data: dict):
    """Update user profile fields."""
    data["updated_at"] = datetime.now(timezone.utc)
    await users_collection().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": data}
    )
    user = await users_collection().find_one({"_id": ObjectId(user_id)})
    return serialize_doc(user)


async def update_last_login(email: str):
    """Stamp last_login on every successful authentication."""
    await users_collection().update_one(
        {"email": email},
        {"$set": {"last_login": datetime.now(timezone.utc)}}
    )


async def set_user_role(user_id: str, role: str):
    """Admin utility: set a user's role."""
    valid_roles = {"user", "admin", "broker"}
    if role not in valid_roles:
        raise ValueError(f"Invalid role '{role}'. Must be one of {valid_roles}")

    await users_collection().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"role": role, "updated_at": datetime.now(timezone.utc)}}
    )
    user = await users_collection().find_one({"_id": ObjectId(user_id)})
    return serialize_doc(user)
