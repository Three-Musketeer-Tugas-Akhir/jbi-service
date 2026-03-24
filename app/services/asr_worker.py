"""ASR worker for transcribing video segments from queue."""

import asyncio
import logging
import signal
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProcessingError
from app.db.models.pipeline import PipelineSegment, QueueJob, JobStatus
from app.db.session import get_db_session
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.minio_service import get_minio_service
from app.services.queue_service import queue_service
from app.services.transcriber import get_transcriber_service
from app.services.audio_extractor import get_audio_extractor

logger = logging.getLogger(__name__)


class ASRWorker:
    """
    Background worker for faster-whisper ASR transcription.
    
    Polls the ASR queue, downloads Stage 1 segments from MinIO,
    extracts audio, runs transcription, updates segment records,
    and queues the Cropping stage.
    """
    
    def __init__(
        self,
        poll_interval: int = 5,
        timeout_seconds: int = 1800
    ):
        self.poll_interval = poll_interval
        self.timeout_seconds = timeout_seconds
        self._shutdown_event = asyncio.Event()  # ECH-5: Use asyncio.Event for clean shutdown
        self.minio_service = get_minio_service()
        self.transcriber = get_transcriber_service()
        self.audio_extractor = get_audio_extractor()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    @property
    def running(self) -> bool:
        """Check if worker is running."""
        return not self._shutdown_event.is_set()
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("ASRWorker received shutdown signal")
        self._shutdown_event.set()
    
    async def start(self):
        """Start the worker loop."""
        logger.info("ASRWorker starting...")
        
        while not self._shutdown_event.is_set():
            try:
                # Poll for jobs with timeout to allow checking shutdown_event
                queue_job = await queue_service.dequeue("asr")
                
                if queue_job:
                    await self._process_job(queue_job)
                else:
                    # No jobs available, wait before polling again
                    # Use wait_for to allow interruption by shutdown signal
                    try:
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=self.poll_interval
                        )
                    except asyncio.TimeoutError:
                        # Normal polling interval timeout, continue loop
                        pass
                    
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.poll_interval
                    )
                except asyncio.TimeoutError:
                    pass
        
        logger.info("ASRWorker stopped")
    
    async def _process_job(self, queue_job: QueueJob):
        """Process a single ASR job."""
        job_id = UUID(queue_job.payload["job_id"])
        logger.info(f"Processing ASR job: {job_id}")
        
        async with get_db_session() as db:
            job_repo = JobRepository(db)
            segment_repo = SegmentRepository(db)
            
            try:
                # 1. Update job status to TRANSCRIBING
                await job_repo.update_status(job_id, JobStatus.TRANSCRIBING)
                
                # 2. Get all segments for this job
                segments = await segment_repo.get_by_job_id(job_id)
                if not segments:
                    raise ProcessingError("No segments found for job")
                
                logger.info(f"Processing {len(segments)} segments for job {job_id}")
                
                # 3. Process each segment
                all_low_confidence = True
                processed_count = 0
                
                for segment in segments:
                    success = await self._process_segment(
                        db, job_id, segment
                    )
                    if success:
                        processed_count += 1
                        if segment.asr_confidence and segment.asr_confidence >= 0.5:
                            all_low_confidence = False
                
                # 4. Check if all segments failed or have low confidence
                if all_low_confidence and processed_count > 0:
                    logger.warning(
                        f"All segments have low confidence for job {job_id}"
                    )
                
                if processed_count == 0:
                    raise ProcessingError("No segments could be processed")
                
                # 5. Update job status and queue Cropping stage
                await job_repo.update_status(job_id, JobStatus.CROPPING)
                await queue_service.enqueue(
                    "cropping",
                    {"job_id": str(job_id)},
                    db=db
                )
                await queue_service.mark_completed(queue_job.id, db=db)
                
                logger.info(f"ASR completed for job {job_id}")
                
            except asyncio.TimeoutError:
                logger.error(f"ASR timeout for job {job_id}")
                await self._handle_failure(db, job_repo, queue_job, "Processing timeout")
                
            except ProcessingError as e:
                if getattr(e, "permanent", False):
                    logger.error(f"ASR permanent failure for job {job_id}: {e}")
                    await self._handle_failure(db, job_repo, queue_job, str(e), permanent=True)
                else:
                    logger.error(f"ASR failed for job {job_id}: {e}")
                    await self._handle_failure(db, job_repo, queue_job, str(e))
                
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job_id}")
                await self._handle_failure(
                    db, job_repo, queue_job, f"Internal error: {e}"
                )
                # Don't re-raise - failure has been handled and job is marked for retry via queue_service
    
    async def _process_segment(
        self,
        db: AsyncSession,
        job_id: UUID,
        segment: PipelineSegment
    ) -> bool:
        """
        Process a single segment for ASR.
        
        Returns:
            True if transcription succeeded, False otherwise
        """
        segment_index = segment.segment_index
        temp_files = []  # Track all temp files for cleanup (ECH-1)
        
        logger.info(f"Processing segment {segment_index} for job {job_id}")
        
        try:
            # 1. Download segment from MinIO
            video_data = await self._download_segment(segment.cropped_video_path)
            
            # 2. Save to temp file
            video_path = await self._save_temp_video(video_data, segment_index)
            temp_files.append(video_path)  # Track for cleanup
            
            # 3. Extract audio
            audio_path = await self.audio_extractor.extract(video_path)
            temp_files.append(audio_path)  # Track for cleanup
            
            # 4. Run transcription (with timeout)
            result = await asyncio.wait_for(
                self.transcriber.transcribe(audio_path),
                timeout=self.timeout_seconds
            )
            
            # ECH-3: Handle empty transcription
            if not result.segments:
                logger.warning(f"No speech detected in segment {segment_index}")
                segment.asr_text = ""
                segment.asr_start = 0.0
                segment.asr_end = 0.0
                segment.asr_confidence = 0.0
                segment.asr_review_flag = True  # Flag for review
                await db.flush()
                return True
            
            # 5. Update segment record
            segment.asr_text = result.text
            segment.asr_start = result.start
            segment.asr_end = result.end
            segment.asr_confidence = result.average_confidence
            
            # ECH-2: Validate timestamps against reasonable bounds (0 to 1 hour)
            # Individual segment timestamps are relative to segment start, so should be small
            if result.end > 3600:  # 1 hour max for a single segment
                logger.warning(
                    f"ASR end timestamp ({result.end}s) exceeds 1 hour for segment {segment_index}"
                )
            
            # ECH-4: Flag low confidence segments in DB
            if result.average_confidence < 0.5:
                logger.warning(
                    f"Low confidence ({result.average_confidence:.2f}) "
                    f"for segment {segment_index}"
                )
                segment.asr_review_flag = True
            else:
                segment.asr_review_flag = False
            
            await db.flush()
            
            logger.info(
                f"Segment {segment_index} transcribed: "
                f"{len(result.segments)} segments, "
                f"confidence={result.average_confidence:.2f}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process segment {segment_index}: {e}")
            # Mark segment as failed but continue with others
            segment.asr_text = None
            segment.asr_confidence = 0.0
            segment.asr_review_flag = True  # Flag failed segments for review
            return False
            
        finally:
            # ECH-1: Cleanup all tracked temp files
            for temp_file in temp_files:
                if temp_file and temp_file.exists():
                    try:
                        temp_file.unlink()
                    except OSError as e:
                        logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")
    
    async def _download_segment(self, object_name: str) -> bytes:
        """Download segment from MinIO."""
        try:
            return await self.minio_service.download_file(object_name)
        except Exception as e:
            raise ProcessingError(f"Failed to download segment: {e}")
    
    async def _save_temp_video(self, video_data: bytes, segment_index: int) -> Path:
        """Save video data to temporary file."""
        try:
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".mp4",
                delete=False,
                prefix=f"asr_segment_{segment_index}_"
            )
            temp_file.write(video_data)
            temp_file.close()
            return Path(temp_file.name)
        except (OSError, IOError) as e:
            # Handle disk full, permission denied, etc.
            raise ProcessingError(
                f"Failed to create temp file for segment {segment_index}: {e}",
                permanent=False  # Retryable - disk space might free up
            )
    
    async def _cleanup_temp_files(
        self,
        video_path: Optional[Path],
        audio_path: Optional[Path]
    ):
        """Clean up temporary files."""
        for path in [video_path, audio_path]:
            if path and path.exists():
                try:
                    path.unlink()
                except OSError as e:
                    logger.warning(f"Failed to cleanup temp file {path}: {e}")
    
    async def _handle_failure(
        self,
        db: AsyncSession,
        job_repo: JobRepository,
        queue_job: QueueJob,
        error_message: str,
        permanent: bool = False
    ):
        """Handle job failure - update status and mark queue job failed."""
        job_id = UUID(queue_job.payload["job_id"])
        await job_repo.update_status(job_id, JobStatus.FAILED, error_message)
        await queue_service.mark_failed(queue_job, error_message, db=db)


# Global worker instance
_asr_worker_instance = None


def get_asr_worker() -> ASRWorker:
    """Get or create ASR worker singleton."""
    global _asr_worker_instance
    if _asr_worker_instance is None:
        _asr_worker_instance = ASRWorker()
    return _asr_worker_instance


async def run_asr_worker():
    """Entry point for running the worker."""
    worker = get_asr_worker()
    await worker.start()
