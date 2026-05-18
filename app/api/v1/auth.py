"""
Authentication Router.

Provides authentication endpoints for user login, token refresh, logout,
password reset, and email verification.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_async_session
from app.schemas import (
    LoginRequest, LoginResponse, RefreshRequest, RefreshResponse,
    LogoutRequest, LogoutResponse, AuthErrorResponse,
    ForgotPasswordRequest, ForgotPasswordResponse,
    ResetPasswordRequest, ResetPasswordResponse,
    ForceChangePasswordRequest, ForceChangePasswordResponse,
    VerifyEmailRequest, VerifyEmailResponse,
    ResendVerificationRequest, ResendVerificationResponse,
    EmailVerificationStatusResponse,
    CurrentUserResponse,
)
from app.api.deps import (
    get_current_user,
    require_role,
    require_admin,
    require_annotator,
    require_curator,
    require_annotator_or_curator,
    CurrentUser,
)
from app.services.auth_service import jwt_auth_service
from app.services.email_verification_service import EmailVerificationService
from app.services.password_reset_service import PasswordResetService
from app.services.token_refresh_service import TokenRefreshService
from app.services.user_service import UserService
from app.middleware.rate_limiter import record_failed_login

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"model": AuthErrorResponse, "description": "Invalid credentials"},
        422: {"description": "Validation error"},
        429: {"model": AuthErrorResponse, "description": "Rate limit exceeded"},
    },
)
async def login(
    request: Request,
    login_data: LoginRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Authenticate user and return JWT tokens.
    
    - **email**: User email address
    - **password**: User password
    
    Returns access_token and refresh_token on success.
    Returns generic error message on failure (prevents user enumeration).
    """
    try:
        # Authenticate user
        user_service = UserService(db_session)
        success, user, error_msg = await user_service.authenticate(
            login_data.email, 
            login_data.password
        )
        
        if not success or user is None:
            # Record failed attempt for rate limiting
            try:
                record_failed_login(request)
            except Exception:
                # Don't let rate limiting errors mask auth failure
                pass
            
            # Check for specific error message (e.g., deactivated account)
            if error_msg == "Account is deactivated":
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is deactivated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        # Get primary role (first in list) for backward compatibility
        user_roles = [r.name for r in user.roles] if user.roles else []
        primary_role = user_roles[0] if user_roles else "annotator"
        
        # Generate tokens with primary role
        access_token = jwt_auth_service.create_access_token(user.id, primary_role)
        refresh_token, _ = jwt_auth_service.create_refresh_token(user.id, primary_role)
        
        # Store refresh token in database for rotation tracking
        token_refresh_service = TokenRefreshService(db_session)
        await token_refresh_service.store_refresh_token(refresh_token, user.id)
        
        return LoginResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
            must_change_password=user.must_change_password
        )
    except HTTPException:
        raise
    except Exception:
        # Log the error internally but return generic message
        import logging
        logging.getLogger(__name__).exception("Login error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during authentication"
        )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    responses={
        401: {"model": AuthErrorResponse, "description": "Invalid or expired refresh token"},
        422: {"description": "Validation error"},
    },
)
async def refresh(
    request: Request,
    refresh_data: RefreshRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Refresh access token using refresh token with rotation.
    
    - **refresh_token**: Valid refresh token
    
    Returns new access_token and refresh_token pair.
    Old refresh token is revoked and replaced with new one.
    """
    try:
        token_refresh_service = TokenRefreshService(db_session)
        
        result = await token_refresh_service.rotate_refresh_token(
            refresh_data.refresh_token
        )
        
        if not result["success"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=result["message"],
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        return RefreshResponse(
            access_token=result["access_token"],
            refresh_token=result["refresh_token"],
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Token refresh error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred during token refresh"
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={
        401: {"model": AuthErrorResponse, "description": "Invalid token"},
        422: {"description": "Validation error"},
    },
)
async def logout(
    request: Request,
    logout_data: LogoutRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Logout user and revoke refresh token.
    
    - **refresh_token**: Refresh token to revoke
    
    Returns success message. Access token should be discarded client-side.
    """
    try:
        token_refresh_service = TokenRefreshService(db_session)
        
        result = await token_refresh_service.revoke_refresh_token(
            logout_data.refresh_token
        )
        
        if not result["success"]:
            # Still return 200 even if token was already revoked/invalid
            # Prevents token probing attacks
            pass
        
        return LogoutResponse(
            message="Logged out successfully"
        )
        
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Logout error")
        # Still return success to prevent information leakage
        return LogoutResponse(
            message="Logged out successfully"
        )


@router.post(
    "/forgot-password",
    response_model=ForgotPasswordResponse,
    responses={
        429: {"model": AuthErrorResponse, "description": "Rate limit exceeded"},
        422: {"description": "Validation error"},
    },
)
async def forgot_password(
    request: Request,
    forgot_data: ForgotPasswordRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Request a password reset email.
    
    - **email**: User email address
    
    Returns generic success message even if email not found
    to prevent user enumeration attacks.
    Rate limited to 3 requests per hour per user.
    """
    try:
        password_reset_service = PasswordResetService(db_session)
        
        result = await password_reset_service.request_password_reset(
            forgot_data.email
        )
        
        if not result["success"]:
            # Rate limited
            retry_after = result.get("retry_after", 3600)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=result["message"],
                headers={"Retry-After": str(retry_after)},
            )
        
        return ForgotPasswordResponse(
            message=result["message"]
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Forgot password error")
        # Return generic success to prevent information leakage
        return ForgotPasswordResponse(
            message="If an account exists with this email, you will receive reset instructions."
        )


@router.post(
    "/reset-password",
    response_model=ResetPasswordResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid token or weak password"},
        401: {"model": AuthErrorResponse, "description": "Invalid or expired token"},
        422: {"description": "Validation error"},
    },
)
async def reset_password(
    request: Request,
    reset_data: ResetPasswordRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Reset password using a valid reset token.
    
    - **token**: Reset token received via email
    - **new_password**: New password (min 8 chars, must include uppercase, lowercase, digit, special char)
    
    Returns success message on valid reset.
    All existing tokens are invalidated on successful reset.
    """
    try:
        password_reset_service = PasswordResetService(db_session)
        
        result = await password_reset_service.reset_password(
            reset_data.token,
            reset_data.new_password
        )
        
        if not result["success"]:
            # Determine appropriate status code based on error
            error_msg = result["message"].lower()
            
            if "expired" in error_msg or "already been used" in error_msg:
                status_code = status.HTTP_401_UNAUTHORIZED
            elif "at least" in error_msg or "must contain" in error_msg or "too common" in error_msg:
                status_code = status.HTTP_400_BAD_REQUEST
            else:
                status_code = status.HTTP_400_BAD_REQUEST
            
            raise HTTPException(
                status_code=status_code,
                detail=result["message"],
            )
        
        return ResetPasswordResponse(
            message=result["message"]
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Reset password error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while resetting your password. Please try again."
        )


@router.post(
    "/force-change-password",
    response_model=ForceChangePasswordResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid input or weak password"},
        401: {"model": AuthErrorResponse, "description": "Not authenticated or wrong current password"},
        422: {"description": "Validation error"},
    },
)
async def force_change_password(
    request: Request,
    password_data: ForceChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Force change password on first login.
    
    - **current_password**: The temporary password provided by admin
    - **new_password**: New password (min 8 chars, must include uppercase, lowercase, digit, special char)
    
    Requires valid JWT token from initial login.
    """
    try:
        user_service = UserService(db_session)
        
        # Extract IP address for audit logging
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(",")[0].strip()
        elif request.client:
            ip_address = request.client.host
        else:
            ip_address = None
            
        user_agent = request.headers.get("User-Agent")
        
        result = await user_service.force_change_password(
            user_id=current_user.id,
            current_password=password_data.current_password,
            new_password=password_data.new_password,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        if not result["success"]:
            # Determine appropriate status code
            error_msg = result["message"].lower()
            
            if "incorrect" in error_msg:
                status_code = status.HTTP_401_UNAUTHORIZED
            else:
                status_code = status.HTTP_400_BAD_REQUEST
            
            raise HTTPException(
                status_code=status_code,
                detail=result["message"],
            )
        
        return ForceChangePasswordResponse(
            message=result["message"]
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Force change password error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while changing your password. Please try again."
        )


@router.post(
    "/verify-email",
    response_model=VerifyEmailResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Invalid token"},
        401: {"model": AuthErrorResponse, "description": "Expired or used token"},
        422: {"description": "Validation error"},
    },
)
async def verify_email(
    request: Request,
    verify_data: VerifyEmailRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Verify email address using a verification token.
    
    - **token**: Verification token received via email
    
    Returns success message on valid verification.
    All existing verification tokens are invalidated on success.
    """
    try:
        email_verification_service = EmailVerificationService(db_session)
        
        result = await email_verification_service.verify_email(
            verify_data.token
        )
        
        if not result["success"]:
            error_msg = result["message"].lower()
            
            if "expired" in error_msg or "already been used" in error_msg:
                status_code = status.HTTP_401_UNAUTHORIZED
            else:
                status_code = status.HTTP_400_BAD_REQUEST
            
            raise HTTPException(
                status_code=status_code,
                detail=result["message"],
            )
        
        return VerifyEmailResponse(
            message=result["message"]
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Verify email error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while verifying your email. Please try again."
        )


@router.post(
    "/resend-verification",
    response_model=ResendVerificationResponse,
    responses={
        400: {"model": AuthErrorResponse, "description": "Already verified or user not found"},
        429: {"model": AuthErrorResponse, "description": "Rate limit exceeded"},
        422: {"description": "Validation error"},
    },
)
async def resend_verification(
    request: Request,
    resend_data: ResendVerificationRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Resend email verification email.
    
    - **email**: User email address
    
    Returns success message if email sent.
    Rate limited to 5 requests per 24 hours per user.
    """
    try:
        # First, find the user by email
        user_service = UserService(db_session)
        user = await user_service.get_by_email(resend_data.email)
        
        if user is None:
            # Return generic message to prevent user enumeration
            return ResendVerificationResponse(
                message="If an account exists with this email and is not verified, you will receive verification instructions."
            )
        
        email_verification_service = EmailVerificationService(db_session)
        
        result = await email_verification_service.send_verification_email(
            user.id
        )
        
        if not result["success"]:
            error_msg = result["message"].lower()
            
            if "already verified" in error_msg:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["message"],
                )
            elif "try again later" in error_msg:
                retry_after = result.get("retry_after", 86400)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=result["message"],
                    headers={"Retry-After": str(retry_after)},
                )
            else:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=result["message"],
                )
        
        return ResendVerificationResponse(
            message=result["message"]
        )
        
    except HTTPException:
        raise
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Resend verification error")
        # Return generic success to prevent information leakage
        return ResendVerificationResponse(
            message="If an account exists with this email and is not verified, you will receive verification instructions."
        )


# ============================================================================
# Protected Endpoint Examples (for testing RBAC)
# ============================================================================

@router.get("/me", response_model=CurrentUserResponse)
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Get current authenticated user information.
    
    Requires valid JWT token. Any authenticated user can access.
    """
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.role,
    )


@router.get("/admin-only", response_model=dict)
async def admin_only_endpoint(
    current_user: CurrentUser = Depends(require_admin)
):
    """
    Admin-only endpoint.
    
    Only users with 'admin' role can access.
    """
    return {
        "message": "Admin access granted",
        "user_id": str(current_user.id),
    }


@router.get("/annotator-only", response_model=dict)
async def annotator_only_endpoint(
    current_user: CurrentUser = Depends(require_annotator)
):
    """
    Annotator-only endpoint.
    
    Only users with 'annotator' role can access.
    """
    return {
        "message": "Annotator access granted",
        "user_id": str(current_user.id),
    }


@router.get("/curator-only", response_model=dict)
async def curator_only_endpoint(
    current_user: CurrentUser = Depends(require_curator)
):
    """
    Curator-only endpoint.
    
    Only users with 'curator' role can access.
    """
    return {
        "message": "Curator access granted",
        "user_id": str(current_user.id),
    }


@router.get("/annotator-or-curator", response_model=dict)
async def annotator_or_curator_endpoint(
    current_user: CurrentUser = Depends(require_annotator_or_curator)
):
    """
    Annotator or Curator endpoint.
    
    Users with either 'annotator' or 'curator' role can access.
    """
    return {
        "message": "Annotator or Curator access granted",
        "user_id": str(current_user.id),
        "role": current_user.role,
    }


@router.get("/multi-role-demo", response_model=dict)
async def multi_role_demo_endpoint(
    current_user: CurrentUser = Depends(require_role("admin", "curator"))
):
    """
    Multi-role endpoint example.
    
    Demonstrates require_role with multiple allowed roles.
    Only 'admin' or 'curator' can access.
    """
    return {
        "message": "Admin or Curator access granted",
        "user_id": str(current_user.id),
        "role": current_user.role,
    }
