"""
JWT Authentication Service.

Provides token generation, validation, and refresh functionality.
Uses PyJWT for custom JWT implementation per architecture decision.

NOTE: The actual implementation has been moved to app.core.security.
This module re-exports from there for backward compatibility.
"""

# Re-export all security-related classes and functions from core
from app.core.security import (
    jwt_auth_service,
    JWTAuthService,
    ALLOWED_ROLES,
    generate_temporary_password,
    validate_password_strength,
    hash_password,
    verify_password,
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWTError,
)

# Maintain backward compatibility for any code importing from here
__all__ = [
    "jwt_auth_service",
    "JWTAuthService",
    "ALLOWED_ROLES",
    "generate_temporary_password",
    "validate_password_strength",
    "hash_password",
    "verify_password",
    "ExpiredSignatureError",
    "InvalidTokenError",
    "PyJWTError",
]
