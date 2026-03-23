---
story_id: "2.4"
story_key: "2-4-detection-worker"
epic: 2
status: ready-for-dev
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.4: Detection Worker

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.4  
**Status:** ready-for-dev  
**Priority:** Critical (Foundation)  
**Estimated Effort:** Large (3-4 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.2: MinIO Storage Integration ✅
- Story 2.3: Video Upload API ✅

---

## Story Requirements

### User Story

As the system,  
I want to automatically detect SIBI gestures in uploaded videos,  
So that segments containing sign language can be identified for further processing.

### Business Context

This story implements the first stage of the video processing pipeline - the detection worker. The worker polls the PostgreSQL queue for jobs, downloads videos from MinIO, runs YOLO-based gesture detection, and stores detection results (bounding boxes, timestamps, confidence scores) in the database. This is the core ML inference component that drives the entire pipeline.

### Acceptance Criteria

**Given** a job exists in the `detection` queue with status "pending"  
**When** the Detection Worker polls the queue  
**Then** it dequeues the job and updates pipeline_jobs status to "DETECTING"  
**And** downloads the video from MinIO  
**And** processes the video frame-by-frame using YOLO  
**And** stores detection results in `pipeline_segments`  
**And** updates job status to "DETECTED" on success

**Given** a video has no detectable gestures  
**When** detection completes  
**Then** job status becomes "FAILED"  
**And** error_message indicates "No gestures detected in video"  
**And** a log entry is created in `pipeline_job_logs`

**Given** detection fails due to corrupt video  
**When** exception occurs during processing  
**Then** job status becomes "FAILED"  
**And** error details are logged  
**And** the queue job is retried up to 3 times with exponential backoff

**Given** detection is taking longer than 30 minutes  
**When** timeout occurs  
**Then** processing is terminated  
**And** job status becomes "FAILED"  
**And** error_message indicates "Processing timeout"

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - background worker)
   - **Service Layer**: `app/services/detection_worker.py` - Worker orchestration
   - **Repository Layer**: Uses existing `JobRepository`, new `SegmentRepository`
   - **Pipeline Layer**: Detection logic uses YOLO model from `app/services/detector.py`

2. **Worker Pattern**
   - Polls queue using `queue_service.dequeue("detection")`
   - Implements graceful shutdown on SIGTERM/SIGINT
   - Heartbeat/keepalive to prevent stale worker detection
   - Single-threaded processing (GPU memory constraint)

3. **Database Naming**
   - Table: `pipeline_segments` stores detection bounding boxes
   - Status transitions: DETECTING → DETECTED (or FAILED)
   - Logs: `pipeline_job_logs` for audit trail

4. **State Machine**
   - Input state: `QUEUED` (from queue job)
   - Processing state: `DETECTING`
   - Output states: `DETECTED` (success) or `FAILED` (error)

5. **Storage Patterns**
   - Downloads from: `jobs/{job_id}/original/{filename}` (MinIO)
   - Model weights loaded from local filesystem (cached)
   - Detection metadata stored in PostgreSQL (not MinIO)

6. **Queue Integration**
   - Polls: `detection` queue
   - On success: marks queue job completed
   - On failure: marks queue job failed (triggers retry)

### Technical Requirements

**Detection Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| confidence_threshold | 0.5 | Minimum confidence for detection |
| iou_threshold | 0.45 | NMS IoU threshold |
| frame_skip | 5 | Process every Nth frame (performance) |
| batch_size | 1 | Frames per batch (GPU memory) |
| timeout_seconds | 1800 | Max processing time (30 min) |

**Segment Schema:**
```python
{
    "job_id": UUID,
    "start_time": "00:00:05.000",  # HH:MM:SS.mmm
    "end_time": "00:00:10.500",
    "start_frame": 150,
    "end_frame": 315,
    "bbox_x": 120.5,      # Bounding box coordinates
    "bbox_y": 80.0,
    "bbox_width": 200.0,
    "bbox_height": 150.0,
    "confidence": 0.87    # Detection confidence
}
```

**Worker Loop:**
```python
while running:
    # 1. Poll queue
    queue_job = await queue_service.dequeue("detection")
    if not queue_job:
        await asyncio.sleep(poll_interval)
        continue
    
    # 2. Update job status
    await job_repo.update_status(job_id, "DETECTING")
    
    # 3. Download video from MinIO
    video_path = await download_video(job_id)
    
    # 4. Run detection
    segments = await detector.detect(video_path)
    
    # 5. Store results
    await segment_repo.create_many(segments)
    
    # 6. Update status
    await job_repo.update_status(job_id, "DETECTED")
    await queue_service.mark_completed(queue_job.id)
```

**Error Handling:**
| Error Type | Action | Retry |
|------------|--------|-------|
| Video download fails | Log, mark failed | Yes |
| Video corrupt/unreadable | Log, mark failed | No |
| No detections found | Log, mark failed | No |
| GPU OOM | Log, mark failed | Yes (with backoff) |
| Timeout (30min) | Log, mark failed | No |
| Model not loaded | Fatal, exit worker | N/A |

---

## Implementation Guide

### Phase 1: Create Segment Repository

#### Step 1.1: Create app/repositories/segment_repository.py

```python
"""Segment repository for detection results."""

from typing import List
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineSegment


class SegmentRepository:
    """Repository for pipeline segment operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_many(self, segments: List[PipelineSegment]) -> None:
        """Bulk insert segments."""
        for segment in segments:
            self.db.add(segment)
        await self.db.flush()
    
    async def get_by_job_id(self, job_id: UUID) -> List[PipelineSegment]:
        """Get all segments for a job."""
        result = await self.db.execute(
            select(PipelineSegment)
            .where(PipelineSegment.job_id == job_id)
            .order_by(PipelineSegment.start_frame)
        )
        return result.scalars().all()


def get_segment_repository(db: AsyncSession) -> SegmentRepository:
    return SegmentRepository(db)
```

### Phase 2: Create Detection Worker Service

#### Step 2.1: Create app/services/detection_worker.py

```python
"""Detection worker for processing videos from queue."""

import asyncio
import signal
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProcessingError
from app.core.logger import logger
from app.db.models.pipeline import PipelineJob, PipelineSegment, QueueJob
from app.db.session import get_db_session
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.minio_service import get_minio_service
from app.services.queue_service import queue_service


class DetectionWorker:
    """
    Background worker for gesture detection processing.
    
    Polls the detection queue, downloads videos, runs YOLO inference,
    and stores detection results.
    """
    
    def __init__(
        self,
        poll_interval: int = 5,
        timeout_seconds: int = 1800,
        confidence_threshold: float = 0.5
    ):
        self.poll_interval = poll_interval
        self.timeout_seconds = timeout_seconds
        self.confidence_threshold = confidence_threshold
        self.running = False
        self.minio_service = get_minio_service()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("DetectionWorker received shutdown signal")
        self.running = False
    
    async def start(self):
        """Start the worker loop."""
        logger.info("DetectionWorker starting...")
        self.running = True
        
        while self.running:
            try:
                # Poll for jobs
                queue_job = await queue_service.dequeue("detection")
                
                if queue_job:
                    await self._process_job(queue_job)
                else:
                    # No jobs available, wait before polling again
                    await asyncio.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                await asyncio.sleep(self.poll_interval)
        
        logger.info("DetectionWorker stopped")
    
    async def _process_job(self, queue_job: QueueJob):
        """Process a single detection job."""
        job_id = UUID(queue_job.payload["job_id"])
        logger.info(f"Processing detection job: {job_id}")
        
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
                
                # 4. Run detection (with timeout)
                segments = await asyncio.wait_for(
                    self._run_detection(job_id, video_path),
                    timeout=self.timeout_seconds
                )
                
                # 5. Check if any detections found
                if not segments:
                    raise ProcessingError("No gestures detected in video")
                
                # 6. Store segments
                await segment_repo.create_many(segments)
                
                # 7. Update job status to DETECTED
                await job_repo.update_status(job_id, "DETECTED")
                await queue_service.mark_completed(queue_job.id, db=db)
                
                logger.info(f"Detection completed for job {job_id}: {len(segments)} segments")
                
            except asyncio.TimeoutError:
                logger.error(f"Detection timeout for job {job_id}")
                await self._handle_failure(db, job_repo, queue_job, "Processing timeout")
                
            except ProcessingError as e:
                logger.error(f"Detection failed for job {job_id}: {e}")
                await self._handle_failure(db, job_repo, queue_job, str(e))
                
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job_id}")
                await self._handle_failure(db, job_repo, queue_job, f"Internal error: {e}")
                raise  # Re-raise to trigger retry
            
            finally:
                # Cleanup temp file
                await self._cleanup_temp_video(video_path)
    
    async def _download_video(self, job_id: UUID, object_name: str) -> Path:
        """Download video from MinIO to temporary file."""
        try:
            video_data = await self.minio_service.download_file(object_name)
            
            # Create temp file with proper extension
            suffix = Path(object_name).suffix or ".mp4"
            temp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            temp_file.write(video_data)
            temp_file.close()
            
            return Path(temp_file.name)
            
        except Exception as e:
            raise ProcessingError(f"Failed to download video: {e}")
    
    async def _run_detection(
        self,
        job_id: UUID,
        video_path: Path
    ) -> List[PipelineSegment]:
        """
        Run YOLO detection on video.
        
        Returns list of PipelineSegment objects.
        """
        # TODO: Integrate with existing detector service
        # For now, placeholder that returns empty list
        logger.info(f"Running detection on {video_path}")
        
        # This will be implemented to:
        # 1. Load YOLO model (cached)
        # 2. Process video frame by frame
        # 3. Apply NMS and filtering
        # 4. Convert detections to PipelineSegment objects
        
        return []
    
    async def _handle_failure(
        self,
        db: AsyncSession,
        job_repo: JobRepository,
        queue_job: QueueJob,
        error_message: str
    ):
        """Handle job failure - update status and mark queue job failed."""
        job_id = UUID(queue_job.payload["job_id"])
        await job_repo.update_status(job_id, "FAILED", error_message)
        await queue_service.mark_failed(queue_job, error_message, db=db)
    
    async def _cleanup_temp_video(self, video_path: Optional[Path]):
        """Clean up temporary video file."""
        if video_path and video_path.exists():
            try:
                video_path.unlink()
            except OSError as e:
                logger.warning(f"Failed to cleanup temp file {video_path}: {e}")


# Global worker instance
_detection_worker: Optional[DetectionWorker] = None


def get_detection_worker() -> DetectionWorker:
    """Get or create detection worker singleton."""
    global _detection_worker
    if _detection_worker is None:
        _detection_worker = DetectionWorker()
    return _detection_worker


async def run_detection_worker():
    """Entry point for running the worker."""
    worker = get_detection_worker()
    await worker.start()
```

### Phase 3: Add Worker Entry Point

#### Step 3.1: Create run_worker.py

```python
#!/usr/bin/env python
"""Entry point for running the detection worker."""

import asyncio
import sys

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.detection_worker import run_detection_worker


if __name__ == "__main__":
    try:
        asyncio.run(run_detection_worker())
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)
```

---

## Testing Strategy

### Unit Tests

1. **Worker Loop Tests**
   - Test dequeue and process flow
   - Test graceful shutdown on signal
   - Test poll interval behavior

2. **Processing Tests**
   - Test successful detection flow
   - Test no detections handling
   - Test timeout handling
   - Test download failure handling

3. **Error Handling Tests**
   - Test retry behavior
   - Test status updates on failure
   - Test cleanup on error

### Integration Tests

1. **End-to-End Test**
   - Submit job via upload API
   - Verify worker picks up job
   - Verify detection results stored
   - Verify status transitions

---

## Open Questions

1. **Detection Model**: Should we use the existing YOLOv8 model from `app/services/detector.py` or create a new wrapper?
2. **Frame Processing**: What frame sampling rate? (Currently: process every 5th frame)
3. **Segment Merging**: Should consecutive detections be merged into single segment?
4. **GPU Memory**: Single worker per GPU or support multiple workers with batching?

---

## References

- Architecture: `docs/architecture.md` - Pipeline State Machine
- Story 2.1: Database schema for `pipeline_segments`
- Story 2.2: MinIO download functionality
- Story 2.3: Queue service usage patterns
