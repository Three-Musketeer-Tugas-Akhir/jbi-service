"""
Job and Pipeline Schemas.

Pydantic models for job API requests and responses.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class JobCreate(BaseModel):
    """Schema for job creation request (URL-based)."""
    video_url: HttpUrl


class SignLanguageCategory(str, Enum):
    """Sign language category enum."""
    SIBI = "SIBI"
    BISINDO = "BISINDO"


class JobCreateResponse(BaseModel):
    """Response for POST /api/v1/jobs."""
    id: UUID
    status: str
    original_filename: str
    file_size: int
    category: Optional[str] = None
    created_at: datetime
    message: str

    class Config:
        from_attributes = True


class JobResponse(BaseModel):
    """Schema for job details response."""
    id: UUID
    status: str
    original_filename: str
    file_size: int
    category: Optional[str] = None
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Legacy schemas (maintaining compatibility)
class JobCreateResponseLegacy(BaseModel):
    """Response for POST /api/v1/jobs (legacy format)."""
    job_id: str
    status: str
    video_title: str
    created_at: datetime


class JobProgressResponse(BaseModel):
    """Progress details for a processing job."""
    phase: str
    current: int
    total: int
    percent: float


class JobStatusResponse(BaseModel):
    """Response for GET /api/v1/jobs/{job_id}."""
    job_id: str
    status: str
    video_title: Optional[str] = None
    category: Optional[str] = None
    progress: Optional[JobProgressResponse] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    original_video_url: Optional[str] = None


class JobCancelResponse(BaseModel):
    """Response for DELETE /api/v1/jobs/{job_id}."""
    job_id: str
    status: str


class VideoMetadataResponse(BaseModel):
    """Video file metadata."""
    fps: float
    total_frames: int
    duration_seconds: float


class DetectionSummaryResponse(BaseModel):
    """Summary statistics of the detection phase."""
    total_seconds_scanned: int
    seconds_with_detection: int


class BboxResponse(BaseModel):
    """Bounding box in pixel coordinates."""
    x_min: float
    y_min: float
    width: float
    height: float


class SegmentResponse(BaseModel):
    """A single detected segment with download link."""
    index: int
    start_time: str
    end_time: str
    start_seconds: int
    end_seconds: int
    duration_seconds: int
    bbox: BboxResponse
    download_url: str


class JobResultsResponse(BaseModel):
    """Response for GET /api/v1/jobs/{job_id}/results."""
    job_id: str
    status: str
    video_metadata: VideoMetadataResponse
    detection_summary: DetectionSummaryResponse
    segments: list[SegmentResponse]


class JobListResponse(BaseModel):
    """Response for GET /api/v1/jobs (list all jobs)."""
    jobs: list[JobStatusResponse]
    total: int
    limit: int
    offset: int


# Story 2.8: New schemas for enhanced job status API

class JobStatusDetailResponse(BaseModel):
    """Detailed job status response for Story 2.8.
    
    Includes progress calculation from segment completion.
    """
    id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Current job status")
    current_stage: Optional[str] = Field(None, description="Current processing stage")
    category: Optional[str] = Field(None, description="Sign language category (SIBI/BISINDO)")
    progress: int = Field(..., ge=0, le=100, description="Completion percentage (0-100)")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    error_message: Optional[str] = Field(None, description="Error details if failed")
    total_segments: int = Field(..., description="Total video segments")
    completed_segments: int = Field(..., description="Processed segments")
    created_by: Optional[str] = Field(None, description="Uploader user ID")


class JobListItemResponse(BaseModel):
    """Job item in paginated list response."""
    id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="Current job status")
    current_stage: Optional[str] = Field(None, description="Current processing stage")
    category: Optional[str] = Field(None, description="Sign language category (SIBI/BISINDO)")
    progress: int = Field(..., ge=0, le=100, description="Completion percentage (0-100)")
    created_at: Optional[datetime] = Field(None, description="Creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    error_message: Optional[str] = Field(None, description="Error details if failed")
    total_segments: int = Field(..., description="Total video segments")
    completed_segments: int = Field(..., description="Processed segments")


class JobListDetailedResponse(BaseModel):
    """Paginated job list response for Story 2.8."""
    items: List[JobListItemResponse] = Field(..., description="Job items")
    total: int = Field(..., description="Total matching jobs")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    total_pages: int = Field(..., description="Total pages available")


# Story 2.9: Job Cancellation Response

class JobCancelResponse(BaseModel):
    """Response for job cancellation (Story 2.9)."""
    id: str = Field(..., description="Job UUID")
    status: str = Field(..., description="New status (CANCELLED)")
    queue_jobs_cancelled: int = Field(..., description="Number of queue jobs cancelled")
    message: str = Field(..., description="Success message")


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health."""
    status: str = Field(..., description="Overall health status (healthy/degraded)")
    database: str = Field(..., description="Database connectivity (connected/disconnected)")
    minio: str = Field(..., description="MinIO connectivity (connected/disconnected)")
    yolo_model: str = Field(..., description="YOLO model status (loaded/not_loaded)")
    gpu_available: bool = Field(..., description="GPU availability")
    disk_space: str = Field(..., description="Disk space status (OK/low/critical)")


class CategoryUpdateRequest(BaseModel):
    """Request body for category update endpoint."""
    category: str = Field(..., description="Sign language category (SIBI or BISINDO)")


class CategoryUpdateResponse(BaseModel):
    """Response for category update endpoint."""
    job_id: str = Field(..., description="Job UUID")
    category: str = Field(..., description="Updated category (SIBI/BISINDO)")
    message: str = Field(..., description="Success message")


class ErrorResponse(BaseModel):
    """Standard error response body."""
    error: str
    detail: str


# ============================================================================
# Stage 1 Results Schemas
# ============================================================================

class BboxDataResponse(BaseModel):
    """Bounding box data for a segment."""
    x: float = Field(..., description="X coordinate (top-left)")
    y: float = Field(..., description="Y coordinate (top-left)")
    width: float = Field(..., description="Bounding box width")
    height: float = Field(..., description="Bounding box height")


class SegmentResultResponse(BaseModel):
    """Single segment result for stage 1."""
    id: str = Field(..., description="Segment UUID")
    segment_index: int = Field(..., description="Segment index (0-based)")
    bbox_data: Optional[BboxDataResponse] = Field(None, description="Bounding box coordinates")
    url: str = Field(..., description="Asset URL for the segment video")


class Stage1ResultsResponse(BaseModel):
    """Response for GET /api/v1/pipeline/jobs/{job_id}/stage1/results."""
    id: str = Field(..., description="Job UUID")
    results: List[SegmentResultResponse] = Field(..., description="List of segment results")


# ============================================================================
# Stage 2 Results Schemas
# ============================================================================

class Stage2UtteranceResponse(BaseModel):
    """Individual ASR utterance result."""
    id: str = Field(..., description="Transcript UUID")
    utterance_index: int = Field(..., description="Index within segment (0-based)")
    text: str = Field(..., description="Transcribed text")
    start: float = Field(..., description="Start time in seconds (relative to segment)")
    end: float = Field(..., description="End time in seconds (relative to segment)")
    confidence: float = Field(..., description="ASR confidence score (0-1)")
    url: Optional[str] = Field(None, description="Asset URL for utterance video")
    status: str = Field(..., description="Cropping status: pending, cropped, or failed")


class Stage2SegmentResponse(BaseModel):
    """Segment with ASR utterances for Stage 2."""
    segment_id: str = Field(..., description="Segment UUID")
    asr_review_flag: bool = Field(..., description="True if segment needs ASR review")
    utterances: List[Stage2UtteranceResponse] = Field(..., description="List of utterances")


class Stage2ResultsResponse(BaseModel):
    """Response for GET /api/v1/pipeline/jobs/{job_id}/stage2/results."""
    id: str = Field(..., description="Job UUID")
    results: List[Stage2SegmentResponse] = Field(..., description="List of segments with ASR data")


# ============================================================================
# Stage 3 Results Schemas
# ============================================================================

class Stage3Summary(BaseModel):
    """Summary of Stage 3 cropping results."""
    total_utterances: int = Field(..., description="Total utterances across all segments")
    cropped: int = Field(..., description="Number of successfully cropped utterances")
    failed: int = Field(..., description="Number of failed utterances")
    pending: int = Field(..., description="Number of pending utterances")


class Stage3UtteranceResponse(BaseModel):
    """Individual cropped utterance result for Stage 3."""
    id: str = Field(..., description="Transcript UUID")
    utterance_index: int = Field(..., description="Index within segment (0-based)")
    text: str = Field(..., description="Transcribed text")
    start: float = Field(..., description="CROPPED start time in seconds (relative to segment)")
    end: float = Field(..., description="CROPPED end time in seconds (relative to segment)")
    confidence: float = Field(..., description="ASR confidence score (0-1)")
    url: Optional[str] = Field(None, description="Asset URL for cropped utterance video")
    status: str = Field(..., description="Cropping status: cropped, pending, or failed")


class Stage3SegmentResponse(BaseModel):
    """Segment with cropped utterances for Stage 3."""
    segment_id: str = Field(..., description="Segment UUID")
    asr_review_flag: bool = Field(..., description="True if segment needs ASR review")
    utterances: List[Stage3UtteranceResponse] = Field(..., description="List of cropped utterances")


class Stage3ResultsResponse(BaseModel):
    """Response for GET /api/v1/pipeline/jobs/{job_id}/stage3/results."""
    id: str = Field(..., description="Job UUID")
    summary: Stage3Summary = Field(..., description="Summary of cropping status")
    results: List[Stage3SegmentResponse] = Field(..., description="List of segments with cropped utterances")


# ============================================================================
# Dataset Explorer Schemas
# ============================================================================

class DatasetExplorerUtterance(BaseModel):
    utterance_index: int
    status: Optional[str] = None
    asr_text: str
    glosa_text: str
    cropped_video_url: Optional[str] = None
    start: float
    end: float

class DatasetExplorerSegment(BaseModel):
    segment_id: str
    segment_index: int
    video_url: Optional[str] = None
    is_completed: bool
    utterances: List[DatasetExplorerUtterance]

class DatasetExplorerResponse(BaseModel):
    job_id: str
    original_filename: str
    segments: List[DatasetExplorerSegment]
