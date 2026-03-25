"""Annotation domain SQLAlchemy models.

This module defines the database models for the annotation workflow,
including edits, reviews, comments, ASR validation, and queue management.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List
from uuid import UUID

from sqlalchemy import ForeignKey, String, Float, Text, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.pipeline import PipelineSegment
    from app.db.models.auth import User


class AnnotationEdit(Base):
    """Stores transcript and timestamp edits made by annotators.
    
    Tracks the complete audit trail from old to new values,
    supporting soft delete to preserve history.
    """
    __tablename__ = "annotation_edits"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    
    # Foreign keys
    segment_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_segments.id", ondelete="CASCADE"), index=True)
    editor_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    
    # Original values (audit trail)
    old_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Original transcript text")
    old_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Original start time in seconds")
    old_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="Original end time in seconds")
    
    # New values (annotator corrections)
    new_text: Mapped[str] = mapped_column(Text, nullable=False, comment="Corrected transcript text")
    new_start: Mapped[float] = mapped_column(Float, nullable=False, comment="Corrected start time in seconds")
    new_end: Mapped[float] = mapped_column(Float, nullable=False, comment="Corrected end time in seconds")
    
    # Status and metadata
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="PENDING")
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="NOW()", nullable=False)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    segment: Mapped["PipelineSegment"] = relationship("PipelineSegment", back_populates="annotation_edits")
    editor: Mapped[Optional["User"]] = relationship("User", back_populates="annotation_edits")
    reviews: Mapped[List["AnnotationReview"]] = relationship("AnnotationReview", back_populates="edit", cascade="all, delete-orphan")
    comments: Mapped[List["AnnotationComment"]] = relationship("AnnotationComment", back_populates="edit", cascade="all, delete-orphan")
    
    # Status constants
    STATUS_DRAFT = "DRAFT"
    STATUS_PENDING = "PENDING"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"


class AnnotationReview(Base):
    """Curator reviews of annotation edits.
    
    Captures approval/rejection decisions with feedback for annotators.
    """
    __tablename__ = "annotation_reviews"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    
    # Foreign keys
    edit_id: Mapped[UUID] = mapped_column(ForeignKey("annotation_edits.id", ondelete="CASCADE"), index=True)
    curator_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    
    # Review details
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Curator feedback to annotator")
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="NOW()", nullable=False)
    
    # Relationships
    edit: Mapped["AnnotationEdit"] = relationship("AnnotationEdit", back_populates="reviews")
    curator: Mapped[Optional["User"]] = relationship("User", back_populates="annotation_reviews")
    
    # Status constants
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"


class AnnotationComment(Base):
    """Comments on annotation edits.
    
    Enables discussion between annotators and curators.
    """
    __tablename__ = "annotation_comments"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    
    # Foreign keys
    edit_id: Mapped[UUID] = mapped_column(ForeignKey("annotation_edits.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    
    # Comment content
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="NOW()", nullable=False)
    
    # Relationships
    edit: Mapped["AnnotationEdit"] = relationship("AnnotationEdit", back_populates="comments")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="annotation_comments")


class ASRReview(Base):
    """Pre-annotation ASR transcript validation.
    
    Allows ASR reviewers to validate and correct transcripts
    before they reach annotators.
    """
    __tablename__ = "asr_reviews"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    
    # Foreign keys
    segment_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_segments.id", ondelete="CASCADE"), index=True)
    reviewer_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True)
    
    # ASR content
    original_text: Mapped[str] = mapped_column(Text, nullable=False, comment="Original ASR transcript")
    corrected_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Reviewer corrections")
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="ASR confidence (0-1)")
    
    # Review status
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="PENDING")
    flag_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, comment="Reason if flagged")
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    segment: Mapped["PipelineSegment"] = relationship("PipelineSegment", back_populates="asr_review")
    reviewer: Mapped[Optional["User"]] = relationship("User", back_populates="asr_reviews")
    
    # Status constants
    STATUS_PENDING = "PENDING"
    STATUS_APPROVED = "APPROVED"
    STATUS_CORRECTED = "CORRECTED"
    STATUS_FLAGGED = "FLAGGED"


class AnnotationQueue(Base):
    """Work assignment queue for annotators.
    
    Manages segment assignment to annotators with priority and due dates.
    """
    __tablename__ = "annotation_queue"
    
    # Primary key
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default="gen_random_uuid()")
    
    # Foreign keys
    segment_id: Mapped[UUID] = mapped_column(ForeignKey("pipeline_segments.id", ondelete="CASCADE"), unique=True)
    annotator_id: Mapped[UUID] = mapped_column(ForeignKey("auth_users.id", ondelete="CASCADE"), index=True)
    
    # Queue metadata
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="ASSIGNED")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="Higher = higher priority")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default="NOW()", nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    segment: Mapped["PipelineSegment"] = relationship("PipelineSegment", back_populates="queue_assignment")
    annotator: Mapped["User"] = relationship("User", back_populates="annotation_queue")
    
    # Status constants
    STATUS_ASSIGNED = "ASSIGNED"
    STATUS_IN_PROGRESS = "IN_PROGRESS"
    STATUS_COMPLETED = "COMPLETED"
