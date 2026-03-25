"""
ASR Worker - Stage 2 Queue Consumer

Processes ASR jobs from the queue using faster-whisper,
then queues Stage 3 (Cropping) for timestamp-based re-cropping.
"""

import logging
from uuid import UUID
from typing import Dict, Any

from app.workers.base import BaseWorker
from app.pipeline.stages.stage2_asr import run_asr, ASRSegmentInput
from app.services.job_service import job_service
from app.services.queue_service import queue_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus

logger = logging.getLogger(__name__)


class ASRWorker(BaseWorker):
    """
    Worker that processes ASR jobs from the queue.
    
    Consumes jobs from 'asr' queue, transcribes audio,
    updates segments, and queues cropping stage.
    """
    
    queue_name = "asr"
    max_retries = 3
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process an ASR job.
        
        Args:
            payload: {"job_id": str, "segment_count": int}
            
        Returns:
            {"segments_processed": int}
        """
        job_id = UUID(payload["job_id"])
        
        logger.info("Processing ASR job: %s", job_id)
        
        # Get job details
        async with async_session() as session:
            job = await job_service.get_job(session, str(job_id))
            segments = await job_service.get_segments(session, str(job_id))
            
            # Update status
            await job_service.update_status(session, str(job_id), JobStatus.TRANSCRIBING)
            await session.commit()
        
        # Prepare inputs for pipeline stage
        asr_inputs = [
            ASRSegmentInput(
                segment_index=seg.segment_index,
                video_path=seg.cropped_video_path or job.video_path,
                is_local=bool(seg.cropped_video_path)
            )
            for seg in segments
        ]
        
        # Run ASR (pure ML)
        results = await run_asr(
            segments=asr_inputs,
            progress_callback=lambda c, t: logger.info("ASR progress: %d/%d", c, t)
        )
        
        # Update segments with ASR data
        async with async_session() as session:
            for result in results:
                await job_service.update_segment_asr(
                    session,
                    segment_index=result.segment_index,
                    job_id=str(job_id),
                    asr_text=result.text,
                    asr_confidence=result.confidence,
                    asr_start=result.start,
                    asr_end=result.end,
                    asr_review_flag=result.review_flag
                )
            await session.commit()
        
        # Populate ASR Review queue if enabled
        await self._populate_asr_review_queue(job_id, results)
        
        # Finalize job and queue cropping stage
        await self._finalize_job_and_queue_cropping(job_id)
        
        return {"segments_processed": len(results)}
    
    async def _populate_asr_review_queue(
        self,
        job_id: UUID,
        segments: list
    ) -> None:
        """
        Populate ASR Review queue if enabled for this job.
        
        Creates asr_reviews records for each segment, allowing
        ASR reviewers to validate transcripts before annotation.
        """
        from app.db.models.pipeline import PipelineSegment
        from app.db.models.annotation import ASRReview
        from sqlalchemy import select
        
        async with async_session() as session:
            # Check if ASR Review is enabled via config
            # For now, check job metadata or use default False
            # Future: Implement ConfigService for per-job configuration
            asr_review_enabled = False  # Default disabled until configured
            
            # TODO: Check job config for asr_review_enabled flag
            # This will be implemented when per-job configuration is available
            
            if not asr_review_enabled:
                logger.info(f"ASR Review disabled for job {job_id}")
                return
            
            # Get segments for this job
            segment_query = select(PipelineSegment).where(
                PipelineSegment.job_id == job_id
            )
            result = await session.execute(segment_query)
            db_segments = result.scalars().all()
            
            # Create ASR review records for each segment
            for segment in db_segments:
                review_record = ASRReview(
                    segment_id=segment.id,
                    reviewer_id=None,  # Unassigned
                    original_text=segment.asr_text or "",
                    corrected_text=None,
                    confidence_score=segment.asr_confidence,
                    status=ASRReview.STATUS_PENDING,
                    flag_reason=None,
                    reviewed_at=None
                )
                session.add(review_record)
            
            await session.commit()
            logger.info(
                f"Created {len(db_segments)} ASR Review records for job {job_id}"
            )
    
    async def _finalize_job_and_queue_cropping(self, job_id: UUID):
        """
        Finalize ASR stage and queue cropping stage.
        
        Updates job to ASR_COMPLETED and queues cropping job.
        If queuing fails, job remains in ASR_COMPLETED state with error logged.
        """
        logger.info("ASR complete for job %s. Queuing cropping stage.", job_id)
        
        async with async_session() as session:
            # Update job status to ASR_COMPLETED
            await job_service.update_status(
                session,
                str(job_id),
                JobStatus.ASR_COMPLETED
            )
            await session.commit()
            
            # Queue cropping job (outside transaction to avoid locking issues)
            try:
                cropping_job = await queue_service.enqueue(
                    queue_name="cropping",
                    payload={"job_id": str(job_id)},
                    db=None,  # Use new session
                    priority=0,
                    max_attempts=3
                )
                logger.info(
                    "Cropping stage queued for job %s (queue_job_id: %s)",
                    job_id, cropping_job.id
                )
            except Exception as e:
                # Log critical error - job is in ASR_COMPLETED but cropping not queued
                logger.error(
                    "CRITICAL: Failed to queue cropping stage for job %s: %s",
                    job_id, e,
                    exc_info=True
                )
                # Update job with error note
                await job_service.update_status(
                    session,
                    str(job_id),
                    JobStatus.ASR_COMPLETED,
                    error_message=f"ASR complete but cropping queue failed: {e}"
                )
                await session.commit()
                # Re-raise to trigger worker retry
                raise
