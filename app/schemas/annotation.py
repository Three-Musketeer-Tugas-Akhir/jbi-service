"""Annotation domain Pydantic schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


# ============================================================================
# Queue Item Schemas
# ============================================================================

class QueueItemBase(BaseModel):
    """Base queue item schema."""
    segment_id: UUID
    status: str
    priority: int
    assigned_at: datetime
    due_date: Optional[datetime] = None


class QueueItemResponse(QueueItemBase):
    """Queue item response with metadata and active edit information."""
    id: UUID
    job_id: UUID
    original_filename: str
    video_preview_url: str
    transcript_text: Optional[str] = None
    asr_confidence: Optional[float] = None
    
    # Active edit information (Option B: latest DRAFT/PENDING/SUBMITTED)
    edit_id: Optional[UUID] = Field(None, description="Latest active edit ID (DRAFT, PENDING, or SUBMITTED)")
    edit_status: Optional[str] = Field(None, description="Status of the active edit")
    has_active_work: bool = Field(False, description="True if has active edit (DRAFT/PENDING/SUBMITTED)")
    last_edited_at: Optional[datetime] = Field(None, description="When the active edit was last modified")
    
    class Config:
        from_attributes = True


class QueueListResponse(BaseModel):
    """Paginated queue list response."""
    items: List[QueueItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ============================================================================
# Segment Detail Schemas
# ============================================================================

class SegmentEditHistory(BaseModel):
    """Edit history entry for segment."""
    edit_id: UUID
    old_text: Optional[str]
    new_text: str
    old_start: Optional[float]
    new_start: float
    old_end: Optional[float]
    new_end: float
    edited_at: datetime
    status: str


class SegmentDetailResponse(BaseModel):
    """Complete segment details for annotation interface."""
    segment_id: UUID
    job_id: UUID
    original_filename: str
    
    # Video
    video_url: str
    video_duration: Optional[float] = None
    
    # ASR Data
    asr_text: Optional[str]
    asr_start: Optional[float]
    asr_end: Optional[float]
    asr_confidence: Optional[float]
    
    # JBI Timestamps (final)
    jbi_start: Optional[float]
    jbi_end: Optional[float]
    
    # Current State
    current_text: str
    current_start: float
    current_end: float
    
    # Edit History
    edit_history: List[SegmentEditHistory]
    
    # Queue Info
    queue_status: str
    priority: int
    
    class Config:
        from_attributes = True


# ============================================================================
# Filter/Query Schemas
# ============================================================================

class QueueFilterParams(BaseModel):
    """Query parameters for queue filtering."""
    status: Optional[str] = Field(None, pattern="^(ASSIGNED|IN_PROGRESS|COMPLETED)$")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ============================================================================
# Annotation Edit Schemas
# ============================================================================

class AnnotationEditCreate(BaseModel):
    """Schema for creating a new annotation edit."""
    new_text: str = Field(..., min_length=1, description="Corrected transcript text")
    new_start: float = Field(..., ge=0, description="New start time in seconds")
    new_end: float = Field(..., gt=0, description="New end time in seconds")
    
    @model_validator(mode='after')
    def validate_timestamps(self):
        """Validate that start < end."""
        if self.new_start >= self.new_end:
            raise ValueError("Start time must be less than end time")
        return self


class AnnotationEditResponse(BaseModel):
    """Response schema for annotation edit."""
    id: UUID
    segment_id: UUID
    editor_id: Optional[UUID]
    
    # Old values
    old_text: Optional[str]
    old_start: Optional[float]
    old_end: Optional[float]
    
    # New values
    new_text: str
    new_start: float
    new_end: float
    
    # Metadata
    status: str
    is_deleted: bool
    edited_at: datetime
    submitted_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class AnnotationEditListResponse(BaseModel):
    """Response schema for list of edits."""
    segment_id: UUID
    edits: List[AnnotationEditResponse]
    total: int


# ============================================================================
# Preview and Draft Schemas
# ============================================================================

class AnnotationPreviewRequest(BaseModel):
    """Request to preview annotation with specific timestamps."""
    start_time: float = Field(..., ge=0, description="Start time in seconds")
    end_time: float = Field(..., gt=0, description="End time in seconds")
    transcript_text: Optional[str] = Field(None, description="Transcript to preview")
    
    @model_validator(mode='after')
    def validate_timestamps(self):
        """Validate that start < end."""
        if self.start_time >= self.end_time:
            raise ValueError("Start time must be less than end time")
        return self


class AnnotationPreviewResponse(BaseModel):
    """Preview response with video URL and metadata."""
    segment_id: UUID
    video_url: str
    start_time: float
    end_time: float
    transcript_text: Optional[str]
    duration: float
    
    class Config:
        from_attributes = True


class SaveDraftRequest(BaseModel):
    """Request to save annotation as draft."""
    new_text: str = Field(..., min_length=1, description="Corrected transcript text")
    new_start: float = Field(..., ge=0, description="New start time in seconds")
    new_end: float = Field(..., gt=0, description="New end time in seconds")
    
    @model_validator(mode='after')
    def validate_timestamps(self):
        """Validate that start < end."""
        if self.new_start >= self.new_end:
            raise ValueError("Start time must be less than end time")
        return self


class SaveDraftResponse(BaseModel):
    """Response after saving draft."""
    edit_id: UUID
    segment_id: UUID
    status: str
    saved_at: datetime
    message: str = "Draft saved successfully"


class ResetResponse(BaseModel):
    """Response after resetting annotations."""
    segment_id: UUID
    reset_edit_id: UUID
    edits_removed: int
    message: str
    reverted_to: dict  # ASR original values


# ============================================================================
# Submission Schemas
# ============================================================================

class SubmitForReviewRequest(BaseModel):
    """Request to submit annotation for curator review."""
    confirm_no_changes: bool = Field(
        False,
        description="Confirm submission even if no edits were made"
    )


class ReviewActionRequest(BaseModel):
    """Request for curator to approve or reject an annotation review."""
    feedback: Optional[str] = Field(
        default=None,
        description="Optional feedback to the annotator (especially for rejections)"
    )


class SubmitForReviewResponse(BaseModel):
    """Response after submitting for review."""
    segment_id: UUID
    edit_id: UUID
    review_id: UUID
    status: str
    message: str
    submitted_at: datetime


class SubmissionStatusResponse(BaseModel):
    """Status of a segment's submission."""
    segment_id: UUID
    has_edits: bool
    edit_count: int
    last_edit_status: Optional[str]
    can_submit: bool
    warning: Optional[str] = None


# ============================================================================
# Review Status Schemas (for annotator to track their submissions)
# ============================================================================

class ReviewStatusResponse(BaseModel):
    """Review status for an annotator's submission."""
    segment_id: UUID
    review_id: Optional[UUID] = None
    status: str  # NOT_SUBMITTED, PENDING, APPROVED, REJECTED
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None
    curator_id: Optional[UUID] = None
    feedback: Optional[str] = None
    
    class Config:
        from_attributes = True


class ReviewStatusListResponse(BaseModel):
    """List of review statuses for annotator's submissions."""
    items: List[ReviewStatusResponse]
    total: int
