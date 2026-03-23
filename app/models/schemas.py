from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class JobCreateResponse(BaseModel):
    """Response for POST /api/v1/jobs."""
    job_id: str
    status: str
    video_title: str
    created_at: datetime


class JobProgressResponse(BaseModel):
    """Progress details for a processing job."""
    phase: str
    current: int
    total: int
    percent: float


class JobStatusResponse(BaseModel):
    """Response for GET /api/v1/jobs/{job_id}."""
    job_id: str
    status: str
    video_title: Optional[str] = None
    progress: Optional[JobProgressResponse] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobCancelResponse(BaseModel):
    """Response for DELETE /api/v1/jobs/{job_id}."""
    job_id: str
    status: str


class VideoMetadataResponse(BaseModel):
    """Video file metadata."""
    fps: float
    total_frames: int
    duration_seconds: float


class DetectionSummaryResponse(BaseModel):
    """Summary statistics of the detection phase."""
    total_seconds_scanned: int
    seconds_with_detection: int


class BboxResponse(BaseModel):
    """Bounding box in pixel coordinates."""
    x_min: float
    y_min: float
    width: float
    height: float


class SegmentResponse(BaseModel):
    """A single detected segment with download link."""
    index: int
    start_time: str
    end_time: str
    start_seconds: int
    end_seconds: int
    duration_seconds: int
    bbox: BboxResponse
    download_url: str


class JobResultsResponse(BaseModel):
    """Response for GET /api/v1/jobs/{job_id}/results."""
    job_id: str
    status: str
    video_metadata: VideoMetadataResponse
    detection_summary: DetectionSummaryResponse
    segments: list[SegmentResponse]


class JobListResponse(BaseModel):
    """Response for GET /api/v1/jobs (list all jobs)."""
    jobs: list[JobStatusResponse]
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health."""
    status: str  # "healthy", "degraded", "unhealthy"
    model_loaded: bool
    gpu_available: bool
    gpu_name: str | None = None
    disk_free_gb: float


class ErrorResponse(BaseModel):
    """Standard error response body."""
    error: str
    detail: str


# Authentication Schemas

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


# Email Verification Schemas

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


# User Profile Schemas

class UserProfileResponse(BaseModel):
    """Response for GET /api/v1/users/me."""
    id: str
    email: str
    roles: list[str]
    is_active: bool
    email_verified: bool
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


# Admin User Management Schemas

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
    email: str
    password: Optional[str] = None  # Optional, auto-generated if not provided
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


# Dedicated Role Update Endpoint Schemas (Story 1.7)

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
