"""
Stage 1: JBI Detection Pipeline

Pure ML processing - no database access, no HTTP concerns.
Runs YOLOv8 detection and merges contiguous segments.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional

import logging

logger = logging.getLogger(__name__)
from app.core.exceptions import ProcessingError
from app.pipeline.models.detector import get_detector, DetectionResult


@dataclass
class JBIDetection:
    """Single JBI detection result."""
    frame_number: int
    timestamp: float
    bbox: Dict[str, float]  # x, y, width, height
    confidence: float


@dataclass
class JBISegment:
    """Merged JBI segment for Stage 1 cropping."""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    bbox_data: Dict[str, float]
    confidence: float


class JBIDetector:
    """
    JBI (Juru Bahasa Isyarat) detector for pipeline processing.
    
    Wraps the existing YOLOv8 detector and provides segment merging
    for Stage 1 cropping.
    """
    
    # Detection parameters
    CONFIDENCE_THRESHOLD = 0.5
    MIN_SEGMENT_DURATION = 5.0  # seconds
    MAX_GAP_SECONDS = 1.0  # Max gap to merge segments
    
    def __init__(self):
        self._detector = get_detector()
    
    async def detect(
        self,
        video_path: Path,
        min_segment_duration: float = None
    ) -> List[JBISegment]:
        """
        Detect JBI regions in video and return merged segments.
        
        Args:
            video_path: Path to video file
            min_segment_duration: Minimum segment duration (default: 5.0s)
            
        Returns:
            List of JBISegment objects for Stage 1 cropping
            
        Raises:
            ProcessingError: If detection fails
        """
        min_segment_duration = min_segment_duration or self.MIN_SEGMENT_DURATION
        
        try:
            # Run detection using existing detector
            result: DetectionResult = self._detector.detect(str(video_path))
            
            if not result.detections:
                logger.info(f"No detections in video: {video_path}")
                return []
            
            # Convert to JBIDetection list
            detections = self._convert_detections(result)
            
            # Merge into segments
            segments = self._merge_detections(
                detections,
                min_segment_duration=min_segment_duration
            )
            
            logger.info(
                f"Detected {len(detections)} frames with JBI, "
                f"merged into {len(segments)} segments"
            )
            
            return segments
            
        except Exception as e:
            logger.error(f"JBI detection failed: {e}")
            raise ProcessingError(f"Detection failed: {e}")
    
    def _convert_detections(self, result: DetectionResult) -> List[JBIDetection]:
        """Convert DetectionResult to list of JBIDetection."""
        detections = []
        
        fps = result.metadata.fps
        
        for second, detected in enumerate(result.detections):
            if detected and second in result.bboxes:
                bbox = result.bboxes[second]
                # bbox format: [x_min, y_min, width, height]
                # NOTE: Confidence is not available from the underlying DetectorService.
                # The existing implementation only returns boolean detections and bboxes.
                # TODO: Modify DetectorService to return confidence scores from YOLOv8
                detections.append(JBIDetection(
                    frame_number=int(second * fps),
                    timestamp=float(second),
                    bbox={
                        "x": bbox[0],
                        "y": bbox[1],
                        "width": bbox[2],
                        "height": bbox[3]
                    },
                    confidence=1.0
                ))
        
        return detections
    
    def _merge_detections(
        self,
        detections: List[JBIDetection],
        min_segment_duration: float = None
    ) -> List[JBISegment]:
        """
        Merge consecutive detections into segments.
        
        Args:
            detections: List of JBIDetection
            min_segment_duration: Minimum segment duration in seconds
            
        Returns:
            List of merged JBISegment
        """
        min_segment_duration = min_segment_duration or self.MIN_SEGMENT_DURATION
        
        if not detections:
            return []
        
        # Sort by timestamp
        sorted_detections = sorted(detections, key=lambda d: d.timestamp)
        
        segments = []
        current = JBISegment(
            start_frame=sorted_detections[0].frame_number,
            end_frame=sorted_detections[0].frame_number,
            start_time=sorted_detections[0].timestamp,
            end_time=sorted_detections[0].timestamp,
            bbox_data=sorted_detections[0].bbox,
            confidence=sorted_detections[0].confidence
        )
        
        for detection in sorted_detections[1:]:
            gap = detection.timestamp - current.end_time
            
            if gap <= self.MAX_GAP_SECONDS:
                # Extend current segment
                current.end_frame = detection.frame_number
                current.end_time = detection.timestamp
                # Keep bbox with highest confidence
                if detection.confidence > current.confidence:
                    current.bbox_data = detection.bbox
                    current.confidence = detection.confidence
            else:
                # Gap too large, save current and start new
                duration = current.end_time - current.start_time
                if duration >= min_segment_duration:
                    segments.append(current)
                
                current = JBISegment(
                    start_frame=detection.frame_number,
                    end_frame=detection.frame_number,
                    start_time=detection.timestamp,
                    end_time=detection.timestamp,
                    bbox_data=detection.bbox,
                    confidence=detection.confidence
                )
        
        # Don't forget the last segment
        duration = current.end_time - current.start_time
        if duration >= min_segment_duration:
            segments.append(current)
        
        return segments


# Global instance
_jbi_detector: Optional[JBIDetector] = None


def get_jbi_detector() -> JBIDetector:
    """Get or create JBI detector singleton."""
    global _jbi_detector
    if _jbi_detector is None:
        _jbi_detector = JBIDetector()
    return _jbi_detector
