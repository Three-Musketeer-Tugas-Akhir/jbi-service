"""
Authentication and User Schemas.

Pydantic models for auth API requests and responses.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel


# =============================================================================
# Authentication Schemas
# =============================================================================

class LoginRequest(BaseModel):
    """Request body for POST /api/v1/auth/login."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Response for successful login."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires
    must_change_password: bool = False  # True if user must change password


class AuthErrorResponse(BaseModel):
    """Response for authentication errors."""
    error: str
    detail: str


class RefreshRequest(BaseModel):
    """Request body for POST /api/v1/auth/refresh."""
    refresh_token: str


class RefreshResponse(BaseModel):
    """Response for successful token refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires


class LogoutRequest(BaseModel):
    """Request body for POST /api/v1/auth/logout."""
    refresh_token: str


class LogoutResponse(BaseModel):
    """Response for successful logout."""
    message: str


class ForgotPasswordRequest(BaseModel):
    """Request body for POST /api/v1/auth/forgot-password."""
    email: str


class ForgotPasswordResponse(BaseModel):
    """Response for password reset request."""
    message: str
    retry_after: Optional[int] = None  # Seconds until retry allowed (if rate limited)


class ResetPasswordRequest(BaseModel):
    """Request body for POST /api/v1/auth/reset-password."""
    token: str
    new_password: str


class ResetPasswordResponse(BaseModel):
    """Response for successful password reset."""
    message: str


class ForceChangePasswordRequest(BaseModel):
    """Request body for POST /api/v1/auth/force-change-password."""
    current_password: str
    new_password: str


class ForceChangePasswordResponse(BaseModel):
    """Response for successful forced password change."""
    message: str


# =============================================================================
# Email Verification Schemas
# =============================================================================

class VerifyEmailRequest(BaseModel):
    """Request body for POST /api/v1/auth/verify-email."""
    token: str


class VerifyEmailResponse(BaseModel):
    """Response for email verification."""
    message: str


class ResendVerificationRequest(BaseModel):
    """Request body for POST /api/v1/auth/resend-verification."""
    email: str


class ResendVerificationResponse(BaseModel):
    """Response for resend verification email request."""
    message: str
    retry_after: Optional[int] = None  # Seconds until retry allowed (if rate limited)


class EmailVerificationStatusResponse(BaseModel):
    """Response for email verification status check."""
    is_verified: bool
    verified_at: Optional[str] = None  # ISO format datetime


class CurrentUserResponse(BaseModel):
    """Response for current user info from token."""
    id: str
    email: str
    role: str


# =============================================================================
# User Profile Schemas
# =============================================================================

class UserProfileResponse(BaseModel):
    """Response for GET /api/v1/users/me."""
    id: str
    email: str
    roles: list[str]
    is_active: bool
    email_verified: bool
    must_change_password: bool = False
    created_at: str  # ISO format datetime
    updated_at: str  # ISO format datetime


class UpdateProfileRequest(BaseModel):
    """Request body for PATCH /api/v1/users/me."""
    email: Optional[str] = None
    # TODO: Add more fields when User model is extended (name, avatar, etc.)


class UpdateProfileResponse(BaseModel):
    """Response for successful profile update."""
    id: str
    email: str
    message: str


class ChangePasswordRequest(BaseModel):
    """Request body for POST /api/v1/users/me/password."""
    current_password: str
    new_password: str


class ChangePasswordResponse(BaseModel):
    """Response for successful password change."""
    message: str


# =============================================================================
# Admin User Management Schemas
# =============================================================================

class AdminUserListItem(BaseModel):
    """User item in admin user list."""
    id: str
    email: str
    roles: list[str]
    is_active: bool
    email_verified: bool
    created_at: str
    updated_at: str


class AdminUserListResponse(BaseModel):
    """Response for GET /api/v1/admin/users."""
    users: list[AdminUserListItem]
    total: int
    limit: int
    offset: int


class AdminCreateUserRequest(BaseModel):
    """Request body for POST /api/v1/admin/users."""
    email: Optional[str] = None  # Optional if first_name and last_name provided
    password: Optional[str] = None  # Optional, auto-generated if not provided
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    roles: list[str] = ["annotator"]  # Default roles
    is_active: bool = True
    email_verified: bool = False


class AdminCreateUserResponse(BaseModel):
    """Response for successful user creation."""
    id: str
    email: str
    roles: list[str]
    message: str
    temporary_password: Optional[str] = None  # Only present if auto-generated


class AdminUserDetailResponse(BaseModel):
    """Response for GET /api/v1/admin/users/{id}."""
    id: str
    email: str
    roles: list[str]
    is_active: bool
    email_verified: bool
    created_at: str
    updated_at: str


class PasswordChangeLogItem(BaseModel):
    """Item for password change history."""
    id: str
    changed_at: str
    change_type: str
    ip_address: Optional[str] = None
    was_temporary: bool


class PasswordChangeHistoryResponse(BaseModel):
    """Response for GET /api/v1/admin/users/{id}/password-history."""
    history: list[PasswordChangeLogItem]


class AdminUpdateUserRequest(BaseModel):
    """Request body for PATCH /api/v1/admin/users/{id}."""
    email: Optional[str] = None
    roles: Optional[list[str]] = None
    is_active: Optional[bool] = None
    email_verified: Optional[bool] = None


class AdminUpdateUserResponse(BaseModel):
    """Response for successful user update."""
    id: str
    email: str
    roles: list[str]
    is_active: bool
    message: str
    previous_roles: Optional[list[str]] = None  # Only present when roles are changed


class AdminDeactivateUserResponse(BaseModel):
    """Response for successful user deactivation."""
    id: str
    message: str


class AdminReactivateUserResponse(BaseModel):
    """Response for successful user reactivation."""
    id: str
    message: str


# =============================================================================
# Role Update Schemas
# =============================================================================

class UserRoleUpdateRequest(BaseModel):
    """Request body for PUT /api/v1/admin/users/{id}/role."""
    role: str


class UserRoleUpdateResponse(BaseModel):
    """Response for successful role update."""
    id: str
    email: str
    role: str
    previous_role: str
    updated_at: str
