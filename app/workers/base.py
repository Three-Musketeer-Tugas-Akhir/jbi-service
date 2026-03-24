"""
Base Worker Abstract Class.

Provides the foundation for all queue-based workers in the system.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
import asyncio
import logging

from app.db.session import async_session
from app.services.queue_service import queue_service

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
    
    async def _dequeue(self) -> Optional[Dict[str, Any]]:
        """
        Atomically fetch the next pending job from the queue.
        
        Returns:
            Job payload dict or None if no jobs available
        """
        async with async_session() as session:
            job = await queue_service.dequeue(
                session, 
                queue_name=self.queue_name
            )
            await session.commit()
            return job
    
    async def _process_with_retry(self, job: Dict[str, Any]) -> None:
        """
        Process a job with automatic retry logic.
        
        Args:
            job: The job payload from the queue
        """
        job_id = job.get("job_id", "unknown")
        attempts = 0
        
        while attempts < self.max_retries:
            try:
                logger.info(f"Processing job {job_id} (attempt {attempts + 1})")
                result = await self.process(job["payload"])
                
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
    
    async def _mark_completed(self, job: Dict[str, Any], result: dict) -> None:
        """Mark job as completed in queue."""
        async with async_session() as session:
            await queue_service.mark_completed(
                session, 
                job_id=job["id"],
                result=result
            )
            await session.commit()
    
    async def _mark_failed(self, job: Dict[str, Any], error: str) -> None:
        """Mark job as failed in queue."""
        async with async_session() as session:
            await queue_service.mark_failed(
                session,
                job_id=job["id"],
                error_message=error
            )
            await session.commit()
