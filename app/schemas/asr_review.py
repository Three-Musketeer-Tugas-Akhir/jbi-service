"""ASR Review domain Pydantic schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# ASR Review Queue Schemas
# ============================================================================

class ASRReviewQueueItem(BaseModel):
    """ASR Review queue item."""
    review_id: UUID
    segment_id: UUID
    job_id: UUID
    original_filename: str
    
    # ASR Data
    video_url: str
    asr_text: str
    asr_start: Optional[float]
    asr_end: Optional[float]
    confidence_score: Optional[float]
    
    # Flags
    is_low_confidence: bool
    requires_attention: bool
    
    class Config:
        from_attributes = True


class ASRReviewQueueResponse(BaseModel):
    """ASR Review queue response."""
    items: List[ASRReviewQueueItem]
    total: int
    page: int
    page_size: int
    pages: int
    low_confidence_count: int


# ============================================================================
# ASR Review Detail Schema
# ============================================================================

class ASRReviewDetailResponse(BaseModel):
    """Complete ASR review details."""
    review_id: UUID
    segment_id: UUID
    job_id: UUID
    original_filename: str
    
    # Video
    video_url: str
    video_duration: Optional[float] = None
    
    # ASR Data
    asr_text: str
    asr_start: Optional[float]
    asr_end: Optional[float]
    confidence_score: Optional[float]
    
    # Review Status
    status: str
    reviewer_id: Optional[UUID]
    reviewed_at: Optional[datetime]
    
    # Flags
    is_low_confidence: bool
    attention_message: Optional[str] = None
    
    class Config:
        from_attributes = True


# ============================================================================
# Filter/Query Schemas
# ============================================================================

class ASRReviewFilterParams(BaseModel):
    """Query parameters for ASR review filtering."""
    confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    low_confidence_only: bool = False


# ============================================================================
# ASR Review Action Schemas
# ============================================================================

class ASRReviewApproveRequest(BaseModel):
    """Request to approve ASR transcript."""
    notes: Optional[str] = Field(None, description="Optional approval notes")


class ASRReviewCorrectRequest(BaseModel):
    """Request to correct ASR transcript."""
    corrected_text: str = Field(..., min_length=1, description="Corrected transcript")
    notes: Optional[str] = Field(None, description="Optional correction notes")


class ASRReviewFlagRequest(BaseModel):
    """Request to flag ASR segment for reprocessing."""
    flag_reason: str = Field(
        ...,
        pattern="^(background_noise|overlapping_speech|unclear_audio|other)$",
        description="Reason for flagging"
    )
    notes: str = Field(..., min_length=1, description="Detailed description of issue")


class ASRReviewActionResponse(BaseModel):
    """Response after ASR review action."""
    review_id: UUID
    segment_id: UUID
    action: str  # APPROVED, CORRECTED, FLAGGED
    status: str
    reviewer_id: UUID
    reviewed_at: datetime
    message: str
    
    # Queue info
    moved_to_annotation_queue: bool
    queue_entry_id: Optional[UUID] = None


class ASRReviewStatusCheck(BaseModel):
    """Status check response for ASR review."""
    review_id: UUID
    segment_id: UUID
    is_reviewed: bool
    status: Optional[str] = None
    reviewer_id: Optional[UUID] = None
    can_review: bool
    message: str
