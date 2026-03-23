"""Queue service for job queue management."""

from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.db.models.pipeline import QueueJob


class QueueService:
    """Service for PostgreSQL-backed job queue."""
    
    async def enqueue(
        self,
        queue_name: str,
        payload: Dict[str, Any],
        priority: int = 0,
        delay_seconds: int = 0
    ) -> QueueJob:
        """
        Add a job to the queue.
        
        Args:
            queue_name: Target queue (e.g., "detection", "asr", "cropping")
            payload: Job payload data
            priority: Higher number = higher priority
            delay_seconds: Delay before job becomes available
            
        Returns:
            Created QueueJob
        """
        async with get_db_session() as db:
            scheduled_at = datetime.utcnow()
            if delay_seconds > 0:
                scheduled_at += timedelta(seconds=delay_seconds)
            
            job = QueueJob(
                queue_name=queue_name,
                payload=payload,
                priority=priority,
                status="pending",
                attempts=0,
                max_attempts=3,
                scheduled_at=scheduled_at
            )
            
            db.add(job)
            await db.commit()
            await db.refresh(job)
            
            return job
    
    async def dequeue(
        self,
        queue_name: str,
        max_attempts: int = 3
    ) -> Optional[QueueJob]:
        """
        Fetch next available job from queue.
        
        Uses SELECT FOR UPDATE SKIP LOCKED for concurrent workers.
        
        Args:
            queue_name: Queue to fetch from
            max_attempts: Maximum retry attempts
            
        Returns:
            QueueJob or None if no jobs available
        """
        async with get_db_session() as db:
            # Find next pending job
            result = await db.execute(
                select(QueueJob)
                .where(
                    QueueJob.queue_name == queue_name,
                    QueueJob.status == "pending",
                    QueueJob.attempts < QueueJob.max_attempts,
                    QueueJob.scheduled_at <= datetime.utcnow()
                )
                .order_by(QueueJob.priority.desc(), QueueJob.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            
            job = result.scalar_one_or_none()
            
            if job:
                job.status = "processing"
                job.attempts += 1
                await db.commit()
            
            return job
    
    async def mark_completed(self, job_id: UUID) -> None:
        """Mark job as completed."""
        async with get_db_session() as db:
            await db.execute(
                update(QueueJob)
                .where(QueueJob.id == job_id)
                .values(
                    status="completed",
                    processed_at=datetime.utcnow()
                )
            )
            await db.commit()
    
    async def mark_failed(
        self,
        job_id: UUID,
        error_message: str,
        retry_delay_seconds: int = 60
    ) -> None:
        """
        Mark job as failed with retry scheduling.
        
        If attempts < max_attempts, reschedules with exponential backoff.
        """
        async with get_db_session() as db:
            result = await db.execute(
                select(QueueJob).where(QueueJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            
            if job:
                if job.attempts < job.max_attempts:
                    # Reschedule with backoff
                    job.status = "pending"
                    job.scheduled_at = datetime.utcnow() + timedelta(
                        seconds=retry_delay_seconds * (2 ** (job.attempts - 1))
                    )
                else:
                    # Max attempts reached
                    job.status = "failed"
                
                job.error_message = error_message
                job.processed_at = datetime.utcnow()
                await db.commit()


# Global instance
queue_service = QueueService()
