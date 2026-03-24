"""
ASR Worker - Stage 2 Queue Consumer

Processes ASR jobs from the queue using faster-whisper.
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
    updates segments, and queues Cropping stage.
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
        
        logger.info(f"Processing ASR job: {job_id}")
        
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
            progress_callback=lambda c, t: logger.info(f"ASR progress: {c}/{t}")
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
        
        # Queue next stage
        await self._queue_next_stage(job_id)
        
        return {"segments_processed": len(results)}
    
    async def _queue_next_stage(self, job_id: UUID):
        """Queue cropping stage after ASR."""
        async with async_session() as session:
            await queue_service.enqueue(session, "cropping", {"job_id": str(job_id)})
            await session.commit()
