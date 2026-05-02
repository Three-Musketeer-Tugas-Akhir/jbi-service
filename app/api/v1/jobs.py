import uuid
import logging
from pathlib import Path
from typing import Optional, Annotated
import io
import zipfile

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
from app.db.models.pipeline import JobStatus, PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationEdit
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
    Stage1ResultsResponse,
    SegmentResultResponse,
    BboxDataResponse,
    Stage2ResultsResponse,
    Stage2SegmentResponse,
    Stage2UtteranceResponse,
    Stage3ResultsResponse,
    Stage3SegmentResponse,
    Stage3UtteranceResponse,
    Stage3Summary,
    DatasetExplorerResponse,
    DatasetExplorerSegment,
    DatasetExplorerUtterance,
)
from app.repositories.segment_repository import SegmentRepository
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.services.streaming_token_service import streaming_token_service

# Terminal states
TERMINAL_STATES = {JobStatus.READY_FOR_ANNOTATION, JobStatus.NEEDS_VOICE_ANNOTATION, JobStatus.FAILED, JobStatus.CANCELLED}

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
    
    # Build original video URL from video_path
    original_video_url = None
    if record.video_path:
        # video_path is like "jobs/{job_id}/original/{filename}"
        # Construct the assets URL
        original_video_url = f"{settings.api_v1_prefix}/assets/{record.video_path}"
    
    return JobStatusResponse(
        job_id=str(record.id),
        status=record.status,
        video_title=record.original_filename or None,
        category=record.category,
        progress=progress,
        error=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
        original_video_url=original_video_url,
    )


# ── GET /jobs ─────────────────────────────────────────────────────────────

# Valid statuses from PipelineJob model (see app/db/models/pipeline.py)
VALID_STATUSES = {
    "UPLOADED",
    "QUEUED", 
    "DETECTING",
    "TRANSCRIBING",
    "CROPPING",
    "NEEDS_VOICE_ANNOTATION",
    "VOICE_ANNOTATION_IN_PROGRESS",
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

    # Results are available when job has completed cropping (including voice annotation states)
    allowed_for_results = {
        JobStatus.READY_FOR_ANNOTATION,
        JobStatus.NEEDS_VOICE_ANNOTATION,
        JobStatus.VOICE_ANNOTATION_IN_PROGRESS,
    }
    if record.status not in allowed_for_results:
        raise HTTPException(
            status_code=409,
            detail=f"Job '{job_id}' is '{record.status}' — results are only available when job has completed processing",
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


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 1 RESULTS API
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/pipeline/jobs/{job_id}/stage1/results",
    response_model=Stage1ResultsResponse,
    summary="Get Stage 1 (detection) results",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    }
)
async def get_stage1_results(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository),
):
    """
    Get Stage 1 detection results with segment information.
    
    Returns segments with bounding box data and asset URLs.
    
    - **id**: Job UUID
    - **results**: List of segment results containing:
      - Segment ID and index
      - Bounding box coordinates (x, y, width, height)
      - Asset URL for accessing the segment video
    
    ## Authorization
    - Users can only access their own job results
    - Admins can access any job results
    
    ## Example Response
    ```json
    {
      "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
      "results": [
        {
          "id": "segment-uuid",
          "segment_index": 0,
          "bbox_data": {
            "x": 100.5,
            "y": 200.0,
            "width": 300.0,
            "height": 150.0
          },
          "url": "/api/v1/assets/jobs/196d54f7-f2c2-4326-ad0e-c3849b8d3d72/segments/segment_0000.mp4"
        }
      ]
    }
    ```
    """
    try:
        # Validate job_id format
        try:
            job_uuid = uuid.UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Get job from database
        job = await job_repo.get_by_id(job_uuid)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Authorization check
        if not current_user.is_admin and str(job.created_by) != str(current_user.id):
            raise PermissionError("Not authorized to access this job")
        
        # Get segments for this job
        from app.repositories.segment_repository import SegmentRepository, get_segment_repository
        segment_repo = get_segment_repository(db)
        segments = await segment_repo.get_by_job_id(job_uuid)
        
        # Build response
        results = []
        for segment in segments:
            # Parse bbox_data from JSON
            bbox_data = None
            if segment.bbox_data:
                bbox_data = BboxDataResponse(
                    x=segment.bbox_data.get("x", 0.0),
                    y=segment.bbox_data.get("y", 0.0),
                    width=segment.bbox_data.get("width", 0.0),
                    height=segment.bbox_data.get("height", 0.0),
                )
            
            # Build asset URL
            # Use the cropped_video_path if available (MinIO key), otherwise construct from pattern
            if segment.cropped_video_path:
                # If it's a MinIO key, use it directly
                if segment.cropped_video_path.startswith("jobs/"):
                    url = f"/api/v1/assets/{segment.cropped_video_path}"
                else:
                    # Legacy path format
                    url = f"/api/v1/assets/jobs/{job_id}/segments/segment_{segment.segment_index:04d}.mp4"
            else:
                # Default pattern
                url = f"/api/v1/assets/jobs/{job_id}/segments/segment_{segment.segment_index:04d}.mp4"
            
            results.append(
                SegmentResultResponse(
                    id=str(segment.id),
                    segment_index=segment.segment_index,
                    bbox_data=bbox_data,
                    url=url,
                )
            )
        
        return Stage1ResultsResponse(
            id=job_id,
            results=results,
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
        logger.exception("Failed to get stage 1 results for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to get stage 1 results: {str(e)}"
                }
            }
        )


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 2 RESULTS API
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/pipeline/jobs/{job_id}/stage2/results",
    response_model=Stage2ResultsResponse,
    summary="Get Stage 2 (ASR) results",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    }
)
async def get_stage2_results(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository),
):
    """
    Get Stage 2 ASR results with utterance-level transcription data.
    
    Returns segments with their transcribed utterances, timestamps, and confidence scores.
    
    - **id**: Job UUID
    - **results**: List of segments containing:
      - Segment ID and ASR review flag
      - List of utterances with text, timestamps, confidence, and asset URLs
    
    ## Authorization
    - Users can only access their own job results
    - Admins can access any job results
    
    ## Example Response
    ```json
    {
      "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
      "results": [
        {
          "segment_id": "segment-uuid",
          "asr_review_flag": false,
          "utterances": [
            {
              "id": "utterance-uuid",
              "utterance_index": 0,
              "text": "Ini adalah contoh transkripsi",
              "start": 0.0,
              "end": 3.5,
              "confidence": 0.92,
              "url": "/api/v1/assets/jobs/.../utterance_0000_0000.mp4",
              "status": "cropped"
            }
          ]
        }
      ]
    }
    ```
    """
    try:
        # Validate job_id format
        try:
            job_uuid = uuid.UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Get job from database
        job = await job_repo.get_by_id(job_uuid)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Authorization check
        if not current_user.is_admin and str(job.created_by) != str(current_user.id):
            raise PermissionError("Not authorized to access this job")
        
        # Get segments with their transcripts
        from app.repositories.segment_repository import SegmentRepository, get_segment_repository
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from app.db.models.pipeline import PipelineSegment, PipelineTranscript
        
        # Query segments with eager-loaded transcripts
        result = await db.execute(
            select(PipelineSegment)
            .where(PipelineSegment.job_id == job_uuid)
            .options(selectinload(PipelineSegment.transcripts))
            .order_by(PipelineSegment.segment_index)
        )
        segments = result.scalars().all()
        
        # Build response
        results = []
        for segment in segments:
            # Build utterances list
            utterances = []
            for transcript in segment.transcripts:
                # Build asset URL for utterance video
                if transcript.video_path:
                    if transcript.video_path.startswith("jobs/"):
                        url = f"/api/v1/assets/{transcript.video_path}"
                    else:
                        url = f"/api/v1/assets/jobs/{job_id}/utterances/{transcript.video_path}"
                else:
                    # Default pattern: utterance_{segment_index}_{utterance_index}.mp4
                    url = f"/api/v1/assets/jobs/{job_id}/utterances/utterance_{segment.segment_index:04d}_{transcript.utterance_index:04d}.mp4"
                
                utterances.append(
                    Stage2UtteranceResponse(
                        id=str(transcript.id),
                        utterance_index=transcript.utterance_index,
                        text=transcript.text,
                        start=transcript.start,
                        end=transcript.end,
                        confidence=transcript.confidence,
                        url=url,
                        status=transcript.status or "pending",
                    )
                )
            
            # Sort utterances by index
            utterances.sort(key=lambda u: u.utterance_index)
            
            results.append(
                Stage2SegmentResponse(
                    segment_id=str(segment.id),
                    asr_review_flag=segment.asr_review_flag or False,
                    utterances=utterances,
                )
            )
        
        return Stage2ResultsResponse(
            id=job_id,
            results=results,
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
        logger.exception("Failed to get stage 2 results for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to get stage 2 results: {str(e)}"
                }
            }
        )


# ═══════════════════════════════════════════════════════════════════════════
# STAGE 3 RESULTS API
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/pipeline/jobs/{job_id}/stage3/results",
    response_model=Stage3ResultsResponse,
    summary="Get Stage 3 (cropping) results",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    }
)
async def get_stage3_results(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository),
):
    """
    Get Stage 3 cropping results with final cropped timestamps and videos.
    
    Returns segments with their cropped utterances, including the FINAL timestamps
    after the cropping algorithm has been applied, along with the cropped video URLs.
    
    - **id**: Job UUID
    - **summary**: Overview of cropping status (total, cropped, failed, pending)
    - **results**: List of segments containing cropped utterances
    
    ## Cropping Algorithm
    The cropping worker applies the following algorithm to each utterance:
    - First utterance: start unchanged
    - Subsequent utterances: start += 1s offset
    - End calculated based on gap to next utterance:
      - Gap > 2s: add 2s buffer
      - Gap <= 2s: extend to next + 1s
    - Last utterance: extend to video duration or +1s
    
    ## Authorization
    - Users can only access their own job results
    - Admins can access any job results
    
    ## Example Response
    ```json
    {
      "id": "196d54f7-f2c2-4326-ad0e-c3849b8d3d72",
      "summary": {
        "total_utterances": 10,
        "cropped": 9,
        "failed": 1,
        "pending": 0
      },
      "results": [
        {
          "segment_id": "segment-uuid",
          "asr_review_flag": false,
          "utterances": [
            {
              "id": "utterance-uuid",
              "utterance_index": 0,
              "text": "Ini adalah contoh transkripsi",
              "start": 1.0,
              "end": 6.5,
              "confidence": 0.92,
              "url": "/api/v1/assets/jobs/.../utterance_xxx.mp4",
              "status": "cropped"
            }
          ]
        }
      ]
    }
    ```
    
    ## Difference from Stage 2
    - **Stage 2**: Returns ORIGINAL ASR timestamps (from Whisper)
    - **Stage 3**: Returns CROPPED timestamps (modified by algorithm)
    - **Stage 2**: URL points to segment video (Stage 1)
    - **Stage 3**: URL points to individual utterance video (Stage 3)
    """
    try:
        # Validate job_id format
        try:
            job_uuid = uuid.UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Get job from database
        job = await job_repo.get_by_id(job_uuid)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Authorization check
        if not current_user.is_admin and str(job.created_by) != str(current_user.id):
            raise PermissionError("Not authorized to access this job")
        
        # Get segments with their transcripts
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from app.db.models.pipeline import PipelineSegment, PipelineTranscript
        
        # Query segments with eager-loaded transcripts
        result = await db.execute(
            select(PipelineSegment)
            .where(PipelineSegment.job_id == job_uuid)
            .options(selectinload(PipelineSegment.transcripts))
            .order_by(PipelineSegment.segment_index)
        )
        segments = result.scalars().all()
        
        # Build response and calculate summary
        results = []
        total_utterances = 0
        cropped_count = 0
        failed_count = 0
        pending_count = 0
        
        for segment in segments:
            # Build utterances list
            utterances = []
            for transcript in segment.transcripts:
                total_utterances += 1
                
                # Count by status
                cropping_status = transcript.status or "pending"
                if cropping_status == "cropped":
                    cropped_count += 1
                elif cropping_status == "failed":
                    failed_count += 1
                else:
                    pending_count += 1
                
                # Build asset URL for cropped utterance video
                if transcript.video_path:
                    if transcript.video_path.startswith("jobs/"):
                        url = f"/api/v1/assets/{transcript.video_path}"
                    else:
                        url = f"/api/v1/assets/jobs/{job_id}/utterances/{transcript.video_path}"
                else:
                    # Default pattern
                    url = f"/api/v1/assets/jobs/{job_id}/utterances/utterance_{segment.segment_index:04d}_{transcript.utterance_index:04d}.mp4"
                
                utterances.append(
                    Stage3UtteranceResponse(
                        id=str(transcript.id),
                        utterance_index=transcript.utterance_index,
                        text=transcript.text,
                        start=transcript.start,
                        end=transcript.end,
                        confidence=transcript.confidence,
                        url=url,
                        status=cropping_status,
                    )
                )
            
            # Sort utterances by index
            utterances.sort(key=lambda u: u.utterance_index)
            
            results.append(
                Stage3SegmentResponse(
                    segment_id=str(segment.id),
                    asr_review_flag=segment.asr_review_flag or False,
                    utterances=utterances,
                )
            )
        
        # Build summary
        summary = Stage3Summary(
            total_utterances=total_utterances,
            cropped=cropped_count,
            failed=failed_count,
            pending=pending_count,
        )
        
        return Stage3ResultsResponse(
            id=job_id,
            summary=summary,
            results=results,
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
        logger.exception("Failed to get stage 3 results for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to get stage 3 results: {str(e)}"
                }
            }
        )


# ═══════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════
# DATASET DOWNLOAD API
# ═══════════════════════════════════════════════════════════════════════════

@router.get(
    "/pipeline/jobs/{job_id}/dataset/explorer",
    response_model=DatasetExplorerResponse,
    summary="Get hierarchical dataset for explorer UI",
    tags=["Pipeline Jobs"],
    responses={
        404: {"model": ErrorResponse},
    }
)
async def get_dataset_explorer(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
    """
    Get the complete dataset hierarchy for the explorer UI.
    Shows segments and their utterances with physical video crop URLs.
    """
    import uuid
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    segment_repo = SegmentRepository(db)
    edit_repo = AnnotationEditRepository(db)

    # Get all segments for job with their transcripts
    segments = await segment_repo.get_by_job_id(uuid.UUID(job_id))
    
    explorer_segments = []
    for segment in segments:
        # Get original ASR transcripts
        asr_transcripts = sorted(segment.transcripts, key=lambda t: t.utterance_index) if segment.transcripts else []
        
        # Get the latest active edit (to get glosa and cropped video)
        latest_edit = await edit_repo.get_latest_by_segment(segment.id)
        
        utterances_map = {}
        if latest_edit and latest_edit.utterance_corrections:
            for u in latest_edit.utterance_corrections:
                utterances_map[u["utterance_index"]] = u

        explorer_utterances = []
        is_segment_completed = True
        
        for asr_t in asr_transcripts:
            u_data = utterances_map.get(asr_t.utterance_index, {})
            status = u_data.get("status")
            if status != "OK":
                is_segment_completed = False
                
            cv_path = u_data.get("cropped_video_path")
            cv_url = None
            if cv_path:
                token = streaming_token_service.generate_token(current_user.id, cv_path)
                cv_url = f"{settings.api_v1_prefix}/assets/{cv_path}?token={token}"

            explorer_utterances.append(DatasetExplorerUtterance(
                utterance_index=asr_t.utterance_index,
                status=status,
                asr_text=asr_t.text,
                glosa_text=u_data.get("text", ""),
                cropped_video_url=cv_url,
                start=u_data.get("start", asr_t.start),
                end=u_data.get("end", asr_t.end)
            ))

        # Generate segment master video URL
        seg_video_url = None
        if segment.cropped_video_path:
            token = streaming_token_service.generate_token(current_user.id, segment.cropped_video_path)
            seg_video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"

        explorer_segments.append(DatasetExplorerSegment(
            segment_id=str(segment.id),
            segment_index=segment.segment_index,
            video_url=seg_video_url,
            is_completed=is_segment_completed if len(explorer_utterances) > 0 else False,
            utterances=explorer_utterances
        ))
        
    explorer_segments.sort(key=lambda s: s.segment_index)

    return DatasetExplorerResponse(
        job_id=job_id,
        original_filename=job.original_filename,
        segments=explorer_segments
    )



@router.get(
    "/pipeline/jobs/{job_id}/dataset/download",
    summary="Download dataset as ZIP",
    tags=["Pipeline Jobs"],
    responses={
        200: {"content": {"application/zip": {}}, "description": "Dataset ZIP file"},
        404: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        400: {"model": ErrorResponse},
    },
)
async def download_dataset_zip(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository),
):
    """
    Download the complete dataset for a job as a ZIP file.

    Includes:
    - Original video
    - Segment videos (stage 1)
    - Utterance videos (stage 3)
    - Audio WAV files
    - ASR transcripts (JSON)
    - Annotated transcripts (JSON)
    - Normalized transcripts (JSON, if available)

    Only available when job curation_status is READY_TO_BE_NORMALIZED or NORMALIZED.
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

        # Check curation status
        allowed_statuses = {"READY_TO_BE_NORMALIZED", "NORMALIZED"}
        if job.curation_status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "BAD_REQUEST",
                        "message": (
                            f"Dataset download is only available when curation_status "
                            f"is one of: {allowed_statuses}. Current status: {job.curation_status}"
                        )
                    }
                }
            )

        # Get segments with transcripts and annotation edits
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select

        result = await db.execute(
            select(PipelineSegment)
            .where(PipelineSegment.job_id == job_uuid)
            .options(
                selectinload(PipelineSegment.transcripts),
                selectinload(PipelineSegment.annotation_edits)
            )
            .order_by(PipelineSegment.segment_index)
        )
        segments = result.scalars().all()

        minio_service = get_minio_service()

        # Prepare ZIP in memory
        zip_buffer = io.BytesIO()

        # Track transcript data for JSON files
        asr_transcripts = []
        annotated_transcripts = []
        normalized_transcripts = []

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Original video
            if job.video_path:
                try:
                    video_data = await minio_service.download_file(job.video_path)
                    original_name = job.original_filename or "original_video.mp4"
                    zf.writestr(f"original/{original_name}", video_data)
                except Exception as e:
                    logger.warning("Failed to add original video to ZIP: %s", e)

            for segment in segments:
                seg_idx = segment.segment_index

                # 2. Segment videos (stage 1)
                if segment.cropped_video_path:
                    try:
                        seg_data = await minio_service.download_file(segment.cropped_video_path)
                        zf.writestr(f"segments/segment_{seg_idx:04d}.mp4", seg_data)
                    except Exception as e:
                        logger.warning("Failed to add segment %s to ZIP: %s", seg_idx, e)

                # Get latest submitted annotation edit for this segment
                latest_edit = None
                for edit in segment.annotation_edits:
                    if edit.status == AnnotationEdit.STATUS_SUBMITTED:
                        latest_edit = edit
                        break

                for transcript in segment.transcripts:
                    utt_idx = transcript.utterance_index

                    # 3. Utterance videos (stage 3)
                    if transcript.video_path:
                        try:
                            utt_data = await minio_service.download_file(transcript.video_path)
                            zf.writestr(
                                f"utterances/{segment.id}_utt_{utt_idx}.mp4",
                                utt_data
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to add utterance video to ZIP: segment=%s utt=%s error=%s",
                                segment.id, utt_idx, e
                            )

                    # 4. Audio WAV files
                    if transcript.audio_path:
                        try:
                            audio_data = await minio_service.download_file(transcript.audio_path)
                            zf.writestr(
                                f"audio/{segment.id}.wav",
                                audio_data
                            )
                        except Exception as e:
                            logger.warning(
                                "Failed to add audio to ZIP: segment=%s error=%s",
                                segment.id, e
                            )

                    # Collect transcript data
                    asr_transcripts.append({
                        "segment_index": seg_idx,
                        "utterance_index": utt_idx,
                        "text": transcript.text,
                        "start": transcript.start,
                        "end": transcript.end,
                        "confidence": transcript.confidence,
                    })

                    if latest_edit:
                        annotated_transcripts.append({
                            "segment_index": seg_idx,
                            "utterance_index": utt_idx,
                            "text": latest_edit.new_text,
                            "start": latest_edit.new_start,
                            "end": latest_edit.new_end,
                        })

                        if latest_edit.normalized_text:
                            normalized_transcripts.append({
                                "segment_index": seg_idx,
                                "utterance_index": utt_idx,
                                "text": latest_edit.normalized_text,
                                "start": latest_edit.new_start,
                                "end": latest_edit.new_end,
                            })

            # 5. Transcript JSON files
            import json

            zf.writestr(
                "transcripts/asr.json",
                json.dumps(asr_transcripts, indent=2, ensure_ascii=False).encode("utf-8")
            )

            if annotated_transcripts:
                zf.writestr(
                    "transcripts/annotated.json",
                    json.dumps(annotated_transcripts, indent=2, ensure_ascii=False).encode("utf-8")
                )

            if normalized_transcripts:
                zf.writestr(
                    "transcripts/normalized.json",
                    json.dumps(normalized_transcripts, indent=2, ensure_ascii=False).encode("utf-8")
                )

        # Prepare response
        zip_buffer.seek(0)
        safe_name = (job.original_filename or "dataset").rsplit(".", 1)[0]
        zip_filename = f"{safe_name}_dataset.zip"

        return StreamingResponse(
            iter([zip_buffer.read()]),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{zip_filename}"'
            }
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
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to generate dataset ZIP for job %s", job_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": f"Failed to generate dataset ZIP: {str(e)}"
                }
            }
        )
