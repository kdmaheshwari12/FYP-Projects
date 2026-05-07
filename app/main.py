# app/main.py
"""
FastAPI application entry point.

Startup:
    1. Connect to MongoDB

Shutdown:
    1. Close MongoDB connection
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.database.mongodb import connect_to_mongo, close_mongo_connection
from app.core.config import settings
from app.routes import auth_routes
import uvicorn
import logging

# Configure root logger
logging.basicConfig(
    level=logging.INFO,  # Changed to INFO to prevent pymongo DEBUG spam
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Lifespan — modern replacement for on_event("startup") / on_event("shutdown")
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    logger.info("🚀 Starting Pakvel Backend...")

    # 1. Connect to MongoDB
    await connect_to_mongo()

    logger.info("✅ All startup tasks completed.")
    yield

    # ── Shutdown ──
    logger.info("🛑 Shutting down Pakvel Backend...")
    await close_mongo_connection()
    logger.info("👋 Shutdown complete.")


# --------------------------------------------------------------------------
# FastAPI App
# --------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Pakvel Backend API with Email/Password Authentication",
    version="1.0.0",
    lifespan=lifespan,
)

# --------------------------------------------------------------------------
# CORS — CRITICAL for frontend ↔ backend communication
#
# When allow_credentials=True you must NOT use allow_origins=["*"] in
# production.  For mobile dev (React Native), credentials are usually not
# sent via cookies so the wildcard is acceptable.  We default to a safe
# explicit list but allow override via CORS_ALLOW_ALL env var.
# --------------------------------------------------------------------------
if settings.CORS_ALLOW_ALL:
    # Development mode — accept any origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,  # must be False when origin is "*"
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info("🌐 CORS: allow ALL origins (dev mode)")
else:
    # Production mode — explicit allowlist
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"🌐 CORS: allowed origins = {settings.CORS_ORIGINS}")

# --------------------------------------------------------------------------
# Routers
# --------------------------------------------------------------------------
app.include_router(auth_routes.router)


# --------------------------------------------------------------------------
# Health check
# --------------------------------------------------------------------------
@app.get("/", tags=["Health"])
async def root():
    return {
        "message": "Pakvel Backend API is running",
        "status": "healthy",
        "auth": "Email/Password Authentication",
    }


@app.get("/ping", tags=["Health"])
async def ping():
    return {"message": "pong"}


# --------------------------------------------------------------------------
# Local dev entry
# --------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)