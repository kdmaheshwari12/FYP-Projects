# app/main.py
"""
FastAPI application entry point.

Startup:
    1. Connect to MongoDB

Shutdown:
    1. Close MongoDB connection
"""

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
from app.database.mongodb import connect_to_mongo, close_mongo_connection
from app.core.config import settings
from app.middleware.input_sanitization import InputSanitizationMiddleware, RequestLoggingMiddleware
from app.routes import (
    auth_routes,
    broker_routes,
    chat_routes,
    review_routes,
    traveler_routes,
    trip_routes,
    weather_routes,
)
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
    """
    App Lifespan: Handles startup and shutdown logic.
    """
    logger.info("🚀 Starting Pakvel Backend...")
    try:
        # 1. Connect to MongoDB
        await connect_to_mongo()
        logger.info("✅ MongoDB connected successfully.")
        
        # 2. Add other startup tasks here (e.g. index checks)
        
        logger.info("⚡ Application startup complete.")
        yield
    except Exception as e:
        logger.error(f"💥 Critical error during startup: {e}")
        # Allow the app to crash if DB connection fails
        raise e
    finally:
        # Shutdown phase
        logger.info("🛑 Shutting down Pakvel Backend...")
        try:
            await close_mongo_connection()
            logger.info("✅ Database connections closed.")
        except Exception as e:
            logger.error(f"⚠️ Error during cleanup: {e}")
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
# Custom Exception Handlers
# --------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Catch Pydantic validation errors (422) and return them as uniform 400 JSON.
    """
    error_details = exc.errors()
    # Create a user-friendly message from the first error
    msg = "Invalid input data"
    if error_details:
        first_error = error_details[0]
        field = ".".join(str(loc) for loc in first_error.get("loc", []))
        msg = f"Error in field '{field}': {first_error.get('msg')}"

    logger.warning(f"🛡️ Global Validation Error: {msg}")
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "message": msg,
            "errors": error_details
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for any unhandled server errors.
    """
    logger.error(f"💥 UNHANDLED SERVER ERROR: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "message": "A critical server error occurred. Please try again later."
        }
    )

# --------------------------------------------------------------------------
# Security & Request Processing Middleware
#
# Note: Middleware is executed in REVERSE order of addition.
# Last added = executed first.
# --------------------------------------------------------------------------

# 1. Request Logging (executed first)
app.add_middleware(RequestLoggingMiddleware)

# 2. Input Sanitization (sanitize JSON payloads)
app.add_middleware(InputSanitizationMiddleware)

logger.info("✅ Security middleware added: InputSanitization, RequestLogging")

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
app.include_router(broker_routes.router)
app.include_router(chat_routes.router)
app.include_router(review_routes.router)
app.include_router(traveler_routes.router)
app.include_router(trip_routes.router)
app.include_router(weather_routes.router)


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