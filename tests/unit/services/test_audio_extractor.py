"""Tests for audio extractor service."""

import tempfile
from pathlib import Path

import pytest

from app.services.audio_extractor import AudioExtractor, get_audio_extractor
from app.core.exceptions import ProcessingError


class TestAudioExtractor:
    """Test suite for audio extraction service."""
    
    @pytest.fixture
    def extractor(self):
        """Create audio extractor instance."""
        return AudioExtractor()
    
    @pytest.mark.asyncio
    async def test_singleton_pattern(self):
        """Test that get_audio_extractor returns singleton."""
        extractor1 = get_audio_extractor()
        extractor2 = get_audio_extractor()
        assert extractor1 is extractor2
    
    @pytest.mark.asyncio
    async def test_extract_creates_wav(self, extractor, tmp_path):
        """Test extraction creates valid WAV file."""
        # Create a dummy video file (we'll use a small valid video or mock)
        # For this test, we need a real video file with audio
        # We'll skip if ffmpeg is not available
        
        # First, create a test video with ffmpeg
        video_path = tmp_path / "test_video.mp4"
        
        import subprocess
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "sine=frequency=1000:duration=1",
                "-f", "lavfi",
                "-i", "color=c=black:s=320x240:d=1",
                "-shortest",
                str(video_path)
            ], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("FFmpeg not available")
        
        # Extract audio
        output_path = tmp_path / "output.wav"
        result = await extractor.extract(video_path, output_path)
        
        # Verify output
        assert result.exists()
        assert result.suffix == ".wav"
        assert result.stat().st_size > 0
    
    @pytest.mark.asyncio
    async def test_extract_respects_sample_rate(self, extractor, tmp_path):
        """Test output is 16kHz."""
        video_path = tmp_path / "test_video.mp4"
        
        import subprocess
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "sine=frequency=1000:duration=1",
                "-f", "lavfi",
                "-i", "color=c=black:s=320x240:d=1",
                "-shortest",
                str(video_path)
            ], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("FFmpeg not available")
        
        output_path = tmp_path / "output.wav"
        await extractor.extract(video_path, output_path)
        
        # Check sample rate using ffprobe
        try:
            result = subprocess.run([
                "ffprobe", "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(output_path)
            ], capture_output=True, text=True, check=True)
            sample_rate = int(result.stdout.strip())
            assert sample_rate == 16000
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("ffprobe not available")
    
    @pytest.mark.asyncio
    async def test_extract_creates_temp_file(self, extractor, tmp_path):
        """Test extraction creates temp file when no output path provided."""
        video_path = tmp_path / "test_video.mp4"
        
        import subprocess
        try:
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "sine=frequency=1000:duration=1",
                "-f", "lavfi",
                "-i", "color=c=black:s=320x240:d=1",
                "-shortest",
                str(video_path)
            ], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pytest.skip("FFmpeg not available")
        
        result = await extractor.extract(video_path)
        
        # Verify temp file was created
        assert result.exists()
        assert "asr_audio_" in result.name
        
        # Cleanup
        result.unlink(missing_ok=True)
    
    @pytest.mark.asyncio
    async def test_invalid_video_raises_error(self, extractor, tmp_path):
        """Test that invalid video file raises ProcessingError."""
        # Create a fake video file
        video_path = tmp_path / "fake_video.mp4"
        video_path.write_text("not a video file")
        
        with pytest.raises(ProcessingError):
            await extractor.extract(video_path)
