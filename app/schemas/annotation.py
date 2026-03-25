"""Annotation domain Pydantic schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


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
    """Queue item response with metadata."""
    id: UUID
    job_id: UUID
    original_filename: str
    video_preview_url: str
    transcript_text: Optional[str] = None
    asr_confidence: Optional[float] = None
    
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
