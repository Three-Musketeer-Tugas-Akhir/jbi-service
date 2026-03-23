"""Detection worker for processing videos from queue."""

import asyncio
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProcessingError
import logging
from app.db.models.pipeline import PipelineSegment, QueueJob
from app.db.session import get_db_session
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.minio_service import get_minio_service
from app.services.queue_service import queue_service
from app.services.jbi_detector import get_jbi_detector, JBISegment

logger = logging.getLogger(__name__)


class DetectionWorker:
    """
    Background worker for YOLOv8-based JBI detection.
    
    Polls the detection queue, downloads videos, runs inference,
    performs Stage 1 cropping, and queues ASR stage.
    """
    
    def __init__(
        self,
        poll_interval: int = 5,
        timeout_seconds: int = 1800
    ):
        self.poll_interval = poll_interval
        self.timeout_seconds = timeout_seconds
        self.running = False
        self._shutdown_event = asyncio.Event()
        self.minio_service = get_minio_service()
        self.detector = get_jbi_detector()
    
    def _handle_shutdown(self, signum):
        """Handle shutdown signals gracefully."""
        logger.info(f"DetectionWorker received signal {signum}")
        self.running = False
        self._shutdown_event.set()
    
    async def start(self):
        """Start the worker loop."""
        logger.info("DetectionWorker starting...")
        self.running = True
        
        # Setup signal handlers (async-safe)
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: self._handle_shutdown(s))
        
        try:
            while self.running:
                try:
                    # Poll for jobs with shutdown event check
                    queue_job = await asyncio.wait_for(
                        queue_service.dequeue("detection"),
                        timeout=self.poll_interval
                    )
                    
                    if queue_job:
                        await self._process_job(queue_job)
                    
                except asyncio.TimeoutError:
                    # No jobs available, continue polling
                    continue
                except Exception as e:
                    logger.error(f"Unexpected error in worker loop: {e}")
                    await asyncio.sleep(self.poll_interval)
        finally:
            # Remove signal handlers
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)
            logger.info("DetectionWorker stopped")
    
    async def _process_job(self, queue_job: QueueJob, attempt: int = 1, max_attempts: int = 3):
        """
        Process a single detection job with retry logic.
        
        Args:
            queue_job: The queue job to process
            attempt: Current attempt number (for retries)
            max_attempts: Maximum number of retry attempts
        """
        job_id_str = queue_job.payload.get("job_id")
        if not job_id_str:
            logger.error("Queue job missing 'job_id' in payload")
            await queue_service.mark_failed(queue_job, "Invalid job payload: missing job_id")
            return
        
        try:
            job_id = UUID(job_id_str)
        except ValueError:
            logger.error(f"Invalid job_id format: {job_id_str}")
            await queue_service.mark_failed(queue_job, f"Invalid job_id format: {job_id_str}")
            return
        
        logger.info(f"Processing detection job: {job_id} (attempt {attempt}/{max_attempts})")
        
        video_path: Optional[Path] = None
        
        async with get_db_session() as db:
            job_repo = JobRepository(db)
            segment_repo = SegmentRepository(db)
            
            try:
                # 1. Update job status to DETECTING
                await job_repo.update_status(job_id, "DETECTING")
                
                # 2. Get job details
                job = await job_repo.get_by_id(job_id)
                if not job:
                    raise ProcessingError(f"Job {job_id} not found")
                
                # 3. Download video from MinIO to temp file
                video_path = await self._download_video(job_id, job.video_path)
                
                # 4. Run JBI detection (with timeout)
                segments = await asyncio.wait_for(
                    self.detector.detect(video_path),
                    timeout=self.timeout_seconds
                )
                
                # 5. Check if any detections found
                if not segments:
                    raise ProcessingError("No JBI regions detected in video")
                
                # 6. Stage 1 cropping and upload
                pipeline_segments = await self._process_segments(
                    db, job_id, video_path, segments
                )
                
                # 7. Store segment records
                await segment_repo.create_many(pipeline_segments)
                
                # 8. Update job status and queue ASR stage
                await job_repo.update_status(job_id, "TRANSCRIBING")
                await queue_service.enqueue(
                    "asr",
                    {"job_id": str(job_id)},
                    db=db
                )
                await queue_service.mark_completed(queue_job.id, db=db)
                
                logger.info(
                    f"Detection completed for job {job_id}: "
                    f"{len(pipeline_segments)} segments"
                )
                
            except asyncio.TimeoutError:
                logger.error(f"Detection timeout for job {job_id}")
                await self._handle_failure_with_retry(
                    db, job_repo, queue_job, "Processing timeout",
                    attempt, max_attempts, is_retryable=True
                )
                
            except ProcessingError as e:
                logger.error(f"Detection failed for job {job_id}: {e}")
                # Don't retry on "No JBI regions detected" - it's a permanent failure
                is_retryable = "No JBI regions detected" not in str(e)
                await self._handle_failure_with_retry(
                    db, job_repo, queue_job, str(e),
                    attempt, max_attempts, is_retryable
                )
                
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job_id}")
                await self._handle_failure_with_retry(
                    db, job_repo, queue_job, f"Internal error: {e}",
                    attempt, max_attempts, is_retryable=True
                )
            
            finally:
                # Cleanup temp file
                if video_path:
                    await self._cleanup_temp_video(video_path)
    
    async def _handle_failure_with_retry(
        self,
        db: AsyncSession,
        job_repo: JobRepository,
        queue_job: QueueJob,
        error_message: str,
        attempt: int,
        max_attempts: int,
        is_retryable: bool
    ):
        """
        Handle job failure with retry logic.
        
        If retryable and attempts remain, re-enqueue the job with backoff.
        Otherwise, mark as failed.
        """
        job_id_str = queue_job.payload.get("job_id", "unknown")
        
        if is_retryable and attempt < max_attempts:
            # Calculate backoff delay (5s, 15s, 45s)
            delay = 5 * (3 ** (attempt - 1))
            logger.info(
                f"Retrying job {job_id_str} after {delay}s "
                f"(attempt {attempt + 1}/{max_attempts})"
            )
            
            # Re-enqueue with delay
            await queue_service.enqueue(
                "detection",
                queue_job.payload,
                db=db,
                delay_seconds=delay
            )
            # Mark current attempt as completed (will be retried)
            await queue_service.mark_completed(queue_job.id, db=db)
        else:
            # Max attempts reached or not retryable
            if not is_retryable:
                logger.info(f"Job {job_id_str} failed permanently: {error_message}")
            else:
                logger.error(f"Job {job_id_str} failed after {max_attempts} attempts")
            
            job_id = UUID(job_id_str) if job_id_str != "unknown" else None
            if job_id:
                await job_repo.update_status(job_id, "FAILED", error_message)
            await queue_service.mark_failed(queue_job, error_message, db=db)
    
    async def _download_video(self, job_id: UUID, object_name: str) -> Path:
        """Download video from MinIO to temporary file."""
        if not object_name:
            raise ProcessingError("Video object name is empty")
        
        try:
            video_data = await self.minio_service.download_file(object_name)
            
            if not video_data:
                raise ProcessingError("Downloaded video is empty")
            
            # Create temp file with proper extension
            suffix = Path(object_name).suffix or ".mp4"
            temp_file = tempfile.NamedTemporaryFile(
                suffix=suffix,
                delete=False,
                prefix=f"detection_{job_id}_"
            )
            temp_file.write(video_data)
            temp_file.close()
            
            video_path = Path(temp_file.name)
            
            # Verify file was written
            if not video_path.exists() or video_path.stat().st_size == 0:
                raise ProcessingError("Video file validation failed")
            
            return video_path
            
        except Exception as e:
            if isinstance(e, ProcessingError):
                raise
            raise ProcessingError(f"Failed to download video: {e}")
    
    async def _process_segments(
        self,
        db: AsyncSession,
        job_id: UUID,
        video_path: Path,
        segments: list
    ) -> list:
        """
        Crop Stage 1 segments and upload to MinIO.
        
        Returns list of PipelineSegment objects.
        """
        pipeline_segments = []
        
        for idx, seg_data in enumerate(segments):
            # Validate segment data
            if not self._validate_segment(seg_data):
                logger.warning(f"Invalid segment data at index {idx}, skipping")
                continue
            
            # Create segment record
            segment = PipelineSegment(
                job_id=job_id,
                segment_index=idx,
                bbox_data=seg_data.bbox_data,
                status="DETECTED"
            )
            
            # Stage 1 cropping using FFmpeg
            cropped_path = await self._crop_segment(
                video_path, seg_data, idx, job_id
            )
            
            try:
                # Upload to MinIO
                object_name = f"jobs/{job_id}/stage1/segment_{idx}.mp4"
                with open(cropped_path, "rb") as f:
                    await self.minio_service.upload_file(
                        file_data=f.read(),
                        object_name=object_name,
                        content_type="video/mp4"
                    )
                
                segment.cropped_video_path = object_name
                pipeline_segments.append(segment)
                
            finally:
                # Cleanup temp cropped file
                if cropped_path.exists():
                    cropped_path.unlink(missing_ok=True)
        
        return pipeline_segments
    
    def _validate_segment(self, seg_data: JBISegment) -> bool:
        """Validate segment data before processing."""
        if not seg_data.bbox_data:
            return False
        
        required_keys = ["x", "y", "width", "height"]
        for key in required_keys:
            if key not in seg_data.bbox_data:
                return False
            val = seg_data.bbox_data[key]
            if val is None or not isinstance(val, (int, float)):
                return False
            if key in ("width", "height") and val <= 0:
                return False
        
        # Validate time range
        if seg_data.end_time <= seg_data.start_time:
            return False
        
        return True
    
    async def _crop_segment(
        self,
        video_path: Path,
        seg_data: JBISegment,
        segment_index: int,
        job_id: UUID
    ) -> Path:
        """
        Crop video segment using FFmpeg (async subprocess).
        
        Returns path to cropped file.
        """
        output_path = Path(tempfile.gettempdir()) / f"stage1_segment_{segment_index}_{str(job_id)}.mp4"
        
        # Get bbox coordinates
        bbox = seg_data.bbox_data
        x = int(round(bbox["x"]))
        y = int(round(bbox["y"]))
        w = int(round(bbox["width"]))
        h = int(round(bbox["height"]))
        
        duration = seg_data.end_time - seg_data.start_time
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-ss", str(seg_data.start_time),
            "-t", str(duration),
            "-i", str(video_path),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",  # No audio for Stage 1
            str(output_path)
        ]
        
        # Use async subprocess instead of blocking subprocess.run
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=300  # 5 minute timeout for FFmpeg
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                raise ProcessingError("FFmpeg crop timed out after 5 minutes")
            
            if proc.returncode != 0:
                stderr_str = stderr.decode() if stderr else "Unknown error"
                raise ProcessingError(f"FFmpeg crop failed: {stderr_str}")
            
            # Validate output file exists and has content
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise ProcessingError("FFmpeg produced empty output file")
            
            return output_path
            
        except FileNotFoundError:
            raise ProcessingError("FFmpeg not found. Please install FFmpeg.")
    
    async def _cleanup_temp_video(self, video_path: Optional[Path]):
        """Clean up temporary video file."""
        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except OSError as e:
                logger.warning(f"Failed to cleanup temp file {video_path}: {e}")


# Global worker instance
detection_worker: Optional[DetectionWorker] = None


def get_detection_worker() -> DetectionWorker:
    """Get or create detection worker singleton."""
    global detection_worker
    if detection_worker is None:
        detection_worker = DetectionWorker()
    return detection_worker


async def run_detection_worker():
    """Entry point for running the worker."""
    worker = get_detection_worker()
    await worker.start()
