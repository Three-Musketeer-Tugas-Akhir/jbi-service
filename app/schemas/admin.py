"""Admin API schemas."""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class SystemConfigResponse(BaseModel):
    """Pipeline configuration response."""
    min_segment_duration: int = Field(..., description="Minimum segment duration in seconds")
    max_concurrent_jobs: int = Field(..., description="Maximum concurrent processing jobs")
    queue_max_depth: int = Field(..., description="Maximum queue depth")
    asr_model_default: str = Field(..., description="Default ASR model size")
    asr_compute_type: str = Field(..., description="ASR compute type")
    jbi_buffer_seconds: int = Field(..., description="JBI buffer in seconds")


class SystemConfigUpdateRequest(BaseModel):
    """Pipeline configuration update request."""
    min_segment_duration: Optional[int] = Field(None, ge=1, description="Minimum segment duration")
    max_concurrent_jobs: Optional[int] = Field(None, ge=1, description="Max concurrent jobs")
    queue_max_depth: Optional[int] = Field(None, ge=1, description="Queue max depth")
    asr_model_default: Optional[str] = Field(None, description="ASR model (tiny/base/small/medium/large-v3)")
    asr_compute_type: Optional[str] = Field(None, description="ASR compute type")
    jbi_buffer_seconds: Optional[int] = Field(None, ge=0, description="JBI buffer seconds")


class SystemMetricsResponse(BaseModel):
    """System metrics response."""
    jobs_completed_today: int
    jobs_failed_today: int
    jobs_cancelled_today: int
    average_processing_time_seconds: float
    queue_depth_by_stage: Dict[str, int]
    gpu_utilization_percent: float
    timestamp: str


class FailedJobItem(BaseModel):
    """Single failed job item."""
    job_id: str
    error_message: str
    failed_at: Optional[str]
    stage: str
    retry_count: int
    original_filename: str


class FailedJobsResponse(BaseModel):
    """Failed jobs list response."""
    jobs: List[FailedJobItem]
    total: int
    limit: int
    offset: int
