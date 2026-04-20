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
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.queue_service import queue_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus, PipelineTranscript
from app.services.minio_service import get_minio_service
from app.core.exceptions import ProcessingError

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
            job_repo = JobRepository(session)
            segment_repo = SegmentRepository(session)
            job = await job_repo.get_by_id(job_id)
            segments = await segment_repo.get_by_job_id(job_id)
            
            # Update status
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, "TRANSCRIBING")
            await session.commit()
        
        # Prepare inputs for pipeline stage
        # cropped_video_path now stores MinIO object keys, not local paths
        asr_inputs = [
            ASRSegmentInput(
                segment_index=seg.segment_index,
                video_path=seg.cropped_video_path or job.video_path,
                is_local=False  # Always download from MinIO
            )
            for seg in segments
        ]
        
        # Run ASR (pure ML)
        results = await run_asr(
            segments=asr_inputs,
            progress_callback=lambda c, t: logger.info("ASR progress: %d/%d", c, t)
        )
        
        # Check if any segments succeeded (confidence > 0 or text not empty)
        successful_segments = [r for r in results if r.confidence > 0 or r.text.strip()]
        failed_segments = [r for r in results if r.confidence == 0 and not r.text.strip()]
        
        if not successful_segments:
            # All segments failed - mark job as FAILED
            logger.error(f"ASR failed for all {len(results)} segments in job {job_id}")
            async with async_session() as session:
                job_repo = JobRepository(session)
                await job_repo.update_status(
                    job_id, 
                    "FAILED", 
                    error_message=f"ASR failed for all {len(results)} segments"
                )
                await session.commit()
            raise ProcessingError(f"ASR failed for all {len(results)} segments")
        
        if failed_segments:
            logger.warning(
                f"ASR partially failed for job {job_id}: "
                f"{len(failed_segments)}/{len(results)} segments failed"
            )
        
        # Store individual utterances in pipeline_transcripts
        # Note: ASR data is now stored only at utterance-level, not in pipeline_segments
        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job_id)
            
            for result in results:
                for seg in segments:
                    if seg.segment_index == result.segment_index:
                        # Update only the review flag in pipeline_segments
                        seg.asr_review_flag = result.review_flag
                        
                        # Upload WAV audio to MinIO if available
                        # One audio file per segment (contains all utterances)
                        minio_service = get_minio_service()
                        segment_audio_path = None
                        if result.audio_path and result.audio_path.exists():
                            try:
                                wav_key = f"jobs/{job_id}/audio/{seg.id}.wav"
                                with open(result.audio_path, "rb") as f:
                                    wav_bytes = f.read()
                                await minio_service.upload_file(
                                    file_data=wav_bytes,
                                    object_name=wav_key,
                                    content_type="audio/wav"
                                )
                                segment_audio_path = wav_key
                                logger.info("Uploaded WAV audio for segment %s", seg.id)
                            except Exception as e:
                                logger.warning("Failed to upload WAV audio for segment %s: %s", seg.id, e)
                        
                        # Store individual utterances in pipeline_transcripts
                        for utt in result.utterances:
                            transcript = PipelineTranscript(
                                segment_id=seg.id,
                                utterance_index=utt.utterance_index,
                                text=utt.text,
                                start=utt.start,
                                end=utt.end,
                                confidence=utt.confidence,
                                audio_path=segment_audio_path
                            )
                            session.add(transcript)
                        
                        logger.info(
                            "Stored %d utterances for segment %s", 
                            len(result.utterances), 
                            seg.id
                        )
                        break
            
            await session.commit()
        
        # Cleanup temp audio files
        for result in results:
            if result.audio_path and result.audio_path.exists():
                try:
                    result.audio_path.unlink()
                except OSError as e:
                    logger.warning("Failed to cleanup temp audio file %s: %s", result.audio_path, e)
        
        # Populate ASR Review queue if enabled
        await self._populate_asr_review_queue(job_id, results)
        
        # Finalize job and queue cropping stage
        await self._finalize_job_and_queue_cropping(job_id)
        
        return {"segments_processed": len(results)}
    
    async def _populate_asr_review_queue(
        self,
        job_id: UUID,
        asr_results: list
    ) -> None:
        """
        Populate ASR Review queue if enabled for this job.
        
        Creates asr_reviews records for each segment, allowing
        ASR reviewers to validate transcripts before annotation.
        """
        from app.db.models.pipeline import PipelineSegment
        from app.db.models.annotation import ASRReview
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        
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
            
            # Get segments for this job with transcripts loaded
            segment_query = (
                select(PipelineSegment)
                .options(selectinload(PipelineSegment.transcripts))
                .where(PipelineSegment.job_id == job_id)
            )
            result = await session.execute(segment_query)
            db_segments = result.scalars().all()
            
            # Create ASR review records for each segment using ASR results
            for segment in db_segments:
                # Find matching ASR result by segment_index
                asr_result = None
                for r in asr_results:
                    if r.segment_index == segment.segment_index:
                        asr_result = r
                        break
                
                review_record = ASRReview(
                    segment_id=segment.id,
                    reviewer_id=None,  # Unassigned
                    original_text=asr_result.text if asr_result else (segment.asr_text or ""),
                    corrected_text=None,
                    confidence_score=asr_result.confidence if asr_result else segment.asr_confidence,
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
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, "ASR_COMPLETED")
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
                job_repo = JobRepository(session)
                await job_repo.update_status(
                    job_id,
                    "ASR_COMPLETED"
                )
                await session.commit()
                # Re-raise to trigger worker retry
                raise
