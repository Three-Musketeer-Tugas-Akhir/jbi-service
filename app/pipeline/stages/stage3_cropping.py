"""
Stage 3: Timestamp-based Cropping Pipeline

Re-crops Stage 1 videos using ASR timestamps with JBI buffer.
Formula: jbi_start = max(0, asr_start - 2), jbi_end = min(duration, asr_end + 2)
"""

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from app.pipeline.utils.video import get_video_duration, run_ffmpeg_crop

logger = logging.getLogger(__name__)


@dataclass
class CroppingInput:
    """Input for Stage 2 cropping - combines Stage 1 video with ASR timestamps."""
    segment_id: str  # Unique segment identifier
    stage1_video_path: str  # Path to Stage 1 cropped video (bbox-based)
    asr_start: float  # ASR segment start time (seconds)
    asr_end: float  # ASR segment end time (seconds)
    transcript: str  # ASR transcript text


@dataclass
class CroppingResult:
    """Result of Stage 2 cropping."""
    segment_id: str
    success: bool
    stage2_video_path: Optional[str]  # Path to output video
    jbi_start: float  # Final JBI start time (with buffer)
    jbi_end: float  # Final JBI end time (with buffer)
    transcript: str
    error: Optional[str] = None


class TimestampBasedCropper:
    """
    Stage 2 cropper that creates final JBI clips using ASR timestamps.
    
    JBI Buffer Formula (FR6a):
    - jbi_start = max(0, asr_start - 2)
    - jbi_end = min(video_duration, asr_end + 2)
    """
    
    BUFFER_SECONDS = 2.0
    MIN_CLIP_DURATION = 1.0  # Minimum 1 second clip
    
    def __init__(self):
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None
    
    def calculate_jbi_timestamps(
        self,
        asr_start: float,
        asr_end: float,
        video_duration: float
    ) -> tuple[float, float]:
        """
        Calculate JBI timestamps with buffer.
        
        Formula:
        - jbi_start = max(0, asr_start - 2)
        - jbi_end = min(video_duration, asr_end + 2)
        
        Args:
            asr_start: ASR segment start time in seconds
            asr_end: ASR segment end time in seconds
            video_duration: Total video duration in seconds
            
        Returns:
            Tuple of (jbi_start, jbi_end)
        """
        jbi_start = max(0.0, asr_start - self.BUFFER_SECONDS)
        jbi_end = min(video_duration, asr_end + self.BUFFER_SECONDS)
        
        # Ensure minimum duration
        if jbi_end - jbi_start < self.MIN_CLIP_DURATION:
            logger.warning(
                f"JBI duration {jbi_end - jbi_start:.2f}s is below minimum, "
                f"clamping to {self.MIN_CLIP_DURATION}s"
            )
            jbi_end = min(video_duration, jbi_start + self.MIN_CLIP_DURATION)
        
        return jbi_start, jbi_end
    
    async def crop_segment(
        self,
        input_data: CroppingInput,
        output_dir: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> CroppingResult:
        """
        Crop a single segment using ASR timestamps with JBI buffer.
        
        Args:
            input_data: CroppingInput with stage1 video and ASR timestamps
            output_dir: Directory to save cropped video
            progress_callback: Optional callback(segment_id, progress_0_to_1)
            
        Returns:
            CroppingResult with output path or error
        """
        segment_id = input_data.segment_id
        
        try:
            if progress_callback:
                progress_callback(segment_id, 0.1)
            
            # Validate input video exists
            stage1_path = Path(input_data.stage1_video_path)
            if not stage1_path.exists():
                raise FileNotFoundError(
                    f"Stage 1 video not found: {input_data.stage1_video_path}"
                )
            
            # Get video duration
            video_duration = await get_video_duration(str(stage1_path))
            
            if progress_callback:
                progress_callback(segment_id, 0.3)
            
            # Calculate JBI timestamps with buffer
            jbi_start, jbi_end = self.calculate_jbi_timestamps(
                input_data.asr_start,
                input_data.asr_end,
                video_duration
            )
            
            logger.info(
                f"Segment {segment_id}: ASR [{input_data.asr_start:.2f} -> "
                f"{input_data.asr_end:.2f}] -> JBI [{jbi_start:.2f} -> {jbi_end:.2f}]"
            )
            
            # Validate timestamps
            if jbi_start >= jbi_end:
                raise ValueError(
                    f"Invalid time range: start ({jbi_start:.2f}) >= end ({jbi_end:.2f})"
                )
            
            if jbi_start >= video_duration:
                raise ValueError(
                    f"Start time {jbi_start:.2f} exceeds video duration {video_duration:.2f}"
                )
            
            if progress_callback:
                progress_callback(segment_id, 0.5)
            
            # Generate output filename: {segment_id}_stage2.mp4
            output_path = Path(output_dir) / f"{segment_id}_stage2.mp4"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Run FFmpeg crop with precise seeking
            # Use -ss before -i for input seeking (faster, more accurate)
            success = await run_ffmpeg_crop(
                input_path=str(stage1_path),
                output_path=str(output_path),
                start_time=jbi_start,
                end_time=jbi_end,
                use_input_seeking=True
            )
            
            if progress_callback:
                progress_callback(segment_id, 1.0)
            
            if not success:
                raise RuntimeError("FFmpeg cropping failed")
            
            return CroppingResult(
                segment_id=segment_id,
                success=True,
                stage2_video_path=str(output_path),
                jbi_start=jbi_start,
                jbi_end=jbi_end,
                transcript=input_data.transcript
            )
            
        except Exception as e:
            logger.error(f"Failed to crop segment {segment_id}: {e}")
            return CroppingResult(
                segment_id=segment_id,
                success=False,
                stage2_video_path=None,
                jbi_start=0.0,
                jbi_end=0.0,
                transcript=input_data.transcript,
                error=str(e)
            )


async def run_cropping(
    inputs: List[CroppingInput],
    output_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> List[CroppingResult]:
    """
    Run Stage 2 cropping on multiple segments.
    
    Args:
        inputs: List of CroppingInput for each segment
        output_dir: Directory to save all cropped videos
        progress_callback: Optional callback(completed_count, total_count)
        
    Returns:
        List of CroppingResult in same order as inputs
    """
    cropper = TimestampBasedCropper()
    results: List[CroppingResult] = []
    
    total = len(inputs)
    logger.info(f"Starting Stage 2 cropping for {total} segments")
    
    for i, inp in enumerate(inputs):
        result = await cropper.crop_segment(inp, output_dir)
        results.append(result)
        
        if progress_callback:
            progress_callback(i + 1, total)
    
    # Log summary
    success_count = sum(1 for r in results if r.success)
    logger.info(
        f"Stage 2 cropping complete: {success_count}/{total} successful"
    )
    
    return results
