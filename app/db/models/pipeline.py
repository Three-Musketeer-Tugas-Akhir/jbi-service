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
    from app.db.models.dataset import Dataset


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
    release_date: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
        comment="Release/Upload date from YouTube or external source (YYYYMMDD)"
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
    
    # Voice annotation counters (populated by VoiceAnnotationService)
    clean_utterance_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Number of utterances that passed Sastrawi validation"
    )
    flagged_utterance_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Number of utterances with OOV flagged words"
    )

    # Curation status (Curation module)
    curation_status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Curation workflow status: PENDING, ANNOTATED, READY_TO_BE_NORMALIZED, NORMALIZING, NORMALIZED, READY_TO_EXPORT"
    )
    
    # Dataset relation
    dataset_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated dataset/project"
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
    dataset: Mapped[Optional["Dataset"]] = relationship(
        "Dataset",
        back_populates="jobs"
    )
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
    asr_review_flag: Mapped[bool] = mapped_column(
        default=False,
        nullable=False,
        comment="True if segment needs ASR review (low confidence or failed)"
    )
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cropped_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Note: ASR and cropping data moved to pipeline_transcripts (utterance-level)
    # - asr_text, asr_confidence, asr_start, asr_end -> pipeline_transcripts
    # - jbi_start, jbi_end, stage2_video_path -> pipeline_transcripts
    
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
    
    # Backward-compatible properties for migrated ASR fields
    # ASR data moved to pipeline_transcripts (utterance-level) in migration 011
    @property
    def asr_text(self) -> Optional[str]:
        """Concatenated ASR text from all transcripts."""
        from sqlalchemy import inspect
        state = inspect(self)
        if 'transcripts' in state.unloaded:
            return None
        if self.transcripts:
            sorted_transcripts = sorted(self.transcripts, key=lambda x: x.utterance_index)
            return " ".join(t.text for t in sorted_transcripts)
        return None

    @property
    def asr_start(self) -> Optional[float]:
        """ASR start time (minimum of all transcript starts)."""
        from sqlalchemy import inspect
        state = inspect(self)
        if 'transcripts' in state.unloaded:
            return None
        if self.transcripts:
            return min(t.start for t in self.transcripts)
        return None

    @property
    def asr_end(self) -> Optional[float]:
        """ASR end time (maximum of all transcript ends)."""
        from sqlalchemy import inspect
        state = inspect(self)
        if 'transcripts' in state.unloaded:
            return None
        if self.transcripts:
            return max(t.end for t in self.transcripts)
        return None

    @property
    def jbi_start(self) -> Optional[float]:
        """Backward-compatible JBI start (alias for ASR start)."""
        return self.asr_start

    @property
    def jbi_end(self) -> Optional[float]:
        """Backward-compatible JBI end (alias for ASR end)."""
        return self.asr_end

    @property
    def asr_confidence(self) -> Optional[float]:
        """Average ASR confidence across all transcripts."""
        from sqlalchemy import inspect
        state = inspect(self)
        if 'transcripts' in state.unloaded:
            return None
        if self.transcripts:
            return sum(t.confidence for t in self.transcripts) / len(self.transcripts)
        return None

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
    
    # Dependency tracking for pipeline stages (added for chunked upload)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="Associated pipeline job"
    )
    depends_on: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("queue_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Previous stage queue job that must complete first"
    )
    stage: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Pipeline stage: detection, asr, cropping"
    )
    
    def __repr__(self) -> str:
        return f"<QueueJob(id={self.id}, queue={self.queue_name}, status={self.status}, stage={self.stage})>"


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
    video_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="MinIO key to cropped video for this utterance"
    )
    audio_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="MinIO key to WAV audio for this utterance"
    )
    status: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default="pending",
        comment="Cropping status: pending, cropped, failed"
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
    # Voice annotation quality gate
    NEEDS_VOICE_ANNOTATION = "NEEDS_VOICE_ANNOTATION"
    VOICE_ANNOTATION_IN_PROGRESS = "VOICE_ANNOTATION_IN_PROGRESS"
    READY_FOR_ANNOTATION = "READY_FOR_ANNOTATION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class QueueStatus:
    """Queue job status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Upload(Base):
    """
    Resumable file upload tracking for Tus Protocol.
    
    Tracks chunked uploads and links to pipeline job after completion.
    """
    
    __tablename__ = "uploads"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    upload_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
        comment="Tus upload ID (UUID)"
    )
    filename: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Original filename"
    )
    file_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Total file size in bytes (max 10GB)"
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="File MIME type"
    )
    
    # Upload status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="pending, uploading, assembling, complete, cancelled, failed"
    )
    
    # Chunk tracking
    chunk_size: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5 * 1024 * 1024,  # 5MB
        comment="Size of each chunk in bytes"
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Total number of chunks"
    )
    chunks_received: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        comment="List of received chunk indices [0, 1, 2, 5, ...]"
    )
    chunks_uploading: Mapped[list] = mapped_column(
        JSONB,
        default=list,
        comment="List of chunks currently being uploaded"
    )
    
    # Storage locations
    temp_bucket: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="temp-uploads",
        comment="MinIO bucket for temporary chunks"
    )
    temp_prefix: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Path prefix in temp bucket (uploads/{user_id}/{upload_id}/)"
    )
    final_bucket: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="raw-videos",
        comment="MinIO bucket for assembled file"
    )
    final_key: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="Final path in raw-videos bucket"
    )
    
    # Metadata
    category: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Sign language category: SIBI or BISINDO"
    )
    checksum: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="SHA-256 checksum of complete file"
    )
    
    # User relation
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Job relation (set after assembly)
    job_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    job: Mapped[Optional["PipelineJob"]] = relationship(
        "PipelineJob",
        back_populates="upload",
        foreign_keys=[job_id]
    )
    
    # Timestamps
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
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Cleanup incomplete uploads after this time"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_upload_status_expires', 'status', 'expires_at'),
        Index('idx_upload_user_created', 'user_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<Upload(id={self.id}, upload_id={self.upload_id}, status={self.status})>"


# Add relationship to PipelineJob
PipelineJob.upload = relationship(
    "Upload",
    back_populates="job",
    foreign_keys=[Upload.job_id],
    uselist=False
)
