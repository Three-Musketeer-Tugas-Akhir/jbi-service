"""Voice Annotation Service — business logic for the transcript quality gate.

Manages the lifecycle of voice annotations: initialisation from ASR output,
ground-truth editing, re-validation, and job-status aggregation.
"""
import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.pipeline import PipelineJob, PipelineTranscript, PipelineSegment, JobStatus
from app.db.models.voice_annotation import VoiceAnnotation
from app.services.voice_annotation_validator import validate_text
from app.core.config import settings

logger = logging.getLogger(__name__)


class VoiceAnnotationService:
    """Core service for the Voice Annotation quality gate."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Initialisation (called by cropping worker) ──────────────────

    async def initialize_for_job(self, job_id: UUID) -> dict:
        """Create VoiceAnnotation rows for every utterance in the job.

        For each PipelineTranscript belonging to this job:
        1. Copy asr_text → ground_truth_text
        2. Run KBBI exact-match validation
        3. Set per-utterance status (FLAGGED / CLEAN)
        4. Aggregate job-level counters and set job status.

        Returns summary dict.
        """
        # Fetch all segments → transcripts for job
        segments = (
            await self.db.execute(
                select(PipelineSegment)
                .where(PipelineSegment.job_id == job_id)
                .options(selectinload(PipelineSegment.transcripts))
            )
        ).scalars().all()

        all_transcripts: list[PipelineTranscript] = []
        for seg in segments:
            all_transcripts.extend(seg.transcripts)

        if not all_transcripts:
            logger.warning("No transcripts found for job %s — skipping voice annotation init", job_id)
            return {"job_id": str(job_id), "total": 0, "clean": 0, "flagged": 0}

        clean_count = 0
        flagged_count = 0

        for transcript in all_transcripts:
            # Check if voice annotation already exists
            existing = (
                await self.db.execute(
                    select(VoiceAnnotation).where(
                        VoiceAnnotation.transcript_id == transcript.id
                    )
                )
            ).scalar_one_or_none()
            if existing:
                continue

            asr_text = transcript.text or ""
            flagged_words = await validate_text(asr_text)
            has_flag = len(flagged_words) > 0

            status = VoiceAnnotation.STATUS_FLAGGED if has_flag else VoiceAnnotation.STATUS_CLEAN

            va = VoiceAnnotation(
                transcript_id=transcript.id,
                job_id=job_id,
                asr_text=asr_text,
                ground_truth_text=asr_text,  # initial copy
                flagged_words=flagged_words,
                has_flag=has_flag,
                voice_annotation_status=status,
            )
            self.db.add(va)

            if has_flag:
                flagged_count += 1
            else:
                clean_count += 1

        # Update job counters only (status is managed by CV2 / update_ground_truth)
        await self.db.execute(
            update(PipelineJob)
            .where(PipelineJob.id == job_id)
            .values(
                clean_utterance_count=clean_count,
                flagged_utterance_count=flagged_count,
            )
        )

        await self.db.flush()

        logger.info(
            "Voice annotation init for job %s: %d clean, %d flagged",
            job_id, clean_count, flagged_count,
        )

        return {
            "job_id": str(job_id),
            "total": clean_count + flagged_count,
            "clean": clean_count,
            "flagged": flagged_count,
        }

    # ── Read operations ─────────────────────────────────────────────

    async def get_job_summary(self, job_id: UUID) -> dict:
        """Return voice annotation summary for a job."""
        job = (
            await self.db.execute(
                select(PipelineJob).where(PipelineJob.id == job_id)
            )
        ).scalar_one_or_none()

        if not job:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"Job {job_id} not found")

        total = job.clean_utterance_count + job.flagged_utterance_count

        return {
            "job_id": str(job.id),
            "original_filename": job.original_filename,
            "status": job.status,
            "total_utterances": total,
            "clean_count": job.clean_utterance_count,
            "flagged_count": job.flagged_utterance_count,
            "is_gate_passed": job.flagged_utterance_count == 0 and total > 0,
        }

    async def get_utterances(self, job_id: UUID) -> List[dict]:
        """List all voice annotations for a job, ordered by transcript timing."""
        rows = (
            await self.db.execute(
                select(VoiceAnnotation)
                .where(VoiceAnnotation.job_id == job_id)
                .options(selectinload(VoiceAnnotation.transcript))
                .order_by(VoiceAnnotation.created_at)
            )
        ).scalars().all()

        result = []
        # Sort by transcript start time for consistent ordering
        sorted_rows = sorted(rows, key=lambda va: va.transcript.start if va.transcript else 0)

        for idx, va in enumerate(sorted_rows):
            t = va.transcript

            # Build asset URL for utterance audio WAV (mirrors stage-2 results logic)
            audio_url = None
            if t and t.audio_path:
                if t.audio_path.startswith("jobs/"):
                    audio_url = f"{settings.api_v1_prefix}/assets/{t.audio_path}"
                else:
                    audio_url = f"{settings.api_v1_prefix}/assets/jobs/{job_id}/audio/{t.audio_path}"

            result.append({
                "id": str(va.id),
                "transcript_id": str(va.transcript_id),
                "global_index": idx + 1,
                "asr_text": va.asr_text,
                "ground_truth_text": va.ground_truth_text,
                "flagged_words": va.flagged_words or [],
                "has_flag": va.has_flag,
                "voice_annotation_status": va.voice_annotation_status,
                "start": t.start if t else 0,
                "end": t.end if t else 0,
                "audio_url": audio_url,
                "annotator_id": str(va.annotator_id) if va.annotator_id else None,
                "edited_at": va.edited_at.isoformat() if va.edited_at else None,
            })

        return result

    async def get_jobs_needing_annotation(self, page: int = 1, page_size: int = 50, dataset_id: Optional[UUID] = None) -> dict:
        """List jobs that need voice annotation, optionally filtered by dataset."""
        statuses = [
            JobStatus.NEEDS_VOICE_ANNOTATION,
            JobStatus.VOICE_ANNOTATION_IN_PROGRESS,
            JobStatus.READY_FOR_ANNOTATION,
        ]

        # Build base filters
        filters = [
            PipelineJob.status.in_(statuses),
            PipelineJob.is_cancelled == False,
        ]
        if dataset_id:
            filters.append(PipelineJob.dataset_id == dataset_id)

        # Count total
        total_q = await self.db.execute(
            select(func.count(PipelineJob.id)).where(*filters)
        )
        total = total_q.scalar() or 0

        # Fetch page
        offset = (page - 1) * page_size
        rows = (
            await self.db.execute(
                select(PipelineJob)
                .where(*filters)
                .order_by(PipelineJob.created_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        ).scalars().all()

        items = []
        for job in rows:
            total_utt = job.clean_utterance_count + job.flagged_utterance_count
            items.append({
                "job_id": str(job.id),
                "original_filename": job.original_filename,
                "status": job.status,
                "total_utterances": total_utt,
                "clean_count": job.clean_utterance_count,
                "flagged_count": job.flagged_utterance_count,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            })

        pages = max(1, (total + page_size - 1) // page_size)

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
        }

    # ── Write operations ────────────────────────────────────────────

    async def update_ground_truth(
        self,
        voice_annotation_id: UUID,
        new_text: str,
        user_id: UUID,
        is_unflagged: bool = False,
    ) -> dict:
        """Update ground truth text, re-validate, and recalculate job status.

        This is the core annotator action per the PRD:
        1. Save new ground_truth_text
        2. Re-run KBBI exact-match validation (unless is_unflagged is true)
        3. Update per-utterance flag status
        4. Recalculate job-level counters and status
        """
        va = (
            await self.db.execute(
                select(VoiceAnnotation).where(VoiceAnnotation.id == voice_annotation_id)
            )
        ).scalar_one_or_none()

        if not va:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"VoiceAnnotation {voice_annotation_id} not found")

        # 1. Update ground truth
        old_text = va.ground_truth_text
        va.ground_truth_text = new_text
        va.annotator_id = user_id
        va.edited_at = datetime.utcnow()

        # 2. Re-run validation or force unflag
        if is_unflagged:
            flagged_words = []
            has_flag = False
        else:
            flagged_words = await validate_text(new_text)
            has_flag = len(flagged_words) > 0

        va.flagged_words = flagged_words
        va.has_flag = has_flag
        va.voice_annotation_status = (
            VoiceAnnotation.STATUS_FLAGGED if has_flag else VoiceAnnotation.STATUS_CLEAN
        )

        await self.db.flush()

        # 3. Recalculate job-level counters
        job_summary = await self._recalculate_job_status(va.job_id)

        return {
            "id": str(va.id),
            "ground_truth_text": va.ground_truth_text,
            "flagged_words": va.flagged_words,
            "has_flag": va.has_flag,
            "voice_annotation_status": va.voice_annotation_status,
            "old_text": old_text,
            "job_status": job_summary["status"],
            "job_clean_count": job_summary["clean"],
            "job_flagged_count": job_summary["flagged"],
        }

    async def _recalculate_job_status(self, job_id: UUID) -> dict:
        """Recount clean/flagged utterances and update job status."""
        clean_q = await self.db.execute(
            select(func.count(VoiceAnnotation.id)).where(
                VoiceAnnotation.job_id == job_id,
                VoiceAnnotation.has_flag == False,
            )
        )
        clean = clean_q.scalar() or 0

        flagged_q = await self.db.execute(
            select(func.count(VoiceAnnotation.id)).where(
                VoiceAnnotation.job_id == job_id,
                VoiceAnnotation.has_flag == True,
            )
        )
        flagged = flagged_q.scalar() or 0

        new_status = (
            JobStatus.READY_FOR_ANNOTATION
            if flagged == 0
            else JobStatus.NEEDS_VOICE_ANNOTATION
        )

        await self.db.execute(
            update(PipelineJob)
            .where(PipelineJob.id == job_id)
            .values(
                clean_utterance_count=clean,
                flagged_utterance_count=flagged,
                status=new_status,
            )
        )

        await self.db.flush()

        return {"clean": clean, "flagged": flagged, "status": new_status}
