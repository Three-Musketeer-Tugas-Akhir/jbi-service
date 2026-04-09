"""
Annotation Synchronization API.

Endpoints for video-audio temporal alignment and sync workbench.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.db.models.auth import User
from app.services.annotation_sync_service import AnnotationSyncService
from app.schemas.annotation_sync import (
    AnnotationSyncUpdateRequest,
    AnnotationSyncFineTuneRequest,
    AnnotationSyncValidateRequest,
    StitchPreviewRequest,
    MergeSegmentRequest,
    AnnotationSyncResponse,
    AnnotationSyncContextResponse,
    StitchPreviewResponse,
    AnnotationSyncValidateResponse,
    FineTuneResponse,
    MergeSegmentResponse,
    TimelineRangeResponse
)

router = APIRouter(prefix="/sync", tags=["annotation-sync"])


@router.get(
    "/{edit_id}",
    response_model=AnnotationSyncResponse,
    summary="Get sync data",
    description="Get synchronization data for an annotation edit."
)
async def get_sync_data(
    edit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get synchronization data for an annotation edit.
    
    Returns:
    - Original ASR timestamps (audio_start, audio_end)
    - Adjusted video boundaries (video_start_offset, video_end_offset)
    - Sync status and quality indicators
    - Glosa (sign language gloss)
    """
    service = AnnotationSyncService(db)
    result = await service.get_sync_data(
        edit_id=edit_id,
        user_id=current_user.id
    )
    return result


@router.put(
    "/{edit_id}",
    response_model=AnnotationSyncResponse,
    summary="Update sync boundaries",
    description="Update video boundaries for temporal alignment."
)
async def update_sync_boundaries(
    edit_id: UUID,
    update_data: AnnotationSyncUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Update video boundaries for synchronization.
    
    Allows adjusting video start/end times to capture complete JBI movement
    that may extend beyond original ASR timestamps.
    
    Example:
    - ASR audio: 5.0s - 10.0s
    - Video with lag: 4.8s - 12.5s (JBI takes longer to complete)
    """
    service = AnnotationSyncService(db)
    result = await service.update_sync_boundaries(
        edit_id=edit_id,
        user_id=current_user.id,
        video_start_offset=update_data.video_start_offset,
        video_end_offset=update_data.video_end_offset,
        glosa=update_data.glosa,
        precision_ms=update_data.precision_ms
    )
    return result


@router.post(
    "/{edit_id}/fine-tune",
    response_model=FineTuneResponse,
    summary="Fine-tune sync",
    description="Fine-tune synchronization with millisecond precision."
)
async def fine_tune_sync(
    edit_id: UUID,
    tune_data: AnnotationSyncFineTuneRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Fine-tune sync boundaries with millisecond precision.
    
    Adjust video boundaries by small increments (e.g., ±100ms) to achieve
    perfect synchronization between audio and sign language video.
    
    Adjustment range: ±5000ms (±5 seconds)
    """
    service = AnnotationSyncService(db)
    result = await service.fine_tune_sync(
        edit_id=edit_id,
        user_id=current_user.id,
        adjustment_ms=tune_data.adjustment_ms,
        target=tune_data.target
    )
    return result


@router.post(
    "/{edit_id}/validate",
    response_model=AnnotationSyncValidateResponse,
    summary="Validate sync",
    description="Validate sync status and update quality indicators."
)
async def validate_sync(
    edit_id: UUID,
    validate_data: AnnotationSyncValidateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Validate synchronization and update status indicators.
    
    Sets quality indicators:
    - TEXT_MATCH: Text aligns with audio
    - VIDEO_COMPLETE: JBI movement fully captured
    - SYNC_LOCKED: Alignment is finalized
    
    Returns validation warnings and suggestions.
    """
    service = AnnotationSyncService(db)
    result = await service.validate_sync(
        edit_id=edit_id,
        user_id=current_user.id,
        text_match=validate_data.text_match,
        video_complete=validate_data.video_complete,
        sync_locked=validate_data.sync_locked
    )
    return result


@router.get(
    "/{edit_id}/preview",
    response_model=StitchPreviewResponse,
    summary="Get stitched preview",
    description="Get preview URL for stitched video with sync adjustments."
)
async def get_stitched_preview(
    edit_id: UUID,
    buffer_seconds: float = Query(2.0, description="Buffer time for stitching"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get preview for stitched video.
    
    Returns a pre-signed video URL that includes any sync adjustments
    (extended boundaries beyond original ASR timestamps).
    
    If video boundaries extend into adjacent segments, the system
    will stitch multiple video chunks together for seamless playback.
    """
    service = AnnotationSyncService(db)
    result = await service.get_stitched_preview(
        edit_id=edit_id,
        user_id=current_user.id,
        buffer_seconds=buffer_seconds
    )
    return result


@router.get(
    "/segments/{segment_id}/context",
    response_model=dict,  # AnnotationSyncContextResponse
    summary="Get sync context",
    description="Get synchronization data with surrounding segment context."
)
async def get_sync_context(
    segment_id: UUID,
    context_range: int = Query(2, ge=0, le=5, description="Number of neighboring segments"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get sync context with neighboring segments.
    
    Returns:
    - Current segment sync data
    - Previous segments (for context)
    - Next segments (for look-ahead stitching)
    - Waveform data for visualization
    """
    service = AnnotationSyncService(db)
    result = await service.get_sync_context(
        segment_id=segment_id,
        user_id=current_user.id,
        context_range=context_range
    )
    return result


@router.get(
    "/{edit_id}/timeline",
    response_model=TimelineRangeResponse,
    summary="Get timeline range",
    description="Get timeline data with range slider configuration."
)
async def get_timeline_range(
    edit_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get timeline configuration for the sync editor.
    
    Returns:
    - Audio range (original ASR timestamps)
    - Video range (adjusted boundaries)
    - Min/max bounds for range slider
    - Step size for precise adjustments
    """
    service = AnnotationSyncService(db)
    
    # Get sync data
    sync_data = await service.get_sync_data(
        edit_id=edit_id,
        user_id=current_user.id
    )
    
    # Calculate bounds (allow up to 5 seconds beyond original)
    min_bound = sync_data["audio_start"] - 5.0
    max_bound = sync_data["audio_end"] + 5.0
    
    return {
        "edit_id": edit_id,
        "audio_start": sync_data["audio_start"],
        "audio_end": sync_data["audio_end"],
        "video_start": sync_data.get("video_start_offset") or sync_data["audio_start"],
        "video_end": sync_data.get("video_end_offset") or sync_data["audio_end"],
        "playhead_position": sync_data["audio_start"],
        "text_overlay": "",
        "min_bound": max(0, min_bound),
        "max_bound": max_bound,
        "step": sync_data["precision_ms"] / 1000.0
    }


@router.post(
    "/{edit_id}/merge",
    response_model=dict,  # MergeSegmentResponse
    summary="Merge with adjacent segment",
    description="Merge video boundaries with adjacent segment for stitching."
)
async def merge_with_segment(
    edit_id: UUID,
    merge_data: MergeSegmentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Merge video with adjacent segment.
    
    For cases where JBI movement extends significantly into the next
    or previous segment, this allows explicitly merging boundaries.
    
    Direction:
    - 'next': Merge with following segment
    - 'prev': Merge with previous segment
    """
    # TODO: Implement merge logic
    return {
        "edit_id": edit_id,
        "merged": False,
        "message": "Merge feature not yet implemented"
    }
