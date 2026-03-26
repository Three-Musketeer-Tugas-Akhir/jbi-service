"""
Stage 2: Automatic Speech Recognition Pipeline

Extracts audio from video segments and transcribes using Whisper.
Pure ML processing - no database access, no HTTP concerns.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from app.core.exceptions import ProcessingError
from app.pipeline.models.transcriber import get_transcriber_service
from app.pipeline.utils.video import extract_audio
from app.pipeline.utils.storage import download_video

logger = logging.getLogger(__name__)


@dataclass
class ASRUtterance:
    """Individual utterance from ASR transcription."""
    utterance_index: int
    text: str
    start: float  # Relative to segment start
    end: float    # Relative to segment start
    confidence: float


@dataclass
class ASRResult:
    """Result from ASR processing of a segment."""
    segment_index: int
    text: str
    start: float
    end: float
    confidence: float
    review_flag: bool
    utterances: List[ASRUtterance]  # Individual utterances


@dataclass
class ASRSegmentInput:
    """Input for ASR processing."""
    segment_index: int
    video_path: str  # Can be local path or MinIO object key
    is_local: bool = False


async def run_asr(
    segments: List[ASRSegmentInput],
    timeout_seconds: int = 1800,
    progress_callback=None
) -> List[ASRResult]:
    """
    Run ASR on video segments.
    
    Args:
        segments: List of segment inputs (local paths or MinIO keys)
        timeout_seconds: Maximum time per segment
        progress_callback: Optional callback(current, total)
        
    Returns:
        List of ASR results with text, timestamps, and confidence
        
    Raises:
        ProcessingError: If ASR fails
    """
    transcriber = get_transcriber_service()
    results = []
    
    for idx, segment_input in enumerate(segments):
        try:
            result = await _process_single_segment(
                segment_input=segment_input,
                transcriber=transcriber,
                timeout_seconds=timeout_seconds
            )
            results.append(result)
            
            if progress_callback:
                progress_callback(idx + 1, len(segments))
                
        except Exception as e:
            logger.error(f"Failed to process segment {segment_input.segment_index}: {e}")
            # Add failed result
            results.append(ASRResult(
                segment_index=segment_input.segment_index,
                text="",
                start=0.0,
                end=0.0,
                confidence=0.0,
                review_flag=True,  # Flag failed segments for review
                utterances=[]  # Empty utterances on failure
            ))
    
    return results


async def _process_single_segment(
    segment_input: ASRSegmentInput,
    transcriber,
    timeout_seconds: int
) -> ASRResult:
    """
    Process a single segment for ASR.
    
    Args:
        segment_input: Segment input data
        transcriber: Transcriber service instance
        timeout_seconds: Timeout for transcription
        
    Returns:
        ASRResult with transcription data
    """
    segment_index = segment_input.segment_index
    temp_files = []
    
    try:
        # 1. Get video (download if needed)
        if segment_input.is_local:
            video_path = Path(segment_input.video_path)
        else:
            # Download from MinIO
            video_data = await download_video(segment_input.video_path)
            video_path = await _save_temp_video(video_data, segment_index)
            temp_files.append(video_path)
        
        # 2. Extract audio
        audio_path = await extract_audio(str(video_path))
        temp_files.append(Path(audio_path))
        
        # 3. Run transcription (with timeout)
        result = await asyncio.wait_for(
            transcriber.transcribe(audio_path),
            timeout=timeout_seconds
        )
        
        # 4. Handle empty transcription
        if not result.segments:
            logger.warning(f"No speech detected in segment {segment_index}")
            return ASRResult(
                segment_index=segment_index,
                text="",
                start=0.0,
                end=0.0,
                confidence=0.0,
                review_flag=True,  # Flag for review
                utterances=[]  # Empty utterances
            )
        
        # 5. Check confidence
        review_flag = result.average_confidence < 0.5
        if review_flag:
            logger.warning(
                f"Low confidence ({result.average_confidence:.2f}) "
                f"for segment {segment_index}"
            )
        
        # 6. Validate timestamps
        if result.end > 3600:  # 1 hour max for a single segment
            logger.warning(
                f"ASR end timestamp ({result.end}s) exceeds 1 hour for segment {segment_index}"
            )
        
        # Build individual utterances list (matching notebook format)
        utterances = [
            ASRUtterance(
                utterance_index=idx,
                text=seg.text,
                start=seg.start,
                end=seg.end,
                confidence=seg.confidence
            )
            for idx, seg in enumerate(result.segments)
        ]
        
        return ASRResult(
            segment_index=segment_index,
            text=result.text,
            start=result.start,
            end=result.end,
            confidence=result.average_confidence,
            review_flag=review_flag,
            utterances=utterances
        )
        
    except asyncio.TimeoutError:
        logger.error(f"ASR timeout for segment {segment_index}")
        raise ProcessingError(f"ASR timeout for segment {segment_index}")
        
    except Exception as e:
        logger.error(f"ASR failed for segment {segment_index}: {e}")
        raise ProcessingError(f"ASR failed for segment {segment_index}: {e}")
        
    finally:
        # Cleanup temp files
        for temp_file in temp_files:
            if temp_file and temp_file.exists():
                try:
                    temp_file.unlink()
                except OSError as e:
                    logger.warning(f"Failed to cleanup temp file {temp_file}: {e}")


async def _save_temp_video(video_data: bytes, segment_index: int) -> Path:
    """Save video data to temporary file."""
    try:
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp4",
            delete=False,
            prefix=f"asr_segment_{segment_index}_"
        )
        temp_file.write(video_data)
        temp_file.close()
        return Path(temp_file.name)
    except (OSError, IOError) as e:
        raise ProcessingError(
            f"Failed to create temp file for segment {segment_index}: {e}"
        )
