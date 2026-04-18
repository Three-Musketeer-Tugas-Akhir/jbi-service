"""Notification domain models.

Database models for user notifications about job and annotation events.
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Boolean, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Notification(Base):
    """User notification for system events.
    
    Tracks notifications about pipeline completion, annotation status changes,
    and other relevant events.
    """
    
    __tablename__ = "notifications"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Recipient user"
    )
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Notification type: job_complete, annotation_ready, review_approved, etc."
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Short notification title"
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Notification body"
    )
    job_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Related pipeline job (optional)"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Whether the user has read this notification"
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the notification was marked as read"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_notifications_user_read', 'user_id', 'is_read'),
        Index('idx_notifications_user_created', 'user_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, user_id={self.user_id}, type={self.type})>"
