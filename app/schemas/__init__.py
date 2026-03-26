"""
Pydantic Schemas for API.

Request/response models for API validation and serialization.
Organized by domain: auth, job, annotation.
"""

# Auth schemas
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    AuthErrorResponse,
    RefreshRequest,
    RefreshResponse,
    LogoutRequest,
    LogoutResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
    ResendVerificationRequest,
    ResendVerificationResponse,
    EmailVerificationStatusResponse,
    CurrentUserResponse,
)

# Job schemas
from app.schemas.job import (
    JobCreate,
    JobCreateResponse,
    JobResponse,
    JobProgressResponse,
    JobStatusResponse,
    JobCancelResponse,
    VideoMetadataResponse,
    DetectionSummaryResponse,
    BboxResponse,
    SegmentResponse,
    JobResultsResponse,
    JobListResponse,
    HealthResponse,
    ErrorResponse,
    SignLanguageCategory,
    CategoryUpdateResponse,
)

# User/Profile schemas (from auth domain)
from app.schemas.auth import (
    UserProfileResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
)

# Admin schemas (from auth domain)
from app.schemas.auth import (
    AdminUserListItem,
    AdminUserListResponse,
    AdminCreateUserRequest,
    AdminCreateUserResponse,
    AdminUserDetailResponse,
    AdminUpdateUserRequest,
    AdminUpdateUserResponse,
    AdminDeactivateUserResponse,
    AdminReactivateUserResponse,
    UserRoleUpdateRequest,
    UserRoleUpdateResponse,
)

__all__ = [
    # Auth
    "LoginRequest",
    "LoginResponse",
    "AuthErrorResponse",
    "RefreshRequest",
    "RefreshResponse",
    "LogoutRequest",
    "LogoutResponse",
    "ForgotPasswordRequest",
    "ForgotPasswordResponse",
    "ResetPasswordRequest",
    "ResetPasswordResponse",
    "VerifyEmailRequest",
    "VerifyEmailResponse",
    "ResendVerificationRequest",
    "ResendVerificationResponse",
    "EmailVerificationStatusResponse",
    "CurrentUserResponse",
    # User/Profile
    "UserProfileResponse",
    "UpdateProfileRequest",
    "UpdateProfileResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
    # Admin
    "AdminUserListItem",
    "AdminUserListResponse",
    "AdminCreateUserRequest",
    "AdminCreateUserResponse",
    "AdminUserDetailResponse",
    "AdminUpdateUserRequest",
    "AdminUpdateUserResponse",
    "AdminDeactivateUserResponse",
    "AdminReactivateUserResponse",
    "UserRoleUpdateRequest",
    "UserRoleUpdateResponse",
    # Job
    "JobCreate",
    "JobCreateResponse",
    "JobResponse",
    "JobProgressResponse",
    "JobStatusResponse",
    "JobCancelResponse",
    "VideoMetadataResponse",
    "DetectionSummaryResponse",
    "BboxResponse",
    "SegmentResponse",
    "JobResultsResponse",
    "JobListResponse",
    "HealthResponse",
    "ErrorResponse",
    "SignLanguageCategory",
    "CategoryUpdateResponse",
]
