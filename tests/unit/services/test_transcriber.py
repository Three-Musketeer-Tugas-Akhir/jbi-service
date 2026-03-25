"""Tests for transcriber service."""

from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

from app.services.transcriber import (
    TranscriberService,
    TranscriptionSegment,
    TranscriptionResult,
    get_transcriber_service
)
from app.core.exceptions import ProcessingError


class TestTranscriptionSegment:
    """Test suite for TranscriptionSegment named tuple."""
    
    def test_creation(self):
        """Test creating a transcription segment."""
        segment = TranscriptionSegment(
            start=1.0,
            end=2.0,
            text="test text",
            confidence=0.95
        )
        assert segment.start == 1.0
        assert segment.end == 2.0
        assert segment.text == "test text"
        assert segment.confidence == 0.95


class TestTranscriptionResult:
    """Test suite for TranscriptionResult dataclass."""
    
    def test_creation(self):
        """Test creating a transcription result."""
        segments = [
            TranscriptionSegment(1.0, 2.0, "hello", 0.9),
            TranscriptionSegment(2.5, 3.5, "world", 0.85)
        ]
        result = TranscriptionResult(
            segments=segments,
            text="hello world",
            average_confidence=0.875
        )
        assert result.text == "hello world"
        assert result.average_confidence == 0.875
        assert len(result.segments) == 2
    
    def test_start_property(self):
        """Test start property returns first segment start."""
        segments = [
            TranscriptionSegment(1.5, 2.0, "hello", 0.9),
        ]
        result = TranscriptionResult(segments, "hello", 0.9)
        assert result.start == 1.5
    
    def test_end_property(self):
        """Test end property returns last segment end."""
        segments = [
            TranscriptionSegment(1.0, 2.0, "hello", 0.9),
            TranscriptionSegment(2.5, 4.0, "world", 0.85)
        ]
        result = TranscriptionResult(segments, "hello world", 0.875)
        assert result.end == 4.0
    
    def test_empty_segments(self):
        """Test properties with empty segments."""
        result = TranscriptionResult([], "", 0.0)
        assert result.start == 0.0
        assert result.end == 0.0


class TestTranscriberService:
    """Test suite for transcriber service."""
    
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        TranscriberService._instance = None
        TranscriberService._model = None
        TranscriberService._model_size = None
        TranscriberService._compute_type = None
        yield
        # Reset after test too
        TranscriberService._instance = None
        TranscriberService._model = None
        TranscriberService._model_size = None
        TranscriberService._compute_type = None
    
    def test_singleton_pattern(self):
        """Test transcriber is singleton."""
        service1 = get_transcriber_service()
        service2 = get_transcriber_service()
        assert service1 is service2
    
    @pytest.mark.asyncio
    @patch("app.services.transcriber.WhisperModel")
    async def test_transcribe_returns_result(self, mock_model_class):
        """Test transcribe returns TranscriptionResult."""
        # Setup mock
        mock_segment = Mock()
        mock_segment.start = 1.0
        mock_segment.end = 2.0
        mock_segment.text = "hello world"
        mock_segment.avg_logprob = -0.5
        
        mock_info = Mock()
        mock_info.no_speech_prob = 0.1
        
        mock_model = Mock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        mock_model_class.return_value = mock_model
        
        # Create service and set model directly
        service = TranscriberService()
        service._model = mock_model
        
        # Create dummy audio file
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"dummy audio data")
            audio_path = Path(f.name)
        
        try:
            result = await service.transcribe(audio_path)
            
            assert isinstance(result, TranscriptionResult)
            assert result.text == "hello world"
            assert len(result.segments) == 1
            assert result.segments[0].text == "hello world"
        finally:
            audio_path.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    @patch("app.services.transcriber.WhisperModel")
    async def test_transcribe_respects_language(self, mock_model_class):
        """Test language parameter is passed to model."""
        mock_model = Mock()
        mock_model.transcribe.return_value = ([], Mock())
        mock_model_class.return_value = mock_model
        
        service = TranscriberService()
        service._model = mock_model
        
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio_path = Path(f.name)
        
        try:
            await service.transcribe(audio_path, language="en")
            
            call_kwargs = mock_model.transcribe.call_args[1]
            assert call_kwargs["language"] == "en"
        finally:
            audio_path.unlink(missing_ok=True)
    
    def test_format_segments_txt(self):
        """Test segments.txt formatting."""
        service = TranscriberService()
        
        segments = [
            TranscriptionSegment(1.0, 2.5, "first segment", 0.9),
            TranscriptionSegment(3.0, 4.5, "second segment", 0.85)
        ]
        result = TranscriptionResult(segments, "first segment second segment", 0.875)
        
        formatted = service.format_segments_txt(result)
        
        assert "[00:00:01.000 -> 00:00:02.500] first segment" in formatted
        assert "[00:00:03.000 -> 00:00:04.500] second segment" in formatted
    
    def test_format_segments_txt_with_offset(self):
        """Test segments.txt formatting with time offset."""
        service = TranscriberService()
        
        segments = [
            TranscriptionSegment(1.0, 2.0, "text", 0.9)
        ]
        result = TranscriptionResult(segments, "text", 0.9)
        
        formatted = service.format_segments_txt(result, segment_offset=10.0)
        
        # With 10 second offset, 1.0 becomes 11.0
        assert "[00:00:11.000 -> 00:00:12.000]" in formatted
    
    def test_format_timestamp(self):
        """Test timestamp formatting."""
        service = TranscriberService()
        
        assert service._format_timestamp(0.0) == "00:00:00.000"
        assert service._format_timestamp(1.5) == "00:00:01.500"
        assert service._format_timestamp(61.5) == "00:01:01.500"
        assert service._format_timestamp(3661.5) == "01:01:01.500"
    
    @pytest.mark.asyncio
    @patch("app.services.transcriber.WhisperModel")
    async def test_low_confidence_detection(self, mock_model_class):
        """Test confidence scores are calculated."""
        # Setup mock with low confidence
        mock_segment = Mock()
        mock_segment.start = 1.0
        mock_segment.end = 2.0
        mock_segment.text = "unclear"
        mock_segment.avg_logprob = -2.5  # Low confidence
        
        mock_info = Mock()
        mock_info.no_speech_prob = 0.1
        
        mock_model = Mock()
        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        mock_model_class.return_value = mock_model
        
        service = TranscriberService()
        service._model = mock_model
        
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            audio_path = Path(f.name)
        
        try:
            result = await service.transcribe(audio_path)
            
            # Confidence should be low (clamped to 0)
            assert result.average_confidence < 0.5
        finally:
            audio_path.unlink(missing_ok=True)
