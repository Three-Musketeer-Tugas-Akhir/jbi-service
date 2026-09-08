"""Annotation API endpoints."""
import uuid as _uuid
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status, BackgroundTasks, HTTPException
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
    ReviewStatusListResponse,
    ReviewActionRequest,
)
from app.services.annotation_submission_service import AnnotationSubmissionService
from app.repositories.annotation_review_repository import AnnotationReviewRepository
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.db.models.annotation import AnnotationEdit
from app.repositories.job_repository import JobRepository
from app.services.notification_service import NotificationService
from app.core.exceptions import NotFoundError


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
    dataset_id: Optional[str] = Query(None, description="Filter by dataset ID"),
    job_id: Optional[str] = Query(
        None,
        description="Filter by pipeline job ID — returns only that job's segments"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=500, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Get the annotation queue for the current annotator.

    Returns segments assigned to the annotator with metadata
    and pre-signed URLs for video access.
    """
    dataset_uuid = None
    if dataset_id:
        try:
            dataset_uuid = _uuid.UUID(dataset_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid dataset_id: {dataset_id}")

    job_uuid = None
    if job_id:
        try:
            job_uuid = _uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid job_id: {job_id}")

    service = AnnotationQueueService(db)
    result = await service.get_annotator_queue(
        annotator_id=current_user.id,
        status=status,
        dataset_id=dataset_uuid,
        job_id=job_uuid,
        page=page,
        page_size=page_size,
        is_admin=current_user.has_role("admin")
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
    current_user: User = Depends(require_role("admin", "annotator", "curator"))
):
    """
    Get complete details for a segment to annotate.

    Includes:
    - Pre-signed video URL (1 hour expiry)
    - ASR transcript and timestamps
    - Edit history
    - Current values (ASR or latest approved edit)

    Curators reach this to view a submitted segment before approving/rejecting
    it -- they never have their own queue entry for it, so they're granted the
    same bypass as admin on the "must be the assigned annotator" check below.
    They get no additional write access from this: /draft, /crop and /revert
    all still require role annotator/admin.
    """
    service = AnnotationQueueService(db)
    result = await service.get_segment_for_annotation(
        segment_id=segment_id,
        annotator_id=current_user.id,
        is_admin=current_user.has_role("admin") or current_user.has_role("curator")
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
        utterances=edit_data.utterances,
        is_admin=current_user.has_role("admin")
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
        user_id=current_user.id,
        is_admin=current_user.has_role("admin")
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
        end_time=preview_data.end_time,
        is_admin=current_user.has_role("admin")
    )
    
    # Add transcript (always include, may be None)
    preview["transcript_text"] = preview_data.transcript_text
    
    return preview


@router.post("/{segment_id}/utterances/{utterance_index}/crop")
async def crop_utterance_physically(
    segment_id: UUID,
    utterance_index: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    Triggers physical FFmpeg cropping for a specific utterance that is marked as OK.
    """
    from sqlalchemy import select
    from sqlalchemy.orm.attributes import flag_modified
    from app.db.models.annotation import AnnotationEdit
    
    result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    edit = result.scalars().first()
    
    if not edit or not edit.utterance_corrections:
        raise HTTPException(status_code=404, detail="Sesi pengeditan aktif tidak ditemukan")
        
    utt_list = list(edit.utterance_corrections)
    utt_idx_in_array = None
    target_utt = None
    for i, utt in enumerate(utt_list):
        if utt.get("utterance_index") == utterance_index:
            utt_idx_in_array = i
            target_utt = utt
            break
            
    if target_utt is None:
        raise HTTPException(status_code=404, detail="Indeks ucapan (utterance) tidak ditemukan dalam sesi pengeditan aktif")
        
    # Mark as 'OK' synchronously so frontend can lock it instantly
    utt_list[utt_idx_in_array]["status"] = "OK"
    edit.utterance_corrections = utt_list
    flag_modified(edit, "utterance_corrections")
    await db.commit()
    
    # Spawn background task.
    # Pass the exact edit_id so the cropped_video_path is written back to THIS
    # edit row, preventing the result from being orphaned if a concurrent draft
    # save creates a newer edit before the crop finishes.
    from app.services.utterance_cropping_service import UtteranceCroppingService
    background_tasks.add_task(
        UtteranceCroppingService.crop_and_upload,
        segment_id=segment_id,
        utterance_index=utterance_index,
        start_time=target_utt["start"],
        end_time=target_utt["end"],
        edit_id=edit.id
    )
    
    return {"status": "processing", "message": "Physical cropping started in background"}


@router.post("/{segment_id}/utterances/{utterance_index}/revert")
async def revert_utterance_trim(
    segment_id: UUID,
    utterance_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator"))
):
    """
    IMPROVEMENT 1: Revert a previously-trimmed utterance to its pre-trim state.
    
    Reads the pre_trim_snapshot stored during the crop operation and restores:
    1. The current utterance's start/end/status back to DRAFT
    2. The next utterance's start (if it was shifted by cascade)
    3. Clears merged_video_path for both utterances
    """
    from app.services.utterance_cropping_service import UtteranceCroppingService
    
    result = await UtteranceCroppingService.revert_utterance(
        segment_id=segment_id,
        utterance_index=utterance_index
    )
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.get(
    "/segments/{segment_id}/utterances/{utterance_index}/merged-video",
    response_model=dict,
    summary="Get merged video for utterance",
    description="Returns a merged video (utterance N + N+1) for seamless annotation. Creates the merge if it doesn't exist."
)
async def get_merged_video_for_utterance(
    segment_id: UUID,
    utterance_index: int,
    include_prev: bool = False,
    lookahead: int = Query(1, ge=1, le=3, description="Clips after N to append to the tape"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator", "curator"))
):
    """
    Get merged video for an utterance (video-editor-sibi style).

    The merged video concatenates utterance N with utterance N+1 so the annotator
    can see the transition and decide where utterance N should end.

    If the merge already exists, returns the cached video.
    If not, creates the merge on-the-fly and caches it.

    With ``include_prev=true`` the tape is prefixed with what utterance N-1 holds
    behind it, so the start handle can be dragged backwards. That prefix has two
    parts, reported separately because they cost different things: the orphan
    (``prev_available``, released by N-1's own trim-in, free to take) and the
    borrowable stretch (``prev_borrowable``, still owned by N-1 — reaching into it
    shortens N-1 and forces it to be re-cropped).

    With ``lookahead`` > 1 the tape appends N+2 … N+k, for when the footage the
    annotator needs is not in the next clip but two or three rows further on.
    ``lookahead_available`` reports how many following clips actually exist.

    Both counts are returned on every call so the client can decide whether to
    offer either option at all, without a second round trip.
    """
    from app.services.annotation_queue_service import AnnotationQueueService
    from app.services.utterance_merge_service import UtteranceMergeService
    from app.db.models.pipeline import PipelineSegment
    from sqlalchemy import select
    
    # Verify assignment (admins and curators may view any segment -- curators
    # have no queue entry of their own for it, they're reviewing someone else's)
    queue_service = AnnotationQueueService(db)
    queue_entry = await queue_service.queue_repo.get_by_segment(segment_id)
    is_admin = current_user.has_role("admin") or current_user.has_role("curator")
    if not queue_entry or (not is_admin and queue_entry.annotator_id != current_user.id):
        raise HTTPException(status_code=403, detail="Segmen ini tidak ditugaskan kepada Anda")
    
    # Get job_id
    segment_result = await db.execute(
        select(PipelineSegment).where(PipelineSegment.id == segment_id)
    )
    segment = segment_result.scalar_one_or_none()
    if not segment:
        raise HTTPException(status_code=404, detail="Segmen tidak ditemukan")
    
    # Get or create merged video
    result = await UtteranceMergeService.get_or_create_merged_video(
        job_id=segment.job_id,
        segment_id=segment_id,
        utterance_index=utterance_index,
        include_prev=include_prev,
        lookahead=lookahead
    )
    
    if not result:
        raise HTTPException(status_code=404, detail="Tidak dapat membuat video hasil penggabungan")
    
    # Convert direct MinIO URL to proxy URL (browser can't access internal MinIO)
    from app.services.streaming_token_service import streaming_token_service
    from app.core.config import settings
    
    video_path = result.get("merged_video_path")
    if video_path:
        token = streaming_token_service.generate_token(str(current_user.id), video_path)
        result["merged_video_url"] = f"{settings.api_v1_prefix}/assets/{video_path}?token={token}"
    
    return result


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
    from sqlalchemy import select
    from app.db.models.annotation import AnnotationEdit
    
    result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    existing_edit = result.scalars().first()
    
    # NOTE: Lock removed — annotators can always revise (human error handling)
    # if existing_edit and existing_edit.utterance_corrections:
    #     existing_map = {u.get("utterance_index"): u for u in existing_edit.utterance_corrections}
    #     for incoming_utt in draft_data.utterances:
    #         ext_utt = existing_map.get(incoming_utt.utterance_index)
    #         if ext_utt and ext_utt.get("status") == "OK":
    #             if ext_utt.get("start") != incoming_utt.start or ext_utt.get("end") != incoming_utt.end:
    #                 raise HTTPException(
    #                     status_code=400,
    #                     detail=f"Cannot modify utterance {incoming_utt.utterance_index} because it is already locked (OK)."
    #                 )
    
    service = AnnotationEditService(db)
    draft = await service.create_draft(
        segment_id=segment_id,
        editor_id=current_user.id,
        utterances=draft_data.utterances,
        is_admin=current_user.has_role("admin")
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
        editor_id=current_user.id,
        is_admin=current_user.has_role("admin")
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
        user_id=current_user.id,
        is_admin=current_user.has_role("admin")
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
        user_id=current_user.id,
        is_admin=current_user.has_role("admin")
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
        confirm_no_changes=submit_data.confirm_no_changes,
        is_admin=current_user.has_role("admin")
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
        user_id=current_user.id,
        is_admin=current_user.has_role("admin")
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
    current_user: User = Depends(require_role("admin", "annotator", "curator"))
):
    """
    List all annotations submitted by the current user.

    Returns paginated list with review status for each submission.

    Curators use this as their review queue -- they have no queue entries of
    their own (they never do JBI annotation work), so is_admin's existing
    "ignore the annotator_id filter, return everyone's" behavior is reused
    for them here rather than adding a second parallel code path.
    """
    service = AnnotationSubmissionService(db)
    result = await service.list_my_submissions(
        user_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size,
        is_admin=current_user.has_role("admin") or current_user.has_role("curator")
    )
    return result


@router.post(
    "/reviews/{review_id}/approve",
    response_model=dict,
    summary="Approve annotation review",
    description="Curator approves an annotation review. If all reviews for the job are approved, the job becomes ready for curation."
)
async def approve_annotation_review(
    review_id: UUID,
    action_data: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator"))
):
    """
    Approve an annotation review.
    
    After approval, the system checks whether all annotation reviews for the
    associated pipeline job are approved. If so, the job's curation_status
    is automatically updated to ANNOTATED.
    """
    review_repo = AnnotationReviewRepository(db)
    job_repo = JobRepository(db)
    
    review = await review_repo.get_by_id(review_id)
    if not review:
        raise NotFoundError(f"Review '{review_id}' not found")
    
    await review_repo.update_status(
        review_id=review_id,
        status="APPROVED",
        curator_id=current_user.id,
        feedback=action_data.feedback
    )
    
    # Trigger curation readiness check
    job_id = await review_repo.get_job_id_by_review_id(review_id)
    if job_id:
        has_pending = await review_repo.has_pending_reviews_for_job(job_id)
        if not has_pending:
            await job_repo.update_curation_status(job_id, "READY_TO_BE_NORMALIZED")
            # Notify job creator that annotations are ready
            job = await job_repo.get_by_id(job_id)
            if job and job.created_by:
                notif_service = NotificationService(db)
                await notif_service.notify_annotation_ready(
                    user_id=job.created_by,
                    job_id=job_id,
                    job_name=job.original_filename
                )
    
    await db.commit()
    
    return {
        "review_id": review_id,
        "status": "APPROVED",
        "curator_id": current_user.id,
        "message": "Review approved successfully"
    }


@router.post(
    "/reviews/{review_id}/reject",
    response_model=dict,
    summary="Reject annotation review",
    description="Curator rejects an annotation review with optional feedback."
)
async def reject_annotation_review(
    review_id: UUID,
    action_data: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "curator"))
):
    """
    Reject an annotation review.
    
    The annotator can revise and resubmit after receiving feedback.
    """
    review_repo = AnnotationReviewRepository(db)
    
    review = await review_repo.get_by_id(review_id)
    if not review:
        raise NotFoundError(f"Review '{review_id}' not found")

    await review_repo.update_status(
        review_id=review_id,
        status="REJECTED",
        curator_id=current_user.id,
        feedback=action_data.feedback
    )

    # Unstick the underlying edit. submit_for_review() blocks on ANY edit row
    # for the segment still marked SUBMITTED (AnnotationEditRepository.
    # has_submitted_edit), and this reject only touched the review row —
    # the edit itself was left at SUBMITTED from the original submission.
    # Left alone, the annotator's next submit attempt 409s forever, even
    # after saving a fresh draft with the requested fix. Flip it to the
    # edit's own REJECTED status so has_submitted_edit() stops matching it.
    edit_repo = AnnotationEditRepository(db)
    await edit_repo.update_status(review.edit_id, AnnotationEdit.STATUS_REJECTED)

    await db.commit()

    return {
        "review_id": review_id,
        "status": "REJECTED",
        "curator_id": current_user.id,
        "message": "Review rejected successfully"
    }
