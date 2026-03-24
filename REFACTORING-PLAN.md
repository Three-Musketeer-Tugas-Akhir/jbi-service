# JBI Service Comprehensive Refactoring Plan

**Objective:** Complete codebase restructuring to align 100% with `architecture.md`  
**Approach:** Controlled big-bang refactoring with validation gates  
**Estimated Duration:** 3-4 development days  
**Risk Level:** Medium (mitigated by phased execution)

---

## Table of Contents

1. [Pre-Refactoring Checklist](#1-pre-refactoring-checklist)
2. [Phase 1: Foundation & Safety](#2-phase-1-foundation--safety)
3. [Phase 2: Pipeline Layer Creation](#3-phase-2-pipeline-layer-creation)
4. [Phase 3: Worker Layer Restructuring](#4-phase-3-worker-layer-restructuring)
5. [Phase 4: Services Layer Cleanup](#5-phase-4-services-layer-cleanup)
6. [Phase 5: State Machine Unification](#6-phase-5-state-machine-unification)
7. [Phase 6: Legacy Cleanup](#6-phase-6-legacy-cleanup)
8. [Phase 7: Validation & Testing](#7-phase-7-validation--testing)
9. [Rollback Procedures](#8-rollback-procedures)
10. [File Migration Matrix](#9-file-migration-matrix)

---

## 1. Pre-Refactoring Checklist

### 1.1 Prerequisites

- [ ] All current tests passing (`pytest`)
- [ ] Database backup created
- [ ] Git commit with message: `PRE-REFACTOR: Save state before architecture migration`
- [ ] Team notification sent (if applicable)
- [ ] Feature freeze declared (no new stories during refactor)

### 1.2 Create Backup Branch

```bash
git checkout -b refactor/architecture-migration
git push -u origin refactor/architecture-migration
```

### 1.3 Document Current State

```bash
# Save file inventory
find app -name "*.py" -type f | sort > /tmp/pre-refactor-files.txt
wc -l app/**/*.py > /tmp/pre-refactor-line-counts.txt
```

---

## 2. Phase 1: Foundation & Safety (30 minutes)

### 2.1 Create New Directory Structure

```bash
# Create all target directories first
mkdir -p app/pipeline/{models,stages,utils}
mkdir -p app/workers/queue
touch app/pipeline/__init__.py
touch app/pipeline/models/__init__.py
touch app/pipeline/stages/__init__.py
touch app/pipeline/utils/__init__.py
touch app/workers/__init__.py
touch app/workers/queue/__init__.py
```

### 2.2 Create Compatibility Shim

Create `app/core/compat.py` for temporary backward compatibility during transition:

```python
"""
Compatibility layer for refactoring.

WARNING: This module is temporary and will be removed after refactoring.
It allows gradual migration of imports without breaking the application.
"""

# State machine compatibility - maps old enum to new constants
from app.db.models.pipeline import JobStatus as _JobStatus

# Legacy state names -> New state names
STATE_MAPPING = {
    "queued": _JobStatus.QUEUED,
    "processing": _JobStatus.DETECTING,  # Map to first processing state
    "completed": _JobStatus.READY_FOR_ANNOTATION,
    "failed": _JobStatus.FAILED,
    "cancelled": _JobStatus.CANCELLED,
}

# Reverse mapping for backward compatibility
REVERSE_STATE_MAPPING = {v: k for k, v in STATE_MAPPING.items()}


def migrate_state(old_state: str) -> str:
    """Convert legacy state name to new state constant."""
    return STATE_MAPPING.get(old_state.lower(), old_state)


def compat_state(new_state: str) -> str:
    """Convert new state constant to legacy state name (for过渡期)."""
    return REVERSE_STATE_MAPPING.get(new_state, new_state)
```

### 2.3 Create Base Worker Abstract Class

Create `app/workers/base.py`:

```python
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
```

**Validation Gate 1:**
```bash
# Verify structure created
ls -la app/pipeline/{models,stages,utils}
ls -la app/workers/

# Verify imports work
python -c "from app.workers.base import BaseWorker; print('✓ BaseWorker import OK')"
```

---

## 3. Phase 2: Pipeline Layer Creation (4 hours)

### 3.1 Move ML Model Wrappers

#### 3.1.1 Detector (YOLOv8)

**Source:** `app/services/detector.py`  
**Target:** `app/pipeline/models/detector.py`

```bash
# Move file
git mv app/services/detector.py app/pipeline/models/detector.py
```

**Update imports in moved file:**
```python
# OLD (in services/detector.py):
# from app.core.config import settings
# from app.models.job import JobStatus

# NEW (in pipeline/models/detector.py):
from app.core.config import settings
# Remove JobStatus import - pipeline is pure ML, no state machine
```

#### 3.1.2 Transcriber (Whisper)

**Source:** `app/services/transcriber.py`  
**Target:** `app/pipeline/models/transcriber.py`

```bash
git mv app/services/transcriber.py app/pipeline/models/transcriber.py
```

#### 3.1.3 Cropper (Video Processing)

**Source:** `app/services/cropper.py`  
**Target:** `app/pipeline/models/cropper.py`

```bash
git mv app/services/cropper.py app/pipeline/models/cropper.py
```

### 3.2 Create Pipeline Stages

#### 3.2.1 Stage 1: Detection

**Source:** `app/services/jbi_detector.py`  
**Target:** `app/pipeline/stages/stage1_detection.py`

```bash
git mv app/services/jbi_detector.py app/pipeline/stages/stage1_detection.py
```

**Refactor to pure function:**
```python
# OLD: May have had database calls or HTTP concerns
# NEW: Pure processing, returns results, no side effects

"""
Stage 1: JBI Detection Pipeline

Pure ML processing - no database access, no HTTP concerns.
"""

from typing import List, Dict
from app.pipeline.models.detector import detect_objects
from app.core.config import settings


class DetectionResult:
    """Result from detection stage."""
    
    def __init__(self, segments: List[Dict], confidence: float):
        self.segments = segments
        self.confidence = confidence


async def run_detection(
    video_path: str,
    progress_callback=None
) -> DetectionResult:
    """
    Run Stage 1 detection on video.
    
    Args:
        video_path: Path to input video file
        progress_callback: Optional callback(current, total)
        
    Returns:
        DetectionResult with segments and confidence scores
        
    Raises:
        DetectionError: If detection fails
    """
    # Pure ML processing - detect JBI regions
    detections = await detect_objects(video_path, progress_callback)
    
    # Convert to segments
    segments = _convert_detections_to_segments(detections)
    
    # Calculate overall confidence
    confidence = _calculate_confidence(detections)
    
    return DetectionResult(segments=segments, confidence=confidence)


def _convert_detections_to_segments(detections: List[Dict]) -> List[Dict]:
    """Convert raw detections to segment format."""
    # Implementation...
    pass


def _calculate_confidence(detections: List[Dict]) -> float:
    """Calculate overall detection confidence."""
    # Implementation...
    pass
```

#### 3.2.2 Stage 2: ASR

**Extract from:** `app/services/asr_worker.py`  
**Create:** `app/pipeline/stages/stage2_asr.py`

```python
# app/pipeline/stages/stage2_asr.py
"""
Stage 2: Automatic Speech Recognition Pipeline

Extracts audio from video and transcribes using Whisper.
"""

from typing import List
from app.pipeline.models.transcriber import transcribe_audio
from app.pipeline.utils.video import extract_audio


async def run_asr(
    video_path: str,
    segments: List[dict],
    progress_callback=None
) -> List[dict]:
    """
    Run ASR on video segments.
    
    Args:
        video_path: Original video path
        segments: List of detected segments from Stage 1
        progress_callback: Optional progress callback
        
    Returns:
        Segments with added 'asr_text', 'asr_confidence', 'asr_start', 'asr_end'
    """
    results = []
    
    for idx, segment in enumerate(segments):
        # Extract audio for this segment
        audio_path = await extract_audio(
            video_path,
            start_time=segment['jbi_start'],
            end_time=segment['jbi_end']
        )
        
        # Transcribe
        transcription = await transcribe_audio(audio_path)
        
        # Merge with segment data
        segment_with_asr = {
            **segment,
            'asr_text': transcription.text,
            'asr_confidence': transcription.confidence,
            'asr_start': transcription.start,
            'asr_end': transcription.end,
        }
        results.append(segment_with_asr)
        
        if progress_callback:
            progress_callback(idx + 1, len(segments))
    
    return results
```

#### 3.2.3 Stage 3: Cropping

**Create:** `app/pipeline/stages/stage3_cropping.py`

```python
# app/pipeline/stages/stage3_cropping.py
"""
Stage 3: Video Cropping Pipeline

Crops detected JBI segments from original video.
"""

from typing import List
from pathlib import Path
from app.pipeline.models.cropper import crop_video_segment
from app.core.config import settings


async def run_cropping(
    video_path: str,
    segments: List[dict],
    output_dir: str,
    progress_callback=None
) -> List[dict]:
    """
    Crop video segments with JBI buffer.
    
    Args:
        video_path: Original video path
        segments: Segments with ASR data
        output_dir: Directory for output files
        progress_callback: Optional progress callback
        
    Returns:
        Segments with added 'cropped_video_path'
    """
    results = []
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    for idx, segment in enumerate(segments):
        output_file = output_path / f"segment_{idx:06d}.mp4"
        
        # Crop with JBI buffer
        await crop_video_segment(
            input_path=video_path,
            output_path=str(output_file),
            bbox=segment['bbox_data'],
            start_time=segment['jbi_start'],
            end_time=segment['jbi_end'],
            buffer_seconds=settings.jbi_buffer_seconds
        )
        
        results.append({
            **segment,
            'cropped_video_path': str(output_file)
        })
        
        if progress_callback:
            progress_callback(idx + 1, len(segments))
    
    return results
```

### 3.3 Create Pipeline Utilities

#### 3.3.1 Video Utils

**Merge:** `app/services/audio_extractor.py` + `app/services/transcoder.py`  
**Create:** `app/pipeline/utils/video.py`

```python
# app/pipeline/utils/video.py
"""
Video processing utilities for pipeline.

FFmpeg operations - no database access, no business logic.
"""

import subprocess
from pathlib import Path
from typing import Optional


async def extract_audio(
    video_path: str,
    output_path: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    codec: str = "aac"
) -> str:
    """
    Extract audio from video file.
    
    Args:
        video_path: Input video file
        output_path: Output audio file (optional)
        start_time: Start time in seconds (optional)
        end_time: End time in seconds (optional)
        codec: Audio codec
        
    Returns:
        Path to extracted audio file
    """
    # Implementation using FFmpeg
    pass


async def transcode_video(
    input_path: str,
    output_path: str,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    crf: int = 16
) -> str:
    """
    Transcode video to standard format.
    
    Args:
        input_path: Input video file
        output_path: Output video file
        video_codec: Video codec
        audio_codec: Audio codec
        crf: Constant rate factor (quality)
        
    Returns:
        Path to transcoded video
    """
    # Implementation using FFmpeg
    pass


async def get_video_info(video_path: str) -> dict:
    """
    Get video metadata (duration, fps, resolution).
    
    Args:
        video_path: Path to video file
        
    Returns:
        Dict with duration, fps, width, height
    """
    # Implementation using FFprobe
    pass
```

#### 3.3.2 Storage Utils

**Extract from:** `app/services/minio_service.py`  
**Create:** `app/pipeline/utils/storage.py`

```python
# app/pipeline/utils/storage.py
"""
Storage utilities for pipeline.

S3/MinIO operations - pure I/O, no business logic.
"""

from typing import Optional
from app.services.minio_service import minio_service


async def download_video(video_key: str, local_path: str) -> str:
    """
    Download video from storage to local path.
    
    Args:
        video_key: S3/MinIO object key
        local_path: Local file path to save
        
    Returns:
        Local file path
    """
    await minio_service.download_file(video_key, local_path)
    return local_path


async def upload_segment(local_path: str, segment_key: str) -> str:
    """
    Upload processed segment to storage.
    
    Args:
        local_path: Local file path
        segment_key: S3/MinIO object key
        
    Returns:
        Storage URL
    """
    return await minio_service.upload_file(local_path, segment_key)


async def get_presigned_url(object_key: str, expiry: int = 3600) -> str:
    """Generate presigned URL for object access."""
    return await minio_service.get_presigned_url(object_key, expiry)
```

**Validation Gate 2:**
```bash
# Verify all pipeline files created
ls -la app/pipeline/models/
ls -la app/pipeline/stages/
ls -la app/pipeline/utils/

# Test imports
python -c "
from app.pipeline.models.detector import detect_objects
from app.pipeline.models.transcriber import transcribe_audio
from app.pipeline.models.cropper import crop_video_segment
from app.pipeline.stages.stage1_detection import run_detection
from app.pipeline.stages.stage2_asr import run_asr
from app.pipeline.stages.stage3_cropping import run_cropping
from app.pipeline.utils.video import extract_audio, transcode_video
from app.pipeline.utils.storage import download_video, upload_segment
print('✓ All pipeline imports OK')
"
```

---

## 4. Phase 3: Worker Layer Restructuring (2 hours)

### 4.1 Move Workers to Correct Location

#### 4.1.1 Detection Worker

**Source:** `app/services/detection_worker.py`  
**Target:** `app/workers/detection_worker.py`

```bash
git mv app/services/detection_worker.py app/workers/detection_worker.py
```

**Refactor to use BaseWorker:**
```python
# app/workers/detection_worker.py
"""
Detection Worker - Stage 1 Queue Consumer
"""

from app.workers.base import BaseWorker
from app.pipeline.stages.stage1_detection import run_detection
from app.services.job_service import job_service


class DetectionWorker(BaseWorker):
    """
    Worker that processes detection jobs from the queue.
    
    Consumes jobs from 'detection' queue, runs YOLO inference,
    and queues next stage (ASR).
    """
    
    queue_name = "detection"
    max_retries = 3
    
    async def process(self, payload: dict) -> dict:
        """
        Process a detection job.
        
        Args:
            payload: {"job_id": str, "video_path": str}
            
        Returns:
            {"segments_detected": int, "confidence": float}
        """
        job_id = payload["job_id"]
        video_path = payload["video_path"]
        
        # Update status to DETECTING
        await job_service.update_status(job_id, "DETECTING")
        
        # Run detection (pure ML, no DB)
        result = await run_detection(
            video_path=video_path,
            progress_callback=lambda c, t: self._report_progress(job_id, c, t)
        )
        
        # Store segments in database
        for segment in result.segments:
            await job_service.create_segment(job_id, segment)
        
        # Queue next stage
        await self._queue_next_stage(job_id, result.segments)
        
        return {
            "segments_detected": len(result.segments),
            "confidence": result.confidence
        }
    
    def _report_progress(self, job_id: str, current: int, total: int):
        """Report progress to job service."""
        # Async update via job_service
        pass
    
    async def _queue_next_stage(self, job_id: str, segments: list):
        """Queue ASR stage after detection."""
        from app.services.queue_service import queue_service
        await queue_service.enqueue("asr", {
            "job_id": job_id,
            "segment_count": len(segments)
        })
```

#### 4.1.2 ASR Worker

**Source:** `app/services/asr_worker.py`  
**Target:** `app/workers/asr_worker.py`

```bash
git mv app/services/asr_worker.py app/workers/asr_worker.py
```

**Refactor to use BaseWorker:**
```python
# app/workers/asr_worker.py
"""
ASR Worker - Stage 2 Queue Consumer
"""

from app.workers.base import BaseWorker
from app.pipeline.stages.stage2_asr import run_asr
from app.services.job_service import job_service


class ASRWorker(BaseWorker):
    """Worker that processes ASR jobs from the queue."""
    
    queue_name = "asr"
    max_retries = 3
    
    async def process(self, payload: dict) -> dict:
        """Process an ASR job."""
        job_id = payload["job_id"]
        
        # Get job details
        job = await job_service.get_job(job_id)
        segments = await job_service.get_segments(job_id)
        
        # Update status
        await job_service.update_status(job_id, "TRANSCRIBING")
        
        # Run ASR (pure ML)
        results = await run_asr(
            video_path=job.video_path,
            segments=segments,
            progress_callback=lambda c, t: self._report_progress(job_id, c, t)
        )
        
        # Update segments with ASR data
        for segment in results:
            await job_service.update_segment_asr(
                segment_id=segment["id"],
                asr_text=segment["asr_text"],
                asr_confidence=segment["asr_confidence"]
            )
        
        # Queue next stage
        await self._queue_next_stage(job_id)
        
        return {"segments_processed": len(results)}
    
    async def _queue_next_stage(self, job_id: str):
        """Queue cropping stage after ASR."""
        from app.services.queue_service import queue_service
        await queue_service.enqueue("cropping", {"job_id": job_id})
```

#### 4.1.3 Cropping Worker

**Create:** `app/workers/cropping_worker.py`

```python
# app/workers/cropping_worker.py
"""
Cropping Worker - Stage 3 Queue Consumer
"""

from app.workers.base import BaseWorker
from app.pipeline.stages.stage3_cropping import run_cropping
from app.services.job_service import job_service
from app.core.config import settings


class CroppingWorker(BaseWorker):
    """Worker that processes cropping jobs from the queue."""
    
    queue_name = "cropping"
    max_retries = 2  # Lower retries for resource-intensive operations
    
    async def process(self, payload: dict) -> dict:
        """Process a cropping job."""
        job_id = payload["job_id"]
        
        # Get job details
        job = await job_service.get_job(job_id)
        segments = await job_service.get_segments(job_id)
        
        # Update status
        await job_service.update_status(job_id, "CROPPING")
        
        # Run cropping (pure ML)
        output_dir = f"{settings.output_dir}/{job_id}"
        results = await run_cropping(
            video_path=job.video_path,
            segments=segments,
            output_dir=output_dir,
            progress_callback=lambda c, t: self._report_progress(job_id, c, t)
        )
        
        # Update segments with cropped paths
        for segment in results:
            await job_service.update_segment_cropped_path(
                segment_id=segment["id"],
                cropped_path=segment["cropped_video_path"]
            )
        
        # Mark job as complete
        await job_service.update_status(job_id, "READY_FOR_ANNOTATION")
        
        return {"segments_cropped": len(results)}
```

**Validation Gate 3:**
```bash
# Verify worker imports
python -c "
from app.workers.base import BaseWorker
from app.workers.detection_worker import DetectionWorker
from app.workers.asr_worker import ASRWorker
from app.workers.cropping_worker import CroppingWorker
print('✓ All worker imports OK')
"
```

---

## 5. Phase 4: Services Layer Cleanup (2 hours)

### 5.1 Update Service Imports

Now that files have moved, update all imports in services that reference the old locations.

#### 5.1.1 Update `app/services/job_service.py`

```python
# OLD imports (may have been):
# from app.services.detector import detect_objects
# from app.services.transcriber import transcribe_audio

# NEW imports:
from app.pipeline.stages.stage1_detection import run_detection
from app.pipeline.stages.stage2_asr import run_asr
from app.pipeline.stages.stage3_cropping import run_cropping

# Workers are now in app.workers, not app.services
# Remove any direct worker imports - services should use queue_service instead
```

#### 5.1.2 Update `app/services/cleanup.py`

```python
# Remove import of legacy job store
# OLD: from app.models.job_store import job_store
# NEW: Use app.repositories.job_repository instead
```

### 5.2 Remove ML Code from Services

The following files should now be DELETED (moved to pipeline):
- ~~`app/services/detector.py`~~ → `app/pipeline/models/detector.py`
- ~~`app/services/transcriber.py`~~ → `app/pipeline/models/transcriber.py`
- ~~`app/services/cropper.py`~~ → `app/pipeline/models/cropper.py`
- ~~`app/services/jbi_detector.py`~~ → `app/pipeline/stages/stage1_detection.py`
- ~~`app/services/audio_extractor.py`~~ → `app/pipeline/utils/video.py`
- ~~`app/services/transcoder.py`~~ → `app/pipeline/utils/video.py`
- ~~`app/services/asr_worker.py`~~ → `app/workers/asr_worker.py`
- ~~`app/services/detection_worker.py`~~ → `app/workers/detection_worker.py`

### 5.3 Verify Services are Pure Business Logic

After cleanup, `app/services/` should contain ONLY:
```
app/services/
├── __init__.py
├── auth_service.py          # Authentication business logic
├── job_service.py           # Job lifecycle orchestration
├── user_service.py          # User management
├── audit_service.py         # Audit logging
├── email_service.py         # Email sending
├── email_verification_service.py  # Email verification flow
├── password_reset_service.py      # Password reset flow
├── token_refresh_service.py       # Token refresh
├── queue_service.py         # Queue management (enqueue/dequeue)
├── cleanup.py               # Cleanup scheduler
├── scheduler.py             # Job scheduling
├── validator.py             # Input validation
├── minio_service.py         # S3/MinIO operations (or move to pipeline/utils/)
└── downloader.py            # HTTP download utility
```

**Validation Gate 4:**
```bash
# Verify no ML imports remain in services
grep -r "import detector\|import transcriber\|import cropper\|from.*detector import\|from.*transcriber import\|from.*cropper import" app/services/ || echo "✓ No ML imports in services"

# Verify services only import from pipeline stages (not models directly)
grep -r "from app.pipeline.models import" app/services/ || echo "✓ Services don't import pipeline models directly"
```

---

## 6. Phase 5: State Machine Unification (1 hour)

### 6.1 Update All Imports

Replace all occurrences of legacy state machine with new one:

```bash
# Find all files using old JobStatus
find app -name "*.py" -exec grep -l "from app.models.job import" {} \;

# Files to update:
# - app/workers/tasks.py
# - app/api/v1/jobs.py
# - app/services/cleanup.py
```

### 6.2 Update Import Statements

In each file:
```python
# OLD:
from app.models.job import JobStatus, is_terminal

# NEW:
from app.db.models.pipeline import JobStatus

# Update usage:
# OLD: if job.status == JobStatus.PROCESSING:
# NEW: if job.status == JobStatus.DETECTING:
```

### 6.3 Migration Mapping

| Old State | New State | Notes |
|-----------|-----------|-------|
| `queued` | `QUEUED` | Direct mapping |
| `processing` | `DETECTING` | First processing stage |
| `completed` | `READY_FOR_ANNOTATION` | Pipeline complete |
| `failed` | `FAILED` | Direct mapping |
| `cancelled` | `CANCELLED` | Direct mapping |

### 6.4 Update Helper Functions

```python
# OLD (in app/models/job.py):
def is_terminal(status: JobStatus) -> bool:
    return status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

# NEW (add to app/db/models/pipeline.py or app/services/job_service.py):
TERMINAL_STATES = {
    JobStatus.READY_FOR_ANNOTATION,
    JobStatus.FAILED,
    JobStatus.CANCELLED
}

def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATES
```

**Validation Gate 5:**
```bash
# Verify no old JobStatus imports remain
grep -r "from app.models.job import" app/ || echo "✓ No legacy JobStatus imports"

# Verify new imports are correct
grep -r "from app.db.models.pipeline import.*JobStatus" app/ | head -5
```

---

## 7. Phase 6: Legacy Cleanup (30 minutes)

### 7.1 Delete `app/models/` Folder

```bash
# Verify all imports have been migrated first
grep -r "from app.models" app/ || echo "No remaining imports from app.models"

# Delete folder
git rm -rf app/models/
```

### 7.2 Delete `app/utils/` Folder

```bash
# Verify no imports
grep -r "from app.utils import" app/ || echo "No remaining imports from app.utils"

# Delete folder
git rm -rf app/utils/
```

### 7.3 Remove Root `app/middleware.py`

```bash
# First, ensure all middleware is moved to app/middleware/ folder
cat app/middleware.py | head -20

# If empty or all code moved, delete
git rm app/middleware.py
```

### 7.4 Remove Compatibility Shim

```bash
# After all migrations are verified
git rm app/core/compat.py
```

**Validation Gate 6:**
```bash
# Verify folder structure
find app -type d | sort

# Should NOT see:
# - app/models
# - app/utils
```

---

## 8. Phase 7: Validation & Testing (2 hours)

### 8.1 Import Verification

```bash
# Test all major imports
python -c "
import sys
errors = []

try:
    from app.pipeline.models.detector import detect_objects
except Exception as e:
    errors.append(f'pipeline.models.detector: {e}')

try:
    from app.pipeline.stages.stage1_detection import run_detection
    from app.pipeline.stages.stage2_asr import run_asr
    from app.pipeline.stages.stage3_cropping import run_cropping
except Exception as e:
    errors.append(f'pipeline.stages: {e}')

try:
    from app.workers.base import BaseWorker
    from app.workers.detection_worker import DetectionWorker
    from app.workers.asr_worker import ASRWorker
    from app.workers.cropping_worker import CroppingWorker
except Exception as e:
    errors.append(f'workers: {e}')

try:
    from app.services.job_service import JobService
    from app.services.auth_service import AuthService
except Exception as e:
    errors.append(f'services: {e}')

try:
    from app.api.deps import get_current_user, require_role
except Exception as e:
    errors.append(f'api.deps: {e}')

if errors:
    print('IMPORT ERRORS:')
    for err in errors:
        print(f'  - {err}')
    sys.exit(1)
else:
    print('✓ All imports successful')
"
```

### 8.2 Unit Tests

```bash
# Run all tests
pytest tests/ -v

# If tests fail due to import errors, fix them
# Common issues:
# - Test files importing from old locations
# - Mock paths need updating
```

### 8.3 Application Startup Test

```bash
# Test FastAPI startup
python -c "
from app.main import app
print('✓ FastAPI app loads successfully')
print(f'Routes: {len(app.routes)}')
"
```

### 8.4 Integration Test

```bash
# Start the application
python run.py &
APP_PID=$!

# Wait for startup
sleep 3

# Test health endpoint
curl -s http://localhost:8000/api/v1/health | grep -q "status" && echo "✓ Health check OK"

# Kill application
kill $APP_PID
```

### 8.5 Final Verification Checklist

- [ ] All tests passing
- [ ] Application starts without import errors
- [ ] Health endpoint responds
- [ ] No `app/models/` folder exists
- [ ] No `app/utils/` folder exists
- [ ] `app/pipeline/` folder exists with models, stages, utils
- [ ] `app/workers/` has base.py and all workers
- [ ] `app/services/` has no ML code
- [ ] All imports use `app.db.models.pipeline.JobStatus`

---

## 9. Rollback Procedures

### 9.1 Quick Rollback

If critical issues are found:

```bash
# Reset to pre-refactor state
git checkout main
git branch -D refactor/architecture-migration

# Or restore from backup branch
git checkout pre-refactor-backup
```

### 9.2 Selective Rollback

If specific files have issues:

```bash
# Restore specific file from main
git checkout main -- app/services/detector.py

# Revert specific commit
git revert <commit-hash>
```

### 9.3 Database Rollback

If database schema changes were made:

```bash
# Restore from backup
pg_restore -d anotasi_db /path/to/backup.sql
```

---

## 10. File Migration Matrix

### Complete File Mapping

| Source File | Target File | Action | Status Check |
|-------------|-------------|--------|--------------|
| `app/services/detector.py` | `app/pipeline/models/detector.py` | Move | Import test |
| `app/services/transcriber.py` | `app/pipeline/models/transcriber.py` | Move | Import test |
| `app/services/cropper.py` | `app/pipeline/models/cropper.py` | Move | Import test |
| `app/services/jbi_detector.py` | `app/pipeline/stages/stage1_detection.py` | Move | Import test |
| `app/services/asr_worker.py` | `app/workers/asr_worker.py` | Move | Import test |
| `app/services/detection_worker.py` | `app/workers/detection_worker.py` | Move | Import test |
| `app/services/audio_extractor.py` | `app/pipeline/utils/video.py` | Merge | Import test |
| `app/services/transcoder.py` | `app/pipeline/utils/video.py` | Merge | Import test |
| `app/models/job.py` | — | Delete | No imports remain |
| `app/models/job_model.py` | — | Delete | No imports remain |
| `app/models/job_store.py` | — | Delete | No imports remain |
| `app/models/result_serializer.py` | `app/pipeline/utils/serializers.py` | Move (optional) | Import test |
| `app/models/__init__.py` | — | Delete | Folder deleted |
| `app/utils/__init__.py` | — | Delete | No imports remain |
| `app/middleware.py` (root) | `app/middleware/request_logging.py` | Move | Import test |
| — | `app/workers/base.py` | Create | Import test |
| — | `app/workers/cropping_worker.py` | Create | Import test |
| — | `app/pipeline/stages/stage2_asr.py` | Create | Import test |
| — | `app/pipeline/stages/stage3_cropping.py` | Create | Import test |

### Expected Final Structure

```
app/
├── api/
│   ├── deps.py
│   └── v1/
│       ├── admin.py
│       ├── auth.py
│       ├── health.py
│       ├── jobs.py
│       └── users.py
├── core/
│   ├── config.py
│   ├── exceptions.py
│   └── security.py
├── db/
│   ├── base.py
│   ├── models/
│   │   ├── auth.py
│   │   ├── pipeline.py
│   │   └── audit.py
│   └── session.py
├── middleware/
│   ├── __init__.py
│   ├── cors.py
│   ├── rate_limiter.py
│   └── request_logging.py
├── pipeline/
│   ├── __init__.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── cropper.py
│   │   ├── detector.py
│   │   └── transcriber.py
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── stage1_detection.py
│   │   ├── stage2_asr.py
│   │   └── stage3_cropping.py
│   └── utils/
│       ├── __init__.py
│       ├── storage.py
│       └── video.py
├── repositories/
│   ├── __init__.py
│   ├── audit_log_repository.py
│   ├── email_verification_repository.py
│   ├── job_repository.py
│   ├── password_reset_repository.py
│   ├── refresh_token_repository.py
│   ├── segment_repository.py
│   └── user_repository.py
├── schemas/
│   ├── annotation.py
│   ├── auth.py
│   └── job.py
├── services/
│   ├── __init__.py
│   ├── auth_service.py
│   ├── audit_service.py
│   ├── cleanup.py
│   ├── downloader.py
│   ├── email_service.py
│   ├── email_verification_service.py
│   ├── job_service.py
│   ├── minio_service.py
│   ├── password_reset_service.py
│   ├── queue_service.py
│   ├── scheduler.py
│   ├── token_refresh_service.py
│   ├── user_service.py
│   └── validator.py
├── workers/
│   ├── __init__.py
│   ├── base.py
│   ├── cropping_worker.py
│   ├── detection_worker.py
│   └── asr_worker.py
└── main.py
```

---

## Summary

### Timeline

| Phase | Duration | Cumulative |
|-------|----------|------------|
| Phase 1: Foundation | 30 min | 30 min |
| Phase 2: Pipeline | 4 hours | 4.5 hours |
| Phase 3: Workers | 2 hours | 6.5 hours |
| Phase 4: Services | 2 hours | 8.5 hours |
| Phase 5: State Machine | 1 hour | 9.5 hours |
| Phase 6: Cleanup | 30 min | 10 hours |
| Phase 7: Validation | 2 hours | 12 hours |
| **Total** | **~3-4 dev days** | |

### Success Criteria

- ✅ All 69 Python files in correct locations
- ✅ All imports resolve without errors
- ✅ All tests passing
- ✅ Application starts successfully
- ✅ No legacy `app/models/` or `app/utils/` folders
- ✅ `app/pipeline/` layer fully functional
- ✅ `app/workers/` using BaseWorker pattern
- ✅ Services layer contains only business logic

---

*Generated by Amelia (Developer Agent)*  
*Based on architecture: `jbi-service/_bmad-output/planning-artifacts/architecture.md`*
