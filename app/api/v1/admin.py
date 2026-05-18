"""
Admin Router.

Administrative endpoints for user management.
All endpoints require admin role.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List

from app.db.session import get_async_session
from app.api.deps import require_admin, CurrentUser
from app.services.user_service import UserService


# ============================================================================
# Schemas
# ============================================================================

class UserRoleUpdateRequest(BaseModel):
    """Request schema for user role update."""
    role: str = Field(..., description="New role for the user (admin, annotator, curator)")


class UserRoleUpdateResponse(BaseModel):
    """Response schema for user role update."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="New role")
    previous_role: Optional[str] = Field(None, description="Previous role")
    updated_at: Optional[str] = Field(None, description="Update timestamp")


class UserDeactivateResponse(BaseModel):
    """Response schema for user deactivation."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    is_active: bool = Field(..., description="User active status")
    deactivated_at: Optional[str] = Field(None, description="Deactivation timestamp")
    message: str = Field(..., description="Status message")
    tokens_revoked: int = Field(0, description="Number of refresh tokens revoked")


class UserListItem(BaseModel):
    """User item for list views."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="User active status")
    created_at: str = Field(..., description="Creation timestamp")
    
    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    """Response for user list endpoint."""
    items: List[UserListItem] = Field(..., description="List of users")
    total: int = Field(..., description="Total number of users")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total number of pages")
    has_next: bool = Field(..., description="Whether there is a next page")
    has_prev: bool = Field(..., description="Whether there is a previous page")


class UserDetailResponse(BaseModel):
    """Detailed user response."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="User role")
    is_active: bool = Field(..., description="User active status")
    created_at: str = Field(..., description="Creation timestamp")
    updated_at: Optional[str] = Field(None, description="Last update timestamp")
    
    model_config = {"from_attributes": True}

router = APIRouter(prefix="/admin", tags=["admin"])


from app.schemas.auth import AdminCreateUserRequest, PasswordChangeHistoryResponse

@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"description": "Admin access required"},
        409: {"description": "User already exists"},
        422: {"description": "Validation error"},
    },
)
async def create_user(
    user_data: AdminCreateUserRequest,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new user account (Admin only).
    
    Can either provide exact email and temporary_password, or provide first_name
    and last_name to auto-generate the email and password.
    
    Returns created user details. If password was auto-generated, it's included in response.
    An invitation email is sent to the new user.
    """
    user_service = UserService(db_session)
    
    # Extract values from request
    email = user_data.email
    role = user_data.roles[0] if user_data.roles else "annotator"
    temporary_password = user_data.password
    first_name = user_data.first_name
    last_name = user_data.last_name
    
    # Validate required fields
    if not email and not (first_name and last_name):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either email or both first_name and last_name are required"
        )
    
    if not role:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Role is required"
        )
    
    try:
        result = await user_service.create_user(
            email=email,
            password=temporary_password,
            roles=[role],
            is_active=True,
            email_verified=False,
            first_name=first_name,
            last_name=last_name
        )
        
        if not result["success"]:
            error_msg = result["message"]
            
            # Check if it's a duplicate email error
            if "already exists" in error_msg.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User with this email already exists"
                )
            
            # Other validation errors
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=error_msg
            )
        
        user = result["user"]
        response_data = {
            "id": str(user.id),
            "email": user.email,
            "role": role,
            "is_active": user.is_active,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        
        # Include generated password if auto-generated
        if "temporary_password" in result:
            response_data["temporary_password"] = result["temporary_password"]
        
        return response_data
        
    except HTTPException:
        raise
    except IntegrityError:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
    except Exception as e:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating the user"
        )


@router.put(
    "/users/{user_id}/role",
    response_model=UserRoleUpdateResponse,
    responses={
        400: {"description": "Bad request - self-modification or same role"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
        422: {"description": "Validation error - invalid role"},
    },
)
async def update_user_role(
    user_id: UUID,
    role_data: UserRoleUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Update a user's role (Admin only).
    
    - **user_id**: UUID of the user to update
    - **role**: New role (admin, annotator, curator)
    
    The admin cannot modify their own role. The previous role is returned for audit purposes.
    Current sessions remain valid (new role takes effect on next token refresh).
    
    Returns the updated user with their new role and previous role.
    """
    # Validate role manually to return 400 (not 422) per spec
    allowed_roles = {'admin', 'annotator', 'curator'}
    if role_data.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role specified. Must be one of: {', '.join(sorted(allowed_roles))}"
        )
    
    user_service = UserService(db_session)
    
    # Extract IP address for audit logging
    # Check X-Forwarded-For header first (for users behind proxy/load balancer)
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        # Take the first IP if multiple are present
        ip_address = x_forwarded_for.split(",")[0].strip()
    elif request.client:
        ip_address = request.client.host
    else:
        ip_address = None
    
    result = await user_service.update_role(
        admin_id=current_user.user_id,
        target_user_id=user_id,
        new_role=role_data.role,
        ip_address=ip_address
    )
    
    if not result["success"]:
        error_code = result.get("error_code", "UNKNOWN_ERROR")
        error_msg = result["message"]
        
        # Map error codes to HTTP status codes
        error_mapping = {
            "SELF_MODIFICATION": status.HTTP_400_BAD_REQUEST,
            "SAME_ROLE": status.HTTP_400_BAD_REQUEST,
            "INVALID_ROLE": status.HTTP_400_BAD_REQUEST,
            "INACTIVE_USER": status.HTTP_400_BAD_REQUEST,
            "USER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        }
        
        http_status = error_mapping.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        raise HTTPException(
            status_code=http_status,
            detail=error_msg
        )
    
    user = result["user"]
    return UserRoleUpdateResponse(
        id=str(user.id),
        email=user.email,
        role=role_data.role,
        previous_role=result.get("previous_role"),
        updated_at=user.updated_at.isoformat() if user.updated_at else None
    )


@router.delete(
    "/users/{user_id}",
    response_model=UserDeactivateResponse,
    responses={
        400: {"description": "Cannot deactivate own account"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def deactivate_user(
    user_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Deactivate a user account (Admin only).
    
    - **user_id**: UUID of user to deactivate
    
    Performs soft delete (sets is_active=false).
    Preserves all user data and audit history.
    Revokes all refresh tokens for the user.
    """
    user_service = UserService(db_session)
    
    # Extract IP address for audit logging
    x_forwarded_for = request.headers.get("X-Forwarded-For")
    if x_forwarded_for:
        ip_address = x_forwarded_for.split(",")[0].strip()
    elif request.client:
        ip_address = request.client.host
    else:
        ip_address = None
    
    result = await user_service.deactivate_user(
        admin_id=current_user.user_id,
        target_user_id=user_id,
        ip_address=ip_address
    )
    
    if not result["success"]:
        error_code = result.get("error_code", "UNKNOWN_ERROR")
        error_msg = result["message"]
        
        # Map error codes to HTTP status codes
        error_mapping = {
            "SELF_DEACTIVATION": status.HTTP_400_BAD_REQUEST,
            "USER_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        }
        
        http_status = error_mapping.get(error_code, status.HTTP_400_BAD_REQUEST)
        raise HTTPException(
            status_code=http_status,
            detail=error_msg
        )
    
    user = result["user"]
    return UserDeactivateResponse(
        id=str(user.id),
        email=user.email,
        is_active=user.is_active,
        deactivated_at=user.updated_at.isoformat() if user.updated_at else None,
        message=result["message"],
        tokens_revoked=result.get("tokens_revoked", 0)
    )


@router.get(
    "/users",
    response_model=UserListResponse,
    responses={
        403: {"description": "Admin access required"},
    },
)
async def list_users(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    role: Optional[str] = Query(None, description="Filter by role (admin, annotator, curator)"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    sort_by: str = Query("created_at", description="Sort field (created_at, email)"),
    sort_order: str = Query("desc", description="Sort direction (asc, desc)"),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    List all users with filtering and pagination (Admin only).
    
    Query Parameters:
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **role**: Filter by role (admin, annotator, curator)
    - **is_active**: Filter by active status (true/false)
    - **sort_by**: Sort field (created_at, email)
    - **sort_order**: Sort direction (asc, desc)
    
    Returns paginated list of users.
    """
    user_service = UserService(db_session)
    
    try:
        result = await user_service.list_users(
            page=page,
            page_size=page_size,
            role=role,
            is_active=is_active,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        # Convert users to response items
        items = []
        for user in result.users:
            # Get primary role
            user_roles = [r.name for r in user.roles] if user.roles else []
            primary_role = user_roles[0] if user_roles else "annotator"
            
            items.append(UserListItem(
                id=str(user.id),
                email=user.email,
                role=primary_role,
                is_active=user.is_active,
                created_at=user.created_at.isoformat() if user.created_at else ""
            ))
        
        return UserListResponse(
            items=items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
            has_next=result.has_next,
            has_prev=result.has_prev
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/users/{user_id}",
    response_model=UserDetailResponse,
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed user information (Admin only).
    
    - **user_id**: UUID of user to retrieve
    
    Returns detailed user information.
    """
    user_service = UserService(db_session)
    
    user = await user_service.get_user_by_id(user_id)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Get primary role
    user_roles = [r.name for r in user.roles] if user.roles else []
    primary_role = user_roles[0] if user_roles else "annotator"
    
    return UserDetailResponse(
        id=str(user.id),
        email=user.email,
        role=primary_role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else "",
        updated_at=user.updated_at.isoformat() if user.updated_at else None
    )


@router.get(
    "/users/{user_id}/password-history",
    response_model=PasswordChangeHistoryResponse,
    responses={
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user_password_history(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get a user's password change history (Admin only).
    
    - **user_id**: UUID of user to retrieve history for
    
    Returns a list of password change events.
    """
    user_service = UserService(db_session)
    
    # Ensure user exists
    user = await user_service.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
        
    result = await user_service.get_password_change_history(user_id)
    
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("message", "Error fetching history")
        )
        
    history = result["history"]
    
    return PasswordChangeHistoryResponse(
        history=[
            {
                "id": str(item.id),
                "changed_at": item.changed_at.isoformat(),
                "change_type": item.change_type,
                "ip_address": item.ip_address,
                "was_temporary": item.was_temporary
            } for item in history
        ]
    )

# ============================================================================
# System Monitoring Endpoints (Story 2.10)
# ============================================================================

from app.services.metrics_service import get_metrics_service, MetricsService
from app.services.config_service import get_config_service, ConfigService
from app.schemas.admin import (
    SystemConfigResponse,
    SystemConfigUpdateRequest,
    SystemMetricsResponse,
    FailedJobsResponse
)


@router.get(
    "/system/config",
    response_model=SystemConfigResponse,
    summary="Get pipeline configuration",
    tags=["Admin - System"],
)
async def get_system_config(
    db_session: AsyncSession = Depends(get_async_session),
    current_user: CurrentUser = Depends(require_admin)
):
    """Get current pipeline configuration parameters."""
    config_service = get_config_service(db_session)
    config = await config_service.get_config()
    
    return SystemConfigResponse(
        min_segment_duration=int(config["min_segment_duration"]),
        max_concurrent_jobs=int(config["max_concurrent_jobs"]),
        queue_max_depth=int(config["queue_max_depth"]),
        asr_model_default=config["asr_model_default"],
        asr_compute_type=config.get("asr_compute_type", "int8"),
        jbi_buffer_seconds=int(config.get("jbi_buffer_seconds", "2"))
    )


@router.put(
    "/system/config",
    response_model=SystemConfigResponse,
    summary="Update pipeline configuration",
    tags=["Admin - System"],
)
async def update_system_config(
    updates: SystemConfigUpdateRequest,
    db_session: AsyncSession = Depends(get_async_session),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Update pipeline configuration parameters.
    
    Changes take effect for new jobs only.
    Current jobs continue with previous values.
    """
    config_service = get_config_service(db_session)
    
    # Convert request to dict of strings, excluding unset fields
    update_dict = updates.model_dump(exclude_unset=True)
    update_dict = {k: str(v) for k, v in update_dict.items()}
    
    await config_service.update_config(
        update_dict,
        updated_by=str(current_user.user_id)
    )
    
    # Return updated config
    config = await config_service.get_config()
    return SystemConfigResponse(
        min_segment_duration=int(config["min_segment_duration"]),
        max_concurrent_jobs=int(config["max_concurrent_jobs"]),
        queue_max_depth=int(config["queue_max_depth"]),
        asr_model_default=config["asr_model_default"],
        asr_compute_type=config.get("asr_compute_type", "int8"),
        jbi_buffer_seconds=int(config.get("jbi_buffer_seconds", "2"))
    )


@router.get(
    "/system/metrics",
    response_model=SystemMetricsResponse,
    summary="Get system metrics",
    tags=["Admin - System"],
)
async def get_system_metrics(
    db_session: AsyncSession = Depends(get_async_session),
    current_user: CurrentUser = Depends(require_admin)
):
    """Get aggregated system metrics."""
    metrics_service = get_metrics_service(db_session)
    metrics = await metrics_service.get_system_metrics()
    
    return SystemMetricsResponse(**metrics)


@router.get(
    "/jobs/failed",
    response_model=FailedJobsResponse,
    summary="Get failed jobs list",
    tags=["Admin - Jobs"],
)
async def get_failed_jobs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db_session: AsyncSession = Depends(get_async_session),
    current_user: CurrentUser = Depends(require_admin)
):
    """Get list of failed jobs with retry information."""
    metrics_service = get_metrics_service(db_session)
    result = await metrics_service.get_failed_jobs(limit=limit, offset=offset)
    
    return FailedJobsResponse(**result)


# ============================================================================
# ASR Confidence Metrics Endpoint (Story 3.8)
# ============================================================================

from app.schemas.asr_review import ASRConfidenceStatsResponse
from app.services.asr_review_service import ASRReviewService


@router.get(
    "/asr/confidence-stats",
    response_model=ASRConfidenceStatsResponse,
    summary="Get ASR confidence statistics",
    tags=["Admin - ASR"],
)
async def get_asr_confidence_stats(
    db_session: AsyncSession = Depends(get_async_session),
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Get ASR confidence score statistics for all segments.
    
    Returns aggregate statistics including:
    - Average confidence score
    - Minimum and maximum confidence scores
    - Distribution across confidence levels
      - low: < 0.5
      - medium: 0.5 - 0.9
      - high: >= 0.9
    """
    asr_service = ASRReviewService(db_session)
    stats = await asr_service.get_confidence_stats()
    
    return ASRConfidenceStatsResponse(**stats)
