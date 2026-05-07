# app/core/config.py
"""
Application settings.

All secrets and environment-specific values are read from environment
variables (with sensible defaults for local development).
"""

from pydantic_settings import BaseSettings
from typing import List
import os
from dotenv import load_dotenv

load_dotenv()


class Settings(BaseSettings):
    PROJECT_NAME: str = "Pakvel Backend"

    # ---------- MongoDB ----------
    MONGODB_URL: str = os.getenv("MONGODB_URL") or os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
    DATABASE_NAME: str = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME") or "pakvel"

    # ---------- JWT ----------
    JWT_SECRET: str = os.getenv("JWT_SECRET", "YOUR_SUPER_SECRET_KEY")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 24 hours

    # ---------- Refresh Token ----------
    JWT_REFRESH_SECRET: str = os.getenv("JWT_REFRESH_SECRET", os.getenv("JWT_SECRET", "YOUR_SUPER_SECRET_KEY") + "_REFRESH")
    JWT_REFRESH_EXPIRE_DAYS: int = int(os.getenv("JWT_REFRESH_EXPIRE_DAYS", "30"))  # 30 days

    # ---------- CORS ----------
    # Comma-separated list of allowed origins; falls back to permissive defaults
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:8081,http://localhost:19006,"
            "http://10.0.2.2:8081,http://10.0.2.2:19006,"
            "http://127.0.0.1:3000,http://127.0.0.1:8081",
        ).split(",")
    ]
    CORS_ALLOW_ALL: bool = os.getenv("CORS_ALLOW_ALL", "true").lower() == "true"

    # ---------- Roles ----------
    DEFAULT_USER_ROLE: str = "user"  # "user" | "admin" | "broker"

    class Config:
        case_sensitive = True


settings = Settings()
