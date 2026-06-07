"""
ASR Worker - Stage 2 Kafka Consumer

Processes ASR jobs from Kafka using faster-whisper,
then publishes Stage 3 (Cropping) messages.
"""

import logging
import asyncio
import json
import os
from uuid import UUID
from typing import Dict, Any, List, Optional

from app.workers.kafka_base import KafkaPipelineWorker
from app.pipeline.stages.stage2_asr import run_asr, ASRSegmentInput
from app.pipeline.utils.video import crop_audio
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.db.session import async_session
from app.db.models.pipeline import JobStatus, PipelineTranscript
from app.services.minio_service import get_minio_service
from app.core.exceptions import ProcessingError
from app.core.locks import DistributedLockManager
from app.messaging.topics import PipelineTopics
from app.messaging.schemas import PipelineMessage

logger = logging.getLogger(__name__)


class ASRWorker(KafkaPipelineWorker):
    """
    Worker that processes ASR jobs from Kafka.
    
    Consumes from 'pipeline.jobs.asr' topic, transcribes audio,
    updates segments, and publishes cropping stage to 'pipeline.jobs.crop'.
    """
    
    topic = PipelineTopics.ASR.value
    consumer_group = "asr-workers"
    next_stage_topic = PipelineTopics.CROPPING.value
    max_retries = 3
    
    async def _process_message(self, msg) -> None:
        """
        Override parent method to add PostgreSQL advisory lock.
        
        This prevents duplicate processing when multiple workers are scaled up.
        The lock ensures only one worker processes a specific job at a time.
        """
        try:
            data = json.loads(msg.value.decode("utf-8"))
            message = PipelineMessage.from_kafka_dict(data)
            job_id = str(message.job_id)
            
            logger.info(
                f"Processing {message.stage} job: {job_id} "
                f"[msg_id={message.message_id}]"
            )
            
            # Check cancellation
            if await self.is_job_cancelled(job_id):
                logger.warning(f"Job {job_id} was cancelled, skipping")
                await self._commit(msg)
                return
            
            # Try to acquire distributed lock for this job
            # Use the same session for lock and idempotency check to keep transaction consistent
            async with async_session() as session:
                lock = await DistributedLockManager.try_lock_job(
                    session, "asr", job_id
                )
                
                if lock is None:
                    logger.warning(
                        f"Job {job_id} is locked by another worker, skipping"
                    )
                    await self._commit(msg)
                    return
                
                try:
                    # Check idempotency within the same session
                    payload = message.payload if hasattr(message, 'payload') else None
                    if await self.is_already_processed(job_id, payload):
                        logger.info(f"Job {job_id} already processed, skipping")
                        if self.next_stage_topic:
                            await self._ensure_next_stage_queued(message)
                        await self._commit(msg)
                        return

                    await session.commit()

                except Exception as e:
                    await session.rollback()
                    raise
                finally:
                    # Explicitly release the advisory lock before the session closes.
                    # Without this the lock leaks onto the pooled connection and
                    # blocks legitimate retry processing by other (or the same) worker.
                    await lock.release()

            # Process with retry (outside the lock session — lock is now released)
            result = await self._process_with_retry(message)
            
            if result is not None:
                # Publish next stage
                if self.next_stage_topic:
                    await self._publish_next_stage(message, result)
                
                # Commit offset only after everything succeeds
                await self._commit(msg)
                logger.info(f"Job {job_id} completed and committed")
                
        except Exception as e:
            logger.exception(f"Failed to process message: {e}")
            # Don't commit → message will be redelivered
            if isinstance(e, ProcessingError) and e.permanent:
                logger.error(f"Permanent error, sending to DLQ: {e}")
                await self._send_to_dlq(msg, e)
                await self._commit(msg)
    
    async def is_already_processed(self, job_id: str, payload: Optional[Dict[str, Any]] = None) -> bool:
        """Check if ASR was already done for this job.

        For partial retries (mode='partial'), only check the specified segments.
        For full retries, ALL segments must have transcripts to be considered done
        (partial completion from a crashed worker is NOT considered done, so the
        worker re-runs and fills in the missing segments).
        """
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return False

        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job_uuid)
            if not segments:
                return False

            # For partial retries, narrow to requested segments only
            if payload and payload.get("mode") == "partial" and payload.get("segment_ids"):
                requested_ids = set(payload["segment_ids"])
                segments = [s for s in segments if str(s.id) in requested_ids]
                if not segments:
                    return False

            # Every segment in the set must have at least one transcript.
            # If any segment is missing transcripts the job is not done yet.
            from sqlalchemy import select, func
            from app.db.models.pipeline import PipelineTranscript
            for seg in segments:
                result = await session.execute(
                    select(func.count(PipelineTranscript.id)).where(
                        PipelineTranscript.segment_id == seg.id
                    )
                )
                if (result.scalar() or 0) == 0:
                    return False

            return True
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process an ASR job.
        
        Args:
            payload: {"job_id": str, "segment_count": int, "segment_ids": list, "mode": str}
            
        Returns:
            {"transcripts_count": int, "segments_processed": int}
        """
        job_id = UUID(payload["job_id"])
        is_partial = payload.get("mode") == "partial"
        requested_segment_ids = set(payload.get("segment_ids", []))
        
        logger.info(
            "Processing ASR job: %s (mode=%s, segments=%s)", 
            job_id, 
            "partial" if is_partial else "full",
            len(requested_segment_ids) if is_partial else "all"
        )
        
        # Get job details
        async with async_session() as session:
            job_repo = JobRepository(session)
            segment_repo = SegmentRepository(session)
            job = await job_repo.get_by_id(job_id)
            segments = await segment_repo.get_by_job_id(job_id)
            
            # Filter segments for partial retry
            if is_partial and requested_segment_ids:
                segments = [s for s in segments if str(s.id) in requested_segment_ids]
                logger.info(
                    "Filtered to %d segments for partial retry", 
                    len(segments)
                )
                if not segments:
                    logger.warning("No matching segments found for partial retry")
                    return {"transcripts_count": 0, "segments_processed": 0}
            
            # Update status
            await job_repo.update_status(job_id, JobStatus.TRANSCRIBING, current_stage="asr")
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
                    JobStatus.FAILED, 
                    error_message=f"ASR (Transkripsi) gagal pada seluruh {len(results)} segmen",
                    current_stage="asr",
                )
                await session.commit()
            raise ProcessingError(f"Proses ASR gagal pada semua {len(results)} segmen")
        
        if failed_segments:
            logger.warning(
                f"ASR partially failed for job {job_id}: "
                f"{len(failed_segments)}/{len(results)} segments failed"
            )
        
        # Store individual utterances in pipeline_transcripts
        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job_id)
            
            for result in results:
                for seg in segments:
                    if seg.segment_index == result.segment_index:
                        # Update only the review flag in pipeline_segments
                        seg.asr_review_flag = result.review_flag
                        
                        minio_service = get_minio_service()
                        
                        # Store individual utterances in pipeline_transcripts
                        for utt in result.utterances:
                            utterance_audio_path = None
                            if result.audio_path and result.audio_path.exists():
                                try:
                                    tmp_utt_audio = f"/tmp/{seg.id}_utt_{utt.utterance_index}.wav"
                                    wav_key = f"jobs/{job_id}/audio/{seg.id}_utt_{utt.utterance_index}.wav"
                                    
                                    # Crop utterance from the full audio
                                    await crop_audio(
                                        input_path=str(result.audio_path),
                                        output_path=tmp_utt_audio,
                                        start_time=utt.start,
                                        end_time=utt.end
                                    )
                                    
                                    with open(tmp_utt_audio, "rb") as f:
                                        wav_bytes = f.read()
                                    await minio_service.upload_file(
                                        file_data=wav_bytes,
                                        object_name=wav_key,
                                        content_type="audio/wav"
                                    )
                                    utterance_audio_path = wav_key
                                    
                                    # Clean up local crop
                                    if os.path.exists(tmp_utt_audio):
                                        os.remove(tmp_utt_audio)
                                except Exception as e:
                                    logger.warning("Failed to crop/upload WAV audio for utterance %d: %s", utt.utterance_index, e)

                            transcript = PipelineTranscript(
                                segment_id=seg.id,
                                utterance_index=utt.utterance_index,
                                text=utt.text,
                                start=utt.start,
                                end=utt.end,
                                confidence=utt.confidence,
                                audio_path=utterance_audio_path
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
        
        # Update job status to ASR_COMPLETED
        async with async_session() as session:
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, JobStatus.ASR_COMPLETED, current_stage="asr")
            await session.commit()
        
        total_utterances = sum(len(r.utterances) for r in results)
        
        return {
            "segments_processed": len(results),
            "transcripts_count": total_utterances,
        }
    
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
            asr_review_enabled = False  # Default disabled until configured
            
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
