from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class JobCreateResponse(BaseModel):
    """Response for POST /api/v1/jobs."""
    job_id: str
    status: str
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


class HealthResponse(BaseModel):
    """Response for GET /api/v1/health."""
    status: str  # "healthy", "degraded", "unhealthy"
    model_loaded: bool
    gpu_available: bool
    gpu_name: str | None = None
    disk_free_gb: float


class ErrorResponse(BaseModel):
    """Standard error response body."""
    error: str
    detail: str
