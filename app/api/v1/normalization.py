"""Auto-normalization API endpoints.

Provides preview and apply endpoints for normalizing ground truth transcripts
and glosa annotations for OK-status utterances within a pipeline job.
"""
import copy
import uuid
from typing import Dict, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import require_curator
from app.db.models.annotation import AnnotationEdit
from app.db.models.pipeline import PipelineJob, PipelineSegment, PipelineTranscript
from app.db.models.voice_annotation import VoiceAnnotation
from app.db.models.audit import AuditAction
from app.db.session import get_db
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.job_repository import JobRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.schemas.normalization import (
    ApplyNormalizationRequest,
    ApplyNormalizationResponse,
    AutoNormalizeResponse,
    NormalizedUtterance,
)
from app.services.curation.normalizer import TextNormalizer

router = APIRouter()

# Singleton normalizer — loaded once, reused across requests
_normalizer = TextNormalizer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _collect_ok_utterances(
    db: AsyncSession,
    job_id: str,
) -> List[Dict]:
    """Collect all OK-status utterances for a job.

    Returns a flat list of dicts:
        {segment_id, utterance_index, ground_truth_text, glosa_text, start, end}
    """
    job_uuid = uuid.UUID(job_id)

    # 1. Get all segments with transcripts
    seg_result = await db.execute(
        select(PipelineSegment)
        .where(PipelineSegment.job_id == job_uuid)
        .options(selectinload(PipelineSegment.transcripts))
    )
    segments = seg_result.scalars().all()

    if not segments:
        return []

    # 2. Collect transcript IDs for voice annotation lookup
    all_transcript_ids = []
    for seg in segments:
        for t in (seg.transcripts or []):
            all_transcript_ids.append(t.id)

    # 3. Fetch ground truth from VoiceAnnotation
    gt_map: Dict[uuid.UUID, str] = {}
    if all_transcript_ids:
        va_result = await db.execute(
            select(VoiceAnnotation)
            .where(VoiceAnnotation.transcript_id.in_(all_transcript_ids))
        )
        for va in va_result.scalars().all():
            gt_map[va.transcript_id] = va.ground_truth_text

    # 4. Fetch latest annotation edits per segment (for glosa + OK status)
    edit_repo = AnnotationEditRepository(db)
    items = []

    for seg in segments:
        latest_edit = await edit_repo.get_latest_by_segment(seg.id)
        if not latest_edit or not latest_edit.utterance_corrections:
            continue

        # Build a lookup from utterance_index → transcript
        transcript_map = {}
        for t in (seg.transcripts or []):
            transcript_map[t.utterance_index] = t

        for u_corr in latest_edit.utterance_corrections:
            # Only process OK utterances
            if u_corr.get("status") != "OK":
                continue

            utt_idx = u_corr["utterance_index"]
            transcript = transcript_map.get(utt_idx)

            # Ground truth: prefer VoiceAnnotation, fallback to transcript text
            gt_text = ""
            if transcript and transcript.id in gt_map:
                gt_text = gt_map[transcript.id]
            elif transcript:
                gt_text = transcript.text

            glosa_text = u_corr.get("text", "")

            items.append({
                "segment_id": str(seg.id),
                "utterance_index": utt_idx,
                "ground_truth_text": gt_text,
                "glosa_text": glosa_text,
                "normalized_transcript": u_corr.get("normalized_transcript", ""),
                "normalized_glosa": u_corr.get("normalized_glosa", ""),
                "start": u_corr.get("start", transcript.start if transcript else 0.0),
                "end": u_corr.get("end", transcript.end if transcript else 0.0),
            })

    # Sort by start time for consistent ordering
    items.sort(key=lambda x: x["start"])
    return items


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/normalization/slang-dictionary",
    summary="The slang → baku dictionary the normalizer actually applies",
    tags=["Normalization"],
)
async def get_slang_dictionary(
    current_user=Depends(require_curator),
):
    """Expose the real slang dictionary used by the normalizer.

    The curation UI shows a "Kamus Slang → Baku" panel so a curator can see why
    a word was rewritten. That panel used to be a hardcoded list of 14 pairs in
    the frontend, which silently disagreed with the ~1.3k entries the backend
    actually applies. Serving it from the same file the normalizer loads keeps
    the two from drifting apart again.
    """
    normalizer = TextNormalizer()
    entries = [
        {"slang": slang, "standard": standard}
        for slang, standard in sorted(normalizer.slang_dict.items())
    ]
    return {"total": len(entries), "entries": entries}


@router.get(
    "/normalization/segments/{job_id}",
    response_model=AutoNormalizeResponse,
    summary="Get current normalization state for a job's OK utterances",
    tags=["Normalization"],
)
async def get_normalization_segments(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_curator),
):
    """Fetch the current normalization state.

    This returns the saved normalized_transcript and normalized_glosa
    from the database without re-running the normalizer.
    """
    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    ok_utterances = await _collect_ok_utterances(db, job_id)

    results: List[NormalizedUtterance] = []
    for u in ok_utterances:
        results.append(NormalizedUtterance(
            utterance_index=u["utterance_index"],
            segment_id=u["segment_id"],
            original_transcript=u["ground_truth_text"],
            normalized_transcript=u.get("normalized_transcript", ""),
            original_glosa=u["glosa_text"],
            normalized_glosa=u.get("normalized_glosa", ""),
            start=u["start"],
            end=u["end"],
        ))

    return AutoNormalizeResponse(
        job_id=job_id,
        total_ok_utterances=len(results),
        items=results,
    )


@router.post(
    "/normalization/auto-normalize/{job_id}",
    response_model=AutoNormalizeResponse,
    summary="Preview auto-normalization for a job's OK utterances",
    tags=["Normalization"],
)
async def auto_normalize_preview(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_curator),
):
    """Run normalization on all OK-status utterances and return before/after preview.

    This is a **read-only** endpoint — nothing is persisted.
    The user can review the results before calling the apply endpoint.

    - **Ground truth transcript** → universal pipeline (lowercase, numbers, slang, filler, punctuation)
    - **Glosa** → universal + SIBI pipeline (entity mapping, RI standalone, finger spelling)
    """
    # Validate job exists
    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Collect OK utterances
    ok_utterances = await _collect_ok_utterances(db, job_id)

    # Normalize each utterance
    results: List[NormalizedUtterance] = []
    for u in ok_utterances:
        norm_transcript = _normalizer.normalize(u["ground_truth_text"])
        norm_glosa = _normalizer.normalize(u["glosa_text"], category="SIBI")

        results.append(NormalizedUtterance(
            utterance_index=u["utterance_index"],
            segment_id=u["segment_id"],
            original_transcript=u["ground_truth_text"],
            normalized_transcript=norm_transcript,
            original_glosa=u["glosa_text"],
            normalized_glosa=norm_glosa,
            start=u["start"],
            end=u["end"],
        ))

    return AutoNormalizeResponse(
        job_id=job_id,
        total_ok_utterances=len(results),
        items=results,
    )


@router.post(
    "/normalization/apply/{job_id}",
    response_model=ApplyNormalizationResponse,
    summary="Apply auto-normalization results to a job",
    tags=["Normalization"],
)
async def apply_normalization(
    job_id: str,
    request: ApplyNormalizationRequest,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_curator),
):
    """Persist the normalized text for all OK-status utterances.

    Optionally accepts manual overrides for specific utterances.
    After applying, the job's curation_status is updated to NORMALIZED.
    """
    # Validate job exists
    job_repo = JobRepository(db)
    job = await job_repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Re-run normalization to get canonical values
    ok_utterances = await _collect_ok_utterances(db, job_id)
    if not ok_utterances:
        raise HTTPException(
            status_code=400,
            detail="Tidak ditemukan ucapan (utterance) berstatus OK untuk pekerjaan ini",
        )

    # Build normalized map: (segment_id, utterance_index) → (norm_transcript, norm_glosa)
    norm_map: Dict[Tuple[str, int], Tuple[str, str]] = {}
    for u in ok_utterances:
        norm_transcript = _normalizer.normalize(u["ground_truth_text"])
        norm_glosa = _normalizer.normalize(u["glosa_text"], category="SIBI")
        norm_map[(u["segment_id"], u["utterance_index"])] = (norm_transcript, norm_glosa)

    # Apply manual overrides if provided
    if request.overrides:
        for ov in request.overrides:
            key = (ov.segment_id, ov.utterance_index)
            if key in norm_map:
                existing_t, existing_g = norm_map[key]
                norm_map[key] = (
                    ov.normalized_transcript if ov.normalized_transcript is not None else existing_t,
                    ov.normalized_glosa if ov.normalized_glosa is not None else existing_g,
                )

    # Group by segment_id for batch updates
    segment_updates: Dict[str, List[Dict]] = {}
    for (seg_id, utt_idx), (nt, ng) in norm_map.items():
        segment_updates.setdefault(seg_id, []).append({
            "utterance_index": utt_idx,
            "normalized_transcript": nt,
            "normalized_glosa": ng,
        })

    # Persist: update utterance_corrections in AnnotationEdit
    edit_repo = AnnotationEditRepository(db)
    updated_count = 0

    for seg_id, updates in segment_updates.items():
        seg_uuid = uuid.UUID(seg_id)
        latest_edit = await edit_repo.get_latest_by_segment(seg_uuid)
        if not latest_edit or not latest_edit.utterance_corrections:
            continue

        # Build lookup for quick access
        update_lookup = {u["utterance_index"]: u for u in updates}

        # Update each utterance correction — deep-copy to guarantee
        # SQLAlchemy detects the JSONB mutation
        new_corrections = []
        for u_corr in latest_edit.utterance_corrections:
            u_corr_copy = copy.deepcopy(u_corr)
            utt_idx = u_corr_copy["utterance_index"]
            if utt_idx in update_lookup:
                u_corr_copy["normalized_transcript"] = update_lookup[utt_idx]["normalized_transcript"]
                u_corr_copy["normalized_glosa"] = update_lookup[utt_idx]["normalized_glosa"]
                updated_count += 1
            new_corrections.append(u_corr_copy)

        # Write back the updated corrections
        latest_edit.utterance_corrections = new_corrections
        flag_modified(latest_edit, "utterance_corrections")
        # Also update the aggregated normalized_text field
        norm_texts = [
            update_lookup[uc["utterance_index"]]["normalized_glosa"]
            for uc in new_corrections
            if uc["utterance_index"] in update_lookup
        ]
        if norm_texts:
            latest_edit.normalized_text = " ".join(norm_texts)

        await db.flush()

    # Update job curation status
    await job_repo.update_curation_status(job_id, "NORMALIZED")
    
    # Log normalization applied
    audit_repo = AuditLogRepository(db)
    await audit_repo.create(
        action=AuditAction.NORMALIZATION_APPLIED,
        resource_type="normalization",
        actor_id=current_user.id,
        resource_id=uuid.UUID(job_id),
        details={
            "job_id": job_id,
            "utterances_updated": updated_count,
            "curation_status": "NORMALIZED",
        }
    )
    await db.commit()

    return ApplyNormalizationResponse(
        job_id=job_id,
        utterances_updated=updated_count,
        curation_status="NORMALIZED",
    )
