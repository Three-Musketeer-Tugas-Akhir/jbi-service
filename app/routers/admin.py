"""
Admin Router.

Administrative endpoints for user management.
All endpoints require admin role.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.dependencies import require_admin, CurrentUser
from app.services.user_service import UserService


# ============================================================================
# Schemas
# ============================================================================

class UserRoleUpdateRequest(BaseModel):
    """Request schema for user role update."""
    role: str = Field(..., description="New role for the user (admin, annotator, curator)")
    
    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed_roles = {'admin', 'annotator', 'curator'}
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed_roles))}")
        return v


class UserRoleUpdateResponse(BaseModel):
    """Response schema for user role update."""
    id: str = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    role: str = Field(..., description="New role")
    previous_role: Optional[str] = Field(None, description="Previous role")
    updated_at: Optional[str] = Field(None, description="Update timestamp")

router = APIRouter(prefix="/admin", tags=["admin"])


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
    user_data: dict,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new user account (Admin only).
    
    - **email**: User email address (must be unique)
    - **role**: User role (admin, annotator, curator)
    - **temporary_password**: Optional temporary password (auto-generated if not provided)
    
    Returns created user details. If password was auto-generated, it's included in response.
    An invitation email is sent to the new user.
    """
    user_service = UserService(db_session)
    
    # Extract values from request
    email = user_data.get("email")
    role = user_data.get("role")
    temporary_password = user_data.get("temporary_password")
    
    # Validate required fields
    if not email:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Email is required"
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
            email_verified=False
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
        error_msg = result["message"]
        
        # Check for self-modification (400)
        if "own role" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        # Check for same role (400)
        if "already has role" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        # Check for invalid role (400 - though Pydantic should catch this)
        if "invalid role" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
        
        # Check for user not found (404)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        
        # Other errors
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
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
