"""
Admin Router.

Provides admin-only endpoints for user management.
All endpoints require admin role.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import CurrentUser, require_admin
from app.models.schemas import (
    AdminUserListResponse,
    AdminUserListItem,
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminUserDetailResponse,
    AdminUpdateUserRequest,
    AdminUpdateUserResponse,
    AdminDeactivateUserResponse,
    AdminReactivateUserResponse,
    AuthErrorResponse
)
from app.services.audit_service import AuditService
from app.services.user_service import UserService

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_to_list_item(user: User) -> AdminUserListItem:
    """Convert User model to AdminUserListItem."""
    return AdminUserListItem(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.is_email_verified,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat()
    )


def _user_to_detail_response(user: User) -> AdminUserDetailResponse:
    """Convert User model to AdminUserDetailResponse."""
    return AdminUserDetailResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.is_email_verified,
        created_at=user.created_at.isoformat(),
        updated_at=user.updated_at.isoformat()
    )


def _get_client_ip(request: Request) -> Optional[str]:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    responses={
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
    },
)
async def list_users(
    limit: int = Query(20, ge=1, le=100, description="Number of users to return"),
    offset: int = Query(0, ge=0, description="Number of users to skip"),
    role: Optional[str] = Query(None, description="Filter by role"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    search: Optional[str] = Query(None, description="Search in email"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    List all users with filtering and pagination.
    
    - **limit**: Number of users to return (1-100, default: 20)
    - **offset**: Number of users to skip (default: 0)
    - **role**: Filter by role (admin, annotator, curator)
    - **is_active**: Filter by active status
    - **search**: Search in email (case-insensitive)
    
    Returns paginated list of users. Admin access required.
    """
    user_service = UserService(db_session)
    
    result = await user_service.list_users(
        limit=limit,
        offset=offset,
        role=role,
        is_active=is_active,
        search=search
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    
    return AdminUserListResponse(
        users=[_user_to_list_item(u) for u in result["users"]],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"]
    )


@router.post(
    "/users",
    response_model=AdminCreateUserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid input or email exists"},
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        422: {"description": "Validation error"},
    },
)
async def create_user(
    request: Request,
    user_data: AdminCreateUserRequest,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Create a new user.
    
    - **email**: User email address (unique)
    - **password**: Initial password (min 8 chars, must include uppercase, lowercase, digit, special char)
    - **role**: User role (admin, annotator, curator) - default: annotator
    - **is_active**: Whether user is active - default: true
    - **email_verified**: Whether email is pre-verified - default: false
    
    Admin access required. Email must be unique.
    """
    user_service = UserService(db_session)
    audit_service = AuditService(db_session)
    
    result = await user_service.create_user(
        email=user_data.email,
        password=user_data.password,
        role=user_data.role,
        is_active=user_data.is_active,
        email_verified=user_data.email_verified
    )
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    
    user = result["user"]
    
    # Log audit event
    await audit_service.log_user_created(
        actor_id=current_user.id,
        new_user_id=user.id,
        email=user.email,
        role=user.role,
        ip_address=_get_client_ip(request)
    )
    await db_session.commit()
    
    return AdminCreateUserResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        message=result["message"]
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserDetailResponse,
    responses={
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"model": AuthErrorResponse, "description": "User not found"},
    },
)
async def get_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Get detailed information about a specific user.
    
    - **user_id**: UUID of the user
    
    Returns user details. Admin access required.
    """
    user_service = UserService(db_session)
    
    user = await user_service.get_user_by_id(user_id)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    
    return _user_to_detail_response(user)


@router.patch(
    "/users/{user_id}",
    response_model=AdminUpdateUserResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid input or email in use"},
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"model": AuthErrorResponse, "description": "User not found"},
        422: {"description": "Validation error"},
    },
)
async def update_user(
    request: Request,
    user_id: UUID,
    update_data: AdminUpdateUserRequest,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Update a user's information.
    
    - **email**: New email address (optional)
    - **role**: New role (admin, annotator, curator) (optional)
    - **is_active**: Active status (optional)
    - **email_verified**: Email verification status (optional)
    
    Only provided fields are updated. Admin access required.
    Cannot deactivate the last active admin.
    """
    user_service = UserService(db_session)
    audit_service = AuditService(db_session)
    
    # Get the original user data for audit logging
    original_user = await user_service.get_user_by_id(user_id)
    if original_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    
    old_role = original_user.role
    
    result = await user_service.admin_update_user(
        user_id=user_id,
        email=update_data.email,
        role=update_data.role,
        is_active=update_data.is_active,
        email_verified=update_data.email_verified
    )
    
    if not result["success"]:
        # Determine appropriate status code
        error_msg = result["message"].lower()
        
        if "not found" in error_msg:
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(
            status_code=status_code,
            detail=result["message"],
        )
    
    user = result["user"]
    
    # Log audit events based on what changed
    client_ip = _get_client_ip(request)
    
    # Log role change if applicable
    if update_data.role is not None and update_data.role != old_role:
        await audit_service.log_user_role_changed(
            actor_id=current_user.id,
            target_user_id=user_id,
            old_role=old_role,
            new_role=update_data.role,
            ip_address=client_ip
        )
    
    # Log general update for other changes (email, is_active, etc.)
    changes = {}
    if update_data.email is not None and update_data.email != original_user.email:
        changes["email"] = {"old": original_user.email, "new": update_data.email}
    if update_data.is_active is not None and update_data.is_active != original_user.is_active:
        changes["is_active"] = {"old": original_user.is_active, "new": update_data.is_active}
    if update_data.email_verified is not None:
        old_verified = original_user.email_verified_at is not None
        if update_data.email_verified != old_verified:
            changes["email_verified"] = {"old": old_verified, "new": update_data.email_verified}
    
    if changes:
        await audit_service.log_user_updated(
            actor_id=current_user.id,
            target_user_id=user_id,
            email=user.email,
            changes=changes,
            ip_address=client_ip
        )
    
    await db_session.commit()
    
    return AdminUpdateUserResponse(
        id=str(user.id),
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        message=result["message"]
    )


@router.delete(
    "/users/{user_id}",
    response_model=AdminDeactivateUserResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Cannot deactivate last admin"},
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"model": AuthErrorResponse, "description": "User not found"},
    },
)
async def deactivate_user(
    request: Request,
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Deactivate a user (soft delete).
    
    - **user_id**: UUID of the user to deactivate
    
    Soft deletes the user by setting is_active to false.
    Admin access required. Cannot deactivate the last active admin.
    """
    user_service = UserService(db_session)
    audit_service = AuditService(db_session)
    
    # Get user details before deactivation for audit
    user = await user_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    
    user_email = user.email
    
    result = await user_service.deactivate_user(user_id)
    
    if not result["success"]:
        # Determine appropriate status code
        error_msg = result["message"].lower()
        
        if "not found" in error_msg:
            status_code = status.HTTP_404_NOT_FOUND
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(
            status_code=status_code,
            detail=result["message"],
        )
    
    # Log audit event (include tokens revoked count)
    tokens_revoked = result.get("tokens_revoked", 0)
    await audit_service.log_user_deactivated(
        actor_id=current_user.id,
        target_user_id=user_id,
        email=user_email,
        tokens_revoked=tokens_revoked,
        ip_address=_get_client_ip(request)
    )
    await db_session.commit()
    
    return AdminDeactivateUserResponse(
        id=str(user_id),
        message="User deactivated successfully."
    )


@router.post(
    "/users/{user_id}/reactivate",
    response_model=AdminReactivateUserResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "User already active"},
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"model": AuthErrorResponse, "description": "User not found"},
    },
)
async def reactivate_user(
    request: Request,
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_db),
):
    """
    Reactivate a deactivated user.
    
    - **user_id**: UUID of the user to reactivate
    
    Restores user access by setting is_active to true.
    Admin access required.
    """
    user_service = UserService(db_session)
    audit_service = AuditService(db_session)
    
    # Get user details before reactivation for audit
    user = await user_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    
    user_email = user.email
    
    result = await user_service.reactivate_user(user_id)
    
    if not result["success"]:
        # Determine appropriate status code
        error_msg = result["message"].lower()
        
        if "not found" in error_msg:
            status_code = status.HTTP_404_NOT_FOUND
        elif "already active" in error_msg:
            status_code = status.HTTP_400_BAD_REQUEST
        else:
            status_code = status.HTTP_400_BAD_REQUEST
        
        raise HTTPException(
            status_code=status_code,
            detail=result["message"],
        )
    
    # Log audit event
    await audit_service.log_user_reactivated(
        actor_id=current_user.id,
        target_user_id=user_id,
        email=user_email,
        ip_address=_get_client_ip(request)
    )
    await db_session.commit()
    
    return AdminReactivateUserResponse(
        id=str(user_id),
        message="User reactivated successfully."
    )
