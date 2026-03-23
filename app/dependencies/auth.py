"""
Authentication Dependencies.

Provides FastAPI dependencies for extracting and validating
current user from JWT tokens.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.db.models.auth import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import jwt_auth_service

# Security scheme for JWT token
security = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """
    Current authenticated user DTO with RBAC support.
    
    Pydantic model representing the authenticated user
    for use in FastAPI dependencies and route handlers.
    Supports multiple roles and permissions from many-to-many RBAC.
    """
    
    model_config = {"from_attributes": True}
    
    id: UUID = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    roles: List[str] = Field(default_factory=list, description="User roles (admin, annotator, curator)")
    permissions: List[str] = Field(default_factory=list, description="User permissions from all roles")
    is_active: bool = Field(..., description="Whether user account is active")
    email_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
    @property
    def primary_role(self) -> Optional[str]:
        """Get the primary (first) role for backwards compatibility."""
        return self.roles[0] if self.roles else None
    
    @property
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return "admin" in self.roles
    
    @property
    def is_annotator(self) -> bool:
        """Check if user has annotator role."""
        return "annotator" in self.roles
    
    @property
    def is_curator(self) -> bool:
        """Check if user has curator role."""
        return "curator" in self.roles
    
    def has_role(self, *role_names: str) -> bool:
        """
        Check if user has any of the specified roles.
        
        Args:
            *role_names: Variable number of role strings to check
            
        Returns:
            True if user has any of the specified roles
        """
        return any(role in self.roles for role in role_names)
    
    def has_permission(self, permission: str) -> bool:
        """
        Check if user has a specific permission.
        
        Args:
            permission: Permission string to check (e.g., "annotation:read:own")
            
        Returns:
            True if user has the permission
        """
        # Admin with "*" has all permissions
        if "*" in self.permissions:
            return True
        return permission in self.permissions
    
    def has_any_permission(self, *permissions: str) -> bool:
        """
        Check if user has any of the specified permissions.
        
        Args:
            *permissions: Variable number of permission strings
            
        Returns:
            True if user has any of the specified permissions
        """
        return any(self.has_permission(p) for p in permissions)


def _user_to_current_user(user: User) -> CurrentUser:
    """
    Convert SQLAlchemy User model to CurrentUser DTO.
    
    Args:
        user: User database model with loaded roles
        
    Returns:
        CurrentUser DTO instance with roles and permissions
    """
    # Extract role names and permissions from user's roles
    role_names = [role.name for role in user.roles]
    
    # Aggregate all permissions from all roles
    all_permissions = set()
    for role in user.roles:
        all_permissions.update(role.permissions)
    
    return CurrentUser(
        id=user.id,
        email=user.email,
        roles=role_names,
        permissions=list(all_permissions),
        is_active=user.is_active,
        email_verified=user.is_email_verified,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: AsyncSession = Depends(get_async_session)
) -> CurrentUser:
    """
    Get the current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Authorization credentials containing JWT token
        db_session: Database session
        
    Returns:
        Authenticated CurrentUser DTO
        
    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    # Check if credentials provided
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verify token
    try:
        payload = jwt_auth_service.verify_token(token, expected_type="access")
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
    
    # Extract user ID from token
    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: malformed user identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Get user from database
    user_repo = UserRepository(db_session)
    user = await user_repo.get_by_id(user_id)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Convert to DTO and return
    return _user_to_current_user(user)


async def require_authenticated(
    current_user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    """
    Dependency to ensure user is authenticated.
    
    This is a wrapper around get_current_user that can be used
    when you just need to ensure authentication without using
    the user object directly.
    
    Args:
        current_user: Current authenticated user from get_current_user
        
    Returns:
        Authenticated CurrentUser DTO
    """
    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: AsyncSession = Depends(get_async_session)
) -> Optional[CurrentUser]:
    """
    Get the current user if authenticated, or None if not.
    
    This is useful for endpoints that work for both authenticated
    and unauthenticated users.
    
    Args:
        credentials: HTTP Authorization credentials containing JWT token
        db_session: Database session
        
    Returns:
        CurrentUser DTO if authenticated, None otherwise
    """
    if credentials is None:
        return None
    
    try:
        return await get_current_user(credentials, db_session)
    except HTTPException:
        return None


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user)
) -> CurrentUser:
    """
    Dependency to ensure user has admin role.
    
    Must be used after get_current_user to ensure authentication.
    
    Args:
        current_user: Current authenticated user from get_current_user
        
    Returns:
        Authenticated CurrentUser DTO with admin role
        
    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# Allowed roles for validation
ALLOWED_ROLES = {"admin", "annotator", "curator"}


def require_role(*allowed_roles: str) -> callable:
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
    
    async def _check_role(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:
        """Inner dependency that checks user role."""
        if not current_user.has_role(*allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    
    return _check_role


# Convenience dependencies for common role combinations

require_annotator = require_role("annotator")
"""Dependency for annotator-only endpoints."""

require_curator = require_role("curator")
"""Dependency for curator-only endpoints."""

require_annotator_or_curator = require_role("annotator", "curator")
"""Dependency for annotator or curator endpoints."""


# Permission-based dependencies

def require_permission(*required_permissions: str) -> callable:
    """
    FastAPI dependency factory for permission-based access control.
    
    Usage:
        @router.get("/annotations")
        async def list_annotations(
            current_user: CurrentUser = Depends(require_permission("annotation:read:own"))
        ):
            return {"annotations": []}
        
        @router.get("/all-annotations")
        async def list_all_annotations(
            current_user: CurrentUser = Depends(
                require_permission("annotation:read:all")
            )
        ):
            return {"annotations": []}
    
    Args:
        *required_permissions: Variable number of required permission strings
        
    Returns:
        Dependency function that validates permission and returns CurrentUser
    """
    async def _check_permission(
        current_user: CurrentUser = Depends(get_current_user)
    ) -> CurrentUser:
        """Inner dependency that checks user permission."""
        if not current_user.has_any_permission(*required_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required permissions: {', '.join(required_permissions)}"
            )
        return current_user
    
    return _check_permission


# Common permission combinations
require_annotation_read_own = require_permission("annotation:read:own")
"""Dependency for reading own annotations."""

require_annotation_read_all = require_permission("annotation:read:all")
"""Dependency for reading all annotations."""

require_annotation_write_own = require_permission("annotation:write:own")
"""Dependency for writing own annotations."""

require_annotation_write_reviews = require_permission("annotation:write:reviews")
"""Dependency for writing reviews."""
