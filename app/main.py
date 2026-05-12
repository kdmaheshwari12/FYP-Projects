# app/main.py
"""
FastAPI application entry point.

Startup:
    1. Connect to MongoDB

Shutdown:
    1. Close MongoDB connection
"""

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import http_exception_handler
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
        
        # 2. Pre-load LLM resources (embeddings, index, etc.)
        from app.LLM.main import get_llm_resources
        import asyncio
        logger.info("🤖 Pre-loading LLM resources...")
        await asyncio.to_thread(get_llm_resources)
        logger.info("✅ LLM resources loaded.")
        
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
    Catch Pydantic validation errors and return formatted 422 JSON.
    
    Response format (requested):
    {
      "success": false,
      "message": "Validation failed",
      "errors": [
        { "field": "destination", "message": "Destination is required" },
        { "field": "travel_style", "message": "Invalid travel style" }
      ]
    }
    """
    error_details = exc.errors()
    formatted_errors = []

    for err in error_details:
        loc = err.get("loc", [])
        # 'loc' for body fields is usually ('body', 'field_name')
        field = str(loc[-1]) if loc else "unknown"
        
        raw_msg: str = err.get("msg", "")

        # Pydantic v2 prefixes custom ValueError messages with "Value error, "
        # We strip this so only the core message remains.
        if raw_msg.lower().startswith("value error, "):
            raw_msg = raw_msg[len("value error, "):]
        
        # Normalize Enum errors (like travel_style) to "Invalid <field>"
        if "enum" in err.get("type", "") or "enum" in raw_msg.lower():
            raw_msg = f"Invalid {field.replace('_', ' ')}"

        formatted_errors.append({
            "field": field,
            "message": raw_msg
        })

    logger.warning(f"🛡️ Validation failed on {request.url.path}: {formatted_errors}")

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "message": "Validation failed",
            "errors": formatted_errors,
        },
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all for any unhandled server errors.
    """
    # If it's already an HTTPException, let FastAPI handle it normally
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)

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

from fastapi.middleware.gzip import GZipMiddleware

# 3. GZip Compression (for faster dashboard loading)
app.add_middleware(GZipMiddleware, minimum_size=1000)

logger.info("✅ Security middleware added: InputSanitization, RequestLogging, GZip")

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


@app.get("/version", tags=["Health"])
async def version():
    return {"version": "v2026-05-13-01-52", "status": "deployed_with_chat_fixes"}


@app.get("/ping", tags=["Health"])
async def ping():
    return {"message": "pong"}


# --------------------------------------------------------------------------
# Local dev entry
# --------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)