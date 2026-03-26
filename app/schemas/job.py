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
