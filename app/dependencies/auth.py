"""
Authentication and Authorization Dependencies.

FastAPI dependencies for JWT validation, user extraction, and role-based access control.
"""

from typing import Optional, List
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from app.core.security import jwt_auth_service
from app.core.config import settings

# Security scheme for OpenAPI documentation
security_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """
    Authenticated user model for dependency injection.
    
    Extracted from validated JWT token and injected into route handlers.
    """
    id: UUID
    email: str
    role: str
    
    model_config = {"frozen": True}  # Immutable
    
    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == "admin"
    
    @property
    def is_annotator(self) -> bool:
        """Check if user has annotator role."""
        return self.role == "annotator"
    
    @property
    def is_curator(self) -> bool:
        """Check if user has curator role."""
        return self.role == "curator"
    
    def has_role(self, *roles: str) -> bool:
        """
        Check if user has any of the specified roles.
        
        Args:
            *roles: Variable number of role strings to check
            
        Returns:
            True if user's role is in the allowed roles
        """
        return self.role in roles
    
    def __repr__(self) -> str:
        return f"CurrentUser(id={self.id}, email={self.email}, role={self.role})"


# Allowed roles for validation
ALLOWED_ROLES = {"admin", "annotator", "curator"}


def _extract_token_from_header(
    credentials: Optional[HTTPAuthorizationCredentials]
) -> str:
    """
    Extract JWT token from Authorization header.
    
    Args:
        credentials: HTTP Authorization credentials
        
    Returns:
        JWT token string
        
    Raises:
        HTTPException: 401 if credentials missing or malformed
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    scheme = credentials.scheme.lower()
    if scheme != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme. Use Bearer",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return credentials.credentials


def _verify_token_and_extract_payload(token: str) -> dict:
    """
    Verify JWT token and extract payload.
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded token payload
        
    Raises:
        HTTPException: 401 if token invalid or expired
    """
    from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
    
    try:
        payload = jwt_auth_service.verify_token(token, expected_type="access")
        return payload
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _payload_to_current_user(payload: dict) -> CurrentUser:
    """
    Convert token payload to CurrentUser model.
    
    Args:
        payload: Decoded JWT payload
        
    Returns:
        CurrentUser instance
        
    Raises:
        HTTPException: 401 if payload missing required fields
    """
    # Extract required fields
    sub = payload.get("sub")
    role = payload.get("role")
    
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing role claim",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Validate role
    if role not in ALLOWED_ROLES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role in token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Parse UUID
    try:
        user_id = UUID(sub)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user identifier in token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Build CurrentUser (email not in token, fetch from DB if needed)
    # For now, email is optional in token
    return CurrentUser(
        id=user_id,
        email=payload.get("email", ""),  # May not be in token
        role=role,
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_scheme)
) -> CurrentUser:
    """
    FastAPI dependency to extract and validate current user from JWT.
    
    Usage:
        @router.get("/protected")
        async def protected_endpoint(current_user: CurrentUser = Depends(get_current_user)):
            return {"user_id": current_user.id}
    
    Args:
        credentials: HTTP Authorization credentials (injected by FastAPI)
        
    Returns:
        CurrentUser instance
        
    Raises:
        HTTPException: 401 if authentication fails
    """
    # Step 1: Extract token from header
    token = _extract_token_from_header(credentials)
    
    # Step 2: Verify token and get payload
    payload = _verify_token_and_extract_payload(token)
    
    # Step 3: Convert to CurrentUser
    return _payload_to_current_user(payload)


def require_role(*allowed_roles: str):
    """
    FastAPI dependency factory for role-based access control.
    
    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(
            current_user: CurrentUser = Depends(require_role("admin"))
        ):
            return {"message": "Admin access granted"}
        
        @router.get("/multi-role")
        async def multi_role_endpoint(
            current_user: CurrentUser = Depends(require_role("annotator", "curator"))
        ):
            return {"message": "Annotator or Curator access granted"}
    
    Args:
        *allowed_roles: Variable number of allowed role strings
        
    Returns:
        Dependency function that validates role and returns CurrentUser
    """
    # Validate role arguments at definition time
    invalid_roles = set(allowed_roles) - ALLOWED_ROLES
    if invalid_roles:
        raise ValueError(f"Invalid roles specified: {invalid_roles}")
    
    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:
        """Inner dependency that checks user role."""
        if not current_user.has_role(*allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    
    return role_checker


# Convenience dependencies for common role combinations

require_admin = require_role("admin")
"""Dependency for admin-only endpoints."""

require_annotator = require_role("annotator")
"""Dependency for annotator-only endpoints."""

require_curator = require_role("curator")
"""Dependency for curator-only endpoints."""

require_annotator_or_curator = require_role("annotator", "curator")
"""Dependency for annotator or curator endpoints."""
