"""
Pipeline domain models.

Models for video processing pipeline and job queue.
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Float, Integer, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.annotation import AnnotationEdit, ASRReview, AnnotationQueue


class SignLanguageCategory:
    """Sign language category constants."""
    SIBI = "SIBI"      # Sistem Isyarat Bahasa Indonesia
    BISINDO = "BISINDO"  # Bahasa Isyarat Indonesia


class PipelineJob(Base):
    """Video processing job."""
    
    __tablename__ = "pipeline_jobs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Sign language category (SIBI or BISINDO)
    category: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        index=True,
        comment="Sign language category: SIBI or BISINDO"
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="File size in bytes"
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Cancellation fields (Story 2.9)
    is_cancelled: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True if job was cancelled by user"
    )
    
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When job was cancelled"
    )
    
    cancelled_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who cancelled the job"
    )
    
    # Relationships
    segments: Mapped[List["PipelineSegment"]] = relationship(
        "PipelineSegment",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    logs: Mapped[List["PipelineJobLog"]] = relationship(
        "PipelineJobLog",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<PipelineJob(id={self.id}, status={self.status})>"


class PipelineSegment(Base):
    """Video segment from pipeline processing."""
    
    __tablename__ = "pipeline_segments"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    asr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    asr_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    asr_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    asr_review_flag: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True if segment needs ASR review (low confidence or failed)"
    )
    jbi_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    jbi_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cropped_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    stage2_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Relationships
    job: Mapped["PipelineJob"] = relationship("PipelineJob", back_populates="segments")
    annotation_edits: Mapped[List["AnnotationEdit"]] = relationship(
        "AnnotationEdit",
        back_populates="segment",
        cascade="all, delete-orphan"
    )
    asr_review: Mapped[Optional["ASRReview"]] = relationship(
        "ASRReview",
        back_populates="segment",
        cascade="all, delete-orphan",
        uselist=False
    )
    queue_assignment: Mapped[Optional["AnnotationQueue"]] = relationship(
        "AnnotationQueue",
        back_populates="segment",
        cascade="all, delete-orphan",
        uselist=False
    )
    transcripts: Mapped[List["PipelineTranscript"]] = relationship(
        "PipelineTranscript",
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="PipelineTranscript.utterance_index"
    )
    
    def __repr__(self) -> str:
        return f"<PipelineSegment(id={self.id}, job_id={self.job_id}, index={self.segment_index})>"


class PipelineJobLog(Base):
    """Log entry for pipeline job processing."""
    
    __tablename__ = "pipeline_job_logs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    
    # Relationships
    job: Mapped["PipelineJob"] = relationship("PipelineJob", back_populates="logs")
    
    def __repr__(self) -> str:
        return f"<PipelineJobLog(id={self.id}, job_id={self.job_id}, stage={self.stage})>"


class QueueJob(Base):
    """Job queue entry for async processing."""
    
    __tablename__ = "queue_jobs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, server_default=text('0'), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text('0'), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text('3'), nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    def __repr__(self) -> str:
        return f"<QueueJob(id={self.id}, queue={self.queue_name}, status={self.status})>"


class ConfigPipelineParam(Base):
    """Pipeline configuration parameter."""
    
    __tablename__ = "config_pipeline_params"
    
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<ConfigPipelineParam(key={self.key})>"


class PipelineTranscript(Base):
    """
    Individual ASR transcript utterance.
    
    One row per utterance/statement from Whisper transcription.
    References pipeline_segments for grouping.
    """
    
    __tablename__ = "pipeline_transcripts"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    segment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    utterance_index: Mapped[int] = mapped_column(
        Integer, 
        nullable=False,
        comment="Index of utterance within segment (0, 1, 2, ...)"
    )
    text: Mapped[str] = mapped_column(
        Text, 
        nullable=False,
        comment="Transcribed text for this utterance"
    )
    start: Mapped[float] = mapped_column(
        Float, 
        nullable=False,
        comment="Start time in seconds (relative to segment start)"
    )
    end: Mapped[float] = mapped_column(
        Float, 
        nullable=False,
        comment="End time in seconds (relative to segment start)"
    )
    confidence: Mapped[float] = mapped_column(
        Float, 
        nullable=False,
        default=0.0,
        comment="Confidence score for this utterance (0-1)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    segment: Mapped["PipelineSegment"] = relationship(
        "PipelineSegment", 
        back_populates="transcripts"
    )
    
    def __repr__(self) -> str:
        return f"<PipelineTranscript(id={self.id}, segment_id={self.segment_id}, index={self.utterance_index})>"


# Status constants
class JobStatus:
    """Pipeline job status constants."""
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    DETECTING = "DETECTING"
    TRANSCRIBING = "TRANSCRIBING"
    ASR_COMPLETED = "ASR_COMPLETED"
    CROPPING = "CROPPING"
    CROPPING_IN_PROGRESS = "CROPPING_IN_PROGRESS"
    CROPPING_FAILED = "CROPPING_FAILED"
    READY_FOR_ANNOTATION = "READY_FOR_ANNOTATION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class QueueStatus:
    """Queue job status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
