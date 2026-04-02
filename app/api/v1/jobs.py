import uuid
import logging
from pathlib import Path
from typing import Optional, Annotated

import asyncio
from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException, Query, Depends, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas import (
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
    CategoryUpdateRequest,
    CategoryUpdateResponse,
    SignLanguageCategory,
)
from app.db.models.pipeline import JobStatus
from app.repositories.job_repository import JobRepository, get_job_repository
from app.pipeline.utils.result_serializer import deserialize_pipeline_result
from app.services.validator import (
    validate_upload, validate_video_file, VideoValidationError,
)
from app.services.downloader import download_video, infer_extension, DownloadError
from app.services.job_service import JobService, get_job_service
from app.services.minio_service import get_minio_service
from app.workers.tasks import process_job
from app.core.exceptions import ValidationError, NotFoundError, PermissionError, ConflictError
from app.db.models.auth import User
from app.api.deps import get_current_user
from app.schemas.job import (
    JobCreate, 
    JobResponse,
    JobStatusDetailResponse,
    JobListItemResponse,
    JobListDetailedResponse,
)

# Terminal states
TERMINAL_STATES = {JobStatus.READY_FOR_ANNOTATION, JobStatus.FAILED, JobStatus.CANCELLED}

def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Helper: build status response from a DB record ──────────────────────

def _record_to_status_response(record) -> JobStatusResponse:
    """Convert a PipelineJob ORM instance to a JobStatusResponse."""
    # Build progress info if job is in a processing state
    progress = None
    processing_states = {
        "DETECTING",
        "TRANSCRIBING", 
        "CROPPING",
    }
    
    # Try to get progress data if available on the record
    if record.status in processing_states:
        # Check if record has progress fields (may not exist in current schema)
        progress_phase = getattr(record, 'current_stage', record.status.lower())
        progress_current = getattr(record, 'progress_current', 0)
        progress_total = getattr(record, 'progress_total', 0)
        progress_percent = getattr(record, 'progress_percent', 0.0)
        
        if progress_total > 0:
            progress = JobProgressResponse(
                phase=progress_phase,
                current=progress_current,
                total=progress_total,
                percent=progress_percent,
            )
    
    return JobStatusResponse(
        job_id=str(record.id),
        status=record.status,
        video_title=record.original_filename or None,
        category=record.category,
        progress=progress,
        error=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ── GET /jobs ─────────────────────────────────────────────────────────────

# Valid statuses from PipelineJob model (see app/db/models/pipeline.py)
VALID_STATUSES = {
    "UPLOADED",
    "QUEUED", 
    "DETECTING",
    "TRANSCRIBING",
    "CROPPING",
    "READY_FOR_ANNOTATION",
    "FAILED",
    "CANCELLED"
}

# Valid sign language categories
VALID_CATEGORIES = {
    SignLanguageCategory.SIBI.value,
    SignLanguageCategory.BISINDO.value,
}


@router.get(
    "/jobs",
    response_model=JobListResponse,
    responses={400: {"model": ErrorResponse}},
)
async def list_jobs(
    session: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by job status"),
    category: Optional[str] = Query(None, description="Filter by sign language category (SIBI or BISINDO)"),
    limit: int = Query(20, ge=1, le=100, description="Max jobs to return"),
    offset: int = Query(0, ge=0, description="Number of jobs to skip"),
):
    """List all jobs with optional status and category filtering and pagination.

    Jobs are sorted by creation time (newest first).
    """
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status '{status}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )
    
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
        )

    records, total = await JobRepository(session).list_filtered(
        status=status, category=category, limit=limit, offset=offset,
    )

    jobs = [_record_to_status_response(r) for r in records]

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
    session: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    category: Optional[str] = Form(None, description="Sign language category (SIBI or BISINDO)"),
):
    """Upload a video or provide a URL to start a detection job.

    Provide either a `file` (multipart upload) or a `url` (public video link).
    If both are provided, `file` takes priority.
    
    Optional category field to classify the sign language type (SIBI or BISINDO).
    """
    logger.debug(
        "create_job called — file=%s, url=%s, category=%s",
        file.filename if file else None, url, category,
    )

    if file is None and url is None:
        logger.debug("create_job rejected — no file or url provided")
        raise HTTPException(
            status_code=400,
            detail="Either 'file' or 'url' must be provided",
        )
    
    # Validate category if provided
    if category is not None and category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
        )

    job_id = str(uuid.uuid4())
    logger.debug("Generated job_id=%s", job_id)

    if file is not None:
        logger.debug(
            "Processing file upload — filename=%s, content_type=%s",
            file.filename, file.content_type,
        )
        file_path, file_size = await _handle_file_upload(job_id, file)
        video_title = file.filename or ""
        logger.debug("File saved to %s, size=%d bytes", file_path, file_size)
    else:
        logger.debug("Processing URL download — url=%s", url)
        file_path, file_size = _handle_url_download(job_id, url)
        # Extract filename from URL path
        video_title = Path(url).name.split("?")[0] if url else ""
        logger.debug("URL downloaded to %s, size=%d bytes", file_path, file_size)

    # --- Create job record in DB ---
    logger.debug("Creating DB record — job_id=%s, video_title=%s, category=%s", job_id, video_title, category)
    record = await JobRepository(session).create(
        job_id, str(file_path), video_title=video_title, category=category
    )
    logger.debug("DB record created — status=%s, category=%s, created_at=%s", record.status, record.category, record.created_at)

    logger.info("Job created: id=%s, source=%s", job_id, "upload" if file else "url")

    # --- Enqueue background processing ---
    logger.debug("Enqueuing background task for job_id=%s", job_id)
    background_tasks.add_task(process_job, job_id, str(file_path))

    return JobCreateResponse(
        id=record.id,
        status=record.status,
        original_filename=record.original_filename,
        file_size=file_size,
        category=record.category,
        created_at=record.created_at,
        message="Job created successfully",
    )


async def _handle_file_upload(job_id: str, file: UploadFile) -> tuple[Path, int]:
    """Process a multipart file upload. Returns saved file path."""
    logger.debug("_handle_file_upload — reading file into memory")
    content = await file.read()
    file_size = len(content)
    logger.debug("_handle_file_upload — file_size=%d bytes (%.1f MB)", file_size, file_size / (1024 * 1024))

    try:
        validate_upload(file.filename, file_size)
        logger.debug("_handle_file_upload — upload validation passed")
    except VideoValidationError as exc:
        logger.debug("_handle_file_upload — upload validation failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    ext = Path(file.filename).suffix.lower()
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{job_id}{ext}"
    logger.debug("_handle_file_upload — saving to %s", file_path)

    try:
        with open(file_path, "wb") as f:
            f.write(content)
        logger.debug("_handle_file_upload — file written successfully")
    except IOError:
        logger.exception("Failed to save uploaded file for job %s", job_id)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    try:
        validate_video_file(str(file_path))
        logger.debug("_handle_file_upload — video validation passed")
    except VideoValidationError as exc:
        logger.debug("_handle_file_upload — video validation failed: %s", exc)
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))
    
    return file_path, file_size


def _handle_url_download(job_id: str, url: str) -> tuple[Path, int]:
    """Download a video from URL. Returns saved file path."""
    ext = infer_extension(url)
    logger.debug("_handle_url_download — inferred extension=%s from url=%s", ext, url)
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / f"{job_id}{ext}"

    # Download
    try:
        logger.debug("_handle_url_download — downloading to %s", file_path)
        file_size = download_video(url, str(file_path))
        logger.debug("_handle_url_download — downloaded %d bytes (%.1f MB)", file_size, file_size / (1024 * 1024))
    except DownloadError as exc:
        logger.debug("_handle_url_download — download failed: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate extension (inferred ext might not match actual content)
    try:
        validate_upload(f"video{ext}", file_size)
        logger.debug("_handle_url_download — upload validation passed")
    except VideoValidationError as exc:
        logger.debug("_handle_url_download — upload validation failed: %s", exc)
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    # Validate video content
    try:
        validate_video_file(str(file_path))
        logger.debug("_handle_url_download — video validation passed")
    except VideoValidationError as exc:
        logger.debug("_handle_url_download — video validation failed: %s", exc)
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc))

    return file_path, file_size


# ── GET /jobs/{job_id} ───────────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_job_status(job_id: str, session: AsyncSession = Depends(get_db)):
    """Get the current status and progress of a job.

    Clients poll this endpoint to track processing progress.
    Progress details are available when status is "processing".
    Error details are available when status is "failed".
    """
    record = await JobRepository(session).get_by_id( job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return _record_to_status_response(record)


# ── PUT /jobs/{job_id}/category ─────────────────────────────────────────

@router.put(
    "/jobs/{job_id}/category",
    response_model=CategoryUpdateResponse,
    responses={
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    },
)
async def update_job_category(
    job_id: str,
    request: CategoryUpdateRequest,
    session: AsyncSession = Depends(get_db),
):
    """Update the sign language category of a job.
    
    Any user can update the category. The category can be set to:
    - SIBI (Sistem Isyarat Bahasa Indonesia)
    - BISINDO (Bahasa Isyarat Indonesia)
    
    Request body:
    ```json
    {
        "category": "SIBI"
    }
    ```
    """
    category = request.category
    
    # Validate category
    if category not in VALID_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Must be one of: {', '.join(sorted(VALID_CATEGORIES))}",
        )
    
    # Check if job exists
    record = await JobRepository(session).get_by_id(job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    
    # Update category
    success = await JobRepository(session).update_category(job_id, category)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update category")
    
    logger.info("Job category updated: job_id=%s, category=%s", job_id, category)
    
    return CategoryUpdateResponse(
        job_id=job_id,
        category=category,
        message=f"Category updated to {category}",
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
async def cancel_job(job_id: str, session: AsyncSession = Depends(get_db)):
    """Cancel a queued or in-progress job.

    - Queued jobs are cancelled immediately.
    - Processing jobs are marked as cancelled; the background worker
      will detect this and stop cooperatively.
    - Jobs already in a terminal state (completed, failed, cancelled)
      cannot be cancelled and return 409 Conflict.
    """
    record = await JobRepository(session).get_by_id( job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if is_terminal(JobStatus(record.status)):
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is already '{record.status}' and cannot be cancelled",
        )

    success = await JobRepository(session).update_status( job_id, JobStatus.CANCELLED)
    if not success:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel job '{job_id}' in state '{record.status}'",
        )

    # Clean up uploaded video file
    _cleanup_upload(record.video_path)

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
async def get_job_results(job_id: str, session: AsyncSession = Depends(get_db)):
    """Get the detection and segmentation results of a completed job.

    Only available when job status is "READY_FOR_ANNOTATION". For other states:
    - queued/processing: 409 (not ready yet)
    - failed/cancelled: 409 (no results available)
    - not found: 404
    """
    record = await JobRepository(session).get_by_id( job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # Results are only available when job is in READY_FOR_ANNOTATION state
    if record.status != JobStatus.READY_FOR_ANNOTATION:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is '{record.status}' — results are only available when job is completed (READY_FOR_ANNOTATION)",
        )

    if not record.result_data:
        raise HTTPException(
            status_code=500,
            detail=f"Job '{job_id}' is READY_FOR_ANNOTATION but result data is missing",
        )

    result = deserialize_pipeline_result(job_id, record.result_data)

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
        status=record.status,
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
async def download_segment(job_id: str, index: int, session: AsyncSession = Depends(get_db)):
    """Download a cropped segment video file.

    Streams the MP4 file for the given segment index.
    Only available when job status is "completed".
    """
    # --- Validate job ---
    record = await JobRepository(session).get_by_id( job_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if record.status != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is '{record.status}' — downloads are only available for completed jobs",
        )

    if not record.result_data:
        raise HTTPException(
            status_code=500,
            detail=f"Job '{job_id}' is completed but result data is missing",
        )

    result = deserialize_pipeline_result(job_id, record.result_data)

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


# ═══════════════════════════════════════════════════════════════════════════
# NEW PIPELINE API (Story 2.3+)
# ═══════════════════════════════════════════════════════════════════════════
# These endpoints implement the new 4-layer architecture with MinIO storage
# and PostgreSQL queue. They supersede the legacy endpoints above.
# ═══════════════════════════════════════════════════════════════════════════

@router.post(
    "/pipeline/jobs",
    response_model=JobCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload video file for processing (new pipeline)",
    tags=["Pipeline Jobs"],
)
async def upload_video_pipeline(
    video: Annotated[UploadFile, File(...)],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Upload a video file for processing via the new pipeline.
    
    - **video**: Video file (MP4, AVI, MKV, MOV)
    - Max size: 10GB
    - Returns job ID for trackingvideo
    """
    try:
        # Validate content type if provided
        if video.content_type and not video.content_type.startswith("video/"):
            raise ValidationError(
                "Invalid content type, expected video file",
                details={"content_type": video.content_type}
            )
        
        # Get file size without loading entire file into memory
        # FastAPI's UploadFile uses SpooledTemporaryFile
        video_file = video.file
        video_file.seek(0, 2)  # Seek to end
        file_size = video_file.tell()
        video_file.seek(0)  # Reset to beginning
        
        # Create job using streaming upload (pass file object directly)
        job_service = get_job_service(db, job_repo)
        job = await job_service.create_job_from_upload(
            filename=video.filename,
            file_data=video_file,
            file_size=file_size,
            user=current_user
        )
        
        return JobCreateResponse(
            id=job.id,
            status=job.status,
            original_filename=job.original_filename,
            file_size=job.file_size,
            created_at=job.created_at,
            message="Video uploaded successfully, processing will begin shortly"
        )
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": e.code,
                    "message": e.message,
                    "details": e.details
                }
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "UPLOAD_FAILED",
                    "message": f"Failed to upload video: {str(e)}"
                }
            }
        )
    finally:
        # Ensure UploadFile is properly closed to free resources
        await video.close()


@router.post(
    "/pipeline/jobs/from-url",
    response_model=JobCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create job from video URL (new pipeline)",
    tags=["Pipeline Jobs"],
)
async def create_job_from_url_pipeline(
    request: JobCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Create a processing job from a video URL via the new pipeline.
    
    - **video_url**: Public URL to download video from
    - System will download and process the video
    """
    try:
        job_service = get_job_service(db, job_repo)
        job = await job_service.create_job_from_url(
            video_url=str(request.video_url),
            user=current_user
        )
        
        return JobCreateResponse(
            id=job.id,
            status=job.status,
            original_filename=job.original_filename,
            file_size=job.file_size,
            created_at=job.created_at,
            message="Video download started, processing will begin shortly"
        )
        
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail={
                "error": {
                    "code": "NOT_IMPLEMENTED",
                    "message": "URL-based upload not yet implemented"
                }
            }
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "UPLOAD_FAILED",
                    "message": f"Failed to process video URL: {str(e)}"
                }
            }
        )


@router.get(
    "/pipeline/jobs/{job_id}",
    response_model=JobStatusDetailResponse,
    summary="Get job status and details (new pipeline)",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    }
)
async def get_job_pipeline(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Get job details and current status from the new pipeline.
    
    - Returns job details with progress percentage
    - Response cached for 2 seconds (NFR3)
    - 200ms response time target (NFR2)
    - Users can only view their own jobs
    - Admins can view all jobs
    """
    try:
        job_service = get_job_service(db, job_repo)
        
        job_data = await job_service.get_job(
            job_id=job_id,
            current_user_id=str(current_user.id),
            is_admin=current_user.is_admin
        )
        
        return JobStatusDetailResponse(**job_data)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(e)
                }
            }
        )


@router.get(
    "/pipeline/jobs",
    response_model=JobListDetailedResponse,
    summary="List jobs with pagination (new pipeline)",
    tags=["Pipeline Jobs"],
)
async def list_jobs_pipeline(
    status: Optional[str] = Query(None, description="Filter by job status"),
    from_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    to_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    List jobs with pagination and filtering.
    
    - Regular users see only their own jobs
    - Admins see all jobs
    - Supports filtering by status and date range
    - Default page size: 20, max: 100
    """
    try:
        job_service = get_job_service(db, job_repo)
        
        result = await job_service.list_jobs(
            current_user_id=str(current_user.id),
            is_admin=current_user.is_admin,
            status=status,
            from_date=from_date,
            to_date=to_date,
            page=page,
            page_size=page_size
        )
        
        # Convert items to Pydantic models
        items = [JobListItemResponse(**item) for item in result["items"]]
        
        return JobListDetailedResponse(
            items=items,
            total=result["total"],
            page=result["page"],
            page_size=result["page_size"],
            total_pages=result["total_pages"]
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to list jobs: {str(e)}"
                }
            }
        )


@router.delete(
    "/pipeline/jobs/{job_id}",
    response_model=JobCancelResponse,
    summary="Cancel a processing job (Story 2.9)",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    }
)
async def cancel_job_pipeline(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Cancel a video processing job.
    
    - Queued jobs are cancelled immediately
    - Processing jobs are signaled to stop at next checkpoint
    - Cannot cancel completed or failed jobs
    - Users can only cancel their own jobs
    - Admins can cancel any job
    """
    try:
        job_service = get_job_service(db, job_repo)
        
        result = await job_service.cancel_job(
            job_id=job_id,
            current_user_id=str(current_user.id),
            is_admin=current_user.is_admin
        )
        
        return JobCancelResponse(**result)
        
    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(e)
                }
            }
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "CONFLICT",
                    "message": str(e)
                }
            }
        )


def _get_media_type(filename: str) -> str:
    """Infer MIME type from filename extension."""
    ext = Path(filename).suffix.lower()
    mime_types = {
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
    }
    return mime_types.get(ext, "video/mp4")


@router.get(
    "/pipeline/jobs/{job_id}/original",
    summary="Download original video file (new pipeline)",
    tags=["Pipeline Jobs"],
    responses={
        200: {"content": {"video/*": {}}, "description": "Original video file"},
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def download_original_video_pipeline(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Download the original uploaded video file for a job.

    - Streams the original video file
    - Users can only download their own jobs
    - Admins can download any job
    """
    try:
        try:
            job_uuid = uuid.UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")

        job = await job_repo.get_by_id(job_uuid)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")

        # Authorization check
        if not current_user.is_admin and str(job.created_by) != str(current_user.id):
            raise PermissionError("Not authorized to access this job")

        if not job.video_path:
            raise NotFoundError(f"Original video for job {job_id} not found")

        video_path = job.video_path
        path_obj = Path(video_path)

        # Local file path
        if path_obj.is_absolute() or path_obj.exists():
            if not path_obj.exists():
                raise NotFoundError("Original video file not found on disk")

            media_type = _get_media_type(job.original_filename or video_path)
            return FileResponse(
                path=str(path_obj),
                media_type=media_type,
                filename=job.original_filename,
            )

        # MinIO object
        minio_service = get_minio_service()

        exists = await minio_service.object_exists(video_path)
        if not exists:
            raise NotFoundError("Original video not found in storage")

        media_type = _get_media_type(job.original_filename or video_path)

        async def _stream_minio():
            response = await asyncio.to_thread(
                minio_service.client.get_object,
                minio_service._bucket_name,
                video_path
            )
            try:
                while True:
                    chunk = await asyncio.to_thread(response.read, 8192)
                    if not chunk:
                        break
                    yield chunk
            finally:
                await asyncio.to_thread(response.close)

        headers = {
            "Content-Disposition": f'inline; filename="{job.original_filename}"'
        }

        # Add Content-Length if available
        try:
            object_size = await minio_service.get_object_size(video_path)
            headers["Content-Length"] = str(object_size)
        except Exception:
            pass

        return StreamingResponse(
            _stream_minio(),
            media_type=media_type,
            headers=headers,
        )

    except NotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(e)
                }
            }
        )
    except PermissionError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(e)
                }
            }
        )
    except Exception as e:
        logger.exception("Failed to stream original video for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to stream original video: {str(e)}"
                }
            }
        )
