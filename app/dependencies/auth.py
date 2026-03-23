"""
Authentication Dependencies.

Provides FastAPI dependencies for extracting and validating
current user from JWT tokens.
"""

from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.db.models.auth import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import jwt_auth_service

# Security scheme for JWT token
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: AsyncSession = Depends(get_async_session)
) -> User:
    """
    Get the current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Authorization credentials containing JWT token
        db_session: Database session
        
    Returns:
        Authenticated User instance
        
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
    
    return user


async def require_authenticated(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency to ensure user is authenticated.
    
    This is a wrapper around get_current_user that can be used
    when you just need to ensure authentication without using
    the user object directly.
    
    Args:
        current_user: Current authenticated user from get_current_user
        
    Returns:
        Authenticated User instance
    """
    return current_user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db_session: AsyncSession = Depends(get_async_session)
) -> Optional[User]:
    """
    Get the current user if authenticated, or None if not.
    
    This is useful for endpoints that work for both authenticated
    and unauthenticated users.
    
    Args:
        credentials: HTTP Authorization credentials containing JWT token
        db_session: Database session
        
    Returns:
        User instance if authenticated, None otherwise
    """
    if credentials is None:
        return None
    
    try:
        return await get_current_user(credentials, db_session)
    except HTTPException:
        return None


async def require_admin(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency to ensure user has admin role.
    
    Must be used after get_current_user to ensure authentication.
    
    Args:
        current_user: Current authenticated user from get_current_user
        
    Returns:
        Authenticated User instance with admin role
        
    Raises:
        HTTPException: If user is not an admin
    """
    if current_user.role != "admin":
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
    async def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {', '.join(allowed_roles)}",
            )
        return current_user
    return _check_role
