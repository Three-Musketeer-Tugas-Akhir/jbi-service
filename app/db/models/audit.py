"""
Audit domain models.

Models for compliance audit logging.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, String, func, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.auth import User


class AuditLog(Base):
    """
    Audit log entry for compliance tracking.
    
    Records significant system actions for audit purposes.
    Immutable - entries are never updated or deleted.
    """
    
    __tablename__ = "audit_logs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="Unique audit log entry identifier"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="When the action occurred"
    )
    actor_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="User who performed the action (NULL for system)"
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Action type (e.g., 'user.role_changed', 'user.created')"
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of resource affected (e.g., 'user', 'annotation')"
    )
    resource_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        comment="ID of affected resource"
    )
    details: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional action details as JSON"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="IP address of request (IPv6 compatible)"
    )
    
    # Relationships
    actor: Mapped[Optional["User"]] = relationship(
        "User",
        lazy="joined",
        foreign_keys="AuditLog.actor_id",
        primaryjoin="AuditLog.actor_id == User.id"
    )
    
    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"resource={self.resource_type}:{self.resource_id})>"
        )


# Common action types for consistency
class AuditAction:
    """Constants for audit action types."""
    
    # User management
    USER_CREATED = "user.created"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    USER_UPDATED = "user.updated"
    
    # Authentication
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    
    # Token management
    TOKEN_REFRESHED = "token.refreshed"
    TOKEN_REVOKED = "token.revoked"
    
    # Password management
    PASSWORD_CHANGED = "password.changed"
    PASSWORD_RESET_REQUESTED = "password.reset_requested"
    PASSWORD_RESET_COMPLETED = "password.reset_completed"
    
    # Email verification
    EMAIL_VERIFICATION_SENT = "email.verification_sent"
    EMAIL_VERIFIED = "email.verified"
    
    # Job management
    JOB_CREATED = "job.created"
    JOB_CANCELLED = "job.cancelled"
    JOB_DELETED = "job.deleted"
    JOB_STATUS_CHANGED = "job.status_changed"
    
    # Pipeline
    PIPELINE_STAGE_STARTED = "pipeline.stage_started"
    PIPELINE_STAGE_COMPLETED = "pipeline.stage_completed"
    PIPELINE_STAGE_FAILED = "pipeline.stage_failed"
    
    # Annotation
    ANNOTATION_CREATED = "annotation.created"
    ANNOTATION_UPDATED = "annotation.updated"
    ANNOTATION_SUBMITTED = "annotation.submitted"
    ANNOTATION_APPROVED = "annotation.approved"
    ANNOTATION_REJECTED = "annotation.rejected"
    ANNOTATION_DELETED = "annotation.deleted"
    
    # ASR Review
    ASR_REVIEW_SUBMITTED = "asr_review.submitted"
    ASR_REVIEW_CORRECTED = "asr_review.corrected"
    
    # Upload
    UPLOAD_STARTED = "upload.started"
    UPLOAD_COMPLETED = "upload.completed"
    UPLOAD_CANCELLED = "upload.cancelled"
    
    # Classification
    CLASSIFICATION_UPDATED = "classification.updated"
    
    # Voice annotation
    VOICE_ANNOTATION_UPDATED = "voice_annotation.updated"
    
    # JBI annotation
    JBI_ANNOTATION_DRAFT_SAVED = "jbi_annotation.draft_saved"
    JBI_ANNOTATION_EDIT_CREATED = "jbi_annotation.edit_created"
    JBI_ANNOTATION_RESET = "jbi_annotation.reset"
    
    # Normalization
    NORMALIZATION_APPLIED = "normalization.applied"
    
    # Curation
    CURATION_APPROVED = "curation.approved"
    CURATION_NORMALIZED = "curation.normalized"
    
    # Admin
    CONFIG_CHANGED = "config.changed"
    AUDIT_EXPORT_REQUESTED = "audit.export_requested"
