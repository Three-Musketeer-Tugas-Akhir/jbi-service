import uuid
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings
from app.models.schemas import (
    JobCreateResponse,
    JobStatusResponse,
    JobProgressResponse,
    JobCancelResponse,
    JobResultsResponse,
    JobListResponse,
    VideoMetadataResponse,
    DetectionSummaryResponse,
    SegmentResponse,
    BboxResponse,
    ErrorResponse,
)
from app.models.job import Job, JobStatus, is_terminal
from app.models.job_store import job_store
from app.services.validator import (
    validate_upload, validate_video_file, VideoValidationError,
)
from app.services.downloader import download_video, infer_extension, DownloadError
from app.services.pipeline import PipelineResult
from app.workers.tasks import process_job

logger = logging.getLogger(__name__)

router = APIRouter()


# ── GET /jobs ─────────────────────────────────────────────────────────────

VALID_STATUSES = {"queued", "processing", "completed", "failed", "cancelled"}


@router.get(
    "/jobs",
    response_model=JobListResponse,
    responses={400: {"model": ErrorResponse}},
)
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status"),
    limit: int = Query(20, ge=1, le=100, description="Max jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
):
    """List all jobs with optional status filtering and pagination.

    Jobs are sorted by creation time (newest first).
    """
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    all_jobs = job_store.list_filtered(status=status)
    total = len(all_jobs)
    page = all_jobs[offset : offset + limit]

    jobs = []
    for job in page:
        progress = None
        if job.status == JobStatus.PROCESSING and job.progress.total > 0:
            progress = JobProgressResponse(
                phase=job.progress.phase,
                current=job.progress.current,
                total=job.progress.total,
                percent=job.progress.percent,
            )
        jobs.append(
            JobStatusResponse(
                job_id=job.job_id,
                status=job.status.value,
                progress=progress,
                error=job.error,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
        )

    return JobListResponse(jobs=jobs, total=total, limit=limit, offset=offset)


# ── POST /jobs ───────────────────────────────────────────────────────────

@router.post(
    "/jobs",
    status_code=202,
    response_model=JobCreateResponse,
    responses={400: {"model": ErrorResponse}},
)
async def create_job(
    background_tasks: BackgroundTasks,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    """Upload a video or provide a URL to start a detection job.

    Provide either a `file` (multipart upload) or a `url` (public video link).
    If both are provided, `file` takes priority.
    """
    if file is None and url is None:
        raise HTTPException(
            status_code=400,
            detail="Either 'file' or 'url' must be provided",
        )

    job_id = str(uuid.uuid4())

    if file is not None:
        file_path = await _handle_file_upload(job_id, file)
    else:
        file_path = _handle_url_download(job_id, url)

    # --- Create job record ---
    job = Job(job_id=job_id, video_path=str(file_path))
    job_store.create(job)

    logger.info("Job created: id=%s, source=%s", job_id, "upload" if file else "url")

    # --- Enqueue background processing ---
    background_tasks.add_task(process_job, job_id, str(file_path))

    return JobCreateResponse(
        job_id=job.job_id,
        status=job.status.value,
        created_at=job.created_at,
    )


async def _handle_file_upload(job_id: str, file: UploadFile) -> Path:
    """Process a multipart file upload. Returns saved file path."""
    content = await file.read()
    file_size = len(content)

    try:
        validate_upload(file.filename, file_size)
    except VideoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    ext = Path(file.filename).suffix.lower()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{job_id}{ext}"

    try:
        with open(file_path, "wb") as f:
            f.write(content)
    except IOError:
        logger.exception("Failed to save uploaded file for job %s", job_id)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    try:
        validate_video_file(str(file_path))
    except VideoValidationError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    return file_path


def _handle_url_download(job_id: str, url: str) -> Path:
    """Download a video from URL. Returns saved file path."""
    ext = infer_extension(url)
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{job_id}{ext}"

    # Download
    try:
        file_size = download_video(url, str(file_path))
    except DownloadError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate extension (inferred ext might not match actual content)
    try:
        validate_upload(f"video{ext}", file_size)
    except VideoValidationError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate video content
    try:
        validate_video_file(str(file_path))
    except VideoValidationError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    return file_path


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job_status(job_id: str):
    """Get the current status and progress of a job.

    Clients poll this endpoint to track processing progress.
    Progress details are available when status is "processing".
    Error details are available when status is "failed".
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # Build progress object only when processing
    progress = None
    if job.status == JobStatus.PROCESSING and job.progress.total > 0:
        progress = JobProgressResponse(
            phase=job.progress.phase,
            current=job.progress.current,
            total=job.progress.total,
            percent=job.progress.percent,
        )

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status.value,
        progress=progress,
        error=job.error,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


# ── DELETE /jobs/{job_id} ────────────────────────────────────────────────

@router.delete(
    "/jobs/{job_id}",
    response_model=JobCancelResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def cancel_job(job_id: str):
    """Cancel a queued or in-progress job.

    - Queued jobs are cancelled immediately.
    - Processing jobs are marked as cancelled; the background worker
      will detect this and stop cooperatively.
    - Jobs already in a terminal state (completed, failed, cancelled)
      cannot be cancelled and return 409 Conflict.
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if is_terminal(job.status):
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is already '{job.status.value}' and cannot be cancelled",
        )

    success = job_store.update_status(job_id, JobStatus.CANCELLED)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job '{job_id}' in state '{job.status.value}'",
        )

    # Clean up uploaded video file
    _cleanup_upload(job.video_path)

    logger.info("Job cancelled: %s", job_id)

    return JobCancelResponse(
        job_id=job_id,
        status=JobStatus.CANCELLED.value,
    )


def _cleanup_upload(video_path: str):
    """Delete the uploaded video file if it exists."""
    try:
        path = Path(video_path)
        if path.exists():
            path.unlink()
            logger.debug("Cleaned up upload: %s", video_path)
    except OSError:
        logger.warning("Failed to clean up upload: %s", video_path)


# ── GET /jobs/{job_id}/results ───────────────────────────────────────────

@router.get(
    "/jobs/{job_id}/results",
    response_model=JobResultsResponse,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def get_job_results(job_id: str):
    """Get the detection and segmentation results of a completed job.

    Only available when job status is "completed". For other states:
    - queued/processing: 409 (not ready yet)
    - failed/cancelled: 409 (no results available)
    - not found: 404
    """
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is '{job.status.value}' — results are only available for completed jobs",
        )

    result: PipelineResult = job.result
    if not result:
        raise HTTPException(
            status_code=500,
            detail=f"Job '{job_id}' is completed but result data is missing",
        )

    # Build video metadata
    video_metadata = VideoMetadataResponse(
        fps=result.detection.metadata.fps,
        total_frames=result.detection.metadata.frame_count,
        duration_seconds=result.detection.metadata.duration_seconds,
    )

    # Build detection summary
    detection_summary = DetectionSummaryResponse(
        total_seconds_scanned=result.segmentation.total_seconds_scanned,
        seconds_with_detection=result.segmentation.seconds_with_detection,
    )

    # Build segment list with download URLs
    segments = []
    for seg in result.segmentation.segments:
        bbox = BboxResponse(
            x_min=seg.bbox[0],
            y_min=seg.bbox[1],
            width=seg.bbox[2],
            height=seg.bbox[3],
        )
        download_url = f"{settings.api_v1_prefix}/jobs/{job_id}/segments/{seg.index}/download"

        segments.append(SegmentResponse(
            index=seg.index,
            start_time=seg.start_time,
            end_time=seg.end_time,
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            duration_seconds=seg.duration_seconds,
            bbox=bbox,
            download_url=download_url,
        ))

    return JobResultsResponse(
        job_id=job_id,
        status=job.status.value,
        video_metadata=video_metadata,
        detection_summary=detection_summary,
        segments=segments,
    )


# ── GET /jobs/{job_id}/segments/{index}/download ─────────────────────────

@router.get(
    "/jobs/{job_id}/segments/{index}/download",
    responses={
        200: {"content": {"video/mp4": {}}, "description": "Cropped segment video file"},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def download_segment(job_id: str, index: int):
    """Download a cropped segment video file.

    Streams the MP4 file for the given segment index.
    Only available when job status is "completed".
    """
    # --- Validate job ---
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is '{job.status.value}' — downloads are only available for completed jobs",
        )

    result: PipelineResult = job.result
    if not result:
        raise HTTPException(
            status_code=500,
            detail=f"Job '{job_id}' is completed but result data is missing",
        )

    # --- Validate segment index ---
    if index < 0 or index >= len(result.crop.segments):
        raise HTTPException(
            status_code=404,
            detail=f"Segment index {index} not found — job has {len(result.crop.segments)} segments (0–{len(result.crop.segments) - 1})",
        )

    cropped_segment = result.crop.segments[index]
    file_path = Path(cropped_segment.file_path)

    # --- Validate file exists on disk ---
    if not file_path.exists():
        logger.error(
            "Segment file missing: job=%s, index=%d, path=%s",
            job_id, index, file_path,
        )
        raise HTTPException(
            status_code=404,
            detail="Segment file not found on disk — it may have been cleaned up",
        )

    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=cropped_segment.file_name,
    )
