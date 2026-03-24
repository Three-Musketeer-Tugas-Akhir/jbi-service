---
story_id: "2.7"
story_key: "2-7-cropping-worker-jbi-buffer"
epic: 2
title: "Cropping Worker - JBI Buffer"
status: ready-for-dev
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 2.7: Cropping Worker - JBI Buffer

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.7  
**Status:** ready-for-dev  
**Priority:** Critical (Core ML)  
**Estimated Effort:** Large (3-4 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.2: MinIO Storage Integration ✅
- Story 2.4: PostgreSQL Queue Implementation ✅
- Story 2.5: Detection Worker - YOLOv8 Integration ✅
- Story 2.6: ASR Worker - faster-whisper Integration ✅

---

## Story Requirements

### User Story

As a system,  
I want to re-crop segments based on ASR timestamps with JBI buffer,  
So that final clips include full sign language context.

### Business Context

This story implements **Stage 2 cropping** - the third and final stage of the video processing pipeline. After the Detection Worker identifies JBI regions (Stage 1 cropping based on bounding boxes) and the ASR Worker transcribes audio with timestamps, the Cropping Worker performs **timestamp-based re-cropping** with a configurable JBI buffer.

The JBI buffer ensures sign language context is preserved by extending the clip 2 seconds before the ASR start and 2 seconds after the ASR end. This captures the full sign language expression that may extend beyond spoken words.

Key responsibilities:
- Calculate JBI time range from ASR timestamps with ±2s buffer
- Re-crop video segments from Stage 1 cropped clips
- Upload final Stage 2 cropped clips to MinIO
- Mark job as READY_FOR_ANNOTATION when complete

### Acceptance Criteria

**Given** ASR transcription is complete for all segments  
**When** the CroppingWorker picks up the job  
**Then** for each segment, calculate JBI time range:
  - jbi_start = max(0, asr_start - 2)
  - jbi_end = min(video_duration, asr_end + 2)

**Given** JBI time ranges are calculated  
**When** re-cropping is performed  
**Then** FFmpeg extracts the exact time range from original cropped clip  
**And** final cropped clips are uploaded to MinIO  
**And** jbi_start and jbi_end are saved to pipeline_segments

**Given** all segments are processed  
**When** cropping is complete  
**Then** job status is updated to "READY_FOR_ANNOTATION"  
**And** annotation queue entry is created for annotators

**Given** a segment's calculated duration is < 3 seconds  
**When** cropping is performed  
**Then** adjacent segments may be merged (configurable)  
**And** warning is logged for very short segments

**Given** FFmpeg fails to crop a segment  
**When** error occurs  
**Then** the specific segment is marked as failed  
**And** other segments continue processing  
**And** job partially completes with error details

---

## Developer Context

### Architecture Alignment

This story follows the **4-layer architecture** established in the refactoring:

```
app/pipeline/stages/stage2_cropping.py  (Pure ML processing)
app/workers/cropping_worker.py          (Queue consumer)
app/services/job_service.py             (Business logic)
app/api/v1/jobs.py                      (HTTP endpoints)
```

**Key Pattern:** The CroppingWorker extends `BaseWorker` and calls `run_stage2_cropping()` from the pipeline layer. This maintains clean separation between ML processing and business orchestration.

### Technical Requirements

1. **JBI Buffer Calculation:**
   ```python
   jbi_start = max(0, asr_start - JBI_BUFFER_SECONDS)
   jbi_end = min(video_duration, asr_end + JBI_BUFFER_SECONDS)
   ```
   Default JBI_BUFFER_SECONDS = 2.0 (configurable)

2. **Segment Schema:**
   ```python
   {
     "segment_index": int,
     "asr_start": float,      # From ASR stage
     "asr_end": float,        # From ASR stage
     "jbi_start": float,      # Calculated: max(0, asr_start - 2)
     "jbi_end": float,        # Calculated: min(duration, asr_end + 2)
     "stage1_video_path": str,  # Source video (bbox cropped)
     "stage2_video_path": str,  # Output video (timestamp cropped)
   }
   ```

3. **Worker Loop Pattern:**
   ```python
   class CroppingWorker(BaseWorker):
       queue_name = "cropping"
       max_retries = 2
       
       async def process(self, payload: dict) -> dict:
           # 1. Get segments with ASR data from DB
           # 2. For each segment:
           #    - Calculate JBI time range
           #    - Re-crop from Stage 1 video using FFmpeg
           #    - Upload Stage 2 video to MinIO
           #    - Update segment record with jbi_start, jbi_end, stage2_video_path
           # 3. Update job status to READY_FOR_ANNOTATION
   ```

4. **Error Handling:**
   - **Permanent errors:** Invalid video codec, corrupt files (no retry)
   - **Retryable errors:** GPU OOM, network timeout (max 2 retries)
   - **Partial failure:** Individual segment failures don't fail entire job

### Files to Create/Modify

**NEW Files:**
- `app/pipeline/stages/stage2_cropping.py` - Stage 2 cropping logic (timestamp-based)
- `app/workers/cropping_worker.py` - Queue consumer for cropping stage

**MODIFY Files:**
- `app/workers/asr_worker.py` - Add queueing of cropping stage after ASR
- `app/services/job_service.py` - Add methods: `get_segments_with_asr()`, `update_segment_cropping()`
- `app/db/models/pipeline.py` - Ensure PipelineSegment has jbi_start, jbi_end fields

---

## Implementation Guide

### Phase 1: Create Pipeline Stage (stage2_cropping.py)

Create `app/pipeline/stages/stage2_cropping.py`:

```python
"""
Stage 2: Timestamp-based Cropping with JBI Buffer

Re-crops Stage 1 segments based on ASR timestamps with configurable buffer.
Pure ML processing - no database access, no HTTP concerns.
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from app.core.config import settings
from app.core.exceptions import ProcessingError
from app.pipeline.utils.video import extract_segment
from app.pipeline.utils.storage import upload_segment

logger = logging.getLogger(__name__)

# Default JBI buffer in seconds (2 seconds before/after ASR timestamps)
DEFAULT_JBI_BUFFER = 2.0


@dataclass
class Stage2Input:
    """Input for Stage 2 cropping."""
    segment_index: int
    stage1_video_path: str  # Source: Stage 1 bbox-cropped video
    asr_start: float        # ASR transcript start time
    asr_end: float          # ASR transcript end time
    video_duration: float   # Total video duration for bounds checking


@dataclass
class Stage2Result:
    """Result from Stage 2 cropping."""
    segment_index: int
    jbi_start: float        # Calculated: max(0, asr_start - buffer)
    jbi_end: float          # Calculated: min(duration, asr_end + buffer)
    stage2_video_path: str  # Path to re-cropped video
    duration: float         # Final clip duration
    success: bool
    error_message: Optional[str] = None


def calculate_jbi_range(
    asr_start: float,
    asr_end: float,
    video_duration: float,
    buffer_seconds: float = DEFAULT_JBI_BUFFER
) -> tuple[float, float]:
    """
    Calculate JBI time range with buffer.
    
    Formula per FR6a:
    - jbi_start = max(0, asr_start - buffer)
    - jbi_end = min(video_duration, asr_end + buffer)
    
    Args:
        asr_start: ASR transcript start time in seconds
        asr_end: ASR transcript end time in seconds
        video_duration: Total video duration in seconds
        buffer_seconds: JBI buffer before/after (default 2.0s)
        
    Returns:
        Tuple of (jbi_start, jbi_end)
    """
    jbi_start = max(0.0, asr_start - buffer_seconds)
    jbi_end = min(video_duration, asr_end + buffer_seconds)
    
    # Ensure minimum duration of 1 second
    if jbi_end - jbi_start < 1.0:
        jbi_end = min(video_duration, jbi_start + 1.0)
    
    return jbi_start, jbi_end


async def run_stage2_cropping(
    segments: List[Stage2Input],
    output_prefix: str,
    buffer_seconds: float = DEFAULT_JBI_BUFFER,
    progress_callback=None
) -> List[Stage2Result]:
    """
    Run Stage 2 cropping on all segments.
    
    Args:
        segments: List of Stage 2 inputs with ASR timestamps
        output_prefix: Prefix for output file paths (e.g., "jobs/{job_id}/")
        buffer_seconds: JBI buffer to apply (default 2.0s)
        progress_callback: Optional callback(current, total)
        
    Returns:
        List of Stage 2 results with jbi_start, jbi_end, and output paths
        
    Raises:
        ProcessingError: If cropping fails critically
    """
    results = []
    
    for idx, segment in enumerate(segments):
        try:
            result = await _process_single_segment(
                segment=segment,
                output_prefix=output_prefix,
                buffer_seconds=buffer_seconds
            )
            results.append(result)
            
            if progress_callback:
                progress_callback(idx + 1, len(segments))
                
        except Exception as e:
            logger.error(f"Failed to process segment {segment.segment_index}: {e}")
            results.append(Stage2Result(
                segment_index=segment.segment_index,
                jbi_start=0.0,
                jbi_end=0.0,
                stage2_video_path="",
                duration=0.0,
                success=False,
                error_message=str(e)
            ))
    
    return results


async def _process_single_segment(
    segment: Stage2Input,
    output_prefix: str,
    buffer_seconds: float
) -> Stage2Result:
    """
    Process a single segment for Stage 2 cropping.
    
    Args:
        segment: Stage 2 input with ASR timestamps
        output_prefix: Output path prefix
        buffer_seconds: JBI buffer to apply
        
    Returns:
        Stage 2 result with calculated times and output path
    """
    segment_index = segment.segment_index
    
    # Calculate JBI time range per FR6a
    jbi_start, jbi_end = calculate_jbi_range(
        asr_start=segment.asr_start,
        asr_end=segment.asr_end,
        video_duration=segment.video_duration,
        buffer_seconds=buffer_seconds
    )
    
    duration = jbi_end - jbi_start
    
    # Log warning for very short segments (per acceptance criteria)
    if duration < 3.0:
        logger.warning(
            f"Segment {segment_index} has short duration after JBI buffer: "
            f"{duration:.2f}s (ASR: {segment.asr_start:.2f}-{segment.asr_end:.2f}, "
            f"JBI: {jbi_start:.2f}-{jbi_end:.2f})"
        )
    
    try:
        # Extract segment using FFmpeg
        output_filename = f"{output_prefix}/segment_{segment_index:06d}_stage2.mp4"
        
        await extract_segment(
            input_path=segment.stage1_video_path,
            output_path=output_filename,
            start_time=jbi_start,
            end_time=jbi_end,
            codec="libx264"
        )
        
        # Upload to MinIO
        minio_key = await upload_segment(
            local_path=output_filename,
            object_key=f"{output_prefix}/segment_{segment_index:06d}_stage2.mp4"
        )
        
        logger.info(
            f"Segment {segment_index} Stage 2 cropped: "
            f"ASR ({segment.asr_start:.2f}-{segment.asr_end:.2f}) → "
            f"JBI ({jbi_start:.2f}-{jbi_end:.2f}), "
            f"duration={duration:.2f}s"
        )
        
        return Stage2Result(
            segment_index=segment_index,
            jbi_start=jbi_start,
            jbi_end=jbi_end,
            stage2_video_path=minio_key,
            duration=duration,
            success=True
        )
        
    except Exception as e:
        logger.error(f"Stage 2 cropping failed for segment {segment_index}: {e}")
        return Stage2Result(
            segment_index=segment_index,
            jbi_start=jbi_start,
            jbi_end=jbi_end,
            stage2_video_path="",
            duration=0.0,
            success=False,
            error_message=str(e)
        )
```

### Phase 2: Create Cropping Worker

Create `app/workers/cropping_worker.py`:

```python
"""
Cropping Worker - Stage 2 Queue Consumer

Performs timestamp-based re-cropping with JBI buffer.
"""

import logging
from uuid import UUID
from typing import Dict, Any

from app.workers.base import BaseWorker
from app.pipeline.stages.stage2_cropping import (
    run_stage2_cropping,
    Stage2Input,
    calculate_jbi_range,
    DEFAULT_JBI_BUFFER
)
from app.services.job_service import job_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus
from app.core.config import settings

logger = logging.getLogger(__name__)


class CroppingWorker(BaseWorker):
    """
    Worker that processes Stage 2 cropping jobs from the queue.
    
    Consumes jobs from 'cropping' queue, calculates JBI time ranges
    with configurable buffer, re-crops segments from Stage 1 videos,
    uploads final clips to MinIO, and marks job as READY_FOR_ANNOTATION.
    """
    
    queue_name = "cropping"
    max_retries = 2  # Lower retries for resource-intensive operations
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a Stage 2 cropping job.
        
        Args:
            payload: {"job_id": str}
            
        Returns:
            {"segments_processed": int, "segments_failed": int}
        """
        job_id = UUID(payload["job_id"])
        
        logger.info(f"Processing Stage 2 cropping job: {job_id}")
        
        # Get job and segments with ASR data
        async with async_session() as session:
            job = await job_service.get_job(session, str(job_id))
            segments = await job_service.get_segments_with_asr(session, str(job_id))
            
            # Update status to CROPPING
            await job_service.update_status(session, str(job_id), JobStatus.CROPPING)
            await session.commit()
        
        # Get JBI buffer from config (default 2.0s per FR6a)
        jbi_buffer = getattr(settings, 'jbi_buffer_seconds', DEFAULT_JBI_BUFFER)
        
        # Prepare Stage 2 inputs
        stage2_inputs = []
        for seg in segments:
            # Get Stage 1 video path (bbox cropped)
            stage1_path = seg.get('cropped_video_path') or job.video_path
            
            # Get video duration for bounds checking
            video_duration = await self._get_video_duration(stage1_path)
            
            stage2_inputs.append(Stage2Input(
                segment_index=seg['segment_index'],
                stage1_video_path=stage1_path,
                asr_start=seg['asr_start'],
                asr_end=seg['asr_end'],
                video_duration=video_duration
            ))
        
        # Run Stage 2 cropping (pure ML)
        output_prefix = f"jobs/{job_id}/stage2"
        results = await run_stage2_cropping(
            segments=stage2_inputs,
            output_prefix=output_prefix,
            buffer_seconds=jbi_buffer,
            progress_callback=lambda c, t: logger.info(f"Stage 2 progress: {c}/{t}")
        )
        
        # Update segments with JBI data and Stage 2 paths
        async with async_session() as session:
            successful = 0
            failed = 0
            
            for result in results:
                if result.success:
                    await job_service.update_segment_stage2(
                        session,
                        job_id=str(job_id),
                        segment_index=result.segment_index,
                        jbi_start=result.jbi_start,
                        jbi_end=result.jbi_end,
                        stage2_video_path=result.stage2_video_path,
                        duration=result.duration
                    )
                    successful += 1
                else:
                    await job_service.mark_segment_failed(
                        session,
                        job_id=str(job_id),
                        segment_index=result.segment_index,
                        error=result.error_message
                    )
                    failed += 1
            
            await session.commit()
        
        # Finalize job
        await self._finalize_job(job_id, successful, failed)
        
        return {
            "segments_processed": successful,
            "segments_failed": failed
        }
    
    async def _get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        from app.pipeline.utils.video import get_video_info
        info = await get_video_info(video_path)
        return info.get('duration', 0.0)
    
    async def _finalize_job(self, job_id: UUID, successful: int, failed: int):
        """
        Finalize job after Stage 2 cropping.
        
        If all segments failed, mark job as FAILED.
        Otherwise, mark as READY_FOR_ANNOTATION.
        """
        async with async_session() as session:
            if successful == 0 and failed > 0:
                # All segments failed
                await job_service.update_status(
                    session,
                    str(job_id),
                    JobStatus.FAILED,
                    error="All segments failed Stage 2 cropping"
                )
                logger.error(f"Job {job_id} failed: all segments failed cropping")
            else:
                # At least some segments succeeded
                await job_service.update_status(
                    session,
                    str(job_id),
                    JobStatus.READY_FOR_ANNOTATION
                )
                logger.info(
                    f"Job {job_id} ready for annotation: "
                    f"{successful} succeeded, {failed} failed"
                )
            
            await session.commit()
```

### Phase 3: Update ASR Worker to Queue Cropping

Modify `app/workers/asr_worker.py`:

```python
# In ASRWorker.process(), after updating segments with ASR data:

# Update segments with ASR data
async with async_session() as session:
    for result in results:
        await job_service.update_segment_asr(
            session,
            segment_index=result.segment_index,
            job_id=str(job_id),
            asr_text=result.text,
            asr_confidence=result.confidence,
            asr_start=result.start,
            asr_end=result.end,
            asr_review_flag=result.review_flag
        )
    await session.commit()

# Queue Stage 2 (timestamp-based cropping) - ADD THIS
await self._queue_cropping_stage(job_id)

return {"segments_processed": len(results)}

# ADD THIS METHOD:
async def _queue_cropping_stage(self, job_id: UUID):
    """Queue Stage 2 cropping after ASR."""
    from app.services.queue_service import queue_service
    
    logger.info(f"Queueing Stage 2 cropping for job {job_id}")
    
    async with async_session() as session:
        await queue_service.enqueue(session, "cropping", {
            "job_id": str(job_id),
            "stage": "stage2"
        })
        await session.commit()
```

### Phase 4: Add Job Service Methods

Add to `app/services/job_service.py`:

```python
async def get_segments_with_asr(self, session, job_id: str) -> List[Dict]:
    """Get segments that have completed ASR processing."""
    from app.repositories.segment_repository import SegmentRepository
    
    repo = SegmentRepository(session)
    segments = await repo.get_by_job_id(job_id)
    
    # Filter to only segments with ASR data
    return [
        {
            "segment_index": seg.segment_index,
            "asr_start": seg.asr_start,
            "asr_end": seg.asr_end,
            "cropped_video_path": seg.cropped_video_path,  # Stage 1 path
        }
        for seg in segments
        if seg.asr_start is not None and seg.asr_end is not None
    ]

async def update_segment_stage2(
    self,
    session,
    job_id: str,
    segment_index: int,
    jbi_start: float,
    jbi_end: float,
    stage2_video_path: str,
    duration: float
):
    """Update segment with Stage 2 cropping results."""
    from app.repositories.segment_repository import SegmentRepository
    
    repo = SegmentRepository(session)
    await repo.update_stage2_results(
        job_id=job_id,
        segment_index=segment_index,
        jbi_start=jbi_start,
        jbi_end=jbi_end,
        stage2_video_path=stage2_video_path,
        duration=duration
    )
```

### Phase 5: Configuration

Add to `app/core/config.py`:

```python
# JBI Buffer Configuration
jbi_buffer_seconds: float = 2.0  # Per FR6a: ±2 seconds buffer
```

---

## Tasks / Subtasks

### Backend Tasks

- [ ] **2.7.1:** Create `app/pipeline/stages/stage2_cropping.py` with JBI buffer calculation
- [ ] **2.7.2:** Implement `calculate_jbi_range()` function per FR6a formula
- [ ] **2.7.3:** Create FFmpeg segment extraction with precise seeking (-ss before -i)
- [ ] **2.7.4:** Create `app/workers/cropping_worker.py` extending `BaseWorker`
- [ ] **2.7.5:** Implement worker `process()` method with Stage 2 orchestration
- [ ] **2.7.6:** Update `app/workers/asr_worker.py` to queue "cropping" stage after ASR
- [ ] **2.7.7:** Add `get_segments_with_asr()` to job service
- [ ] **2.7.8:** Add `update_segment_stage2()` to job service
- [ ] **2.7.9:** Add `jbi_buffer_seconds` configuration to settings
- [ ] **2.7.10:** Add warning logging for segments < 3 seconds duration
- [ ] **2.7.11:** Implement partial failure handling (continue on segment error)
- [ ] **2.7.12:** Test JBI buffer calculation: `max(0, asr_start - 2)`, `min(duration, asr_end + 2)`

---

## Testing Strategy

### Unit Tests

```python
# test_stage2_cropping.py

class TestCalculateJBIRange:
    def test_normal_case(self):
        """JBI range calculated correctly with buffer."""
        start, end = calculate_jbi_range(
            asr_start=10.0,
            asr_end=20.0,
            video_duration=100.0,
            buffer_seconds=2.0
        )
        assert start == 8.0  # 10 - 2
        assert end == 22.0   # 20 + 2
    
    def test_start_at_zero(self):
        """JBI start clamped to 0 if ASR start < buffer."""
        start, end = calculate_jbi_range(
            asr_start=1.0,
            asr_end=10.0,
            video_duration=100.0,
            buffer_seconds=2.0
        )
        assert start == 0.0  # max(0, 1 - 2)
        assert end == 12.0   # 10 + 2
    
    def test_end_at_duration(self):
        """JBI end clamped to video duration."""
        start, end = calculate_jbi_range(
            asr_start=90.0,
            asr_end=95.0,
            video_duration=100.0,
            buffer_seconds=2.0
        )
        assert start == 88.0  # 90 - 2
        assert end == 100.0   # min(100, 95 + 2)
```

### Integration Test

```python
# Test full Stage 2 flow
async def test_stage2_cropping_flow():
    # Create job with Stage 1 complete
    job_id = create_test_job()
    
    # Add segment with ASR data
    segment = add_segment_with_asr(
        job_id=job_id,
        asr_start=10.0,
        asr_end=20.0,
        stage1_path="test_stage1.mp4"
    )
    
    # Run Stage 2 cropping
    worker = CroppingWorker()
    result = await worker.process({"job_id": job_id})
    
    # Verify JBI times
    assert segment.jbi_start == 8.0  # 10 - 2
    assert segment.jbi_end == 22.0   # 20 + 2
    
    # Verify Stage 2 video exists
    assert segment.stage2_video_path is not None
    
    # Verify job status
    assert job.status == JobStatus.READY_FOR_ANNOTATION
```

---

## Error Handling

| Error Type | Example | Action |
|------------|---------|--------|
| **Permanent** | Invalid video codec, corrupt file | Mark segment failed, continue others |
| **Retryable** | GPU OOM, network timeout | Retry with exponential backoff (max 2) |
| **Partial** | One segment fails | Continue processing other segments |
| **Total** | All segments fail | Mark job FAILED |

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `app/pipeline/stages/stage2_cropping.py` | CREATE | Stage 2 timestamp-based cropping with JBI buffer |
| `app/workers/cropping_worker.py` | CREATE | Queue consumer for cropping stage |
| `app/workers/asr_worker.py` | MODIFY | Add queueing of cropping stage after ASR |
| `app/services/job_service.py` | MODIFY | Add get_segments_with_asr(), update_segment_stage2() |
| `app/core/config.py` | MODIFY | Add jbi_buffer_seconds configuration |

---

## Dependencies

### Python Packages
- `ffmpeg-python` - FFmpeg Python bindings

### System Dependencies
- `ffmpeg` with libx264 codec support
- `ffprobe` for video metadata

---

## Open Questions

1. **Q:** Should we merge adjacent segments if they're both < 3 seconds after JBI buffer?  
   **A:** Per acceptance criteria: "adjacent segments may be merged (configurable)" - implement if time permits, log warning for MVP.

2. **Q:** Should Stage 2 videos replace Stage 1 videos in MinIO or be stored separately?  
   **A:** Store separately with `_stage2` suffix - Stage 1 may be needed for debugging.

3. **Q:** What if ASR timestamps extend beyond Stage 1 cropped video duration?  
   **A:** Clamp to video bounds: `min(video_duration, asr_end + buffer)`.

---

## References

- **FR6, FR6a, FR6b:** Stage 2 cropping requirements with JBI buffer
- **cv_asr_annotation.ipynb:** Reference implementation for Stage 2 cropping
- **Architecture.md:** 4-layer architecture pattern (API → Service → Worker → Pipeline)
- **Story 2.6:** ASR Worker - provides ASR timestamps as input to this stage

---

## Appendix

### State Machine Flow

```
DETECTING (Story 2.5)
    ↓ Queue "asr"
TRANSCRIBING (Story 2.6)
    ↓ Queue "cropping"
CROPPING (This Story 2.7)
    ↓ Complete
READY_FOR_ANNOTATION
```

### JBI Buffer Calculation Examples

| ASR Start | ASR End | Video Duration | JBI Start | JBI End | Duration |
|-----------|---------|----------------|-----------|---------|----------|
| 10.0s | 20.0s | 100.0s | 8.0s | 22.0s | 14.0s |
| 1.0s | 10.0s | 100.0s | 0.0s | 12.0s | 12.0s |
| 90.0s | 95.0s | 100.0s | 88.0s | 100.0s | 12.0s |
| 0.5s | 2.0s | 100.0s | 0.0s | 4.0s | 4.0s |

---

*Generated following epics.md specification*
