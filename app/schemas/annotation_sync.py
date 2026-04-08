"""
Annotation Synchronization Schemas.

Pydantic models for video-audio sync operations.
"""
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# ============================================================================
# Sync Status Constants
# ============================================================================

class SyncStatus:
    """Synchronization status constants."""
    UNSYNCED = "UNSYNCED"
    PARTIAL = "PARTIAL"
    SYNCED = "SYNCED"
    LOCKED = "LOCKED"


# ============================================================================
# Base Schemas
# ============================================================================

class AnnotationSyncBase(BaseModel):
    """Base schema for annotation sync."""
    audio_start: float = Field(..., description="Original ASR start time in seconds")
    audio_end: float = Field(..., description="Original ASR end time in seconds")
    video_start_offset: Optional[float] = Field(None, description="Video start time (may be earlier than audio)")
    video_end_offset: Optional[float] = Field(None, description="Video end time (may be later than audio)")
    glosa: Optional[str] = Field(None, description="Sign language gloss notation")
    precision_ms: float = Field(33.0, description="Precision in milliseconds (default 33ms = 1 frame @ 30fps)")


# ============================================================================
# Request Schemas
# ============================================================================

class AnnotationSyncUpdateRequest(BaseModel):
    """Request to update sync boundaries."""
    video_start_offset: Optional[float] = Field(None, description="Video start time in seconds")
    video_end_offset: Optional[float] = Field(None, description="Video end time in seconds")
    glosa: Optional[str] = Field(None, description="Sign language gloss")
    precision_ms: Optional[float] = Field(None, description="Precision in milliseconds")
    
    @field_validator('video_end_offset')
    @classmethod
    def validate_video_end(cls, v: Optional[float], info) -> Optional[float]:
        """Ensure video_end is after video_start."""
        if v is None:
            return v
        values = info.data
        start = values.get('video_start_offset')
        if start is not None and v <= start:
            raise ValueError("video_end_offset must be greater than video_start_offset")
        return v


class AnnotationSyncFineTuneRequest(BaseModel):
    """Request for fine-tuning sync with millisecond precision."""
    adjustment_ms: float = Field(..., description="Adjustment in milliseconds (positive or negative)")
    target: str = Field(..., pattern="^(start|end|both)$", description="Which boundary to adjust")
    
    @field_validator('adjustment_ms')
    @classmethod
    def validate_adjustment(cls, v: float) -> float:
        """Limit adjustment to reasonable range (±5 seconds)."""
        if abs(v) > 5000:
            raise ValueError("Adjustment must be between -5000ms and +5000ms")
        return v


class AnnotationSyncValidateRequest(BaseModel):
    """Request to validate sync status."""
    text_match: bool = Field(False, description="Text matches audio")
    video_complete: bool = Field(False, description="JBI movement fully captured")
    sync_locked: bool = Field(False, description="Alignment is finalized")


class StitchPreviewRequest(BaseModel):
    """Request for stitched video preview."""
    include_next_segment: bool = Field(True, description="Include next segment for stitching")
    include_prev_segment: bool = Field(False, description="Include previous segment for stitching")
    buffer_seconds: float = Field(2.0, description="Buffer time in seconds for stitching")


# ============================================================================
# Response Schemas
# ============================================================================

class SyncStatusIndicators(BaseModel):
    """Sync status indicator badges."""
    text_match: bool = Field(False, description="Text matches audio")
    video_complete: bool = Field(False, description="JBI movement fully captured")
    sync_locked: bool = Field(False, description="Alignment is finalized")


class AnnotationSyncResponse(BaseModel):
    """Response with sync data."""
    id: UUID
    annotation_edit_id: UUID
    audio_start: float
    audio_end: float
    audio_duration: float = Field(..., description="Original audio duration in seconds")
    video_start_offset: Optional[float]
    video_end_offset: Optional[float]
    video_duration: float = Field(..., description="Adjusted video duration in seconds")
    extension_seconds: float = Field(..., description="Total extension beyond audio boundaries")
    sync_status: str
    glosa: Optional[str]
    precision_ms: float
    indicators: SyncStatusIndicators
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class AnnotationSyncContextItem(BaseModel):
    """Context item for neighboring segments."""
    segment_id: UUID
    transcript_id: UUID
    text: str
    audio_start: float
    audio_end: float
    video_available: bool = Field(..., description="Whether video is available for this segment")
    has_sync_data: bool = Field(..., description="Whether this segment has sync adjustments")


class AnnotationSyncContextResponse(BaseModel):
    """Response with sync data and surrounding context."""
    # Current segment
    segment_id: UUID
    transcript_id: UUID
    edit_id: UUID
    text: str
    
    # Sync data
    sync: AnnotationSyncResponse
    
    # Context
    previous_segments: List[AnnotationSyncContextItem] = Field(default_factory=list)
    next_segments: List[AnnotationSyncContextItem] = Field(default_factory=list)
    
    # Video info
    video_url: Optional[str] = Field(None, description="Pre-signed URL for video")
    waveform_data: Optional[List[float]] = Field(None, description="Audio waveform samples")


class StitchPreviewResponse(BaseModel):
    """Response for stitched video preview."""
    edit_id: UUID
    segment_id: UUID
    
    # Time ranges
    original_start: float
    original_end: float
    stitched_start: float
    stitched_end: float
    total_duration: float
    
    # Video info
    video_url: str = Field(..., description="Pre-signed URL for stitched video")
    
    # Stitching info
    requires_stitching: bool = Field(..., description="Whether video spans multiple chunks")
    stitched_segments: List[dict] = Field(default_factory=list, description="Segments included in stitch")
    
    # Sync info
    sync_status: str
    extension_seconds: float


class AnnotationSyncValidateResponse(BaseModel):
    """Response for sync validation."""
    edit_id: UUID
    is_valid: bool
    sync_status: str
    indicators: SyncStatusIndicators
    warnings: List[str] = Field(default_factory=list)
    suggestions: List[str] = Field(default_factory=list)


class FineTuneResponse(BaseModel):
    """Response for fine-tune operation."""
    edit_id: UUID
    adjustment_ms: float
    previous_start: Optional[float]
    previous_end: Optional[float]
    new_start: Optional[float]
    new_end: Optional[float]
    video_duration: float
    message: str


class MergeSegmentRequest(BaseModel):
    """Request to merge with adjacent segment."""
    direction: str = Field(..., pattern="^(next|prev)$", description="Direction to merge")
    reason: Optional[str] = Field(None, description="Reason for merging")


class MergeSegmentResponse(BaseModel):
    """Response for merge operation."""
    edit_id: UUID
    merged: bool
    new_boundaries: dict
    video_url: str
    message: str


# ============================================================================
# Timeline/Waveform Schemas
# ============================================================================

class WaveformDataResponse(BaseModel):
    """Audio waveform data for visualization."""
    segment_id: UUID
    transcript_id: UUID
    samples: List[float] = Field(..., description="Waveform amplitude samples (0-1)")
    sample_rate: int = Field(..., description="Samples per second")
    duration: float = Field(..., description="Total duration in seconds")
    text_markers: List[dict] = Field(default_factory=list, description="Text positions on timeline")


class TimelineRangeResponse(BaseModel):
    """Timeline range with visual indicators."""
    edit_id: UUID
    
    # Audio range (original)
    audio_start: float
    audio_end: float
    
    # Video range (adjusted)
    video_start: float
    video_end: float
    
    # Visual indicators
    playhead_position: float = Field(..., description="Current playhead position")
    text_overlay: str = Field(..., description="Text at current position")
    
    # Range slider config
    min_bound: float = Field(..., description="Minimum allowed boundary")
    max_bound: float = Field(..., description="Maximum allowed boundary")
    step: float = Field(..., description="Step size for slider (in seconds)")
