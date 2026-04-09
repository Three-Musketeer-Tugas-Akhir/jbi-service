"""Annotation API endpoints."""
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.db.models.auth import User
from app.services.annotation_queue_service import AnnotationQueueService
from app.services.annotation_edit_service import AnnotationEditService
from app.schemas.annotation import (
    QueueListResponse, 
    SegmentDetailResponse, 
    QueueFilterParams,
    AnnotationEditCreate,
    AnnotationEditResponse,
    AnnotationEditListResponse,
    AnnotationPreviewRequest,
    AnnotationPreviewResponse,
    SaveDraftRequest,
    SaveDraftResponse,
    ResetResponse,
    SubmitForReviewRequest,
    SubmitForReviewResponse,
    SubmissionStatusResponse,
    ReviewStatusResponse,
    ReviewStatusListResponse
)
from app.services.annotation_submission_service import AnnotationSubmissionService


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
    current_user: User = Depends(require_role("admin", "annotator"))
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
    current_user: User = Depends(require_role("admin", "annotator"))
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


@router.post(
    "/{segment_id}/edits",
    response_model=AnnotationEditResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation edit",
    description="Create a new edit for a segment with transcript and timestamp corrections."
)
async def create_annotation_edit(
    segment_id: UUID,
    edit_data: AnnotationEditCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Create a new annotation edit for a segment.
    
    The edit records:
    - Old values (from ASR or previous edit)
    - New values (annotator corrections)
    - Editor and timestamp
    
    Validation:
    - Start must be < end
    - Both must be within video bounds
    """
    service = AnnotationEditService(db)
    edit = await service.create_edit(
        segment_id=segment_id,
        editor_id=current_user.id,
        new_text=edit_data.new_text,
        new_start=edit_data.new_start,
        new_end=edit_data.new_end
    )
    return edit


@router.get(
    "/{segment_id}/edits",
    response_model=AnnotationEditListResponse,
    summary="Get edit history",
    description="Get the edit history for a segment."
)
async def get_annotation_edits(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get the edit history for a segment.
    
    Returns all edits ordered by most recent first.
    Only accessible to the assigned annotator.
    """
    service = AnnotationEditService(db)
    edits = await service.get_edit_history(
        segment_id=segment_id,
        user_id=current_user.id
    )
    
    return {
        "segment_id": segment_id,
        "edits": edits,
        "total": len(edits)
    }


@router.post(
    "/{segment_id}/preview",
    response_model=AnnotationPreviewResponse,
    summary="Preview annotation",
    description="Get video preview with specified timestamps for verification."
)
async def preview_annotation(
    segment_id: UUID,
    preview_data: AnnotationPreviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get a preview of the annotation with specified timestamps.
    
    Returns a pre-signed video URL that can be used to verify
    synchronization before saving or submitting.
    """
    service = AnnotationEditService(db)
    preview = await service.get_preview(
        segment_id=segment_id,
        user_id=current_user.id,
        start_time=preview_data.start_time,
        end_time=preview_data.end_time
    )
    
    # Add transcript (always include, may be None)
    preview["transcript_text"] = preview_data.transcript_text
    
    return preview


@router.post(
    "/{segment_id}/draft",
    response_model=SaveDraftResponse,
    summary="Save annotation draft",
    description="Save annotation edits as draft without submitting for review."
)
async def save_annotation_draft(
    segment_id: UUID,
    draft_data: SaveDraftRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Save annotation edits as a draft.
    
    Draft edits:
    - Are not visible to curators
    - Can be overwritten by subsequent drafts
    - Allow saving work-in-progress
    """
    service = AnnotationEditService(db)
    draft = await service.create_draft(
        segment_id=segment_id,
        editor_id=current_user.id,
        new_text=draft_data.new_text,
        new_start=draft_data.new_start,
        new_end=draft_data.new_end
    )
    
    return {
        "edit_id": draft.id,
        "segment_id": segment_id,
        "status": draft.status,
        "saved_at": draft.edited_at,
        "message": "Draft saved successfully"
    }


@router.post(
    "/{segment_id}/reset",
    response_model=ResetResponse,
    summary="Reset to original",
    description="Reset all edits and revert to ASR-original values."
)
async def reset_annotation(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Reset all edits for a segment back to ASR-original state.
    
    This operation:
    - Soft-deletes all your edits for this segment
    - Creates a reset record for audit trail
    - Reverts values to the original ASR output
    """
    service = AnnotationEditService(db)
    result = await service.reset_to_original(
        segment_id=segment_id,
        editor_id=current_user.id
    )
    return result


@router.get(
    "/{segment_id}/current",
    response_model=dict,
    summary="Get current values",
    description="Get current annotation values including any draft edits."
)
async def get_current_annotation_values(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get the current annotation values for a segment.
    
    Returns the most recent values from either:
    - Latest edit (draft, pending, or submitted)
    - ASR original (if no edits)
    """
    service = AnnotationEditService(db)
    values = await service.get_current_values_with_draft(
        segment_id=segment_id,
        user_id=current_user.id
    )
    return values



@router.get(
    "/{segment_id}/submission-status",
    response_model=SubmissionStatusResponse,
    summary="Check submission status",
    description="Check if a segment can be submitted and get any warnings."
)
async def check_submission_status(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Check the submission status for a segment.
    
    Returns:
    - Whether edits exist
    - Edit count
    - Any warnings (e.g., no changes made)
    - Whether submission is allowed
    """
    service = AnnotationSubmissionService(db)
    status_info = await service.check_submission_status(
        segment_id=segment_id,
        user_id=current_user.id
    )
    return status_info


@router.post(
    "/{segment_id}/submit",
    response_model=SubmitForReviewResponse,
    summary="Submit for review",
    description="Submit annotation for curator review."
)
async def submit_for_review(
    segment_id: UUID,
    submit_data: SubmitForReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Submit an annotation for curator review.
    
    This transitions the annotation from "in progress" to "pending review".
    The segment will be added to the curator's review queue.
    
    If no edits were made, set confirm_no_changes=true to submit ASR-original.
    """
    service = AnnotationSubmissionService(db)
    result = await service.submit_for_review(
        segment_id=segment_id,
        user_id=current_user.id,
        confirm_no_changes=submit_data.confirm_no_changes
    )
    return result


@router.get(
    "/{segment_id}/review-status",
    response_model=ReviewStatusResponse,
    summary="Get review status",
    description="Get the review status for a submitted annotation."
)
async def get_review_status(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get the review status for a submitted annotation.
    
    Status values:
    - NOT_SUBMITTED: Not yet submitted
    - SUBMITTED: Awaiting curator review
    - PENDING: In curator queue
    - APPROVED: Accepted by curator
    - REJECTED: Rejected with feedback
    """
    service = AnnotationSubmissionService(db)
    status_info = await service.get_submission_status(
        segment_id=segment_id,
        user_id=current_user.id
    )
    return status_info


@router.get(
    "/my-submissions",
    response_model=ReviewStatusListResponse,
    summary="List my submissions",
    description="List all annotations submitted by the current user with their review status."
)
async def list_my_submissions(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    List all annotations submitted by the current user.
    
    Returns paginated list with review status for each submission.
    """
    service = AnnotationSubmissionService(db)
    result = await service.list_my_submissions(
        user_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size
    )
    return result
