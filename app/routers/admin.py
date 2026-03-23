"""
Admin Router.

Administrative endpoints for user management.
All endpoints require admin role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.dependencies import require_admin, CurrentUser
from app.services.user_service import UserService

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
