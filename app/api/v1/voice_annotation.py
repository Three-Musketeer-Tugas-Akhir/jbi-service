"""Voice Annotation API endpoints.

Provides the quality gate UI with endpoints to list jobs needing
voice annotation, view utterance-level flag data, and update
ground-truth text with automatic re-validation.
"""
import uuid as _uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.db.models.auth import User
from app.services.voice_annotation_service import VoiceAnnotationService
from app.schemas.voice_annotation import (
    VoiceAnnotationJobListResponse,
    VoiceAnnotationJobSummary,
    VoiceAnnotationUtteranceListResponse,
    UpdateGroundTruthRequest,
    UpdateGroundTruthResponse,
)


router = APIRouter()


@router.get(
    "/jobs",
    response_model=VoiceAnnotationJobListResponse,
    summary="List jobs needing voice annotation",
    description="Returns jobs in NEEDS_VOICE_ANNOTATION, VOICE_ANNOTATION_IN_PROGRESS, or READY_FOR_ANNOTATION status.",
)
async def list_voice_annotation_jobs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    dataset_id: Optional[str] = Query(None, description="Filter by dataset ID"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator")),
):
    """Get paginated list of jobs available for voice annotation."""
    dataset_uuid = None
    if dataset_id:
        try:
            dataset_uuid = _uuid.UUID(dataset_id)
        except ValueError:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=f"Invalid dataset_id: {dataset_id}")

    service = VoiceAnnotationService(db)
    return await service.get_jobs_needing_annotation(page=page, page_size=page_size, dataset_id=dataset_uuid)


@router.get(
    "/jobs/{job_id}",
    response_model=VoiceAnnotationJobSummary,
    summary="Get job voice annotation summary",
    description="Returns clean/flagged counts and gate status for a specific job.",
)
async def get_job_summary(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator")),
):
    """Get voice annotation summary for a specific job."""
    service = VoiceAnnotationService(db)
    return await service.get_job_summary(job_id)


@router.get(
    "/jobs/{job_id}/utterances",
    response_model=VoiceAnnotationUtteranceListResponse,
    summary="List utterances for voice annotation",
    description="Returns all utterances with ASR text, ground truth, flagged words, and status.",
)
async def list_utterances(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator")),
):
    """Get all utterances for a job with voice annotation data."""
    service = VoiceAnnotationService(db)
    utterances = await service.get_utterances(job_id)
    return {
        "utterances": utterances,
        "total": len(utterances),
    }


@router.patch(
    "/utterances/{voice_annotation_id}",
    response_model=UpdateGroundTruthResponse,
    summary="Update ground truth text",
    description="Save corrected ground truth, re-run KBBI exact-match validation, recalculate job status.",
)
async def update_ground_truth(
    voice_annotation_id: UUID,
    body: UpdateGroundTruthRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin", "annotator")),
):
    """Update ground truth text for a single utterance.

    This triggers:
    1. Save new ground_truth_text
    2. Re-run KBBI exact-match OOV validation
    3. Recalculate job clean/flagged counters
    4. Update job status (NEEDS_VOICE_ANNOTATION or READY_FOR_ANNOTATION)
    """
    service = VoiceAnnotationService(db)
    result = await service.update_ground_truth(
        voice_annotation_id=voice_annotation_id,
        new_text=body.ground_truth_text,
        user_id=current_user.id,
        is_unflagged=body.is_unflagged,
    )
    await db.commit()
    return result


@router.post(
    "/jobs/{job_id}/initialize",
    summary="Initialize voice annotations for a job",
    description="Manually trigger voice annotation initialization for a job that has completed cropping.",
)
async def initialize_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Admin-only: manually initialize voice annotations for a job.

    Useful for backfilling existing READY_FOR_ANNOTATION jobs.
    """
    service = VoiceAnnotationService(db)
    result = await service.initialize_for_job(job_id)
    await db.commit()
    return result
