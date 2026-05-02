"""
Base Worker Abstract Class.

Provides the foundation for all queue-based workers in the system.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import asyncio
import logging

from app.db.session import async_session
from app.db.models.pipeline import QueueJob
from app.services.queue_service import queue_service
from app.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


class BaseWorker(ABC):
    """
    Abstract base class for all queue workers.
    
    Implementations must define:
    - queue_name: The queue this worker processes
    - process(): The actual work method
    
    Example:
        class DetectionWorker(BaseWorker):
            queue_name = "detection"
            
            async def process(self, payload: dict) -> dict:
                job_id = payload["job_id"]
                result = await stage1_detection.run(job_id)
                return {"segments_detected": len(result.segments)}
    """
    
    queue_name: str = ""
    max_retries: int = 3
    retry_delay: int = 5  # seconds
    
    def __init__(self):
        if not self.queue_name:
            raise ValueError(f"{self.__class__.__name__} must define queue_name")
    
    async def run(self) -> None:
        """
        Main worker loop.
        
        Continuously polls the queue and processes jobs.
        This method runs indefinitely until interrupted.
        """
        logger.info(f"Starting {self.__class__.__name__} for queue: {self.queue_name}")
        
        # Cleanup zombie jobs left over from unexpected container crashes
        await self._cleanup_zombies()
        
        while True:
            try:
                job = await self._dequeue()
                if job:
                    await self._process_with_retry(job)
                else:
                    # No job available, wait before polling again
                    await asyncio.sleep(1)
            except Exception as e:
                logger.exception(f"Error in worker loop: {e}")
                await asyncio.sleep(5)  # Back off on error
                
    async def _cleanup_zombies(self) -> None:
        """
        Detects jobs stuck in 'processing' state (which means the worker crashed 
        while processing them) and marks them as failed.
        """
        try:
            async with async_session() as session:
                pipeline_job_ids = await queue_service.cleanup_zombies(
                    queue_name=self.queue_name,
                    db=session
                )
                
                if pipeline_job_ids:
                    logger.warning(f"Found {len(pipeline_job_ids)} zombie jobs in queue '{self.queue_name}'. Marking as FAILED.")
                    job_repo = JobRepository(session)
                    for job_id in pipeline_job_ids:
                        # Convert UUID to str for update_status
                        await job_repo.update_status(str(job_id), "FAILED")
                    
                await session.commit()
        except Exception as e:
            logger.exception(f"Failed to clean up zombie jobs: {e}")
    
    async def _dequeue(self) -> Optional[QueueJob]:
        """
        Atomically fetch the next pending job from the queue.
        
        Returns:
            QueueJob object or None if no jobs available
        """
        async with async_session() as session:
            job = await queue_service.dequeue(
                queue_name=self.queue_name,
                db=session
            )
            await session.commit()
            return job
    
    async def _process_with_retry(self, job: QueueJob) -> None:
        """
        Process a job with automatic retry logic.
        
        Args:
            job: The QueueJob from the queue
        """
        job_id = job.payload.get("job_id", "unknown") if job.payload else "unknown"
        attempts = 0
        
        while attempts < self.max_retries:
            try:
                logger.info(f"Processing job {job_id} (attempt {attempts + 1})")
                result = await self.process(job.payload)
                
                # Mark job as completed
                await self._mark_completed(job, result)
                logger.info(f"Job {job_id} completed successfully")
                return
                
            except Exception as e:
                attempts += 1
                logger.exception(f"Job {job_id} failed (attempt {attempts})")
                
                if attempts < self.max_retries:
                    logger.info(f"Retrying in {self.retry_delay} seconds...")
                    await asyncio.sleep(self.retry_delay)
                else:
                    logger.error(f"Job {job_id} failed after {self.max_retries} attempts")
                    await self._mark_failed(job, str(e))
    
    @abstractmethod
    async def process(self, payload: dict) -> dict:
        """
        Implement this method with the actual work logic.
        
        Args:
            payload: The job payload from the queue
            
        Returns:
            Dict with processing results
            
        Raises:
            Exception: If processing fails (triggers retry)
        """
        pass
    
    async def _mark_completed(self, job: QueueJob, result: dict) -> None:
        """Mark job as completed in queue."""
        async with async_session() as session:
            await queue_service.mark_completed(
                job_id=job.id,
                db=session
            )
            await session.commit()
    
    async def _mark_failed(self, job: QueueJob, error: str) -> None:
        """Mark job as failed in queue."""
        async with async_session() as session:
            # Attach job to session if not already attached
            if job not in session:
                job = await session.merge(job)
            await queue_service.mark_failed(
                job=job,
                error_message=error,
                db=session
            )
            await session.commit()
    
    async def is_job_cancelled(self, job_id: str) -> bool:
        """
        Check if a job has been cancelled.
        
        Args:
            job_id: Pipeline job ID
            
        Returns:
            True if job is cancelled, False otherwise
        """
        from uuid import UUID
        from app.repositories.job_repository import JobRepository
        
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return False
        
        async with async_session() as session:
            job_repo = JobRepository(session)
            return await job_repo.is_job_cancelled(job_uuid)
    
    async def check_cancellation(self, job_id: str, checkpoint: str = "") -> None:
        """
        Check for job cancellation and raise if cancelled.
        
        Call this at strategic checkpoints during long-running processing.
        
        Args:
            job_id: Pipeline job ID
            checkpoint: Name of the checkpoint (for logging)
            
        Raises:
            ProcessingError: If job was cancelled (permanent, won't retry)
        """
        if await self.is_job_cancelled(job_id):
            from app.core.exceptions import ProcessingError
            msg = f"Job {job_id} was cancelled"
            if checkpoint:
                msg += f" at checkpoint: {checkpoint}"
            raise ProcessingError(msg, permanent=True)
