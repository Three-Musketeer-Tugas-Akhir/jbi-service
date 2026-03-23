"""
Custom exceptions and exception handlers.

Provides standardized error handling across the application.
"""

import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exception Classes
# =============================================================================

class AppException(Exception):
    """Base application exception."""
    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    
    def __init__(self, message: str = None):
        self.message = message or "An internal error occurred"
        super().__init__(self.message)


class ValidationError(AppException):
    """Validation error exception."""
    status_code = 400
    code = "VALIDATION_ERROR"


class NotFoundError(AppException):
    """Resource not found exception."""
    status_code = 404
    code = "NOT_FOUND"


class AuthError(AppException):
    """Authentication error exception."""
    status_code = 401
    code = "UNAUTHORIZED"


class PermissionError(AppException):
    """Permission denied exception."""
    status_code = 403
    code = "FORBIDDEN"


class ConflictError(AppException):
    """Resource conflict exception."""
    status_code = 409
    code = "CONFLICT"


class RateLimitError(AppException):
    """Rate limit exceeded exception."""
    status_code = 429
    code = "RATE_LIMITED"


class StorageError(AppException):
    """Storage operation failed."""
    status_code = 500
    code = "STORAGE_ERROR"


class StorageUnavailableError(StorageError):
    """Storage service is unavailable."""
    status_code = 503
    code = "STORAGE_UNAVAILABLE"


# =============================================================================
# Exception Handlers
# =============================================================================

def register_exception_handlers(app: FastAPI):
    """Register all custom exception handlers on the FastAPI app."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """Handle custom application exceptions."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code.lower(),
                "detail": exc.message,
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        error_names = {
            400: "bad_request",
            401: "authentication_required",
            403: "insufficient_permissions",
            404: "not_found",
            409: "conflict",
            413: "payload_too_large",
            422: "validation_error",
            429: "rate_limited",
            500: "internal_server_error",
        }
        error_type = error_names.get(exc.status_code, f"http_{exc.status_code}")

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": error_type,
                "detail": exc.detail,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError,
    ):
        errors = exc.errors()
        messages = []

        for err in errors:
            loc = err.get("loc", [])
            field_parts = [str(part) for part in loc if part not in ("body", "query", "path")]
            field = ".".join(field_parts) if field_parts else "unknown"
            msg = err.get("msg", "Invalid value")
            messages.append(f"{field}: {msg}")

        detail = "; ".join(messages)

        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "detail": detail,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.exception(
            "Unhandled exception on %s %s",
            request.method, request.url.path,
        )

        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "detail": "An unexpected error occurred",
            },
        )
