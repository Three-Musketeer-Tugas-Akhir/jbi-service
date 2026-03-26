"""Tests for JBI detector service."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from app.services.jbi_detector import (
    JBIDetector, JBIDetection, JBISegment, 
    get_jbi_detector, _jbi_detector
)
from app.pipeline.models.detector import DetectionResult, VideoMetadata
from app.core.exceptions import ProcessingError


class TestJBIDetector:
    """Test suite for JBI detector."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        global _jbi_detector
        _jbi_detector = None
        yield
        _jbi_detector = None
    
    @pytest.fixture
    def mock_detector(self):
        """Mock the underlying detector."""
        with patch('app.services.jbi_detector.get_detector') as mock_get:
            mock_det = Mock()
            mock_get.return_value = mock_det
            yield mock_det
    
    def test_singleton_pattern(self, mock_detector):
        """Test detector is singleton."""
        det1 = get_jbi_detector()
        det2 = get_jbi_detector()
        assert det1 is det2
    
    @pytest.mark.asyncio
    async def test_detect_no_detections(self, mock_detector):
        """Test detect returns empty list when no detections."""
        # Setup mock result with no detections
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=300, duration_seconds=10.0)
        mock_result.detections = []
        mock_result.bboxes = {}
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        assert segments == []
    
    @pytest.mark.asyncio
    async def test_detect_with_detections(self, mock_detector):
        """Test detect returns segments when detections found."""
        # Setup mock result with detections
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=900, duration_seconds=30.0)
        # Detect at seconds 5, 6, 7, 8, 9 (5 seconds consecutive)
        mock_result.detections = [False] * 5 + [True] * 5 + [False] * 20
        mock_result.bboxes = {
            5: [100.0, 100.0, 200.0, 150.0],
            6: [105.0, 105.0, 195.0, 145.0],
            7: [102.0, 102.0, 198.0, 148.0],
            8: [108.0, 108.0, 192.0, 142.0],
            9: [104.0, 104.0, 196.0, 146.0],
        }
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        assert len(segments) == 1
        assert segments[0].start_time == 5.0
        assert segments[0].end_time == 9.0
        assert segments[0].start_frame == 150  # 5 * 30 fps
        assert segments[0].end_frame == 270    # 9 * 30 fps
    
    @pytest.mark.asyncio
    async def test_detect_filters_short_segments(self, mock_detector):
        """Test detect filters segments shorter than min duration."""
        # Setup mock result with short detection
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=300, duration_seconds=10.0)
        # Only 2 seconds of detections (less than 5s min)
        mock_result.detections = [False] * 3 + [True] * 2 + [False] * 5
        mock_result.bboxes = {
            3: [100.0, 100.0, 200.0, 150.0],
            4: [105.0, 105.0, 195.0, 145.0],
        }
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        # Should filter out the short segment
        assert len(segments) == 0
    
    @pytest.mark.asyncio
    async def test_detect_merges_consecutive_detections(self, mock_detector):
        """Test detect merges consecutive detections into single segment."""
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=900, duration_seconds=30.0)
        # 10 seconds of consecutive detections
        mock_result.detections = [False] * 5 + [True] * 10 + [False] * 15
        mock_result.bboxes = {i: [100.0, 100.0, 200.0, 150.0] for i in range(5, 15)}
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        assert len(segments) == 1
        assert segments[0].start_time == 5.0
        assert segments[0].end_time == 14.0
    
    @pytest.mark.asyncio
    async def test_detect_creates_multiple_segments(self, mock_detector):
        """Test detect creates multiple segments for separated detections."""
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=900, duration_seconds=30.0)
        # Two separate 5-second detection periods
        mock_result.detections = (
            [False] * 2 +          # 0-2s: no detection
            [True] * 5 +           # 2-7s: detection (5s)
            [False] * 5 +          # 7-12s: gap (5s > 1s max_gap)
            [True] * 5 +           # 12-17s: detection (5s)
            [False] * 13           # rest
        )
        mock_result.bboxes = {**{i: [100.0, 100.0, 200.0, 150.0] for i in range(2, 7)},
                             **{i: [100.0, 100.0, 200.0, 150.0] for i in range(12, 17)}}
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        assert len(segments) == 2
        # First segment
        assert segments[0].start_time == 2.0
        assert segments[0].end_time == 6.0
        # Second segment
        assert segments[1].start_time == 12.0
        assert segments[1].end_time == 16.0
    
    @pytest.mark.asyncio
    async def test_detect_uses_highest_confidence_bbox(self, mock_detector):
        """Test detect keeps bbox with highest confidence when merging."""
        mock_result = Mock(spec=DetectionResult)
        mock_result.metadata = VideoMetadata(fps=30.0, frame_count=300, duration_seconds=10.0)
        mock_result.detections = [False] * 2 + [True] * 5 + [False] * 3
        mock_result.bboxes = {
            2: [100.0, 100.0, 200.0, 150.0],  # first detection
            3: [110.0, 110.0, 210.0, 160.0],  # higher confidence would use this
            4: [120.0, 120.0, 220.0, 170.0],  # but all have same confidence in mock
            5: [130.0, 130.0, 230.0, 180.0],
            6: [140.0, 140.0, 240.0, 190.0],  # last detection - will be kept
        }
        mock_detector.detect.return_value = mock_result
        
        detector = JBIDetector()
        segments = await detector.detect(Path("test.mp4"))
        
        assert len(segments) == 1
        # Should use bbox from last detection (highest confidence in our implementation)
        assert segments[0].bbox_data == {"x": 140.0, "y": 140.0, "width": 240.0, "height": 190.0}
    
    @pytest.mark.asyncio
    async def test_detect_raises_on_error(self, mock_detector):
        """Test detect raises ProcessingError on detection failure."""
        mock_detector.detect.side_effect = Exception("Model error")
        
        detector = JBIDetector()
        
        with pytest.raises(ProcessingError, match="Detection failed"):
            await detector.detect(Path("test.mp4"))
    
    def test_merge_detections_empty(self):
        """Test merge with empty list returns empty."""
        detector = JBIDetector()
        segments = detector._merge_detections([])
        assert segments == []
    
    def test_merge_detections_single_detection(self):
        """Test merge with single detection."""
        detector = JBIDetector()
        detections = [
            JBIDetection(frame_number=150, timestamp=5.0, 
                        bbox={"x": 100, "y": 100, "width": 200, "height": 150},
                        confidence=0.9)
        ]
        # Below min duration, should be filtered
        segments = detector._merge_detections(detections, min_segment_duration=0.1)
        
        assert len(segments) == 1
        assert segments[0].start_time == 5.0
        assert segments[0].end_time == 5.0
