"""
Stage 3: Timestamp-based Cropping Pipeline

Re-crops Stage 1 videos using ASR timestamps with JBI buffer.
Formula: jbi_start = max(0, asr_start - 2), jbi_end = min(duration, asr_end + 2)
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Protocol

from app.pipeline.utils.video import get_video_duration, run_ffmpeg_crop

logger = logging.getLogger(__name__)


# Type aliases for callback functions
class SegmentProgressCallback(Protocol):
    """Callback type for segment progress updates.
    
    Args:
        segment_id: Unique segment identifier
        progress: Progress value from 0.0 to 1.0
    """
    def __call__(self, segment_id: str, progress: float) -> None: ...


class BatchProgressCallback(Protocol):
    """Callback type for batch progress updates.
    
    Args:
        completed: Number of completed items
        total: Total number of items
    """
    def __call__(self, completed: int, total: int) -> None: ...


@dataclass(frozen=True)
class CroppingInput:
    """Input for Stage 2 cropping - combines Stage 1 video with ASR timestamps.
    
    Attributes:
        segment_id: Unique segment identifier (UUID as string)
        stage1_video_path: Path to Stage 1 cropped video (bbox-based)
        asr_start: ASR segment start time in seconds (relative to Stage 1 video)
        asr_end: ASR segment end time in seconds (relative to Stage 1 video)
        transcript: ASR transcript text for this segment
    """
    segment_id: str
    stage1_video_path: str
    asr_start: float
    asr_end: float
    transcript: str


@dataclass(frozen=True)
class CroppingResult:
    """Result of Stage 2 cropping operation.
    
    Attributes:
        segment_id: Unique segment identifier
        success: True if cropping succeeded
        stage2_video_path: Path to output video (None if failed)
        jbi_start: Final JBI start time with buffer applied
        jbi_end: Final JBI end time with buffer applied
        transcript: Transcript text from input
        error: Error message if success is False
    """
    segment_id: str
    success: bool
    stage2_video_path: Optional[str]
    jbi_start: float
    jbi_end: float
    transcript: str
    error: Optional[str] = None


class TimestampBasedCropper:
    """
    Stage 2 cropper that creates final JBI clips using ASR timestamps.
    
    JBI Buffer Formula (FR6a):
    - jbi_start = max(0, asr_start - 2)
    - jbi_end = min(video_duration, asr_end + 2)
    
    Attributes:
        BUFFER_SECONDS: Seconds to add before/after ASR timestamps (default: 2.0)
        MIN_CLIP_DURATION: Minimum clip duration in seconds (default: 1.0)
    """
    
    #: Seconds of buffer to add before ASR start and after ASR end
    BUFFER_SECONDS: float = 2.0
    
    #: Minimum duration for output clips (prevents sub-second clips)
    MIN_CLIP_DURATION: float = 1.0
    
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
                "JBI duration %.2fs is below minimum, clamping to %.2fs",
                jbi_end - jbi_start, self.MIN_CLIP_DURATION
            )
            jbi_end = min(video_duration, jbi_start + self.MIN_CLIP_DURATION)
        
        return jbi_start, jbi_end
    
    async def crop_segment(
        self,
        input_data: CroppingInput,
        output_dir: str,
        progress_callback: Optional[SegmentProgressCallback] = None
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
            
            # Validate input video exists (with race condition handling)
            stage1_path = Path(input_data.stage1_video_path)
            if not stage1_path.exists():
                raise FileNotFoundError(
                    f"Stage 1 video not found: {input_data.stage1_video_path}"
                )
            
            # Also check readability
            if not stage1_path.is_file():
                raise ValueError(f"Path is not a file: {input_data.stage1_video_path}")
            
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
                "Segment %s: ASR [%.2f -> %.2f] -> JBI [%.2f -> %.2f]",
                segment_id, input_data.asr_start, input_data.asr_end,
                jbi_start, jbi_end
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
            logger.error("Failed to crop segment %s: %s", segment_id, e)
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
    progress_callback: Optional[BatchProgressCallback] = None
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
    logger.info("Starting Stage 2 cropping for %d segments", total)
    
    for i, inp in enumerate(inputs):
        result = await cropper.crop_segment(inp, output_dir)
        results.append(result)
        
        if progress_callback:
            progress_callback(i + 1, total)
    
    # Log summary
    success_count = sum(1 for r in results if r.success)
    logger.info(
        "Stage 2 cropping complete: %d/%d successful", success_count, total
    )
    
    return results
