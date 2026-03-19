"""
JWT Authentication Service.

Provides token generation, validation, and refresh functionality.
Uses PyJWT for custom JWT implementation per architecture decision.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import jwt
from jwt.exceptions import (
    ExpiredSignatureError,
    InvalidTokenError,
    PyJWTError,
)

from app.config import settings

# Allowed roles for validation
ALLOWED_ROLES = {"admin", "annotator", "curator"}


class JWTAuthService:
    """
    Service for JWT token operations.
    
    Handles creation and verification of access and refresh tokens.
    Uses HS256 algorithm with configurable secret key.
    """
    
    def __init__(self) -> None:
        """Initialize with configuration from settings."""
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_minutes = settings.jwt_access_token_expire_minutes
        self.refresh_token_expire_days = settings.jwt_refresh_token_expire_days
        
        # Validate configuration
        self._validate_configuration()
    
    def _validate_configuration(self) -> None:
        """Validate JWT configuration settings."""
        if not self.secret_key:
            raise ValueError(
                "JWT_SECRET_KEY must be set in environment variables"
            )
        if len(self.secret_key) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters long"
            )
        if self.access_token_expire_minutes <= 0:
            raise ValueError(
                "JWT_ACCESS_TOKEN_EXPIRE_MINUTES must be positive"
            )
        if self.refresh_token_expire_days <= 0:
            raise ValueError(
                "JWT_REFRESH_TOKEN_EXPIRE_DAYS must be positive"
            )
    
    def _validate_role(self, role: str) -> None:
        """Validate role parameter."""
        if not role:
            raise ValueError("Role cannot be empty")
        if role not in ALLOWED_ROLES:
            raise ValueError(f"Invalid role: {role}")
    
    def create_access_token(self, user_id: UUID, role: str) -> str:
        """
        Create a new access token.
        
        Args:
            user_id: UUID of the user
            role: User role (admin, annotator, curator)
            
        Returns:
            Encoded JWT token string
            
        Raises:
            ValueError: If role is invalid
        """
        if not isinstance(user_id, UUID):
            raise ValueError("user_id must be a UUID instance")
        self._validate_role(role)
        
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=self.access_token_expire_minutes)
        
        payload = {
            "sub": str(user_id),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "type": "access",
            "iss": "anotasi-api",  # Issuer claim
            "aud": "anotasi-client",  # Audience claim
            "nbf": int(now.timestamp()),  # Not before claim
        }
        
        try:
            return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        except PyJWTError as e:
            raise InvalidTokenError(f"Failed to encode token: {str(e)}") from e
    
    def create_refresh_token(self, user_id: UUID, role: str) -> str:
        """
        Create a new refresh token.
        
        Args:
            user_id: UUID of the user
            role: User role
            
        Returns:
            Encoded JWT token string
            
        Raises:
            ValueError: If role is invalid
        """
        if not isinstance(user_id, UUID):
            raise ValueError("user_id must be a UUID instance")
        self._validate_role(role)
        
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=self.refresh_token_expire_days)
        
        payload = {
            "sub": str(user_id),
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "type": "refresh",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int(now.timestamp()),
        }
        
        try:
            return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        except PyJWTError as e:
            raise InvalidTokenError(f"Failed to encode token: {str(e)}") from e
    
    def verify_token(self, token: str, expected_type: Optional[str] = None) -> dict:
        """
        Verify and decode a JWT token.
        
        Args:
            token: JWT token string to verify
            expected_type: Optional token type to validate ("access" or "refresh")
            
        Returns:
            Decoded token payload as dictionary
            
        Raises:
            ExpiredSignatureError: If token has expired
            InvalidTokenError: If token is malformed or invalid
            ValueError: If token type doesn't match expected_type
        """
        # Validate token is non-empty
        if not token or not token.strip():
            raise InvalidTokenError("Token cannot be empty")
        
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                options={"require": ["sub", "role", "iat", "exp", "type"]}
            )
            
            # Validate token type if specified
            if expected_type and payload.get("type") != expected_type:
                raise ValueError(
                    f"Invalid token type. Expected {expected_type}, "
                    f"got {payload.get('type')}"
                )
            
            return payload
            
        except ExpiredSignatureError as e:
            raise ExpiredSignatureError("Token has expired") from e
        except InvalidTokenError:
            raise
        except PyJWTError as e:
            raise InvalidTokenError(f"Invalid token: {str(e)}") from e
    
    def refresh_access_token(self, refresh_token: str) -> str:
        """
        Create new access token using refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            New access token
            
        Raises:
            ExpiredSignatureError: If refresh token has expired
            InvalidTokenError: If refresh token is invalid
            ValueError: If provided token is not a refresh token
        """
        payload = self.verify_token(refresh_token, expected_type="refresh")
        
        # Validate required claims exist
        sub = payload.get("sub")
        role = payload.get("role")
        
        if not sub:
            raise InvalidTokenError("Token missing 'sub' claim")
        if not role:
            raise InvalidTokenError("Token missing 'role' claim")
        
        # Parse UUID with error handling
        try:
            user_id = UUID(sub)
        except ValueError as e:
            raise InvalidTokenError(f"Invalid user ID in token: {str(e)}") from e
        
        return self.create_access_token(user_id, role)


# Singleton instance for dependency injection
jwt_auth_service = JWTAuthService()
