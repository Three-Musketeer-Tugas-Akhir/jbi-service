# Detection Worker Fix Implementation Plan

**Date:** March 26, 2026  
**Status:** Ready for Implementation  
**Priority:** Critical (Blocking Video Processing Pipeline)

---

## Overview

This document outlines the comprehensive fix for the detection worker failures. The fixes address three cascading issues that prevent video processing from completing successfully.

---

## Issue 1: Wrong enqueue() Argument Order (CRITICAL)

### Problem
The `_queue_next_stage()` method in `detection_worker.py` passes arguments in wrong order to `queue_service.enqueue()`.

### Current Code (Line 121)
```python
await queue_service.enqueue(session, "asr", {
    "job_id": str(job_id),
    "segment_count": len(segments)
})
```

### Implementation

**File:** `app/workers/detection_worker.py`

**Change at line 121:**
```python
async def _queue_next_stage(self, job_id: UUID, segments):
    """Queue ASR stage after detection."""
    async with async_session() as session:
        await queue_service.enqueue(
            queue_name="asr",
            payload={
                "job_id": str(job_id),
                "segment_count": len(segments)
            },
            db=session
        )
        await session.commit()
```

### Verification
- [ ] After fix, new video uploads successfully queue ASR jobs
- [ ] `queue_jobs` table shows new ASR entries with `status = 'pending'`
- [ ] No more `'dict' object has no attribute 'add'` errors in logs

---

## Issue 2: AV1 Video Codec Compatibility (HIGH)

### Problem
Videos encoded with AV1 codec cannot be decoded by FFmpeg in the container, causing frame reading failures.

### Solution: Transcode to H.264 Before Detection

Before running YOLO detection, transcode the video to H.264 codec which is universally supported.

### FFmpeg Command
```bash
ffmpeg -i input.mp4 -c:v libx264 -crf 18 -c:a copy -preset medium -movflags +faststart output.mp4
```

**Parameters Explained:**
| Parameter | Value | Description |
|-----------|-------|-------------|
| `-c:v libx264` | H.264 encoder | Most compatible codec |
| `-crf 18` | Quality 18 | Visually lossless (0-51, lower=better) |
| `-c:a copy` | Copy audio | Don't re-encode audio |
| `-preset medium` | Medium speed | Balance between speed and file size |
| `-movflags +faststart` | Fast start | Enable streaming playback |

### Implementation

**File:** `app/workers/detection_worker.py`

**Add new method:**
```python
import subprocess
import tempfile
from pathlib import Path

async def _transcode_to_h264(self, input_path: Path, job_id: UUID) -> Path:
    """
    Transcode video to H.264 for compatibility.
    
    Args:
        input_path: Path to input video (may be AV1 or other codec)
        job_id: Job ID for temp file naming
        
    Returns:
        Path to transcoded H.264 video
    """
    # Create temp output file
    suffix = input_path.suffix
    temp_output = Path(tempfile.gettempdir()) / f"transcoded_{job_id}{suffix}"
    
    cmd = [
        "ffmpeg",
        "-y",  # Overwrite output if exists
        "-i", str(input_path),
        "-c:v", "libx264",
        "-crf", "18",
        "-c:a", "copy",
        "-preset", "medium",
        "-movflags", "+faststart",
        "-hide_banner",
        "-loglevel", "error",  # Reduce verbosity
        str(temp_output)
    ]
    
    try:
        logger.info(f"Transcoding video to H.264 for job {job_id}")
        
        # Run ffmpeg in subprocess
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            logger.error(f"FFmpeg transcoding failed: {error_msg}")
            raise ProcessingError(f"Video transcoding failed: {error_msg}")
        
        logger.info(f"Transcoding complete: {input_path} -> {temp_output}")
        return temp_output
        
    except Exception as e:
        # Clean up temp file if created
        if temp_output.exists():
            try:
                temp_output.unlink()
            except OSError:
                pass
        raise
```

**Modify `_run_detection()` method:**
```python
async def _run_detection(self, video_path: str, job_id: UUID):
    """Run detection on video with transcoding if needed."""
    from pathlib import Path
    
    input_path = Path(video_path)
    transcoded_path = None
    
    try:
        # Try to detect video codec
        codec_info = await self._get_video_codec(input_path)
        
        if codec_info and codec_info.get("codec_name") in ["av1", "hevc", "vp9"]:
            # Transcode to H.264 for compatibility
            transcoded_path = await self._transcode_to_h264(input_path, job_id)
            video_path_to_use = str(transcoded_path)
        else:
            video_path_to_use = str(input_path)
        
        # Run detection
        jbi_segments = await self.detector.detect(Path(video_path_to_use))
        return jbi_segments
        
    finally:
        # Clean up transcoded file
        if transcoded_path and transcoded_path.exists():
            try:
                transcoded_path.unlink()
            except OSError:
                pass

async def _get_video_codec(self, video_path: Path) -> dict:
    """
    Get video codec information using ffprobe.
    
    Returns:
        Dict with codec_name, width, height, etc.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "json",
        str(video_path)
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            import json
            data = json.loads(stdout.decode())
            streams = data.get("streams", [])
            if streams:
                return streams[0]
        
        return {}
        
    except Exception as e:
        logger.warning(f"Could not detect video codec: {e}")
        return {}
```

### Dockerfile Update

Ensure ffmpeg is installed with x264 support:

**File:** `Dockerfile.gpu`

```dockerfile
# Add to runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 \
    python3.11-venv \
    ffmpeg \
    libx264-dev \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

### Verification
- [ ] Upload AV1-encoded video
- [ ] Worker logs show "Transcoding video to H.264"
- [ ] Detection completes with segments detected
- [ ] No more `[av1] Failed to get pixel format` errors

---

## Issue 3: Job Status Not Updated on Failure (MEDIUM)

### Problem
When detection fails, the pipeline job status remains as `DETECTING` instead of being updated to `FAILED`.

### Implementation

**File:** `app/workers/detection_worker.py`

**Modify `process()` method to add try-except-finally:**
```python
async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a detection job with proper error handling.
    """
    job_id = UUID(payload["job_id"])
    video_key = payload.get("video_key")
    
    logger.info(f"Processing detection job: {job_id}")
    
    # Update status to DETECTING
    async with async_session() as session:
        job_repo = JobRepository(session)
        await job_repo.update_status(job_id, "DETECTING")
        await session.commit()
    
    temp_video = None
    
    try:
        # Download video from MinIO
        if video_key:
            video_data = await self.minio_service.download_file(video_key)
            temp_video = self._save_temp_video(video_data, job_id)
            video_path = str(temp_video)
        else:
            video_path = payload.get("video_path")
        
        # Run detection
        segments = await self._run_detection(video_path, job_id)
        
        # Store segments
        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            db_segments = []
            for i, segment in enumerate(segments):
                db_segment = PipelineSegment(
                    job_id=job_id,
                    segment_index=i,
                    bbox_data=segment.bbox_data if hasattr(segment, 'bbox_data') else None,
                    jbi_start=segment.start_time if hasattr(segment, 'start_time') else None,
                    jbi_end=segment.end_time if hasattr(segment, 'end_time') else None,
                    detection_confidence=segment.confidence if hasattr(segment, 'confidence') else None
                )
                db_segments.append(db_segment)
            await segment_repo.create_many(db_segments)
            await session.commit()
        
        # Queue next stage
        await self._queue_next_stage(job_id, segments)
        
        avg_confidence = sum(s.confidence for s in segments) / len(segments) if segments else 0
        
        return {
            "segments_detected": len(segments),
            "confidence": avg_confidence
        }
        
    except Exception as e:
        # Update job status to FAILED
        logger.error(f"Detection failed for job {job_id}: {e}")
        async with async_session() as session:
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, "FAILED", error_message=str(e))
            await session.commit()
        # Re-raise to trigger retry mechanism
        raise
        
    finally:
        # Cleanup temp file
        if temp_video and temp_video.exists():
            try:
                temp_video.unlink()
            except OSError:
                pass
```

**Update `JobRepository.update_status()` to support error_message:**

**File:** `app/repositories/job_repository.py`

```python
async def update_status(
    self,
    job_id: UUID,
    status: str,
    error_message: Optional[str] = None
) -> bool:
    """
    Update job status.
    
    Args:
        job_id: Job UUID
        status: New status
        error_message: Optional error message for FAILED status
        
    Returns:
        True if job was found and updated, False otherwise
    """
    job = await self.get_by_id(job_id)
    if job:
        job.status = status
        if error_message:
            job.error_message = error_message
        if status in ["READY_FOR_ANNOTATION", "FAILED"]:
            from datetime import datetime
            job.completed_at = datetime.utcnow()
        await self.db.flush()
        return True
    return False
```

### Verification
- [ ] Upload corrupted or unsupported video
- [ ] Worker fails with error
- [ ] Check database: `pipeline_jobs.status = 'FAILED'`
- [ ] Check database: `pipeline_jobs.error_message` contains error details
- [ ] Job does not remain stuck at `DETECTING`

---

## Implementation Order

### Phase 1: Critical Fix (Deploy Immediately)
1. Fix Issue #1 (enqueue argument order)
2. Restart detection-worker container
3. Test with new video upload

### Phase 2: Transcoding Support
1. Add `_transcode_to_h264()` method
2. Add `_get_video_codec()` method
3. Update `_run_detection()` to use transcoding
4. Update Dockerfile to ensure ffmpeg with x264
5. Rebuild and restart containers
6. Test with AV1-encoded video

### Phase 3: Error Handling
1. Update `process()` method with try-except-finally
2. Update `JobRepository.update_status()` to support error_message
3. Test failure scenario
4. Verify job status updates correctly

---

## Testing Checklist

### Test Case 1: Normal H.264 Video
- [ ] Upload H.264 encoded video
- [ ] Detection completes successfully
- [ ] ASR queue job created
- [ ] Job status progresses: UPLOADED → DETECTING → TRANSCRIBING

### Test Case 2: AV1 Video
- [ ] Upload AV1 encoded video
- [ ] Worker detects AV1 codec
- [ ] Transcoding to H.264 triggered
- [ ] Detection completes after transcoding
- [ ] ASR queue job created

### Test Case 3: Corrupted Video
- [ ] Upload corrupted/unreadable video
- [ ] Detection fails
- [ ] Job status updated to FAILED
- [ ] Error message stored in database
- [ ] No infinite retry loop

### Test Case 4: Worker Restart Mid-Processing
- [ ] Start video processing
- [ ] Kill detection-worker container mid-process
- [ ] Restart worker
- [ ] Job should be picked up again (if status != FAILED)

---

## Files to Modify

| File | Changes |
|------|---------|
| `app/workers/detection_worker.py` | Fix enqueue args, add transcoding, add error handling |
| `app/repositories/job_repository.py` | Update update_status() signature |
| `Dockerfile.gpu` | Add libx264-dev package |
| `docker-compose.yml` | No changes needed |

---

## Rollback Plan

If issues occur after deployment:

1. **Revert to previous image:**
   ```bash
   cd ~/jbi-service
   docker compose down
   docker compose --profile gpu up -d
   ```

2. **Clear stuck jobs:**
   ```sql
   UPDATE pipeline_jobs SET status = 'FAILED' 
   WHERE status = 'DETECTING' AND updated_at < NOW() - INTERVAL '1 hour';
   ```

3. **Clear failed queue jobs:**
   ```sql
   DELETE FROM queue_jobs WHERE status = 'failed';
   ```

---

## Post-Deployment Monitoring

Monitor these metrics for 24 hours after deployment:

1. **Detection success rate** - Should be > 95%
2. **Average detection time** - Should not increase significantly
3. **Transcoding frequency** - Track how many videos need transcoding
4. **Queue depth** - Should not accumulate failed jobs
5. **Error log volume** - Should decrease significantly

---

## Success Criteria

✅ All three issues resolved  
✅ AV1 videos process successfully  
✅ Failed jobs properly marked as FAILED  
✅ No jobs stuck in DETECTING status  
✅ ASR stage receives jobs correctly  
✅ No `'dict' object has no attribute 'add'` errors  

---

**Estimated Implementation Time:** 2-3 hours  
**Testing Time:** 1-2 hours  
**Total:** Half day project
