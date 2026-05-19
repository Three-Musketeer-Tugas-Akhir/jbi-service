"""ASR Review API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.db.models.auth import User
from app.services.asr_review_service import ASRReviewService
from app.schemas.asr_review import (
    ASRReviewQueueResponse,
    ASRReviewDetailResponse,
    ASRReviewFilterParams
)


router = APIRouter()


@router.get(
    "/queue",
    response_model=ASRReviewQueueResponse,
    summary="Get ASR Review queue",
    description="Returns pending ASR reviews with confidence scores and flags."
)
async def get_asr_review_queue(
    low_confidence_only: bool = Query(
        False,
        description="Show only low confidence segments (< 50%)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Get the ASR Review queue.
    
    Returns segments pending ASR validation with:
    - Video pre-signed URLs
    - ASR transcripts
    - Confidence scores
    - Low confidence flags (< 50%)
    
    Segments are ordered by confidence (lowest first) to prioritize
    those needing the most attention.
    """
    service = ASRReviewService(db)
    result = await service.get_review_queue(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        low_confidence_only=low_confidence_only
    )
    return result


@router.get(
    "/{review_id}",
    response_model=ASRReviewDetailResponse,
    summary="Get ASR review details",
    description="Returns complete details for an ASR review including video URL."
)
async def get_asr_review_detail(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Get complete details for an ASR review.
    
    Includes:
    - Pre-signed video URL (1 hour expiry)
    - ASR transcript
    - Confidence score
    - Attention warnings for low confidence
    """
    service = ASRReviewService(db)
    detail = await service.get_review_detail(
        review_id=review_id,
        user_id=current_user.id
    )
    return detail


@router.get(
    "/by-segment/{segment_id}",
    summary="Get ASR review by segment",
    description="Check if a segment has an ASR review and get its status."
)
async def get_asr_review_by_segment(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Get ASR review status for a specific segment.
    
    Returns review information or null if no ASR review exists
    (e.g., if ASR Review is disabled or segment skipped review).
    """
    service = ASRReviewService(db)
    review = await service.get_review_by_segment(segment_id)
    
    if not review:
        return {
            "segment_id": segment_id,
            "has_review": False,
            "message": "No ASR review for this segment"
        }
    
    return {
        "segment_id": segment_id,
        "has_review": True,
        "review": review
    }



from app.schemas.asr_review import (
    ASRReviewApproveRequest,
    ASRReviewCorrectRequest,
    ASRReviewFlagRequest,
    ASRReviewActionResponse,
    ASRReviewStatusCheck
)


@router.get(
    "/{review_id}/status",
    response_model=ASRReviewStatusCheck,
    summary="Check review status",
    description="Check if an ASR review can be performed."
)
async def check_asr_review_status(
    review_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Check the status of an ASR review.
    
    Returns whether the review is pending or already completed,
    and if the current user can perform the review.
    """
    service = ASRReviewService(db)
    status = await service.check_review_status(
        review_id=review_id,
        user_id=current_user.id
    )
    return status


@router.post(
    "/{review_id}/approve",
    response_model=ASRReviewActionResponse,
    summary="Approve ASR transcript",
    description="Approve ASR transcript as-is and move to annotation queue."
)
async def approve_asr_review(
    review_id: UUID,
    approve_data: ASRReviewApproveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Approve an ASR transcript.
    
    The ASR output is accepted as-is and the segment
    moves to the annotation queue for timestamp synchronization.
    """
    service = ASRReviewService(db)
    result = await service.approve_asr_review(
        review_id=review_id,
        reviewer_id=current_user.id,
        notes=approve_data.notes
    )
    return result


@router.post(
    "/{review_id}/correct",
    response_model=ASRReviewActionResponse,
    summary="Correct ASR transcript",
    description="Correct ASR transcript errors and move to annotation queue."
)
async def correct_asr_review(
    review_id: UUID,
    correct_data: ASRReviewCorrectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Correct an ASR transcript.
    
    Apply corrections to the ASR output and move the segment
    to the annotation queue with the corrected transcript.
    """
    service = ASRReviewService(db)
    result = await service.correct_asr_review(
        review_id=review_id,
        reviewer_id=current_user.id,
        corrected_text=correct_data.corrected_text,
        notes=correct_data.notes
    )
    return result


@router.post(
    "/{review_id}/flag",
    response_model=ASRReviewActionResponse,
    summary="Flag ASR segment",
    description="Flag segment for reprocessing due to quality issues."
)
async def flag_asr_review(
    review_id: UUID,
    flag_data: ASRReviewFlagRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin"))
):
    """
    Flag an ASR segment for reprocessing.
    
    Use when the audio quality is too poor for ASR or when
    there are issues like background noise or overlapping speech.
    The segment will NOT enter the annotation queue and will
    be routed for manual transcription or specialized handling.
    
    Flag reasons:
    - background_noise: Too much background noise
    - overlapping_speech: Multiple speakers talking over each other
    - unclear_audio: Audio is muffled or unclear
    - other: Other quality issues
    """
    service = ASRReviewService(db)
    result = await service.flag_asr_review(
        review_id=review_id,
        reviewer_id=current_user.id,
        flag_reason=flag_data.flag_reason,
        notes=flag_data.notes
    )
    return result
