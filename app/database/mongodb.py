# app/database/mongodb.py
"""
MongoDB connection manager using Motor (async driver).
"""

from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings
from bson import ObjectId
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Database:
    client: AsyncIOMotorClient = None
    db = None


db = Database()


async def connect_to_mongo():
    logger.info("Connecting to MongoDB...")
    db.client = AsyncIOMotorClient(settings.MONGODB_URL)
    db.db = db.client[settings.DATABASE_NAME]
    # Verify connection
    try:
        await db.client.admin.command("ping")
        logger.info("✅ Connected to MongoDB!")
    except Exception as e:
        logger.error(f"❌ MongoDB connection failed: {e}")
        raise


async def close_mongo_connection():
    logger.info("Closing MongoDB connection...")
    db.client.close()
    logger.info("MongoDB connection closed!")


def get_database():
    return db.db


# Helper to get collections
def get_collection(name: str):
    return db.db[name]


# Collections
users_collection = lambda: get_collection("users")


# --------------------------------------------------------------------------
# Serialization helper — makes MongoDB docs safe for JSON responses
# --------------------------------------------------------------------------
def serialize_doc(doc: dict) -> dict:
    """
    Convert a raw MongoDB document into a JSON-safe dict.

    - Converts ObjectId fields to strings
    - Converts datetime fields to ISO format strings
    - Renames _id → id
    """
    if doc is None:
        return None

    serialized = {}
    for key, value in doc.items():
        if key == "_id":
            serialized["id"] = str(value)
        elif isinstance(value, ObjectId):
            serialized[key] = str(value)
        elif isinstance(value, datetime):
            serialized[key] = value.isoformat()
        else:
            serialized[key] = value

    return serialized
