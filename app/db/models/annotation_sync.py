"""
Annotation Synchronization models.

Models for video-audio temporal alignment and sync workbench.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, String, Float, Text, Boolean, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.annotation import AnnotationEdit
    from app.db.models.auth import User


class AnnotationSync(Base):
    """
    Video-audio synchronization data for annotation.
    
    Stores temporal alignment information to handle the lag between
    audio (ASR) and sign language video (JBI). Allows extending video
    boundaries beyond original ASR timestamps.
    """
    
    __tablename__ = "annotation_syncs"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    
    # Foreign keys
    annotation_edit_id: Mapped[UUID] = mapped_column(
        ForeignKey("annotation_edits.id", ondelete="CASCADE"),
        index=True,
        unique=True,
        comment="Associated annotation edit"
    )
    
    # Original ASR timestamps (reference)
    audio_start: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Original ASR start time in seconds"
    )
    audio_end: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        comment="Original ASR end time in seconds"
    )
    
    # Video boundaries (adjusted)
    video_start_offset: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Video start time in seconds (may be earlier than audio_start)"
    )
    video_end_offset: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        comment="Video end time in seconds (may be later than audio_end)"
    )
    
    # Sync status
    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="UNSYNCED",
        comment="Synchronization status"
    )
    
    # Glosa (sign language gloss notation)
    glosa: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Sign language gloss (e.g., 'SAYA MAKAN NASI RESTORAN')"
    )
    
    # Sync quality indicators
    text_match: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="True if text matches audio"
    )
    video_complete: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="True if JBI movement is fully captured"
    )
    sync_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        comment="True if alignment is finalized"
    )
    
    # Precision settings
    precision_ms: Mapped[int] = mapped_column(
        Float,
        nullable=False,
        server_default="33.0",
        comment="Precision in milliseconds (default 33ms = 1 frame @ 30fps)"
    )
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationships
    annotation_edit: Mapped["AnnotationEdit"] = relationship(
        "AnnotationEdit",
        back_populates="sync_data"
    )
    
    # Status constants
    STATUS_UNSYNCED = "UNSYNCED"
    STATUS_PARTIAL = "PARTIAL"
    STATUS_SYNCED = "SYNCED"
    STATUS_LOCKED = "LOCKED"
    
    def get_effective_video_start(self) -> float:
        """Get effective video start time (falls back to audio_start if not set)."""
        return self.video_start_offset if self.video_start_offset is not None else self.audio_start
    
    def get_effective_video_end(self) -> float:
        """Get effective video end time (falls back to audio_end if not set)."""
        return self.video_end_offset if self.video_end_offset is not None else self.audio_end
    
    def get_video_duration(self) -> float:
        """Get total video duration after sync adjustments."""
        return self.get_effective_video_end() - self.get_effective_video_start()
    
    def get_audio_duration(self) -> float:
        """Get original audio duration."""
        return self.audio_end - self.audio_start
    
    def get_extension_seconds(self) -> float:
        """Get total extension beyond audio boundaries."""
        video_duration = self.get_video_duration()
        audio_duration = self.get_audio_duration()
        return max(0, video_duration - audio_duration)
    
    def __repr__(self) -> str:
        return (
            f"<AnnotationSync(id={self.id}, edit_id={self.annotation_edit_id}, "
            f"status={self.sync_status}, extension={self.get_extension_seconds():.2f}s)>"
        )


class AnnotationSyncHistory(Base):
    """
    History of sync adjustments for audit trail.
    
    Tracks all changes made to sync boundaries for compliance.
    """
    
    __tablename__ = "annotation_sync_history"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    
    # Foreign keys
    sync_id: Mapped[UUID] = mapped_column(
        ForeignKey("annotation_syncs.id", ondelete="CASCADE"),
        index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Change details
    previous_video_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    previous_video_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    new_video_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    new_video_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    change_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Reason for the adjustment"
    )
    
    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<AnnotationSyncHistory(id={self.id}, sync_id={self.sync_id})>"
