---
story_id: "2.7"
story_key: "2-7-cropping-worker-jbi-buffer"
epic: 2
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

As a video processing pipeline,  
I need a cropping worker that takes segments with JBI buffer applied and produces cropped video files,  
So that annotators can review individual JBI segments with precise timing and bounding box cropping.

### Business Context

This story implements the third and final stage of the video processing pipeline - the Cropping Worker. After the Detection Worker identifies JBI regions and the ASR Worker transcribes audio, the Cropping Worker produces the final cropped video segments that annotators will review.

The Cropping Worker applies a configurable JBI buffer (default 0.5s before/after) to the ASR timestamps, then crops the video based on the bounding box data from detection. This creates focused, high-quality video clips containing only the JBI (sign language interpreter) with synchronized audio.

Key responsibilities:
- Apply temporal buffer around ASR timestamps for context
- Apply spatial cropping based on detected bounding boxes
- Maintain aspect ratio and preserve audio quality
- Upload final segments to MinIO for annotation access

### Acceptance Criteria

**Given** a job has completed ASR processing  
**When** the CroppingWorker picks up the job  
**Then** the worker downloads the original video from MinIO  
**And** applies JBI buffer (default 0.5s) to ASR start/end times  
**And** crops video based on bbox_data from detection  
**And** maintains aspect ratio and preserves audio  
**And** uploads cropped segments to `jobs/{job_id}/final/segment_{index}.mp4`

**Given** JBI buffer configuration is specified  
**When** cropping is performed  
**Then** the configured buffer is applied (buffer_before, buffer_after)  
**And** buffer values can be different for start and end  
**And** buffer respects video boundaries (no negative times)

**Given** cropping completes successfully  
**When** results are saved  
**Then** each segment's `cropped_video_path` is updated  
**And** `jbi_start` and `jbi_end` are set (buffer-adjusted timestamps)  
**And** job status is updated to "READY_FOR_ANNOTATION"  
**And** segment status is updated to "CROPPED"

**Given** a segment has no ASR results  
**When** cropping is attempted  
**Then** the segment is skipped with a warning  
**And** processing continues for other segments

**Given** video cropping fails for a segment  
**When** error occurs  
**Then** error is logged and segment is marked as failed  
**And** retry logic attempts reprocessing (max 3 attempts)  
**And** after max retries, job status is FAILED

**Given** output codec is unsupported  
**When** encoding fails  
**Then** error is classified as permanent (no retry)  
**And** job status is FAILED with "Codec not supported"

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - background worker)
   - **Worker Layer**: `app/workers/cropping_worker.py` - Queue consumer extending BaseWorker
   - **Repository Layer**: `SegmentRepository` (from Story 2.5)
   - **Pipeline Layer**: `app/pipeline/stages/stage3_cropping.py` - Pure ML/video processing

2. **Worker Pattern**
   - Extends `BaseWorker` abstract class
   - Sets `queue_name = "cropping"`
   - Implements `process()` method
   - Uses automatic retry logic from BaseWorker

3. **Database Naming**
   - Table: `pipeline_segments` stores cropped paths
   - Fields: `cropped_video_path`, `jbi_start`, `jbi_end`, `status`
   - Status transitions: CROPPING → READY_FOR_ANNOTATION (or FAILED)

4. **State Machine**
   - Input state: `CROPPING` (set by ASR Worker after update)
   - Processing state: `CROPPING`
   - Output states: `READY_FOR_ANNOTATION` (success) or `FAILED` (error)

5. **Storage Patterns**
   - Downloads from: `jobs/{job_id}/original/{filename}` (MinIO)
   - Uploads to: `jobs/{job_id}/final/segment_{index}.mp4`
   - Stage 1 segments remain (for reference)

6. **Queue Integration**
   - Polls: `cropping` queue
   - On success: marks queue job completed
   - On failure: triggers retry via BaseWorker

### Technical Requirements

**Cropping Configuration:**
| Parameter | Default | Description |
|-----------|---------|-------------|
| buffer_before | 0.5 | Seconds to extend before ASR start time |
| buffer_after | 0.5 | Seconds to extend after ASR end time |
| output_codec | "libx264" | Video codec for output |
| output_format | "mp4" | Output container format |
| video_quality | "high" | Quality preset (high/medium/low) |
| maintain_aspect | true | Whether to pad or crop to maintain aspect |
| audio_codec | "aac" | Audio codec for output |
| audio_bitrate | "128k" | Audio bitrate |

**JBI Buffer Calculation:**
```python
# Calculate buffered timestamps
jbi_start = max(0, asr_start - buffer_before)
jbi_end = min(video_duration, asr_end + buffer_after)

# Ensure minimum duration
if (jbi_end - jbi_start) < 1.0:
    jbi_end = jbi_start + 1.0  # Minimum 1 second clip
```

**Segment Schema (Final Output):**
```python
{
    "segment_index": 0,
    "jbi_start": 12.0,  # Buffered start time (seconds)
    "jbi_end": 19.3,    # Buffered end time (seconds)
    "bbox_data": {       # From detection stage
        "x": 120.5,
        "y": 80.0,
        "width": 200.0,
        "height": 150.0
    },
    "cropped_video_path": "jobs/{job_id}/final/segment_0.mp4",
    "status": "CROPPED"
}
```

**Worker Loop (BaseWorker Pattern):**
```python
class CroppingWorker(BaseWorker):
    queue_name = "cropping"
    
    async def process(self, payload: dict) -> dict:
        job_id = UUID(payload["job_id"])
        
        # 1. Get job and segments from DB
        segments = await segment_repo.get_by_job_id(job_id)
        
        # 2. Download original video
        video_data = await minio_service.download_file(job.video_path)
        video_path = save_temp(video_data)
        
        # 3. Process each segment
        for segment in segments:
            # Apply JBI buffer to timestamps
            # Crop video using bbox_data
            # Upload to MinIO
            # Update segment record
        
        # 4. Update job status
        await job_repo.update_status(job_id, "READY_FOR_ANNOTATION")
        
        return {"segments_cropped": len(segments)}
```

**Error Handling:**
| Error Type | Action | Retry |
|------------|--------|-------|
| Video download fails | Log, mark failed | Yes |
| Segment has no ASR data | Log warning, skip | No |
| Video codec error | Log, mark failed | No (permanent) |
| FFmpeg/MoviePy failure | Log, mark failed | Yes |
| MinIO upload fails | Log, mark failed | Yes |
| Disk space error | Log, mark failed | No |

---

## Implementation Guide

### Phase 1: Create Cropping Pipeline Stage

#### Step 1.1: Create app/pipeline/stages/stage3_cropping.py

```python
"""
Stage 3: JBI Video Cropping Pipeline

Applies JBI buffer to ASR timestamps and crops video segments
based on detected bounding boxes. Pure ML/video processing.
"""

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from app.core.exceptions import ProcessingError
from app.pipeline.utils.video import crop_video_segment
from app.pipeline.utils.storage import download_video, upload_video

logger = logging.getLogger(__name__)


@dataclass
class CroppingInput:
    """Input for cropping a single segment."""
    segment_index: int
    video_path: str  # Path to original video (local or MinIO)
    is_local: bool
    asr_start: float
    asr_end: float
    bbox_data: Dict[str, float]  # x, y, width, height


@dataclass
class CroppingResult:
    """Result from cropping a single segment."""
    segment_index: int
    success: bool
    jbi_start: float  # Buffered start time
    jbi_end: float    # Buffered end time
    output_path: Optional[str]  # MinIO path
    error_message: Optional[str] = None


# Default configuration
DEFAULT_BUFFER_BEFORE = 0.5  # seconds
DEFAULT_BUFFER_AFTER = 0.5   # seconds
MIN_SEGMENT_DURATION = 1.0   # seconds


async def run_cropping(
    job_id: str,
    segments: List[CroppingInput],
    buffer_before: float = DEFAULT_BUFFER_BEFORE,
    buffer_after: float = DEFAULT_BUFFER_AFTER,
    progress_callback=None
) -> List[CroppingResult]:
    """
    Run cropping stage on all segments.
    
    Args:
        job_id: The pipeline job ID
        segments: List of segments to crop
        buffer_before: Seconds to add before ASR start
        buffer_after: Seconds to add after ASR end
        progress_callback: Optional callback(current, total)
        
    Returns:
        List of CroppingResult
        
    Raises:
        ProcessingError: If cropping fails critically
    """
    results = []
    temp_files = []
    original_video_path = None
    
    try:
        # Get first segment's video (all segments from same video)
        if not segments:
            return results
        
        first_segment = segments[0]
        
        # Download original video
        if first_segment.is_local:
            original_video_path = Path(first_segment.video_path)
        else:
            video_data = await download_video(first_segment.video_path)
            original_video_path = _save_temp_video(video_data, "original")
            temp_files.append(original_video_path)
        
        # Process each segment
        for idx, segment_input in enumerate(segments):
            try:
                result = await _process_single_segment(
                    job_id=job_id,
                    segment_input=segment_input,
                    original_video_path=original_video_path,
                    buffer_before=buffer_before,
                    buffer_after=buffer_after
                )
                results.append(result)
                
                if progress_callback:
                    progress_callback(idx + 1, len(segments))
                    
            except Exception as e:
                logger.error(f"Failed to crop segment {segment_input.segment_index}: {e}")
                results.append(CroppingResult(
                    segment_index=segment_input.segment_index,
                    success=False,
                    jbi_start=0.0,
                    jbi_end=0.0,
                    output_path=None,
                    error_message=str(e)
                ))
        
        return results
        
    finally:
        # Cleanup temp files
        for temp_file in temp_files:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError as e:
                    logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")


async def _process_single_segment(
    job_id: str,
    segment_input: CroppingInput,
    original_video_path: Path,
    buffer_before: float,
    buffer_after: float
) -> CroppingResult:
    """
    Process a single segment for cropping.
    
    Args:
        job_id: The pipeline job ID
        segment_input: Segment input data
        original_video_path: Path to original video file
        buffer_before: Buffer before ASR start
        buffer_after: Buffer after ASR end
        
    Returns:
        CroppingResult
    """
    segment_index = segment_input.segment_index
    temp_output_path = None
    
    try:
        # Validate ASR data
        if segment_input.asr_start is None or segment_input.asr_end is None:
            logger.warning(f"Segment {segment_index} has no ASR data, skipping")
            return CroppingResult(
                segment_index=segment_index,
                success=False,
                jbi_start=0.0,
                jbi_end=0.0,
                output_path=None,
                error_message="No ASR data available"
            )
        
        # Calculate buffered timestamps
        jbi_start, jbi_end = _calculate_buffered_times(
            asr_start=segment_input.asr_start,
            asr_end=segment_input.asr_end,
            buffer_before=buffer_before,
            buffer_after=buffer_after,
            video_path=original_video_path
        )
        
        logger.info(
            f"Segment {segment_index}: ASR [{segment_input.asr_start:.2f} - "
            f"{segment_input.asr_end:.2f}] -> JBI [{jbi_start:.2f} - {jbi_end:.2f}]"
        )
        
        # Create temp output file
        temp_output_path = Path(tempfile.mktemp(
            suffix=".mp4",
            prefix=f"cropped_segment_{segment_index}_"
        ))
        
        # Crop video
        await crop_video_segment(
            input_path=original_video_path,
            output_path=temp_output_path,
            start_time=jbi_start,
            end_time=jbi_end,
            bbox=segment_input.bbox_data
        )
        
        # Upload to MinIO
        object_name = f"jobs/{job_id}/final/segment_{segment_index}.mp4"
        await upload_video(temp_output_path, object_name)
        
        logger.info(f"Segment {segment_index} cropped and uploaded to {object_name}")
        
        return CroppingResult(
            segment_index=segment_index,
            success=True,
            jbi_start=jbi_start,
            jbi_end=jbi_end,
            output_path=object_name
        )
        
    except Exception as e:
        logger.error(f"Cropping failed for segment {segment_index}: {e}")
        raise ProcessingError(f"Cropping failed for segment {segment_index}: {e}")
        
    finally:
        # Cleanup temp output
        if temp_output_path and temp_output_path.exists():
            try:
                temp_output_path.unlink()
            except OSError:
                pass


def _calculate_buffered_times(
    asr_start: float,
    asr_end: float,
    buffer_before: float,
    buffer_after: float,
    video_path: Path
) -> Tuple[float, float]:
    """
    Calculate JBI timestamps with buffer applied.
    
    Args:
        asr_start: ASR start time
        asr_end: ASR end time
        buffer_before: Seconds to add before
        buffer_after: Seconds to add after
        video_path: Path to video (for duration check)
        
    Returns:
        Tuple of (jbi_start, jbi_end)
    """
    import cv2
    
    # Get video duration
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ProcessingError(f"Cannot open video: {video_path}")
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0
    cap.release()
    
    # Apply buffer
    jbi_start = max(0.0, asr_start - buffer_before)
    jbi_end = min(duration, asr_end + buffer_after)
    
    # Ensure minimum duration
    if (jbi_end - jbi_start) < MIN_SEGMENT_DURATION:
        jbi_end = jbi_start + MIN_SEGMENT_DURATION
        if jbi_end > duration:
            jbi_end = duration
            jbi_start = max(0.0, jbi_end - MIN_SEGMENT_DURATION)
    
    return jbi_start, jbi_end


def _save_temp_video(video_data: bytes, prefix: str) -> Path:
    """Save video data to temporary file."""
    try:
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp4",
            delete=False,
            prefix=f"{prefix}_"
        )
        temp_file.write(video_data)
        temp_file.close()
        return Path(temp_file.name)
    except (OSError, IOError) as e:
        raise ProcessingError(f"Failed to create temp video file: {e}")
```

#### Step 1.2: Create app/pipeline/utils/video.py (update/add crop_video_segment)

```python
"""Video processing utilities."""

import logging
from pathlib import Path
from typing import Dict, Optional

import ffmpeg
import moviepy.editor as mp

from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


async def crop_video_segment(
    input_path: Path,
    output_path: Path,
    start_time: float,
    end_time: float,
    bbox: Optional[Dict[str, float]] = None,
    output_codec: str = "libx264",
    audio_codec: str = "aac",
    video_quality: str = "high"
) -> Path:
    """
    Crop a video segment with optional spatial cropping.
    
    Args:
        input_path: Path to input video
        output_path: Path for output video
        start_time: Start time in seconds
        end_time: End time in seconds
        bbox: Optional bounding box dict with x, y, width, height
        output_codec: Video codec (default: libx264)
        audio_codec: Audio codec (default: aac)
        video_quality: Quality preset (high/medium/low)
        
    Returns:
        Path to output video
        
    Raises:
        ProcessingError: If cropping fails
    """
    duration = end_time - start_time
    
    try:
        if bbox:
            # Spatial + temporal crop using FFmpeg
            x, y = int(bbox["x"]), int(bbox["y"])
            width, height = int(bbox["width"]), int(bbox["height"])
            
            # Ensure even dimensions for codec compatibility
            width = width - (width % 2)
            height = height - (height % 2)
            
            # Build FFmpeg command
            stream = ffmpeg.input(
                str(input_path),
                ss=start_time,
                t=duration
            )
            
            # Apply crop filter
            stream = stream.filter("crop", width, height, x, y)
            
            # Quality settings
            crf = {"high": 18, "medium": 23, "low": 28}.get(video_quality, 23)
            preset = {"high": "slow", "medium": "medium", "low": "fast"}.get(
                video_quality, "medium"
            )
            
            # Output
            stream = ffmpeg.output(
                stream,
                str(output_path),
                vcodec=output_codec,
                acodec=audio_codec,
                crf=crf,
                preset=preset,
                movflags="+faststart",
                pix_fmt="yuv420p"  # Ensure compatibility
            )
            
            ffmpeg.run(stream, overwrite_output=True, quiet=True)
            
        else:
            # Temporal crop only
            stream = ffmpeg.input(
                str(input_path),
                ss=start_time,
                t=duration
            )
            
            crf = {"high": 18, "medium": 23, "low": 28}.get(video_quality, 23)
            preset = {"high": "slow", "medium": "medium", "low": "fast"}.get(
                video_quality, "medium"
            )
            
            stream = ffmpeg.output(
                stream,
                str(output_path),
                vcodec=output_codec,
                acodec=audio_codec,
                crf=crf,
                preset=preset,
                movflags="+faststart",
                pix_fmt="yuv420p"
            )
            
            ffmpeg.run(stream, overwrite_output=True, quiet=True)
        
        logger.info(f"Video cropped: {input_path} -> {output_path}")
        return output_path
        
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8") if e.stderr else str(e)
        
        if "codec" in stderr.lower():
            raise ProcessingError(
                f"Video codec error: {stderr}",
                permanent=True
            )
        
        raise ProcessingError(f"Video cropping failed: {stderr}")
        
    except Exception as e:
        raise ProcessingError(f"Video cropping failed: {e}")


async def extract_audio(
    video_path: Path,
    output_path: Optional[Path] = None
) -> Path:
    """Extract audio from video file."""
    # Existing implementation from stage2_asr
    pass
```

### Phase 2: Create Cropping Worker

#### Step 2.1: Create app/workers/cropping_worker.py

```python
"""
Cropping Worker - Stage 3 Queue Consumer

Processes cropping jobs from the queue.
Applies JBI buffer and produces final cropped segments.
"""

import logging
from typing import Dict, Any
from uuid import UUID

from app.workers.base import BaseWorker
from app.pipeline.stages.stage3_cropping import (
    run_cropping,
    CroppingInput,
    CroppingResult
)
from app.services.job_service import job_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus

logger = logging.getLogger(__name__)


class CroppingWorker(BaseWorker):
    """
    Worker that processes cropping jobs from the queue.
    
    Consumes jobs from 'cropping' queue, applies JBI buffer,
    crops video segments, uploads to MinIO, and marks job complete.
    """
    
    queue_name = "cropping"
    max_retries = 3
    
    # Configuration
    buffer_before = 0.5  # seconds
    buffer_after = 0.5   # seconds
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a cropping job.
        
        Args:
            payload: {"job_id": str}
            
        Returns:
            {"segments_cropped": int, "segments_failed": int}
        """
        job_id = UUID(payload["job_id"])
        
        logger.info(f"Processing cropping job: {job_id}")
        
        # Get job and segments
        async with async_session() as session:
            job = await job_service.get_job(session, str(job_id))
            segments = await job_service.get_segments(session, str(job_id))
            
            # Update status
            await job_service.update_status(session, str(job_id), JobStatus.CROPPING)
            await session.commit()
        
        # Prepare inputs for pipeline stage
        cropping_inputs = []
        for seg in segments:
            # Get video path (use original video)
            video_path = job.video_path
            is_local = False
            
            cropping_inputs.append(CroppingInput(
                segment_index=seg.segment_index,
                video_path=video_path,
                is_local=is_local,
                asr_start=seg.asr_start or 0.0,
                asr_end=seg.asr_end or 0.0,
                bbox_data=seg.bbox_data or {}
            ))
        
        # Run cropping (pure ML/video processing)
        results = await run_cropping(
            job_id=str(job_id),
            segments=cropping_inputs,
            buffer_before=self.buffer_before,
            buffer_after=self.buffer_after,
            progress_callback=lambda c, t: logger.info(f"Cropping progress: {c}/{t}")
        )
        
        # Update segments with cropping data
        async with async_session() as session:
            success_count = 0
            failed_count = 0
            
            for result in results:
                if result.success:
                    await job_service.update_segment_cropping(
                        session,
                        segment_index=result.segment_index,
                        job_id=str(job_id),
                        jbi_start=result.jbi_start,
                        jbi_end=result.jbi_end,
                        cropped_video_path=result.output_path
                    )
                    success_count += 1
                else:
                    logger.warning(
                        f"Segment {result.segment_index} failed: {result.error_message}"
                    )
                    failed_count += 1
            
            await session.commit()
        
        # Finalize job
        await self._finalize_job(job_id, success_count, failed_count)
        
        return {
            "segments_cropped": success_count,
            "segments_failed": failed_count
        }
    
    async def _finalize_job(
        self,
        job_id: UUID,
        success_count: int,
        failed_count: int
    ):
        """
        Finalize job after cropping.
        
        Marks job as READY_FOR_ANNOTATION if any segments succeeded.
        Marks as FAILED if all segments failed.
        """
        async with async_session() as session:
            if success_count > 0:
                await job_service.update_status(
                    session,
                    str(job_id),
                    JobStatus.READY_FOR_ANNOTATION
                )
                logger.info(
                    f"Job {job_id} ready for annotation: "
                    f"{success_count} segments cropped"
                )
            else:
                await job_service.update_status(
                    session,
                    str(job_id),
                    JobStatus.FAILED,
                    error_message="All segments failed to crop"
                )
                logger.error(f"Job {job_id} failed: all segments failed to crop")
            
            await session.commit()
```

### Phase 3: Update ASR Worker to Queue Cropping Stage

#### Step 3.1: Update app/workers/asr_worker.py

Replace the `_finalize_job` method to queue the cropping stage:

```python
async def _finalize_job(self, job_id: UUID):
    """
    Finalize job after ASR.
    
    Queues the cropping stage for further processing.
    """
    from app.services.queue_service import queue_service
    
    logger.info(f"ASR complete for job {job_id}. Queueing cropping stage.")
    
    async with async_session() as session:
        # Update job status to CROPPING
        await job_service.update_status(
            session,
            str(job_id),
            JobStatus.CROPPING
        )
        
        # Queue cropping stage
        await queue_service.enqueue(
            session,
            queue_name="cropping",
            payload={"job_id": str(job_id)}
        )
        
        await session.commit()
```

### Phase 4: Update Job Service for Segment Updates

#### Step 4.1: Update app/services/job_service.py

Add method for updating segment cropping data:

```python
async def update_segment_cropping(
    self,
    session: AsyncSession,
    segment_index: int,
    job_id: str,
    jbi_start: float,
    jbi_end: float,
    cropped_video_path: str
) -> None:
    """
    Update segment with cropping results.
    
    Args:
        session: Database session
        segment_index: Index of the segment
        job_id: UUID of the job
        jbi_start: Buffered start time
        jbi_end: Buffered end time
        cropped_video_path: Path to cropped video in MinIO
    """
    from app.db.models.pipeline import PipelineSegment
    
    result = await session.execute(
        select(PipelineSegment).where(
            PipelineSegment.job_id == job_id,
            PipelineSegment.segment_index == segment_index
        )
    )
    segment = result.scalar_one_or_none()
    
    if segment:
        segment.jbi_start = jbi_start
        segment.jbi_end = jbi_end
        segment.cropped_video_path = cropped_video_path
        segment.status = "CROPPED"
```

### Phase 5: Configuration Updates

#### Step 5.1: Update app/core/config.py

Add cropping-specific settings:

```python
# Cropping Configuration
JBI_BUFFER_BEFORE: float = 0.5  # Seconds before ASR start
JBI_BUFFER_AFTER: float = 0.5   # Seconds after ASR end
CROPPING_VIDEO_QUALITY: str = "high"  # high/medium/low
CROPPING_OUTPUT_CODEC: str = "libx264"
CROPPING_AUDIO_CODEC: str = "aac"
```

---

## Tasks / Subtasks

- [ ] Task 1: Create Pipeline Stage (stage3_cropping.py) (AC: Cropping Stage)
  - [ ] Create CroppingInput and CroppingResult dataclasses
  - [ ] Implement run_cropping() function
  - [ ] Implement _calculate_buffered_times() with boundary checks
  - [ ] Implement _process_single_segment() with video cropping
  - [ ] Add proper error handling and temp file cleanup
  
- [ ] Task 2: Create Video Cropping Utility (AC: Cropping Stage)
  - [ ] Implement crop_video_segment() using FFmpeg
  - [ ] Support temporal cropping (start/end times)
  - [ ] Support spatial cropping (bbox coordinates)
  - [ ] Ensure H.264 codec and MP4 output
  - [ ] Preserve audio during cropping
  
- [ ] Task 3: Create CroppingWorker (AC: Cropping Worker)
  - [ ] Extend BaseWorker with queue_name = "cropping"
  - [ ] Implement process() method
  - [ ] Load segments and prepare CroppingInput
  - [ ] Call run_cropping() and handle results
  - [ ] Update segment records in database
  
- [ ] Task 4: Update ASR Worker (AC: Queue Integration)
  - [ ] Update _finalize_job() to queue cropping stage
  - [ ] Change status to CROPPING instead of READY_FOR_ANNOTATION
  - [ ] Import and use queue_service
  
- [ ] Task 5: Update Job Service (AC: Database Updates)
  - [ ] Add update_segment_cropping() method
  - [ ] Handle segment status updates
  
- [ ] Task 6: Add Configuration Settings (AC: Configuration)
  - [ ] Add JBI buffer settings to config.py
  - [ ] Add video quality and codec settings
  
- [ ] Task 7: Create Worker Entry Point (AC: Cropping Worker)
  - [ ] Create run_croppingWorker.py script
  
- [ ] Task 8: Create Unit Tests (AC: All)
  - [ ] Test run_cropping() function
  - [ ] Test buffer calculation
  - [ ] Test video cropping utility
  - [ ] Test CroppingWorker
  
- [ ] Task 9: Create Integration Tests (AC: All)
  - [ ] Test end-to-end cropping flow
  - [ ] Test error handling and retries
  
- [ ] Task 10: Run Validations
- [ ] Task 11: Code Review
- [ ] Task 12: Mark Story as DONE

---

## Testing Strategy

### Unit Tests

```python
# tests/unit/pipeline/stages/test_stage3_cropping.py

class TestRunCropping:
    """Test suite for cropping pipeline stage."""
    
    async def test_run_cropping_success(self):
        """Test successful cropping of segments."""
        
    async def test_run_cropping_no_segments(self):
        """Test handling of empty segment list."""
        
    async def test_run_cropping_partial_failure(self):
        """Test handling when some segments fail."""


class TestCalculateBufferedTimes:
    """Test suite for buffer calculation."""
    
    def test_buffer_applied_correctly(self):
        """Test buffer is added to ASR times."""
        
    def test_buffer_respects_video_start(self):
        """Test buffer doesn't go below 0."""
        
    def test_buffer_respects_video_end(self):
        """Test buffer doesn't exceed video duration."""
        
    def test_minimum_duration_enforced(self):
        """Test minimum segment duration is enforced."""


# tests/unit/pipeline/utils/test_video.py

class TestCropVideoSegment:
    """Test suite for video cropping utility."""
    
    async def test_temporal_crop_only(self):
        """Test cropping by time only (no bbox)."""
        
    async def test_spatial_and_temporal_crop(self):
        """Test cropping with bbox and time."""
        
    async def test_preserves_audio(self):
        """Test audio is preserved in output."""
        
    async def test_output_codec_h264(self):
        """Test output uses H.264 codec."""


# tests/unit/workers/test_cropping_worker.py

class TestCroppingWorker:
    """Test suite for CroppingWorker."""
    
    async def test_process_success(self):
        """Test successful job processing."""
        
    async def test_process_with_failures(self):
        """Test job with some failed segments."""
        
    async def test_process_all_failures(self):
        """Test job where all segments fail."""
        
    async def test_finalize_job_success(self):
        """Test job finalization on success."""
        
    async def test_finalize_job_all_failed(self):
        """Test job finalization when all failed."""
```

### Integration Tests

```python
# tests/integration/test_cropping_pipeline.py

async def test_end_to_end_cropping():
    """
    Test full flow:
    1. Create job with ASR-completed segments
    2. Queue cropping job
    3. Worker processes
    4. Segments updated with JBI timestamps and paths
    5. Job status is READY_FOR_ANNOTATION
    """

async def test_cropping_with_buffer():
    """
    Test JBI buffer application:
    1. Create segment with ASR times
    2. Run cropping with buffer
    3. Verify JBI times include buffer
    """

async def test_cropping_retry():
    """
    Test retry logic:
    1. Create job that fails once then succeeds
    2. Verify retry occurs
    3. Verify final success
    """
```

---

## Error Handling

### Permanent Errors (No Retry)

| Error | Cause | Action |
|-------|-------|--------|
| Unsupported codec | Video format incompatible | Mark FAILED, log error |
| Invalid bbox data | Detection bbox missing/invalid | Skip segment, continue |
| No ASR data | ASR stage didn't complete | Skip segment, continue |
| Disk space full | Insufficient temp space | Mark FAILED, alert admin |

### Retryable Errors (Max 3 Attempts)

| Error | Cause | Action |
|-------|-------|--------|
| MinIO download failure | Network/storage issue | Retry with backoff |
| MinIO upload failure | Network/storage issue | Retry with backoff |
| FFmpeg error | Transient processing issue | Retry |
| Database connection | DB temporarily unavailable | Retry |

### Error Logging

All errors are logged with:
- Job ID
- Segment index (if applicable)
- Error type and message
- Stack trace (for unexpected errors)
- Retry count

---

## File Changes

### New Files

| File | Purpose |
|------|---------|
| `app/pipeline/stages/stage3_cropping.py` | Stage 3 cropping logic |
| `app/workers/cropping_worker.py` | Cropping queue consumer |
| `run_cropping_worker.py` | Worker entry point script |

### Modified Files

| File | Changes |
|------|---------|
| `app/workers/asr_worker.py` | Update _finalize_job() to queue cropping |
| `app/services/job_service.py` | Add update_segment_cropping() method |
| `app/core/config.py` | Add cropping configuration |
| `app/pipeline/stages/__init__.py` | Export stage3 functions |

---

## Dependencies

**Python Packages:**
- `ffmpeg-python>=0.2.0` - Video processing wrapper
- `moviepy>=1.0.3` - Alternative video processing (optional)

**System Packages:**
- `ffmpeg` - Video encoding/decoding

**Existing Dependencies (from Stories 2.1-2.6):**
- MinIO service (for storage)
- Queue service (for job queue)
- Job service (for database updates)
- Segment repository (from Story 2.5)

---

## Open Questions

1. **Buffer Configuration**: Should buffer values be configurable per-job or system-wide?
2. **Output Quality**: Should quality settings be configurable per-job?
3. **Failed Segments**: Should partial failures (some segments succeed) still mark job as READY_FOR_ANNOTATION?
4. **Stage 1 Cleanup**: Should we delete Stage 1 cropped videos after final cropping?
5. **Aspect Ratio**: Should we pad videos to maintain a specific aspect ratio or just crop?

---

## References

- Architecture: `docs/architecture.md` - Pipeline State Machine
- BaseWorker: `app/workers/base.py` - Worker abstract class
- Story 2.5: Detection Worker pattern
- Story 2.6: ASR Worker pattern (similar structure)
- Database Schema: `app/db/models/pipeline.py` - PipelineSegment model
- FFmpeg Documentation: https://ffmpeg.org/documentation.html

---

## Appendix: State Machine Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   UPLOADED  │────▶│   QUEUED    │────▶│  DETECTING  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                                                ▼
┌─────────────────────┐   ┌─────────────┐   ┌─────────────┐
│ READY_FOR_ANNOTATION│◄──│  CROPPING   │◄──│ TRANSCRIBING│
└─────────────────────┘   └──────┬──────┘   └─────────────┘
                                 │
                         ┌───────┴───────┐
                         │   FAILED      │
                         └───────────────┘
```

**Story 2.7 implements:** TRANSCRIBING → CROPPING → READY_FOR_ANNOTATION
