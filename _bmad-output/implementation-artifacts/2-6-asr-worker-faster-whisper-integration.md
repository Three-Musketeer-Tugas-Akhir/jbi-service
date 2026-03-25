---
story_id: "2.6"
story_key: "2-6-asr-worker-faster-whisper-integration"
epic: 2
status: done
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.6: ASR Worker - faster-whisper Integration

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.6  
**Status:** ready-for-dev  
**Priority:** Critical (Core ML)  
**Estimated Effort:** Large (4-5 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.2: MinIO Storage Integration ✅
- Story 2.4: PostgreSQL Queue Implementation ✅
- Story 2.5: Detection Worker - YOLOv8 Integration ✅

---

## Story Requirements

### User Story

As a system,  
I want to transcribe audio from Stage 1 cropped segments using faster-whisper,  
So that synchronized transcripts can be generated for the annotation workflow.

### Business Context

This story implements the second stage of the video processing pipeline - the ASR (Automatic Speech Recognition) Worker. After the Detection Worker identifies JBI regions and creates Stage 1 cropped segments, the ASR Worker processes these segments to extract speech content. This is a critical ML inference step that converts audio to text, which will later be used by annotators to synchronize sign language interpretation with spoken content.

The ASR Worker must follow the exact implementation from `asr_code.ipynb`, using the `faster-whisper` library (not OpenAI's Whisper API) for local inference. It supports multiple model sizes and compute types for flexibility across different hardware configurations.

### Acceptance Criteria

**Given** segments are ready for ASR processing  
**When** the ASRWorker picks up the job  
**Then** the worker downloads each cropped segment from MinIO  
**And** runs faster-whisper transcription (from asr_code.ipynb)  
**And** generates segments.txt format: `[start -> end] transcript text`

**Given** ASR configuration specifies model size  
**When** transcription runs  
**Then** the specified model is used (tiny/base/small/medium/large-v3)  
**And** compute type is applied (int8/float16/int8_float16)

**Given** ASR transcription completes  
**When** results are processed  
**Then** each segment's asr_text, asr_start, asr_end are saved  
**And** confidence scores are stored (FR49)  
**And** job status is updated to "CROPPING"  
**And** next stage is queued for timestamp-based cropping

**Given** ASR produces low confidence segments (< 0.5)  
**When** results are saved  
**Then** segments are flagged for potential ASR Review  
**And** confidence scores are available for annotator review

**Given** audio codec is unsupported  
**When** transcription fails  
**Then** error is classified as permanent (no retry)  
**And** job status is FAILED with "Audio codec not supported"

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - background worker)
   - **Service Layer**: `app/services/asr_worker.py` - Worker orchestration
   - **Repository Layer**: `SegmentRepository` (from Story 2.5)
   - **Pipeline Layer**: `app/services/transcriber.py` - faster-whisper transcription logic

2. **Worker Pattern**
   - Polls queue using `queue_service.dequeue("asr")`
   - Implements graceful shutdown on SIGTERM/SIGINT
   - Heartbeat/keepalive to prevent stale worker detection
   - Processes segments sequentially (GPU memory constraint)

3. **Database Naming**
   - Table: `pipeline_segments` stores ASR results
   - Fields: `asr_text`, `asr_start`, `asr_end`, `asr_confidence`
   - Status transitions: TRANSCRIBING → CROPPING (or FAILED)

4. **State Machine**
   - Input state: `TRANSCRIBING` (set by Detection Worker)
   - Processing state: `TRANSCRIBING`
   - Output states: `CROPPING` (success) or `FAILED` (error)

5. **Storage Patterns**
   - Downloads from: `jobs/{job_id}/stage1/segment_{index}.mp4` (MinIO)
   - Audio extraction: Temporary WAV files (deleted after transcription)
   - No uploads in this stage (only database updates)

6. **Queue Integration**
   - Polls: `asr` queue
   - On success: marks queue job completed, enqueues `cropping` stage
   - On failure: marks queue job failed (triggers retry)

### Technical Requirements

**ASR Configuration:**
| Parameter | Default | Options | Description |
|-----------|---------|---------|-------------|
| model_size | "base" | tiny, base, small, medium, large-v3 | Whisper model size |
| compute_type | "int8" | int8, float16, int8_float16 | Computation precision |
| beam_size | 5 | 1-10 | Beam search size |
| best_of | 5 | 1-10 | Number of candidates |
| patience | 1.0 | 0.5-2.0 | Beam search patience |
| condition_on_previous_text | true | true, false | Context continuity |
| language | "id" | auto, id, en | Audio language |

**Segment Schema (ASR Results):**
```python
{
    "segment_index": 0,
    "asr_text": "transcribed text content",
    "asr_start": 12.5,  # seconds from segment start
    "asr_end": 18.3,    # seconds from segment start
    "asr_confidence": 0.87,  # average confidence score
    "status": "TRANSCRIBED"
}
```

**Worker Loop:**
```python
while running:
    # 1. Poll queue
    queue_job = await queue_service.dequeue("asr")
    if not queue_job:
        await asyncio.sleep(poll_interval)
        continue
    
    # 2. Get job and segments
    job_id = UUID(queue_job.payload["job_id"])
    segments = await segment_repo.get_by_job_id(job_id)
    
    # 3. Process each segment
    for segment in segments:
        # Download from MinIO
        video_data = await minio_service.download_file(segment.cropped_video_path)
        
        # Extract audio using FFmpeg
        audio_path = await extract_audio(video_data)
        
        # Run faster-whisper transcription
        transcription = await transcriber.transcribe(audio_path)
        
        # Update segment with ASR results
        segment.asr_text = transcription.text
        segment.asr_start = transcription.start
        segment.asr_end = transcription.end
        segment.asr_confidence = transcription.confidence
        
        # Cleanup temp audio file
        await cleanup(audio_path)
    
    # 4. Update job status and queue next stage
    await job_repo.update_status(job_id, "CROPPING")
    await queue_service.enqueue("cropping", {"job_id": str(job_id)})
    await queue_service.mark_completed(queue_job.id)
```

**Error Handling:**
| Error Type | Action | Retry |
|------------|--------|-------|
| Video download fails | Log, mark failed | Yes |
| Audio extraction fails | Log, mark failed | Yes |
| Unsupported codec | Log, mark failed | No (permanent) |
| Transcription timeout | Log, mark failed | Yes (with backoff) |
| GPU OOM | Log, mark failed | Yes (with backoff) |
| Model not loaded | Fatal, exit worker | N/A |

**faster-whisper Model Sizes:**
| Model | Parameters | VRAM Required | Relative Speed |
|-------|------------|---------------|----------------|
| tiny | 39 M | ~1 GB | ~32x |
| base | 74 M | ~1 GB | ~16x |
| small | 244 M | ~2 GB | ~6x |
| medium | 769 M | ~5 GB | ~2x |
| large-v3 | 1550 M | ~10 GB | 1x |

---

## Implementation Guide

### Phase 1: Create Transcriber Service

#### Step 1.1: Create app/services/transcriber.py

```python
"""faster-whisper-based ASR transcription service."""

import os
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, NamedTuple
from dataclasses import dataclass

import ffmpeg
from faster_whisper import WhisperModel

from app.core.config import settings
from app.core.logger import logger
from app.core.exceptions import ProcessingError


class TranscriptionSegment(NamedTuple):
    """Single transcription segment result."""
    start: float  # seconds
    end: float    # seconds
    text: str
    confidence: float


@dataclass
class TranscriptionResult:
    """Complete transcription result for a video segment."""
    segments: List[TranscriptionSegment]
    text: str  # Full concatenated text
    average_confidence: float
    
    @property
    def start(self) -> float:
        """Start time of first segment."""
        return self.segments[0].start if self.segments else 0.0
    
    @property
    def end(self) -> float:
        """End time of last segment."""
        return self.segments[-1].end if self.segments else 0.0


class TranscriberService:
    """
    faster-whisper-based ASR transcription service.
    
    Follows implementation from asr_code.ipynb exactly.
    Loads model once and reuses (singleton pattern).
    Supports configurable model sizes and compute types.
    """
    
    _instance = None
    _model = None
    _model_size = None
    _compute_type = None
    
    # Default configuration
    DEFAULT_MODEL_SIZE = "base"
    DEFAULT_COMPUTE_TYPE = "int8"
    DEFAULT_BEAM_SIZE = 5
    DEFAULT_BEST_OF = 5
    DEFAULT_PATIENCE = 1.0
    DEFAULT_LANGUAGE = "id"
    
    def __new__(cls):
        """Singleton pattern for model reuse."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize transcriber (model loaded lazily)."""
        if self._model_size is None:
            self._model_size = settings.whisper_model_size or self.DEFAULT_MODEL_SIZE
            self._compute_type = settings.whisper_compute_type or self.DEFAULT_COMPUTE_TYPE
    
    def _load_model(self) -> WhisperModel:
        """Load faster-whisper model (cached)."""
        if self._model is None:
            logger.info(
                f"Loading faster-whisper model: {self._model_size} "
                f"(compute_type={self._compute_type})"
            )
            try:
                # Determine device based on compute type
                device = "cuda" if "float" in self._compute_type else "cpu"
                if settings.force_cpu:
                    device = "cpu"
                
                self._model = WhisperModel(
                    self._model_size,
                    device=device,
                    compute_type=self._compute_type,
                    download_root=settings.model_cache_dir or "model_weights"
                )
                logger.info("faster-whisper model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load faster-whisper model: {e}")
                raise ProcessingError(f"ASR model loading failed: {e}")
        return self._model
    
    async def transcribe(
        self,
        audio_path: Path,
        language: str = None,
        beam_size: int = None,
        patience: float = None,
        condition_on_previous_text: bool = None
    ) -> TranscriptionResult:
        """
        Transcribe audio file using faster-whisper.
        
        Args:
            audio_path: Path to audio file (WAV/MP3)
            language: Audio language code (default: "id" for Indonesian)
            beam_size: Beam search size (default: 5)
            patience: Beam search patience (default: 1.0)
            condition_on_previous_text: Use previous text as context (default: True)
            
        Returns:
            TranscriptionResult with segments and metadata
            
        Raises:
            ProcessingError: If transcription fails
        """
        language = language or self.DEFAULT_LANGUAGE
        beam_size = beam_size or self.DEFAULT_BEAM_SIZE
        patience = patience or self.DEFAULT_PATIENCE
        
        if condition_on_previous_text is None:
            condition_on_previous_text = True
        
        model = self._load_model()
        
        try:
            # Run transcription
            segments_gen, info = model.transcribe(
                str(audio_path),
                language=language,
                beam_size=beam_size,
                patience=patience,
                condition_on_previous_text=condition_on_previous_text,
                word_timestamps=False  # Segment-level timestamps
            )
            
            # Collect segments
            segments = []
            total_confidence = 0.0
            segment_count = 0
            full_text_parts = []
            
            for segment in segments_gen:
                # Calculate average confidence for segment
                if segment.words:
                    confidences = [word.probability for word in segment.words]
                    avg_confidence = sum(confidences) / len(confidences)
                else:
                    # Fallback: use heuristic based on no_speech_prob
                    avg_confidence = 1.0 - info.no_speech_prob
                
                transcription_segment = TranscriptionSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                    confidence=avg_confidence
                )
                segments.append(transcription_segment)
                full_text_parts.append(segment.text.strip())
                total_confidence += avg_confidence
                segment_count += 1
            
            # Calculate average confidence
            average_confidence = total_confidence / segment_count if segment_count > 0 else 0.0
            
            result = TranscriptionResult(
                segments=segments,
                text=" ".join(full_text_parts),
                average_confidence=average_confidence
            )
            
            logger.info(
                f"Transcription complete: {segment_count} segments, "
                f"avg_confidence={average_confidence:.2f}"
            )
            return result
            
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise ProcessingError(f"ASR transcription failed: {e}")
    
    def format_segments_txt(
        self,
        result: TranscriptionResult,
        segment_offset: float = 0.0
    ) -> str:
        """
        Format transcription result as segments.txt.
        
        Format: [HH:MM:SS.sss -> HH:MM:SS.sss] transcript text
        
        Args:
            result: TranscriptionResult
            segment_offset: Time offset to add to all timestamps (for job-level timing)
            
        Returns:
            segments.txt formatted string
        """
        lines = []
        for seg in result.segments:
            start = seg.start + segment_offset
            end = seg.end + segment_offset
            start_str = self._format_timestamp(start)
            end_str = self._format_timestamp(end)
            lines.append(f"[{start_str} -> {end_str}] {seg.text}")
        return "\n".join(lines)
    
    def _format_timestamp(self, seconds: float) -> str:
        """Format seconds as HH:MM:SS.sss."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


# Global singleton
transcriber_service = TranscriberService()


def get_transcriber_service() -> TranscriberService:
    """Get transcriber service singleton."""
    return transcriber_service
```

#### Step 1.2: Create app/services/audio_extractor.py

```python
"""Audio extraction service using FFmpeg."""

import tempfile
from pathlib import Path

import ffmpeg

from app.core.logger import logger
from app.core.exceptions import ProcessingError


class AudioExtractor:
    """Extract audio from video files using FFmpeg."""
    
    # Output audio format
    SAMPLE_RATE = 16000  # Whisper expects 16kHz
    CHANNELS = 1         # Mono
    
    async def extract(
        self,
        video_path: Path,
        output_path: Path = None
    ) -> Path:
        """
        Extract audio from video file.
        
        Args:
            video_path: Path to video file
            output_path: Optional output path (creates temp file if None)
            
        Returns:
            Path to extracted WAV file
            
        Raises:
            ProcessingError: If extraction fails
        """
        if output_path is None:
            # Create temp file
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".wav",
                delete=False,
                prefix="asr_audio_"
            )
            output_path = Path(temp_file.name)
            temp_file.close()
        
        try:
            # FFmpeg extraction
            (
                ffmpeg
                .input(str(video_path))
                .output(
                    str(output_path),
                    ac=self.CHANNELS,
                    ar=self.SAMPLE_RATE,
                    acodec="pcm_s16le"  # 16-bit PCM
                )
                .overwrite_output()
                .run(quiet=True)
            )
            
            logger.info(f"Audio extracted: {video_path} -> {output_path}")
            return output_path
            
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8") if e.stderr else str(e)
            
            # Check for unsupported codec
            if "codec" in stderr.lower() or "codec not found" in stderr.lower():
                raise ProcessingError(
                    f"Audio codec not supported: {stderr}",
                    permanent=True
                )
            
            raise ProcessingError(f"Audio extraction failed: {stderr}")
        
        except Exception as e:
            raise ProcessingError(f"Audio extraction failed: {e}")


# Global instance
audio_extractor = AudioExtractor()


def get_audio_extractor() -> AudioExtractor:
    """Get audio extractor instance."""
    return audio_extractor
```

### Phase 2: Create ASR Worker

#### Step 2.1: Create app/services/asr_worker.py

```python
"""ASR worker for transcribing video segments from queue."""

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
from app.services.transcriber import get_transcriber_service, TranscriptionResult
from app.services.audio_extractor import get_audio_extractor


class ASRWorker:
    """
    Background worker for faster-whisper ASR transcription.
    
    Polls the ASR queue, downloads Stage 1 segments from MinIO,
    extracts audio, runs transcription, updates segment records,
    and queues the Cropping stage.
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
        self.transcriber = get_transcriber_service()
        self.audio_extractor = get_audio_extractor()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("ASRWorker received shutdown signal")
        self.running = False
    
    async def start(self):
        """Start the worker loop."""
        logger.info("ASRWorker starting...")
        self.running = True
        
        while self.running:
            try:
                # Poll for jobs
                queue_job = await queue_service.dequeue("asr")
                
                if queue_job:
                    await self._process_job(queue_job)
                else:
                    # No jobs available, wait before polling again
                    await asyncio.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"Unexpected error in worker loop: {e}")
                await asyncio.sleep(self.poll_interval)
        
        logger.info("ASRWorker stopped")
    
    async def _process_job(self, queue_job: QueueJob):
        """Process a single ASR job."""
        job_id = UUID(queue_job.payload["job_id"])
        logger.info(f"Processing ASR job: {job_id}")
        
        async with get_db_session() as db:
            job_repo = JobRepository(db)
            segment_repo = SegmentRepository(db)
            
            try:
                # 1. Update job status to TRANSCRIBING
                await job_repo.update_status(job_id, "TRANSCRIBING")
                
                # 2. Get all segments for this job
                segments = await segment_repo.get_by_job_id(job_id)
                if not segments:
                    raise ProcessingError("No segments found for job")
                
                logger.info(f"Processing {len(segments)} segments for job {job_id}")
                
                # 3. Process each segment
                all_low_confidence = True
                for segment in segments:
                    success = await self._process_segment(
                        db, job_id, segment
                    )
                    if success and segment.asr_confidence >= 0.5:
                        all_low_confidence = False
                
                # 4. Check if all segments failed or have low confidence
                if all_low_confidence:
                    logger.warning(
                        f"All segments have low confidence for job {job_id}"
                    )
                
                # 5. Update job status and queue Cropping stage
                await job_repo.update_status(job_id, "CROPPING")
                await queue_service.enqueue(
                    "cropping",
                    {"job_id": str(job_id)},
                    db=db
                )
                await queue_service.mark_completed(queue_job.id, db=db)
                
                logger.info(f"ASR completed for job {job_id}")
                
            except asyncio.TimeoutError:
                logger.error(f"ASR timeout for job {job_id}")
                await self._handle_failure(db, job_repo, queue_job, "Processing timeout")
                
            except ProcessingError as e:
                if getattr(e, "permanent", False):
                    logger.error(f"ASR permanent failure for job {job_id}: {e}")
                    await self._handle_failure(db, job_repo, queue_job, str(e), permanent=True)
                else:
                    logger.error(f"ASR failed for job {job_id}: {e}")
                    await self._handle_failure(db, job_repo, queue_job, str(e))
                
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job_id}")
                await self._handle_failure(
                    db, job_repo, queue_job, f"Internal error: {e}"
                )
                raise  # Re-raise to trigger retry
    
    async def _process_segment(
        self,
        db: AsyncSession,
        job_id: UUID,
        segment: PipelineSegment
    ) -> bool:
        """
        Process a single segment for ASR.
        
        Returns:
            True if transcription succeeded, False otherwise
        """
        segment_id = segment.id
        segment_index = segment.segment_index
        
        logger.info(f"Processing segment {segment_index} for job {job_id}")
        
        audio_path = None
        
        try:
            # 1. Download segment from MinIO
            video_data = await self._download_segment(segment.cropped_video_path)
            
            # 2. Save to temp file
            video_path = await self._save_temp_video(video_data, segment_index)
            
            # 3. Extract audio
            audio_path = await self.audio_extractor.extract(video_path)
            
            # 4. Run transcription (with timeout)
            result = await asyncio.wait_for(
                self.transcriber.transcribe(audio_path),
                timeout=self.timeout_seconds
            )
            
            # 5. Update segment record
            segment.asr_text = result.text
            segment.asr_start = result.start
            segment.asr_end = result.end
            segment.asr_confidence = result.average_confidence
            
            if result.average_confidence < 0.5:
                logger.warning(
                    f"Low confidence ({result.average_confidence:.2f}) "
                    f"for segment {segment_index}"
                )
            
            await db.flush()
            
            logger.info(
                f"Segment {segment_index} transcribed: "
                f"{len(result.segments)} segments, "
                f"confidence={result.average_confidence:.2f}"
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to process segment {segment_index}: {e}")
            # Mark segment as failed but continue with others
            segment.asr_text = None
            segment.asr_confidence = 0.0
            return False
            
        finally:
            # Cleanup temp files
            await self._cleanup_temp_files(video_path, audio_path)
    
    async def _download_segment(self, object_name: str) -> bytes:
        """Download segment from MinIO."""
        try:
            return await self.minio_service.download_file(object_name)
        except Exception as e:
            raise ProcessingError(f"Failed to download segment: {e}")
    
    async def _save_temp_video(self, video_data: bytes, segment_index: int) -> Path:
        """Save video data to temporary file."""
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp4",
            delete=False,
            prefix=f"asr_segment_{segment_index}_"
        )
        temp_file.write(video_data)
        temp_file.close()
        return Path(temp_file.name)
    
    async def _cleanup_temp_files(
        self,
        video_path: Optional[Path],
        audio_path: Optional[Path]
    ):
        """Clean up temporary files."""
        for path in [video_path, audio_path]:
            if path and path.exists():
                try:
                    path.unlink()
                except OSError as e:
                    logger.warning(f"Failed to cleanup temp file {path}: {e}")
    
    async def _handle_failure(
        self,
        db: AsyncSession,
        job_repo: JobRepository,
        queue_job: QueueJob,
        error_message: str,
        permanent: bool = False
    ):
        """Handle job failure - update status and mark queue job failed."""
        job_id = UUID(queue_job.payload["job_id"])
        await job_repo.update_status(job_id, "FAILED", error_message)
        await queue_service.mark_failed(queue_job, error_message, db=db)


# Global worker instance
asr_worker: Optional[ASRWorker] = None


def get_asr_worker() -> ASRWorker:
    """Get or create ASR worker singleton."""
    global asr_worker
    if asr_worker is None:
        asr_worker = ASRWorker()
    return asr_worker


async def run_asr_worker():
    """Entry point for running the worker."""
    worker = get_asr_worker()
    await worker.start()
```

### Phase 3: Create Worker Entry Point

#### Step 3.1: Create run_asr_worker.py

```python
#!/usr/bin/env python
"""Entry point for running the ASR worker."""

import asyncio
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.asr_worker import run_asr_worker


if __name__ == "__main__":
    try:
        asyncio.run(run_asr_worker())
    except KeyboardInterrupt:
        print("Worker stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}")
        sys.exit(1)
```

### Phase 4: Configuration Updates

#### Step 4.1: Update app/core/config.py

Add ASR-specific settings:

```python
# ASR Configuration
WHISPER_MODEL_SIZE: str = "base"  # tiny, base, small, medium, large-v3
WHISPER_COMPUTE_TYPE: str = "int8"  # int8, float16, int8_float16
WHISPER_BEAM_SIZE: int = 5
WHISPER_LANGUAGE: str = "id"  # Indonesian
MODEL_CACHE_DIR: str = "model_weights"
FORCE_CPU: bool = False  # Set True to disable GPU even if available
```

---

## Tasks / Subtasks

- [x] Task 1: Update ProcessingError to support permanent errors (AC: Error Handling)
  - [ ] Add `permanent` attribute to ProcessingError
- [x] Task 2: Update Configuration for ASR settings (AC: ASR Configuration)
  - [ ] Add whisper_model_size, whisper_compute_type, etc. to Settings
- [x] Task 3: Create Audio Extractor Service (AC: ASR Worker)
  - [ ] Create app/services/audio_extractor.py with FFmpeg integration
  - [ ] Handle unsupported codec errors as permanent
- [x] Task 4: Create Transcriber Service (AC: ASR Worker, ASR Configuration)
  - [ ] Create app/services/transcriber.py with faster-whisper integration
  - [ ] Implement singleton pattern for model reuse
  - [ ] Support configurable model sizes and compute types
  - [ ] Calculate confidence scores
  - [ ] Format output as segments.txt
- [x] Task 5: Create ASR Worker (AC: ASR Worker)
  - [ ] Create app/services/asr_worker.py with worker loop
  - [ ] Implement graceful shutdown
  - [ ] Download segments from MinIO
  - [ ] Process segments sequentially
  - [ ] Update segment records with ASR results
  - [ ] Handle low confidence flagging
  - [ ] Queue next stage (cropping) on success
- [x] Task 6: Create Worker Entry Point (AC: ASR Worker)
  - [ ] Create run_asr_worker.py script
- [x] Task 7: Create Unit Tests (AC: All)
  - [ ] Test audio extractor
  - [ ] Test transcriber service
  - [ ] Test ASR worker
- [x] Task 8: Run Validations
- [x] Task 9: Code Review Fixes (BH-1 to BH-5)
- [x] Task 10: Code Review Fixes (ECH-1 to ECH-5)
- [x] Task 11: Mark Story as DONE
  - [ ] Run tests
  - [ ] Check for regressions

## Testing Strategy

### Unit Tests

```python
# tests/unit/services/test_transcriber.py

class TestTranscriberService:
    """Test suite for faster-whisper transcriber."""
    
    def test_singleton_pattern(self):
        """Test transcriber is singleton."""
        
    async def test_transcribe_returns_result(self):
        """Test transcribe returns TranscriptionResult."""
        
    async def test_transcribe_respects_language(self):
        """Test language parameter is used."""
        
    async def test_format_segments_txt(self):
        """Test segments.txt formatting."""
        
    async def test_low_confidence_detection(self):
        """Test confidence scores are calculated."""


# tests/unit/services/test_audio_extractor.py

class TestAudioExtractor:
    """Test suite for audio extraction."""
    
    async def test_extract_creates_wav(self):
        """Test extraction creates valid WAV file."""
        
    async def test_extract_respects_sample_rate(self):
        """Test output is 16kHz."""
        
    async def test_unsupported_codec_raises_error(self):
        """Test unsupported codec raises permanent error."""


# tests/unit/services/test_asr_worker.py

class TestASRWorker:
    """Test suite for ASR worker."""
    
    async def test_process_job_success(self):
        """Test successful job processing flow."""
        
    async def test_process_job_no_segments(self):
        """Test handling of no segments."""
        
    async def test_process_segment_low_confidence(self):
        """Test low confidence flagging."""
        
    async def test_process_job_download_failure(self):
        """Test handling of download failure."""
```

### Integration Tests

```python
# tests/integration/test_asr_pipeline.py

async def test_end_to_end_asr():
    """
    Test full flow:
    1. Create job with segments
    2. Queue ASR job
    3. Worker processes
    4. Segments updated with ASR results
    5. Cropping job queued
    """
```

---

## Dependencies

**Python Packages:**
- `faster-whisper>=0.10.0` - ASR transcription
- `ffmpeg-python>=0.2.0` - Audio extraction wrapper
- `numpy>=1.24.0` - Array operations

**System Packages:**
- `ffmpeg` - Audio extraction

**Model Files:**
- faster-whisper downloads models automatically on first use
- Cache location: `model_weights/` or configured via `MODEL_CACHE_DIR`

---

## Open Questions

1. **Model Caching**: Should we pre-download models during Docker build?
2. **GPU Memory**: Should we process segments in batches or sequentially?
3. **Language Detection**: Should we auto-detect language or always use Indonesian?
4. **Confidence Threshold**: Is 0.5 the right threshold for low-confidence flagging?
5. **Audio Quality**: Should we normalize audio before transcription?

---

## References

- asr_code.ipynb - Original faster-whisper implementation
- Architecture: `docs/architecture.md` - Pipeline State Machine
- Story 2.1: Database schema for `pipeline_segments`
- Story 2.2: MinIO download functionality
- Story 2.4: Queue service usage patterns
- Story 2.5: Detection Worker pattern (follow similar structure)


---

## Dev Agent Record

### Agent Model Used

Kimi Code CLI (kimi-k2-0715-preview)

### Implementation Plan

**Task Execution Summary:**
1. **Task 1**: Added `permanent` attribute to `ProcessingError` exception class to support permanent vs retryable errors
2. **Task 2**: Added ASR configuration settings to `app/core/config.py` (whisper_model_size, whisper_compute_type, etc.)
3. **Task 3**: Created `app/services/audio_extractor.py` - FFmpeg-based audio extraction service
4. **Task 4**: Created `app/services/transcriber.py` - faster-whisper integration with singleton pattern
5. **Task 5**: Created `app/services/asr_worker.py` - ASR worker with queue integration
6. **Task 6**: Created `run_asr_worker.py` - Entry point script for running the worker
7. **Task 7**: Created comprehensive unit tests for all components
8. **Task 8**: Ran tests - all 51 tests pass (29 new tests + 22 existing queue tests)

### Debug Log References

- No significant debug issues encountered
- All tests pass successfully
- Pre-existing CUDA version conflicts in unrelated tests (test_detection_worker.py, test_jbi_detector.py) - not related to this story

### Completion Notes List

- ✅ ProcessingError now supports permanent error flag
- ✅ Audio extraction service implemented with FFmpeg subprocess
- ✅ Transcriber service implements singleton pattern for model reuse
- ✅ ASR worker implements graceful shutdown on SIGTERM/SIGINT
- ✅ Worker downloads segments from MinIO, extracts audio, transcribes, updates DB
- ✅ Low confidence segments (< 0.5) are flagged in logs
- ✅ Unsupported codec errors marked as permanent (no retry)
- ✅ Worker queues next stage (cropping) on success
- ✅ All components have comprehensive unit tests
- ✅ Tests verify singleton pattern, error handling, and edge cases

### Code Review Fixes (Applied)

**BH-1: Thread Safety Fix**
- Added `threading.Lock` to `TranscriberService` singleton pattern
- Implemented double-checked locking in `__new__` method

**BH-2: FFmpeg Availability Check**
- Added `shutil.which("ffmpeg")` check in `AudioExtractor.__init__`
- Raises permanent `ProcessingError` if FFmpeg not found

**BH-3: Device Selection Logic**
- Fixed fragile `"float" in compute_type` check
- Now uses explicit check: `compute_type in ("float16", "int8_float16")`
- Pure `int8` now correctly uses CPU

**BH-4: Exception Re-raise Fix**
- Removed `raise` after `_handle_failure` in `_process_job`
- Prevents double-logging in worker loop
- Failure handling is complete via `queue_service.mark_failed`

**BH-5: Temp File Creation Error Handling**
- Added try/except around `NamedTemporaryFile` creation
- Raises `ProcessingError` for disk full, permission denied, etc.
- Marked as retryable (not permanent) since disk space may free up

**ECH-1: Robust Temp File Cleanup**
- Changed from individual path variables to `temp_files` list tracking
- All temp files are tracked immediately after creation
- Cleanup loop handles all files even if some were never assigned

**ECH-2: Timestamp Validation**
- Added validation for ASR end timestamp (warns if > 1 hour)
- Prevents storing obviously invalid timestamps

**ECH-3: Empty Transcription Handling**
- Explicitly check if `result.segments` is empty
- Sets empty text, zero timestamps, and flags for review
- Logs warning for visibility

**ECH-4: DB Flag for ASR Review**
- Added `asr_review_flag` boolean column to `pipeline_segments` table
- Set to `True` for: low confidence (< 0.5), failed segments, empty transcription
- Created Alembic migration `009_add_asr_review_flag.py`
- Added index for efficient filtering

**ECH-5: Async-Safe Shutdown**
- Changed from `self.running` boolean to `asyncio.Event`
- New `_shutdown_event` allows clean interruption of `asyncio.sleep`
- Worker loop uses `wait_for` with shutdown event for immediate response
- Property `running` returns `not self._shutdown_event.is_set()`

---

### Final Summary

**Story Status:** ✅ DONE

**All Acceptance Criteria Met:**
- ✅ Downloads segments from MinIO
- ✅ Uses faster-whisper for transcription (from asr_code.ipynb)
- ✅ Supports configurable model sizes (tiny/base/small/medium/large-v3)
- ✅ Supports configurable compute types (int8/float16/int8_float16)
- ✅ Saves asr_text, asr_start, asr_end, asr_confidence
- ✅ Saves confidence scores (FR49)
- ✅ Updates job status to CROPPING
- ✅ Queues next stage for timestamp-based cropping
- ✅ Low confidence segments flagged in DB (asr_review_flag)
- ✅ Unsupported codec errors marked as permanent (no retry)

**Code Review:**
- All BH (Blind Hunter) findings addressed (BH-1 to BH-5)
- All ECH (Edge Case Hunter) findings addressed (ECH-1 to ECH-5)
- 51 tests passing (29 new + 22 existing)

**Ready for:** Story 2.7 - Cropping Worker

### File List

**New Files:**
- `app/services/audio_extractor.py` - Audio extraction service
- `app/services/transcriber.py` - faster-whisper transcription service
- `app/services/asr_worker.py` - ASR worker implementation
- `run_asr_worker.py` - Worker entry point script
- `tests/unit/services/test_audio_extractor.py` - Audio extractor tests
- `tests/unit/services/test_transcriber.py` - Transcriber service tests
- `tests/unit/services/test_asr_worker.py` - ASR worker tests

**Modified Files:**
- `app/core/exceptions.py` - Added `permanent` attribute to ProcessingError
- `app/core/config.py` - Added ASR configuration settings
- `app/services/transcriber.py` - Fixed thread safety (BH-1) and device selection (BH-3)
- `app/services/audio_extractor.py` - Added FFmpeg check (BH-2)
- `app/services/asr_worker.py` - Fixed exception handling (BH-4, ECH-1, ECH-3, ECH-5) and temp file errors (BH-5, ECH-1)
- `app/db/models/pipeline.py` - Added `asr_review_flag` column (ECH-4)
- `alembic/versions/009_add_asr_review_flag.py` - Migration for new column (ECH-4)
- `jbi-service/_bmad-output/implementation-artifacts/sprint-status.yaml` - Updated story status

---

## Change Log

| Date | Change |
|------|--------|
| 2026-03-24 | Story created with comprehensive implementation guide |
| 2026-03-24 | Task 1-2: Core configuration and exception updates |
| 2026-03-24 | Task 3-6: Core services and worker implementation |
| 2026-03-24 | Task 7: Unit tests created (29 tests total) |
| 2026-03-24 | Task 8: All tests pass, story marked for review |
| 2026-03-24 | Task 9: Code review fixes BH-1 to BH-5 applied |
| 2026-03-24 | Task 10: Code review fixes ECH-1 to ECH-5 applied |
| 2026-03-24 | Story marked as DONE - All ACs met, all tests pass |
