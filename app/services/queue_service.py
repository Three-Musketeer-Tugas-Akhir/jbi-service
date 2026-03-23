"""Queue service for job queue management."""

from datetime import datetime, timedelta, timezone
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
        db: AsyncSession = None,
        priority: int = 0,
        delay_seconds: int = 0
    ) -> QueueJob:
        """
        Add a job to the queue.
        
        Args:
            queue_name: Target queue (e.g., "detection", "asr", "cropping")
            payload: Job payload data
            db: Database session (if None, creates new session)
            priority: Higher number = higher priority
            delay_seconds: Delay before job becomes available (must be >= 0)
            
        Returns:
            Created QueueJob
            
        Raises:
            ValueError: If delay_seconds is negative
        """
        if delay_seconds < 0:
            raise ValueError("delay_seconds must be non-negative")
        
        scheduled_at = datetime.now(timezone.utc)
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
        
        if db is not None:
            # Use provided session (for atomic transactions)
            db.add(job)
            await db.flush()
            await db.refresh(job)
            return job
        else:
            # Create new session (for standalone operations)
            async with get_db_session() as db:
                db.add(job)
                await db.commit()
                await db.refresh(job)
                return job
    
    async def dequeue(
        self,
        queue_name: str
    ) -> Optional[QueueJob]:
        """
        Fetch next available job from queue.
        
        Uses SELECT FOR UPDATE SKIP LOCKED for concurrent workers.
        
        Args:
            queue_name: Queue to fetch from
            
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
                    QueueJob.scheduled_at <= datetime.now(timezone.utc)
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
    
    async def mark_completed(
        self,
        job_id: UUID,
        db: AsyncSession = None
    ) -> None:
        """Mark job as completed."""
        now = datetime.now(timezone.utc)
        
        if db is not None:
            await db.execute(
                update(QueueJob)
                .where(QueueJob.id == job_id)
                .values(
                    status="completed",
                    processed_at=now
                )
            )
            await db.flush()
        else:
            async with get_db_session() as db:
                await db.execute(
                    update(QueueJob)
                    .where(QueueJob.id == job_id)
                    .values(
                        status="completed",
                        processed_at=now
                    )
                )
                await db.commit()
    
    async def mark_failed(
        self,
        job: QueueJob,
        error_message: str,
        retry_delay_seconds: int = 60,
        db: AsyncSession = None
    ) -> None:
        """
        Mark job as failed with retry scheduling.
        
        If attempts < max_attempts, reschedules with exponential backoff.
        
        Args:
            job: The QueueJob to mark as failed (must be attached to session)
            error_message: Error message to store
            retry_delay_seconds: Base delay for retry
            db: Database session (if None, creates new session)
        """
        now = datetime.now(timezone.utc)
        
        if job.attempts < job.max_attempts:
            # Reschedule with exponential backoff
            job.status = "pending"
            backoff_multiplier = 2 ** (job.attempts - 1) if job.attempts > 0 else 1
            job.scheduled_at = now + timedelta(
                seconds=retry_delay_seconds * backoff_multiplier
            )
        else:
            # Max attempts reached
            job.status = "failed"
        
        job.error_message = error_message
        job.processed_at = now
        
        if db is not None:
            await db.flush()
        else:
            async with get_db_session() as new_db:
                new_db.add(job)
                await new_db.commit()


# Global instance
queue_service = QueueService()
