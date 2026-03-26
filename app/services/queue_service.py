"""Queue service for job queue management."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.db.models.pipeline import QueueJob


class QueueService:
    """Service for PostgreSQL-backed job queue."""
    
    # Retry delays (exponential backoff base)
    DEFAULT_RETRY_DELAY = 5  # seconds
    
    async def enqueue(
        self,
        queue_name: str,
        payload: Dict[str, Any],
        db: AsyncSession = None,
        priority: int = 0,
        delay_seconds: int = 0,
        max_attempts: int = 3
    ) -> QueueJob:
        """
        Add a job to the queue.
        
        Args:
            queue_name: Target queue (e.g., "detection", "asr", "cropping")
            payload: Job payload data (must be JSON serializable)
            db: Database session (if None, creates new session)
            priority: Higher number = higher priority (0-10)
            delay_seconds: Delay before job becomes available
            max_attempts: Maximum retry attempts
            
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
            max_attempts=max_attempts,
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
            from app.db.session import async_session
            async with async_session() as db:
                db.add(job)
                await db.commit()
                await db.refresh(job)
                return job
    
    async def dequeue(
        self,
        queue_name: str,
        db: AsyncSession = None
    ) -> Optional[QueueJob]:
        """
        Fetch next available job from queue.
        
        Uses SELECT FOR UPDATE SKIP LOCKED for concurrent workers.
        Updates job status to "processing" and increments attempts.
        
        Args:
            queue_name: Queue to fetch from
            db: Database session (if None, creates new session)
            
        Returns:
            QueueJob or None if no jobs available
        """
        async def _dequeue(session: AsyncSession) -> Optional[QueueJob]:
            # Find next pending job with highest priority
            result = await session.execute(
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
                await session.flush()
            
            return job
        
        if db is not None:
            return await _dequeue(db)
        else:
            async with get_db_session() as db:
                job = await _dequeue(db)
                if job:
                    await db.commit()
                return job
    
    async def mark_completed(
        self,
        job_id: UUID,
        db: AsyncSession = None
    ) -> None:
        """
        Mark job as completed.
        
        Args:
            job_id: Queue job ID
            db: Database session (if None, creates new session)
        """
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
        retry_delay_seconds: int = None,
        db: AsyncSession = None
    ) -> bool:
        """
        Mark job as failed with retry scheduling.
        
        If attempts < max_attempts, reschedules with exponential backoff.
        Otherwise marks as permanently failed.
        
        Args:
            job: The QueueJob to mark as failed (must be attached to session)
            error_message: Error message to store
            retry_delay_seconds: Base delay for retry (default: 5s)
            db: Database session (if None, creates new session)
            
        Returns:
            True if job will be retried, False if max attempts reached
        """
        if retry_delay_seconds is None:
            retry_delay_seconds = self.DEFAULT_RETRY_DELAY
        
        now = datetime.now(timezone.utc)
        will_retry = job.attempts < job.max_attempts
        
        if will_retry:
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
        
        return will_retry
    
    async def get_metrics(
        self,
        queue_name: str = None
    ) -> Dict[str, Dict[str, int]]:
        """
        Get queue metrics (pending, processing, failed, completed counts).
        
        Args:
            queue_name: Specific queue to query (None = all queues)
            
        Returns:
            Dict mapping queue_name to status counts
        """
        async with get_db_session() as db:
            query = select(
                QueueJob.queue_name,
                QueueJob.status,
                func.count(QueueJob.id).label("count")
            ).group_by(QueueJob.queue_name, QueueJob.status)
            
            if queue_name:
                query = query.where(QueueJob.queue_name == queue_name)
            
            result = await db.execute(query)
            rows = result.all()
            
            # Build metrics dict
            metrics = {}
            for row in rows:
                q_name, status, count = row
                if q_name not in metrics:
                    metrics[q_name] = {"pending": 0, "processing": 0, "failed": 0, "completed": 0}
                metrics[q_name][status] = count
            
            return metrics
    
    async def cleanup_completed(
        self,
        retention_days: int = 7,
        db: AsyncSession = None
    ) -> int:
        """
        Clean up completed jobs older than retention period.
        
        Args:
            retention_days: Keep completed jobs for this many days
            db: Database session
            
        Returns:
            Number of jobs deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        
        async def _cleanup(session: AsyncSession) -> int:
            result = await session.execute(
                select(QueueJob).where(
                    QueueJob.status == "completed",
                    QueueJob.processed_at < cutoff
                )
            )
            jobs = result.scalars().all()
            
            for job in jobs:
                await session.delete(job)
            
            await session.flush()
            return len(jobs)
        
        if db is not None:
            return await _cleanup(db)
        else:
            async with get_db_session() as db:
                count = await _cleanup(db)
                await db.commit()
                return count
    
    async def cancel_job_queues(
        self,
        job_id: str,
        db: AsyncSession = None
    ) -> int:
        """
        Cancel all pending queue jobs for a pipeline job.
        
        Args:
            job_id: Pipeline job ID
            db: Database session (if None, creates new session)
            
        Returns:
            Number of queue jobs cancelled
        """
        async def _cancel(session: AsyncSession) -> int:
            result = await session.execute(
                update(QueueJob)
                .where(
                    QueueJob.payload["job_id"].astext == job_id,
                    QueueJob.status == "pending"
                )
                .values(status="cancelled")
            )
            await session.flush()
            return result.rowcount
        
        if db is not None:
            return await _cancel(db)
        else:
            async with get_db_session() as db:
                count = await _cancel(db)
                await db.commit()
                return count


# Global instance
queue_service = QueueService()
