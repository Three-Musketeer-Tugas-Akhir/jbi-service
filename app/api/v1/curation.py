"""Curation API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_annotator_or_curator, require_curator
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.repositories.job_repository import JobRepository
from app.schemas.curation import (
    CurationApproveRequest,
    CurationNormalizeRequest,
    CurationNormalizeResponse,
    CurationNormalizedItem,
)
from app.services.curation.normalizer import TextNormalizer

router = APIRouter()


@router.post("/curation/normalize", response_model=CurationNormalizeResponse)
async def normalize_segments(
    request: CurationNormalizeRequest,
    category: Optional[str] = None,
    current_user=Depends(require_annotator_or_curator),
) -> CurationNormalizeResponse:
    """Normalize a list of text segments.

    Runs the universal normalization pipeline on each segment.
    If `category=SIBI`, additional SIBI-specific rules are applied.
    """
    normalizer = TextNormalizer()
    items: list[CurationNormalizedItem] = []

    for seg in request.items:
        normalized = normalizer.normalize(seg.original_text, category=category)
        items.append(
            CurationNormalizedItem(
                id=seg.id,
                original_text=seg.original_text,
                normalized_text=normalized,
            )
        )

    return CurationNormalizeResponse(items=items)


@router.post("/curation/approve")
async def approve_video(
    request: CurationApproveRequest,
    session: AsyncSession = Depends(get_db),
    current_user=Depends(require_curator),
):
    """Approve a video's curated data for export.

    Updates the job's curation_status to READY_TO_EXPORT.
    Only available when the job is currently in NORMALIZED state.
    """
    job_repo = JobRepository(session)
    job = await job_repo.get_by_id(str(request.video_id))

    if job is None:
        raise NotFoundError(f"Job '{request.video_id}' not found")

    allowed_states = {"NORMALIZED", "ANNOTATED"}
    if job.curation_status not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Job '{request.video_id}' has curation_status '{job.curation_status}'. "
                f"Approval is only allowed when status is one of: {allowed_states}."
            ),
        )

    await job_repo.update_curation_status(str(request.video_id), "READY_TO_EXPORT")
    await session.commit()

    return {"success": True, "video_id": str(request.video_id), "curation_status": "READY_TO_EXPORT"}
