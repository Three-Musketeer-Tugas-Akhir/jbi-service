"""Annotation API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.db.models.auth import User
from app.services.annotation_queue_service import AnnotationQueueService
from app.schemas.annotation import QueueListResponse, SegmentDetailResponse, QueueFilterParams


router = APIRouter()


@router.get(
    "/queue",
    response_model=QueueListResponse,
    summary="Get annotator's queue",
    description="Returns a paginated list of segments assigned to the current annotator."
)
async def get_annotation_queue(
    status: Optional[str] = Query(
        None,
        description="Filter by status: ASSIGNED, IN_PROGRESS, COMPLETED"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get the annotation queue for the current annotator.
    
    Returns segments assigned to the annotator with metadata
    and pre-signed URLs for video access.
    """
    service = AnnotationQueueService(db)
    result = await service.get_annotator_queue(
        annotator_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size
    )
    return result


@router.get(
    "/segments/{segment_id}",
    response_model=SegmentDetailResponse,
    summary="Get segment for annotation",
    description="Returns complete segment details including video URL and transcript."
)
async def get_segment_for_annotation(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get complete details for a segment to annotate.
    
    Includes:
    - Pre-signed video URL (1 hour expiry)
    - ASR transcript and timestamps
    - Edit history
    - Current values (ASR or latest approved edit)
    """
    service = AnnotationQueueService(db)
    result = await service.get_segment_for_annotation(
        segment_id=segment_id,
        annotator_id=current_user.id
    )
    return result
