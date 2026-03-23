"""
Authentication Dependencies.

Provides FastAPI dependencies for extracting and validating
current user from JWT tokens.
"""

from datetime import datetime
from typing import Optional
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
    Current authenticated user DTO.
    
    Pydantic model representing the authenticated user
    for use in FastAPI dependencies and route handlers.
    Provides a clean separation between DB models and API layer.
    """
    
    model_config = {"from_attributes": True}
    
    id: UUID = Field(..., description="User unique identifier")
    email: str = Field(..., description="User email address")
    role: str = Field(..., description="User role (admin, annotator, curator)")
    is_active: bool = Field(..., description="Whether user account is active")
    email_verified: bool = Field(..., description="Whether email is verified")
    created_at: datetime = Field(..., description="Account creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    
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
    
    def has_role(self, role: str) -> bool:
        """
        Check if user has a specific role.
        
        Args:
            role: Role name to check
            
        Returns:
            True if user has the specified role
        """
        return self.role == role
    
    def has_any_role(self, roles: set[str]) -> bool:
        """
        Check if user has any of the specified roles.
        
        Args:
            roles: Set of role names to check
            
        Returns:
            True if user has any of the specified roles
        """
        return self.role in roles


def _user_to_current_user(user: User) -> CurrentUser:
    """
    Convert SQLAlchemy User model to CurrentUser DTO.
    
    Args:
        user: User database model
        
    Returns:
        CurrentUser DTO instance
    """
    return CurrentUser(
        id=user.id,
        email=user.email,
        role=user.role,
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


async def require_role(
    allowed_roles: set[str]
) -> callable:
    """
    Factory for creating role-based access control dependencies.
    
    Usage:
        @router.get("/endpoint", dependencies=[Depends(require_role({"admin", "curator"}))])
    
    Args:
        allowed_roles: Set of allowed role names
        
    Returns:
        Dependency function that checks user role
    """
    async def _check_role(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current_user.has_any_role(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {', '.join(allowed_roles)}",
            )
        return current_user
    return _check_role
