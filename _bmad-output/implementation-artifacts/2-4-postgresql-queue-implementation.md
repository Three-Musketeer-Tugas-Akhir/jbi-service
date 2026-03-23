---
story_id: "2.4"
story_key: "2-4-postgresql-queue-implementation"
epic: 2
status: ready-for-dev
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.4: PostgreSQL Queue Implementation

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.4  
**Status:** ready-for-dev  
**Priority:** Critical (Foundation)  
**Estimated Effort:** Medium (2-3 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅

---

## Story Requirements

### User Story

As a developer,  
I want to implement a job queue using PostgreSQL,  
So that video processing stages can be executed asynchronously.

### Business Context

This story provides the foundational queue infrastructure for the video processing pipeline. The PostgreSQL-backed queue enables reliable, ACID-compliant job scheduling with support for priorities, delayed execution, and retry logic. While the schema was created in Story 2.1, this story implements the complete queue service API that workers will use to poll and process jobs.

### Acceptance Criteria

**Given** the queue table exists  
**When** I call `queue.enqueue("detection", {"job_id": "uuid"})`  
**Then** a new queue job is created with status "pending"  
**And** the job is scheduled for immediate processing

**Given** pending jobs exist in the queue  
**When** a worker calls `queue.dequeue("detection")`  
**Then** the highest priority pending job is returned  
**And** its status is updated to "processing"  
**And** the job is locked to prevent other workers from picking it up

**Given** a job fails during processing  
**When** the worker reports failure  
**Then** the job status is set to "failed"  
**And** attempts counter is incremented  
**And** if attempts < max_attempts, job is rescheduled with exponential backoff

**Given** a job completes successfully  
**When** the worker reports completion  
**Then** the job status is set to "completed"  
**And** processed_at timestamp is recorded

**Given** I want to check queue status  
**When** I query queue metrics  
**Then** I can see pending count, processing count, failed count per queue

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - service layer component)
   - **Service Layer**: `app/services/queue_service.py` - Queue operations
   - **Repository Layer**: Direct SQLAlchemy usage (queue is low-level infrastructure)
   - **Pipeline Layer**: Workers use queue service for job management

2. **Queue Patterns**
   - FIFO ordering within same priority level
   - Priority support: high (10), normal (5), low (0)
   - Row-level locking via `SELECT FOR UPDATE SKIP LOCKED`
   - Exponential backoff for retries: 5s, 15s, 45s

3. **Database Naming**
   - Table: `queue_jobs` (from Story 2.1 schema)
   - Status values: `pending`, `processing`, `completed`, `failed`
   - Queue names: lowercase with hyphens (e.g., "detection", "asr", "cropping")

4. **Error Handling**
   - Transient failures (network, timeout) → Retry with backoff
   - Permanent failures (validation, corruption) → Mark failed, no retry
   - Max attempts: 3 (configurable per job)

5. **Service Interface**
   ```python
   await queue_service.enqueue(queue_name, payload, priority=0, delay_seconds=0)
   job = await queue_service.dequeue(queue_name)
   await queue_service.mark_completed(job.id)
   await queue_service.mark_failed(job, error_message, retry_delay_seconds=60)
   ```

### Technical Requirements

**Queue Job Lifecycle:**
```
enqueue() → [pending] → dequeue() → [processing] → mark_completed() → [completed]
                                   ↓
                              mark_failed()
                                   ↓
                    [failed] ← max attempts reached
                    [pending] ← retry with backoff
```

**Enqueue Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| queue_name | str | required | Target queue (detection, asr, cropping) |
| payload | dict | required | Job data (must be JSON serializable) |
| priority | int | 0 | Higher = processed first (0-10 range) |
| delay_seconds | int | 0 | Delay before job becomes available |
| max_attempts | int | 3 | Maximum retry attempts |

**Dequeue Behavior:**
- Returns highest priority pending job (by priority DESC, created_at ASC)
- Uses `SELECT FOR UPDATE SKIP LOCKED` for atomic fetch
- Updates status to "processing" and increments attempts
- Returns None if no jobs available

**Retry Logic:**
| Attempt | Delay | Formula |
|---------|-------|---------|
| 1 | 5s | base_delay × 2^0 |
| 2 | 15s | base_delay × 2^1 |
| 3 | 45s | base_delay × 2^2 |

**Queue Metrics:**
```python
metrics = await queue_service.get_metrics()
# Returns:
{
    "detection": {"pending": 5, "processing": 2, "failed": 1, "completed": 100},
    "asr": {"pending": 3, "processing": 1, "failed": 0, "completed": 50}
}
```

---

## Implementation Guide

### Phase 1: Create Queue Service

The queue service was started in Story 2.3 but needs to be completed with all functionality.

#### Step 1.1: Complete app/services/queue_service.py

```python
"""Queue service for job queue management."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
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
            async with get_db_session() as db:
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


# Global instance
queue_service = QueueService()
```

### Phase 2: Create Queue Management API (Optional)

For admin monitoring of queue status:

```python
# app/api/v1/admin.py additions

@router.get("/admin/queues/metrics")
async def get_queue_metrics(
    current_user: User = Depends(require_admin())
):
    """Get metrics for all queues (admin only)."""
    metrics = await queue_service.get_metrics()
    return {"queues": metrics}

@router.post("/admin/queues/{queue_name}/cleanup")
async def cleanup_queue(
    queue_name: str,
    retention_days: int = 7,
    current_user: User = Depends(require_admin())
):
    """Clean up completed jobs from queue (admin only)."""
    deleted = await queue_service.cleanup_completed(retention_days)
    return {"deleted": deleted}
```

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/services/test_queue_service.py

class TestQueueService:
    """Test suite for queue service."""
    
    async def test_enqueue_creates_pending_job(self):
        """Test enqueue creates job with pending status."""
        
    async def test_dequeue_returns_highest_priority_job(self):
        """Test dequeue respects priority ordering."""
        
    async def test_dequeue_skips_locked_jobs(self):
        """Test dequeue uses SKIP LOCKED for concurrency."""
        
    async def test_mark_failed_reschedules_with_backoff(self):
        """Test retry scheduling with exponential backoff."""
        
    async def test_mark_failed_max_attempts_reached(self):
        """Test job marked failed when max attempts reached."""
        
    async def test_get_metrics_returns_counts(self):
        """Test metrics aggregation."""
```

### Integration Tests

```python
# tests/integration/test_queue.py

async def test_end_to_end_job_lifecycle():
    """Test full job lifecycle: enqueue → dequeue → complete."""
    
async def test_concurrent_workers_no_double_processing():
    """Test that concurrent workers don't process same job."""
    
async def test_retry_on_failure():
    """Test automatic retry with backoff."""
```

---

## Performance Considerations

1. **Indexing**: Ensure indexes on `(queue_name, status, priority, created_at)` for efficient dequeue queries
2. **Connection Pooling**: Use same connection pool as rest of application
3. **Polling Interval**: Workers should poll with reasonable interval (5s) to reduce DB load
4. **Cleanup**: Completed jobs should be cleaned up periodically to prevent table bloat

---

## Migration Path to Redis

The PostgreSQL queue provides ACID guarantees and is suitable for MVP. Future scaling may require Redis:

```python
# Future: Abstract queue interface
class QueueBackend(ABC):
    @abstractmethod
    async def enqueue(self, queue_name, payload, **kwargs): ...
    
    @abstractmethod
    async def dequeue(self, queue_name): ...

class PostgreSQLQueue(QueueBackend): ...
class RedisQueue(QueueBackend): ...
```

---

## References

- Architecture: `docs/architecture.md` - Pipeline State Machine
- Story 2.1: Database schema for `queue_jobs` table
- Story 2.3: Initial queue service implementation (partial)
