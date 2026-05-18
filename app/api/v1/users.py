"""
Users Router.

Provides user profile management endpoints for authenticated users.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.api.deps import CurrentUser, get_current_user
from app.schemas import (
    UserProfileResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
    AuthErrorResponse
)
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _user_to_profile_response(user) -> UserProfileResponse:
    """Convert DB User model to UserProfileResponse."""
    return UserProfileResponse(
        id=str(user.id),
        email=user.email,
        roles=[r.name for r in user.roles],
        is_active=user.is_active,
        email_verified=user.email_verified_at is not None,
        must_change_password=user.must_change_password,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat() if user.updated_at else user.created_at.isoformat()
    )


@router.get(
    "/me",
    response_model=UserProfileResponse,
    responses={
        401: {"model": AuthErrorResponse, "description": "Not authenticated"},
    },
)
async def get_current_user_profile(
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get the current authenticated user's profile.
    
    Returns user details including id, email, roles, and verification status.
    Requires valid JWT access token.
    """
    user_service = UserService(db_session)
    user = await user_service.get_user_by_id(current_user.id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    return _user_to_profile_response(user)


@router.patch(
    "/me",
    response_model=UpdateProfileResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid input or email in use"},
        401: {"model": AuthErrorResponse, "description": "Not authenticated"},
        422: {"description": "Validation error"},
    },
)
async def update_current_user_profile(
    update_data: UpdateProfileRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Update the current user's profile.
    
    - **email**: New email address (optional)
    
    Email must be unique and properly formatted.
    Changing email will require reverification.
    """
    user_service = UserService(db_session)
    
    result = await user_service.update_profile(
        user_id=current_user.id,
        email=update_data.email
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    
    return UpdateProfileResponse(
        id=str(result["user"].id),
        email=result["user"].email,
        message=result["message"]
    )


@router.post(
    "/me/password",
    response_model=ChangePasswordResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid input or weak password"},
        401: {"model": AuthErrorResponse, "description": "Not authenticated or wrong current password"},
        422: {"description": "Validation error"},
    },
)
async def change_current_user_password(
    password_data: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Change the current user's password.
    
    - **current_password**: Current password (for verification)
    - **new_password**: New password (min 8 chars, must include uppercase, lowercase, digit, special char)
    
    Requires current password for security.
    New password must meet strength requirements.
    """
    user_service = UserService(db_session)
    
    result = await user_service.change_password(
        user_id=current_user.id,
        current_password=password_data.current_password,
        new_password=password_data.new_password
    )
    
    if not result["success"]:
        # Determine appropriate status code
        error_msg = result["message"].lower()
        
        if "incorrect" in error_msg:
            status_code = status.HTTP_401_UNAUTHORIZED
        elif "at least" in error_msg or "must contain" in error_msg or "too common" in error_msg:
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(
            status_code=status_code,
            detail=result["message"],
        )
    
    return ChangePasswordResponse(
        message=result["message"]
    )
