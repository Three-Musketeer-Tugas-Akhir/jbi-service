"""
ASR Worker - Stage 2 Kafka Consumer

Processes ASR jobs from Kafka using faster-whisper,
then publishes Stage 3 (Cropping) messages.
"""

import logging
import asyncio
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
from app.messaging.topics import PipelineTopics

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
    
    async def is_already_processed(self, job_id: str) -> bool:
        """Check if ASR was already done for this job."""
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return False
        
        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job_uuid)
            if not segments:
                return False
            
            # Check if any transcripts exist for these segments
            segment_ids = [s.id for s in segments]
            from sqlalchemy import select
            from app.db.models.pipeline import PipelineTranscript
            result = await session.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id.in_(segment_ids)
                )
            )
            transcripts = result.scalars().all()
            return len(transcripts) > 0
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process an ASR job.
        
        Args:
            payload: {"job_id": str, "segment_count": int, "segment_ids": list}
            
        Returns:
            {"transcripts_count": int, "segments_processed": int}
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
