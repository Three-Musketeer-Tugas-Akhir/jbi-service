"""Voice Annotation domain model.

Stores ground-truth transcript corrections and word-level validation
flags for each utterance. Acts as a quality gate before JBI Annotation.
"""
from datetime import datetime
from typing import Optional, List, Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text, Boolean, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pipeline import PipelineTranscript, PipelineJob
    from app.db.models.auth import User


class VoiceAnnotation(Base):
    """Per-utterance voice annotation record.

    One row per pipeline_transcript utterance. Stores the immutable ASR
    text alongside the editable ground-truth text and Sastrawi-based
    word-level validation flags.
    """
    __tablename__ = "voice_annotations"

    # Primary key
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )

    # Foreign keys
    transcript_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_transcripts.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        comment="One-to-one link to the source utterance"
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        index=True,
        comment="Denormalized FK for fast job-level queries"
    )

    # ASR source (immutable)
    asr_text: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Original ASR transcript — never modified"
    )

    # Ground truth (editable by annotator)
    ground_truth_text: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Editable ground-truth text, initially copied from asr_text"
    )

    # Validation flags
    flagged_words: Mapped[Optional[List[Any]]] = mapped_column(
        JSONB, nullable=True, server_default="[]",
        comment='List of OOV words: ["jokowi", "dodo"]'
    )
    has_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True if flagged_words is non-empty"
    )

    # Status
    voice_annotation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING",
        index=True,
        comment="PENDING | FLAGGED | CLEAN"
    )

    # Audit
    annotator_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who last edited ground_truth_text"
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Timestamp of last ground-truth edit"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )

    # Relationships
    transcript: Mapped["PipelineTranscript"] = relationship(
        "PipelineTranscript", backref="voice_annotation"
    )
    annotator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[annotator_id]
    )

    # Status constants
    STATUS_PENDING = "PENDING"
    STATUS_FLAGGED = "FLAGGED"
    STATUS_CLEAN = "CLEAN"

    def __repr__(self) -> str:
        return (
            f"<VoiceAnnotation(id={self.id}, "
            f"transcript_id={self.transcript_id}, "
            f"status={self.voice_annotation_status})>"
        )
