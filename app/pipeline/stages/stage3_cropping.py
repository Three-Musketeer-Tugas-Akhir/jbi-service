"""
Stage 3: Video Cropping Pipeline

Crops detected JBI segments from original video with buffer.
Pure ML processing - no database access, no HTTP concerns.
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass

from app.core.config import settings
from app.core.exceptions import ProcessingError
from app.pipeline.models.cropper import crop_video_segment

logger = logging.getLogger(__name__)


@dataclass
class CroppingInput:
    """Input for cropping a segment."""
    segment_index: int
    video_path: str  # Original video path
    bbox_data: Dict[str, float]  # x, y, width, height
    jbi_start: float  # Start time with JBI buffer
    jbi_end: float  # End time with JBI buffer


@dataclass
class CroppingResult:
    """Result from cropping a segment."""
    segment_index: int
    cropped_video_path: str
    success: bool
    error_message: Optional[str] = None


async def run_cropping(
    segments: List[CroppingInput],
    output_dir: str,
    progress_callback=None
) -> List[CroppingResult]:
    """
    Crop video segments with JBI buffer.
    
    Args:
        segments: List of segments to crop
        output_dir: Directory for output files
        progress_callback: Optional callback(current, total)
        
    Returns:
        List of cropping results with output paths
        
    Raises:
        ProcessingError: If cropping fails
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    for idx, segment in enumerate(segments):
        try:
            result = await _process_single_segment(
                segment=segment,
                output_path=output_path
            )
            results.append(result)
            
            if progress_callback:
                progress_callback(idx + 1, len(segments))
                
        except Exception as e:
            logger.error(f"Failed to crop segment {segment.segment_index}: {e}")
            results.append(CroppingResult(
                segment_index=segment.segment_index,
                cropped_video_path="",
                success=False,
                error_message=str(e)
            ))
    
    return results


async def _process_single_segment(
    segment: CroppingInput,
    output_path: Path
) -> CroppingResult:
    """
    Process a single segment for cropping.
    
    Args:
        segment: Segment input data
        output_path: Output directory path
        
    Returns:
        CroppingResult with output path
    """
    segment_index = segment.segment_index
    output_file = output_path / f"segment_{segment_index:06d}.mp4"
    
    try:
        # Crop with JBI buffer
        await crop_video_segment(
            input_path=segment.video_path,
            output_path=str(output_file),
            bbox=segment.bbox_data,
            start_time=segment.jbi_start,
            end_time=segment.jbi_end,
            buffer_seconds=getattr(settings, 'jbi_buffer_seconds', 0.5)
        )
        
        logger.info(f"Segment {segment_index} cropped to {output_file}")
        
        return CroppingResult(
            segment_index=segment_index,
            cropped_video_path=str(output_file),
            success=True
        )
        
    except Exception as e:
        logger.error(f"Cropping failed for segment {segment_index}: {e}")
        return CroppingResult(
            segment_index=segment_index,
            cropped_video_path="",
            success=False,
            error_message=str(e)
        )
