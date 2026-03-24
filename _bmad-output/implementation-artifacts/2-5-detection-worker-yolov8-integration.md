---
story_id: "2.5"
story_key: "2-5-detection-worker-yolov8-integration"
epic: 2
status: done
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.5: Detection Worker - YOLOv8 Integration

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.5  
**Status:** done  
**Priority:** Critical (Core ML)  
**Estimated Effort:** Large (4-5 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.2: MinIO Storage Integration ✅
- Story 2.3: Video Upload API ✅
- Story 2.4: PostgreSQL Queue Implementation ✅

---

## Story Requirements

### User Story

As a system,  
I want to detect JBI (Juru Bahasa Isyarat / Sign Language Interpreter) regions in videos using YOLOv8,  
So that Juru Bahasa Isyarat (sign language interpreter) segments can be identified for transcription.

### Business Context

This story implements the first stage of the video processing pipeline - the Detection Worker. The worker polls the PostgreSQL queue for detection jobs, downloads videos from MinIO, runs YOLOv8-based gesture detection, performs Stage 1 cropping based on detected bounding boxes, and queues the next stage (ASR). This is the core ML inference component that drives the entire pipeline.

### Acceptance Criteria

**Given** a job is queued for detection stage  
**When** the DetectionWorker picks up the job  
**Then** the worker downloads the video from MinIO  
**And** runs YOLOv8 detection (from VideoDetector3.ipynb)  
**And** identifies all JBI regions with confidence scores

**Given** YOLOv8 detects JBI regions  
**When** detection is complete  
**Then** Stage 1 cropping is performed (bbox crop)  
**And** cropped segments are uploaded to MinIO  
**And** segment records are created in pipeline_segments table  
**And** job status is updated to "TRANSCRIBING"  
**And** next stage is queued for ASR processing

**Given** no JBI regions are detected  
**When** detection is complete  
**Then** job status is updated to "FAILED"  
**And** error_message: "No JBI regions detected in video"  
**And** user is notified via API

**Given** YOLOv8 model is not available  
**When** attempting detection  
**Then** error is caught and job is retried (max 3 attempts)  
**And** after max retries, status is FAILED with error details

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - background worker)
   - **Service Layer**: `app/services/detection_worker.py` - Worker orchestration
   - **Repository Layer**: `JobRepository`, `SegmentRepository`
   - **Pipeline Layer**: `app/services/detector.py` - YOLOv8 detection logic

2. **Worker Pattern**
   - Polls queue using `queue_service.dequeue("detection")`
   - Implements graceful shutdown on SIGTERM/SIGINT
   - Heartbeat/keepalive to prevent stale worker detection
   - Single-threaded processing (GPU memory constraint)

3. **Database Naming**
   - Table: `pipeline_segments` stores detection bounding boxes
   - Status transitions: DETECTING → TRANSCRIBING (or FAILED)
   - Logs: `pipeline_job_logs` for audit trail

4. **State Machine**
   - Input state: `QUEUED` (pipeline_jobs) + pending (queue_jobs)
   - Processing state: `DETECTING`
   - Output states: `TRANSCRIBING` (success) or `FAILED` (error)

5. **Storage Patterns**
   - Downloads from: `jobs/{job_id}/original/{filename}` (MinIO)
   - Stage 1 uploads to: `jobs/{job_id}/stage1/segment_{index}.mp4`
   - Model weights: Local filesystem (cached singleton)

6. **Queue Integration**
   - Polls: `detection` queue
   - On success: marks queue job completed, enqueues `asr` stage
   - On failure: marks queue job failed (triggers retry)

### Technical Requirements

**Detection Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| confidence_threshold | 0.5 | Minimum confidence for detection |
| iou_threshold | 0.45 | NMS IoU threshold |
| frame_skip | 5 | Process every Nth frame (performance) |
| min_segment_duration | 5.0 | Minimum segment duration in seconds |
| batch_size | 1 | Frames per batch (GPU memory) |
| timeout_seconds | 1800 | Max processing time (30 min) |

**Segment Schema (Stage 1):**
```python
{
    "job_id": UUID,
    "segment_index": 0,
    "bbox_data": {
        "x": 120.5,
        "y": 80.0,
        "width": 200.0,
        "height": 150.0,
        "confidence": 0.87
    },
    "start_frame": 150,
    "end_frame": 315,
    "status": "DETECTED"
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
    
    # 4. Run YOLOv8 detection
    detections = await detector.detect(video_path)
    
    # 5. Check for detections
    if not detections:
        raise ProcessingError("No JBI regions detected")
    
    # 6. Stage 1 cropping
    segments = await crop_segments(video_path, detections)
    
    # 7. Upload to MinIO
    await upload_stage1_segments(job_id, segments)
    
    # 8. Store segment records
    await segment_repo.create_many(segments)
    
    # 9. Update status and queue next stage
    await job_repo.update_status(job_id, "TRANSCRIBING")
    await queue_service.enqueue("asr", {"job_id": str(job_id)})
    await queue_service.mark_completed(queue_job.id)
```

**Error Handling:**
| Error Type | Action | Retry |
|------------|--------|-------|
| Video download fails | Log, mark failed | Yes |
| Video corrupt/unreadable | Log, mark failed | No |
| No detections found | Log, mark failed | No |
| GPU OOM | Log, mark failed | Yes (with backoff) |
| Model not loaded | Fatal, exit worker | N/A |
| Timeout (30min) | Log, mark failed | No |

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
            .order_by(PipelineSegment.segment_index)
        )
        return result.scalars().all()


def get_segment_repository(db: AsyncSession) -> SegmentRepository:
    return SegmentRepository(db)
```

### Phase 2: Create Detector Service

#### Step 2.1: Create app/services/detector.py

```python
"""YOLOv8-based JBI detection service."""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional
import tempfile

import cv2
import numpy as np
from ultralytics import YOLO

from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import ProcessingError


class DetectionResult:
    """Result from YOLOv8 detection."""
    
    def __init__(
        self,
        frame_number: int,
        timestamp: float,
        bbox: Dict[str, float],  # x, y, width, height
        confidence: float
    ):
        self.frame_number = frame_number
        self.timestamp = timestamp
        self.bbox = bbox
        self.confidence = confidence


class DetectorService:
    """
    YOLOv8-based JBI (Juru Bahasa Isyarat) detector.
    
    Follows implementation from VideoDetector3.ipynb exactly.
    Loads model once and reuses (singleton pattern).
    """
    
    _instance = None
    _model = None
    _model_path = None
    
    # Detection parameters
    CONFIDENCE_THRESHOLD = 0.5
    IOU_THRESHOLD = 0.45
    FRAME_SKIP = 5
    MIN_SEGMENT_DURATION = 5.0  # seconds
    
    def __new__(cls):
        """Singleton pattern for model reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize detector (model loaded lazily)."""
        if self._model_path is None:
            # Default model path - should be configurable
            self._model_path = settings.yolo_model_path or "model_weights/yolov8s.pt"
    
    def _load_model(self) -> YOLO:
        """Load YOLOv8 model (cached)."""
        if self._model is None:
            logger.info(f"Loading YOLOv8 model from {self._model_path}")
            try:
                self._model = YOLO(self._model_path)
                logger.info("YOLOv8 model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load YOLOv8 model: {e}")
                raise ProcessingError(f"Model loading failed: {e}")
        return self._model
    
    async def detect(
        self,
        video_path: Path,
        confidence_threshold: float = None,
        frame_skip: int = None
    ) -> List[DetectionResult]:
        """
        Detect JBI (Juru Bahasa Isyarat) regions in video.
        
        Args:
            video_path: Path to video file
            confidence_threshold: Minimum confidence (default: 0.5)
            frame_skip: Process every Nth frame (default: 5)
            
        Returns:
            List of DetectionResult objects
            
        Raises:
            ProcessingError: If detection fails
        """
        confidence_threshold = confidence_threshold or self.CONFIDENCE_THRESHOLD
        frame_skip = frame_skip or self.FRAME_SKIP
        
        model = self._load_model()
        
        # Open video
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            raise ProcessingError(f"Cannot open video: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        detections = []
        frame_number = 0
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                # Process every Nth frame
                if frame_number % frame_skip == 0:
                    timestamp = frame_number / fps
                    
                    # Run YOLOv8 inference
                    results = model(frame, verbose=False)
                    
                    # Parse detections
                    for result in results:
                        boxes = result.boxes
                        for box in boxes:
                            confidence = float(box.conf[0])
                            if confidence >= confidence_threshold:
                                # Get bounding box coordinates
                                x1, y1, x2, y2 = box.xyxy[0].tolist()
                                
                                detection = DetectionResult(
                                    frame_number=frame_number,
                                    timestamp=timestamp,
                                    bbox={
                                        "x": x1,
                                        "y": y1,
                                        "width": x2 - x1,
                                        "height": y2 - y1
                                    },
                                    confidence=confidence
                                )
                                detections.append(detection)
                
                frame_number += 1
                
        finally:
            cap.release()
        
        logger.info(f"Detected {len(detections)} regions in {video_path}")
        return detections
    
    def merge_detections(
        self,
        detections: List[DetectionResult],
        min_segment_duration: float = None
    ) -> List[Dict[str, Any]]:
        """
        Merge consecutive detections into segments.
        
        Args:
            detections: List of DetectionResult
            min_segment_duration: Minimum segment duration in seconds
            
        Returns:
            List of merged segments with start/end timestamps
        """
        min_segment_duration = min_segment_duration or self.MIN_SEGMENT_DURATION
        
        if not detections:
            return []
        
        # Sort by timestamp
        sorted_detections = sorted(detections, key=lambda d: d.timestamp)
        
        # Group consecutive detections into segments
        segments = []
        current_segment = {
            "start_frame": sorted_detections[0].frame_number,
            "end_frame": sorted_detections[0].frame_number,
            "start_time": sorted_detections[0].timestamp,
            "end_time": sorted_detections[0].timestamp,
            "bbox_data": sorted_detections[0].bbox,
            "confidence": sorted_detections[0].confidence
        }
        
        for detection in sorted_detections[1:]:
            # If gap is small (< 1 second), extend current segment
            if detection.timestamp - current_segment["end_time"] < 1.0:
                current_segment["end_frame"] = detection.frame_number
                current_segment["end_time"] = detection.timestamp
                # Update bbox to average or most confident
                if detection.confidence > current_segment["confidence"]:
                    current_segment["bbox_data"] = detection.bbox
                    current_segment["confidence"] = detection.confidence
            else:
                # Start new segment
                duration = current_segment["end_time"] - current_segment["start_time"]
                if duration >= min_segment_duration:
                    segments.append(current_segment)
                
                current_segment = {
                    "start_frame": detection.frame_number,
                    "end_frame": detection.frame_number,
                    "start_time": detection.timestamp,
                    "end_time": detection.timestamp,
                    "bbox_data": detection.bbox,
                    "confidence": detection.confidence
                }
        
        # Add final segment
        duration = current_segment["end_time"] - current_segment["start_time"]
        if duration >= min_segment_duration:
            segments.append(current_segment)
        
        return segments


# Global singleton
detector_service = DetectorService()


def get_detector_service() -> DetectorService:
    """Get detector service singleton."""
    return detector_service
```

### Phase 3: Create Detection Worker

#### Step 3.1: Create app/services/detection_worker.py

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
from app.services.detector import get_detector_service


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
        self.minio_service = get_minio_service()
        self.detector = get_detector_service()
        
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
                
                # 4. Run YOLOv8 detection (with timeout)
                detections = await asyncio.wait_for(
                    self.detector.detect(video_path),
                    timeout=self.timeout_seconds
                )
                
                # 5. Check if any detections found
                if not detections:
                    raise ProcessingError("No JBI regions detected in video")
                
                # 6. Merge detections into segments
                segments_data = self.detector.merge_detections(detections)
                
                if not segments_data:
                    raise ProcessingError("No valid segments after merging (all too short)")
                
                # 7. Stage 1 cropping and upload
                segments = await self._process_segments(
                    db, job_id, video_path, segments_data
                )
                
                # 8. Store segment records
                await segment_repo.create_many(segments)
                
                # 9. Update job status and queue ASR stage
                await job_repo.update_status(job_id, "TRANSCRIBING")
                await queue_service.enqueue(
                    "asr",
                    {"job_id": str(job_id)},
                    db=db
                )
                await queue_service.mark_completed(queue_job.id, db=db)
                
                logger.info(
                    f"Detection completed for job {job_id}: "
                    f"{len(segments)} segments"
                )
                
            except asyncio.TimeoutError:
                logger.error(f"Detection timeout for job {job_id}")
                await self._handle_failure(db, job_repo, queue_job, "Processing timeout")
                
            except ProcessingError as e:
                logger.error(f"Detection failed for job {job_id}: {e}")
                await self._handle_failure(db, job_repo, queue_job, str(e))
                
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job_id}")
                await self._handle_failure(
                    db, job_repo, queue_job, f"Internal error: {e}"
                )
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
            temp_file = tempfile.NamedTemporaryFile(
                suffix=suffix,
                delete=False,
                prefix=f"detection_{job_id}_"
            )
            temp_file.write(video_data)
            temp_file.close()
            
            return Path(temp_file.name)
            
        except Exception as e:
            raise ProcessingError(f"Failed to download video: {e}")
    
    async def _process_segments(
        self,
        db: AsyncSession,
        job_id: UUID,
        video_path: Path,
        segments_data: list
    ) -> list:
        """
        Crop Stage 1 segments and upload to MinIO.
        
        Returns list of PipelineSegment objects.
        """
        import cv2
        
        segments = []
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        
        for idx, seg_data in enumerate(segments_data):
            # Create segment record
            segment = PipelineSegment(
                job_id=job_id,
                segment_index=idx,
                bbox_data=seg_data["bbox_data"],
                status="DETECTED"
            )
            
            # Stage 1 cropping using FFmpeg
            cropped_path = await self._crop_segment(
                video_path, seg_data, idx
            )
            
            # Upload to MinIO
            object_name = f"jobs/{job_id}/stage1/segment_{idx}.mp4"
            with open(cropped_path, "rb") as f:
                await self.minio_service.upload_file(
                    file_data=f.read(),
                    object_name=object_name,
                    content_type="video/mp4"
                )
            
            segment.cropped_video_path = object_name
            segments.append(segment)
            
            # Cleanup temp cropped file
            cropped_path.unlink(missing_ok=True)
        
        return segments
    
    async def _crop_segment(
        self,
        video_path: Path,
        seg_data: dict,
        segment_index: int
    ) -> Path:
        """
        Crop video segment using FFmpeg.
        
        Returns path to cropped file.
        """
        import subprocess
        
        output_path = Path(tempfile.gettempdir()) / f"stage1_segment_{segment_index}.mp4"
        
        # Get bbox coordinates
        bbox = seg_data["bbox_data"]
        x, y = int(bbox["x"]), int(bbox["y"])
        w, h = int(bbox["width"]), int(bbox["height"])
        
        # FFmpeg crop filter
        start_time = seg_data["start_time"]
        duration = seg_data["end_time"] - seg_data["start_time"]
        
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output
            "-ss", str(start_time),
            "-t", str(duration),
            "-i", str(video_path),
            "-vf", f"crop={w}:{h}:{x}:{y}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-an",  # No audio for Stage 1
            str(output_path)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            raise ProcessingError(f"FFmpeg crop failed: {result.stderr}")
        
        return output_path
    
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
```

### Phase 4: Create Worker Entry Point

#### Step 4.1: Create run_detection_worker.py

```python
#!/usr/bin/env python
"""Entry point for running the detection worker."""

import asyncio
import sys
from pathlib import Path

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

```python
# tests/unit/services/test_detector.py

class TestDetectorService:
    """Test suite for YOLOv8 detector."""
    
    def test_singleton_pattern(self):
        """Test detector is singleton."""
        
    async def test_detect_returns_detections(self):
        """Test detect returns list of DetectionResult."""
        
    async def test_detect_respects_confidence_threshold(self):
        """Test low confidence detections are filtered."""
        
    async def test_merge_detections_creates_segments(self):
        """Test merging consecutive detections."""
        
    async def test_merge_detections_respects_min_duration(self):
        """Test short segments are filtered."""


# tests/unit/services/test_detection_worker.py

class TestDetectionWorker:
    """Test suite for detection worker."""
    
    async def test_process_job_success(self):
        """Test successful job processing flow."""
        
    async def test_process_job_no_detections(self):
        """Test handling of no detections."""
        
    async def test_process_job_download_failure(self):
        """Test handling of download failure."""
        
    async def test_process_job_timeout(self):
        """Test handling of processing timeout."""
```

### Integration Tests

```python
# tests/integration/test_detection_pipeline.py

async def test_end_to_end_detection():
    """
    Test full flow:
    1. Upload video
    2. Queue detection job
    3. Worker processes
    4. Segments created
    5. ASR job queued
    """
```

---

## Dependencies

**Python Packages:**
- `ultralytics>=8.0.0` - YOLOv8
- `opencv-python>=4.8.0` - Video processing
- `numpy>=1.24.0` - Array operations

**System Packages:**
- `ffmpeg` - Video cropping

**Model Files:**
- YOLOv8 weights file (configured via `settings.yolo_model_path`)

---

## Open Questions

1. **Model Path**: Should the YOLOv8 model path be configurable per environment?
2. **GPU Memory**: Single worker per GPU or support multiple with batching?
3. **Segment Merging**: Should we merge overlapping detections from same frame?
4. **FFmpeg Quality**: What CRF/preset values for Stage 1 cropping?

---

## References

- VideoDetector3.ipynb - Original YOLOv8 implementation
- Architecture: `docs/architecture.md` - Pipeline State Machine
- Story 2.1: Database schema for `pipeline_segments`
- Story 2.2: MinIO download/upload functionality
- Story 2.4: Queue service usage patterns
