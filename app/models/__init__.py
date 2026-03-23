"""
Models package.

NOTE: Pydantic schemas have been moved to app.schemas per architecture.
SQLAlchemy models are in app.db.models.

This module maintains backward compatibility for existing imports.
"""

# Re-export Pydantic schemas for backward compatibility
from app.schemas import (
    # Job schemas
    JobCreateResponse,
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
    # Auth schemas
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
    UserProfileResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    ChangePasswordRequest,
    ChangePasswordResponse,
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

# Re-export job domain models
from app.models.job import (
    Job,
    JobStatus,
    JobProgress,
    can_transition,
    is_terminal,
    TERMINAL_STATES,
    VALID_TRANSITIONS,
)

# Re-export job store
from app.models.job_store import JobStore

# Re-export serializers
from app.models.result_serializer import ResultSerializer

__all__ = [
    # Pydantic schemas
    "JobCreateResponse",
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
    "UserProfileResponse",
    "UpdateProfileRequest",
    "UpdateProfileResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
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
    # Domain models
    "Job",
    "JobStatus",
    "JobProgress",
    "can_transition",
    "is_terminal",
    "TERMINAL_STATES",
    "VALID_TRANSITIONS",
    # Storage
    "JobStore",
    # Serializers
    "ResultSerializer",
]
