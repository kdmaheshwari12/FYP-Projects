"""
Input sanitization middleware for FastAPI.

Automatically sanitizes incoming request data:
- Strips whitespace from string fields
- Removes null bytes and control characters
- Prevents malicious input
"""

import json
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


class InputSanitizationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that sanitizes all incoming request data.
    
    Functionality:
    - Strips whitespace from string fields
    - Removes null bytes and control characters
    - Validates JSON structure
    - Logs potentially malicious input attempts
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and sanitize input."""
        
        # Only process specific content types and methods
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")
            
            if "application/json" in content_type:
                try:
                    # Read the request body
                    body = await request.body()
                    
                    if body:
                        # Parse JSON
                        data = json.loads(body)
                        
                        # Sanitize the data
                        sanitized_data = self._sanitize_data(data)
                        
                        # Re-encode to bytes
                        sanitized_body = json.dumps(sanitized_data).encode()
                        
                        # Replace the request body
                        async def receive():
                            return {
                                "type": "http.request",
                                "body": sanitized_body,
                                "more_body": False
                            }
                        
                        request._receive = receive
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON received: {e}")
                    # Allow the request to continue; let FastAPI handle the error
                except Exception as e:
                    logger.warning(f"Error sanitizing input: {e}")
                    # Allow the request to continue; let FastAPI handle the error
        
        # Process the request
        response = await call_next(request)
        return response
    
    @staticmethod
    def _sanitize_data(data: any) -> any:
        """
        Recursively sanitize data structures.
        
        - Strips whitespace from strings
        - Removes null bytes and control characters
        - Handles nested objects and lists
        """
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Sanitize the key (field name)
                sanitized_key = InputSanitizationMiddleware._sanitize_string(str(key))
                # Recursively sanitize the value
                sanitized[sanitized_key] = InputSanitizationMiddleware._sanitize_data(value)
            return sanitized
        
        elif isinstance(data, list):
            return [
                InputSanitizationMiddleware._sanitize_data(item)
                for item in data
            ]
        
        elif isinstance(data, str):
            return InputSanitizationMiddleware._sanitize_string(data)
        
        elif isinstance(data, (int, float, bool, type(None))):
            # These types don't need sanitization
            return data
        
        else:
            # Unknown type; return as-is
            return data
    
    @staticmethod
    def _sanitize_string(value: str) -> str:
        """
        Sanitize a string:
        - Strip leading/trailing whitespace
        - Remove null bytes and control characters
        - Preserve intentional whitespace within text
        """
        # Strip leading/trailing whitespace
        value = value.strip()
        
        # Remove null bytes
        value = value.replace('\x00', '')
        
        # Remove control characters (except tab, newline, carriage return)
        value = ''.join(
            char for char in value
            if ord(char) >= 32 or char in '\t\n\r'
        )
        
        return value


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs incoming requests for debugging/security.
    
    Logs:
    - Request method and path
    - Content type
    - Sanitized payload (first 500 chars)
    - Response status code
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log request and response."""
        
        # Log request info
        logger.debug(f"→ {request.method} {request.url.path}")
        logger.debug(f"  Content-Type: {request.headers.get('content-type', 'N/A')}")
        
        # Log body for debugging (first 500 chars, sanitized)
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body:
                    # Try to parse as JSON for cleaner logging
                    try:
                        data = json.loads(body)
                        # Log sanitized version (don't log sensitive fields)
                        log_data = RequestLoggingMiddleware._redact_sensitive_fields(data)
                        logger.debug(f"  Body: {json.dumps(log_data)[:500]}")
                    except json.JSONDecodeError:
                        # Log as raw text
                        logger.debug(f"  Body: {body[:500]}")
                
                # Re-create receive for the request
                async def receive():
                    return {
                        "type": "http.request",
                        "body": body,
                        "more_body": False
                    }
                
                request._receive = receive
                
            except Exception as e:
                logger.debug(f"  Could not log body: {e}")
        
        # Process the request
        response = await call_next(request)
        
        # Log response status
        logger.debug(f"← {response.status_code} {request.url.path}")
        
        return response
    
    @staticmethod
    def _redact_sensitive_fields(data: dict) -> dict:
        """Redact sensitive fields from logs."""
        sensitive_fields = [
            "password", "hashed_password", "refresh_token", "access_token",
            "cnic", "phone", "email", "api_key", "secret", "token"
        ]
        
        if not isinstance(data, dict):
            return data
        
        redacted = {}
        for key, value in data.items():
            if any(sensitive in key.lower() for sensitive in sensitive_fields):
                redacted[key] = "***REDACTED***"
            elif isinstance(value, dict):
                redacted[key] = RequestLoggingMiddleware._redact_sensitive_fields(value)
            elif isinstance(value, list):
                redacted[key] = [
                    RequestLoggingMiddleware._redact_sensitive_fields(item)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                redacted[key] = value
        
        return redacted
