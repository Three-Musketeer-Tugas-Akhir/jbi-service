"""
Swagger Documentation Helpers.

Provides reusable response definitions and documentation utilities
for consistent API documentation across all endpoints.
"""

from typing import Dict, Any
from fastapi import status


class ApiResponses:
    """
    Standard API response definitions for Swagger documentation.
    
    Usage:
        @router.get(
            "/items",
            responses={
                **ApiResponses.AUTH_REQUIRED,
                **ApiResponses.FORBIDDEN,
                **ApiResponses.NOT_FOUND,
            }
        )
        async def get_items():
            pass
    """
    
    # Authentication & Authorization
    AUTH_REQUIRED: Dict[int, Dict[str, Any]] = {
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Unauthorized - Valid JWT token required",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Authentication required"
                    }
                }
            }
        }
    }
    
    FORBIDDEN: Dict[int, Dict[str, Any]] = {
        status.HTTP_403_FORBIDDEN: {
            "description": "Forbidden - Insufficient permissions",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Admin access required"
                    }
                }
            }
        }
    }
    
    # Resource Errors
    NOT_FOUND: Dict[int, Dict[str, Any]] = {
        status.HTTP_404_NOT_FOUND: {
            "description": "Resource not found",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Resource not found"
                    }
                }
            }
        }
    }
    
    CONFLICT: Dict[int, Dict[str, Any]] = {
        status.HTTP_409_CONFLICT: {
            "description": "Conflict - Resource already exists",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "User with this email already exists"
                    }
                }
            }
        }
    }
    
    # Validation Errors
    VALIDATION_ERROR: Dict[int, Dict[str, Any]] = {
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "Validation error - Invalid request data",
            "content": {
                "application/json": {
                    "example": {
                        "detail": [
                            {
                                "loc": ["body", "email"],
                                "msg": "invalid email format",
                                "type": "value_error.email"
                            }
                        ]
                    }
                }
            }
        }
    }
    
    BAD_REQUEST: Dict[int, Dict[str, Any]] = {
        status.HTTP_400_BAD_REQUEST: {
            "description": "Bad request - Invalid parameters",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Invalid request parameters"
                    }
                }
            }
        }
    }
    
    # Rate Limiting
    RATE_LIMITED: Dict[int, Dict[str, Any]] = {
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Rate limit exceeded",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "Rate limit exceeded. Try again in 15 minutes."
                    }
                }
            }
        }
    }
    
    # Server Errors
    SERVER_ERROR: Dict[int, Dict[str, Any]] = {
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "An unexpected error occurred"
                    }
                }
            }
        }
    }
    
    # Convenience Combinations
    @classmethod
    def protected(cls) -> Dict[int, Dict[str, Any]]:
        """Standard responses for protected endpoints."""
        return {
            **cls.AUTH_REQUIRED,
            **cls.FORBIDDEN,
        }
    
    @classmethod
    def with_validation(cls) -> Dict[int, Dict[str, Any]]:
        """Standard responses including validation errors."""
        return {
            **cls.AUTH_REQUIRED,
            **cls.FORBIDDEN,
            **cls.VALIDATION_ERROR,
        }
    
    @classmethod
    def crud(cls) -> Dict[int, Dict[str, Any]]:
        """Standard CRUD responses."""
        return {
            **cls.AUTH_REQUIRED,
            **cls.FORBIDDEN,
            **cls.NOT_FOUND,
            **cls.CONFLICT,
            **cls.VALIDATION_ERROR,
        }


# ============================================================================
# Endpoint Documentation Examples
# ============================================================================

class EndpointExamples:
    """
    Example request/response payloads for documentation.
    """
    
    LOGIN_REQUEST = {
        "email": "user@example.com",
        "password": "securepassword123"
    }
    
    LOGIN_RESPONSE = {
        "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        "token_type": "bearer",
        "expires_in": 900,
        "role": "annotator"
    }
    
    ERROR_RESPONSE = {
        "detail": "Error message describing what went wrong"
    }
    
    VALIDATION_ERROR_RESPONSE = {
        "detail": [
            {
                "loc": ["body", "field_name"],
                "msg": "error message",
                "type": "error_type"
            }
        ]
    }


# ============================================================================
# Description Templates
# ============================================================================

class DescriptionTemplates:
    """
    Reusable description templates for common patterns.
    """
    
    PAGINATION = """
    ## Pagination
    
    This endpoint supports pagination using the following query parameters:
    
    - `page`: Page number (1-indexed, default: 1)
    - `page_size`: Items per page (default: 20, max: 100)
    
    ## Response
    
    Paginated responses include:
    - `items`: List of items for the current page
    - `total`: Total number of items
    - `page`: Current page number
    - `page_size`: Items per page
    - `pages`: Total number of pages
    - `has_next`: Whether there is a next page
    - `has_prev`: Whether there is a previous page
    """
    
    AUTH_REQUIRED = """
    ## Authentication
    
    This endpoint requires a valid JWT token in the Authorization header:
    
    ```
    Authorization: Bearer <your-jwt-token>
    ```
    
    Obtain a token via `/api/v1/auth/login`.
    """
    
    ADMIN_REQUIRED = """
    ## Authorization
    
    **Admin role required.**
    
    This endpoint is restricted to users with the `admin` role.
    """
    
    ASYNC_PROCESSING = """
    ## Async Processing
    
    This endpoint initiates an asynchronous job. The response includes a `job_id`
    that can be used to track progress via the status endpoint.
    
    ## Job States
    
    - `PENDING`: Job queued, waiting to start
    - `PROCESSING`: Job is actively running
    - `COMPLETED`: Job finished successfully
    - `FAILED`: Job failed (check error message)
    """


# ============================================================================
# Swagger UI Tags Configuration
# ============================================================================

TAGS_CONFIG = [
    {"name": "health", "description": "Health check and system status"},
    {"name": "authentication", "description": "User authentication and account management"},
    {"name": "users", "description": "User profile management"},
    {"name": "admin", "description": "Administrative endpoints (admin only)"},
    {"name": "jobs", "description": "Video processing job management"},
    {"name": "annotations", "description": "Annotation workflow management"},
    {"name": "asr-review", "description": "ASR review queue management"},
]
