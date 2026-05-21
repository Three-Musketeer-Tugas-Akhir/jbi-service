"""
Audit Log Schemas.

Pydantic models for audit log API requests and responses.
"""

from datetime import datetime
from typing import Optional, List, Any, Dict
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Request Schemas
# ============================================================================

class AuditLogListRequest(BaseModel):
    """Request for listing audit logs with filters."""
    start_date: Optional[datetime] = Field(None, description="Filter by start date (ISO8601)")
    end_date: Optional[datetime] = Field(None, description="Filter by end date (ISO8601)")
    actor_id: Optional[UUID] = Field(None, description="Filter by user who performed action")
    action: Optional[str] = Field(None, description="Filter by action type (e.g., 'user.created')")
    resource_type: Optional[str] = Field(None, description="Filter by resource type (e.g., 'job', 'user')")
    resource_id: Optional[UUID] = Field(None, description="Filter by specific resource ID")
    ip_address: Optional[str] = Field(None, description="Filter by IP address")
    page: int = Field(1, ge=1, description="Page number")
    page_size: int = Field(50, ge=1, le=100, description="Items per page")


class AuditLogExportRequest(BaseModel):
    """Request for exporting audit logs."""
    format: str = Field("json", pattern="^(json|csv)$", description="Export format: 'json' or 'csv'")
    start_date: Optional[datetime] = Field(None, description="Export from date")
    end_date: Optional[datetime] = Field(None, description="Export to date")
    filters: Optional[Dict[str, Any]] = Field(None, description="Additional filters")


# ============================================================================
# Response Schemas
# ============================================================================

class AuditLogActorResponse(BaseModel):
    """Actor information in audit log."""
    id: Optional[UUID] = Field(None, description="User ID")
    email: Optional[str] = Field(None, description="User email")


class AuditLogResourceResponse(BaseModel):
    """Resource information in audit log."""
    type: str = Field(..., description="Resource type")
    id: Optional[UUID] = Field(None, description="Resource ID")


class AuditLogResponse(BaseModel):
    """Single audit log entry response."""
    id: UUID = Field(..., description="Log entry UUID")
    timestamp: datetime = Field(..., description="When the action occurred")
    actor: Optional[AuditLogActorResponse] = Field(None, description="Who performed the action")
    action: str = Field(..., description="Action type (e.g., 'user.created')")
    action_label: str = Field(..., description="Human-readable action label")
    resource: AuditLogResourceResponse = Field(..., description="Affected resource")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    ip_address: Optional[str] = Field(None, description="IP address of request")
    
    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Response for listing audit logs."""
    items: List[AuditLogResponse] = Field(..., description="List of audit log entries")
    total: int = Field(..., description="Total matching entries")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    pages: int = Field(..., description="Total number of pages")


class AuditLogDetailResponse(BaseModel):
    """Detailed single audit log response."""
    id: UUID = Field(..., description="Log entry UUID")
    timestamp: datetime = Field(..., description="When the action occurred")
    actor: Optional[AuditLogActorResponse] = Field(None, description="Who performed the action")
    action: str = Field(..., description="Action type")
    action_label: str = Field(..., description="Human-readable action label")
    resource: AuditLogResourceResponse = Field(..., description="Affected resource")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional details")
    ip_address: Optional[str] = Field(None, description="IP address")
    user_agent: Optional[str] = Field(None, description="User agent string")
    
    class Config:
        from_attributes = True


# ============================================================================
# Statistics Schemas
# ============================================================================

class ActionCount(BaseModel):
    """Action type with count."""
    action: str = Field(..., description="Action type")
    label: str = Field(..., description="Human-readable label")
    count: int = Field(..., description="Number of occurrences")


class DailyActivity(BaseModel):
    """Daily activity count."""
    date: str = Field(..., description="Date (YYYY-MM-DD)")
    count: int = Field(..., description="Number of actions")


class AuditStatsSummary(BaseModel):
    """Summary statistics for audit logs."""
    total_logs: int = Field(..., description="Total log entries")
    unique_users: int = Field(..., description="Number of unique actors")
    period_start: Optional[datetime] = Field(None, description="Period start date")
    period_end: Optional[datetime] = Field(None, description="Period end date")
    top_actions: List[ActionCount] = Field(default_factory=list, description="Most frequent actions")
    daily_activity: List[DailyActivity] = Field(default_factory=list, description="Activity by day")


class UserActivitySummary(BaseModel):
    """Activity summary for a specific user."""
    user_id: UUID = Field(..., description="User ID")
    email: str = Field(..., description="User email")
    total_actions: int = Field(..., description="Total actions performed")
    last_active: Optional[datetime] = Field(None, description="Last activity timestamp")
    actions_by_type: List[ActionCount] = Field(default_factory=list, description="Actions breakdown")
    period_days: int = Field(30, description="Period in days")


class ResourceActivitySummary(BaseModel):
    """Activity summary for a specific resource."""
    resource_type: str = Field(..., description="Resource type")
    resource_id: UUID = Field(..., description="Resource ID")
    total_actions: int = Field(..., description="Total actions on this resource")
    created_at: Optional[datetime] = Field(None, description="When resource was created")
    last_modified: Optional[datetime] = Field(None, description="Last modification")
    action_history: List[AuditLogResponse] = Field(default_factory=list, description="Recent actions")


# ============================================================================
# Export Response
# ============================================================================

class AuditLogExportResponse(BaseModel):
    """Response for audit log export."""
    filename: str = Field(..., description="Export filename")
    format: str = Field(..., description="Export format")
    total_records: int = Field(..., description="Number of records exported")
    download_url: Optional[str] = Field(None, description="Temporary download URL")


# ============================================================================
# Action Labels Mapping
# ============================================================================

ACTION_LABELS = {
    # User management
    "user.created": "User Created",
    "user.role_changed": "User Role Changed",
    "user.deactivated": "User Deactivated",
    "user.reactivated": "User Reactivated",
    "user.updated": "User Updated",
    
    # Authentication
    "user.login": "User Login",
    "user.logout": "User Logout",
    "user.login_failed": "Failed Login Attempt",
    
    # Token management
    "token.refreshed": "Token Refreshed",
    "token.revoked": "Token Revoked",
    
    # Password management
    "password.changed": "Password Changed",
    "password.reset_requested": "Password Reset Requested",
    "password.reset_completed": "Password Reset Completed",
    
    # Email verification
    "email.verification_sent": "Verification Email Sent",
    "email.verified": "Email Verified",
    
    # Job management
    "job.created": "Job Created",
    "job.cancelled": "Job Cancelled",
    "job.deleted": "Job Deleted",
    "job.status_changed": "Job Status Changed",
    
    # Pipeline
    "pipeline.stage_started": "Pipeline Stage Started",
    "pipeline.stage_completed": "Pipeline Stage Completed",
    "pipeline.stage_failed": "Pipeline Stage Failed",
    
    # Annotation
    "annotation.created": "Annotation Created",
    "annotation.updated": "Annotation Updated",
    "annotation.submitted": "Annotation Submitted",
    "annotation.approved": "Annotation Approved",
    "annotation.rejected": "Annotation Rejected",
    "annotation.deleted": "Annotation Deleted",
    
    # ASR Review
    "asr_review.submitted": "ASR Review Submitted",
    "asr_review.corrected": "ASR Review Corrected",
    
    # Upload
    "upload.started": "Upload Started",
    "upload.completed": "Upload Completed",
    "upload.cancelled": "Upload Cancelled",
    
    # Classification
    "classification.updated": "Classification Updated",
    
    # Voice annotation
    "voice_annotation.updated": "Voice Annotation Updated",
    
    # JBI annotation
    "jbi_annotation.draft_saved": "JBI Annotation Draft Saved",
    "jbi_annotation.edit_created": "JBI Annotation Edit Created",
    "jbi_annotation.reset": "JBI Annotation Reset",
    
    # Normalization
    "normalization.applied": "Normalization Applied",
    
    # Curation
    "curation.approved": "Curation Approved",
    "curation.normalized": "Curation Normalized",
    
    # Admin
    "config.changed": "Configuration Changed",
    "audit.export_requested": "Audit Log Export Requested",
}


def get_action_label(action: str) -> str:
    """Get human-readable label for action type."""
    return ACTION_LABELS.get(action, action.replace(".", " ").title())
