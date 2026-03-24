"""Audio extraction service using FFmpeg."""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


class AudioExtractor:
    """Extract audio from video files using FFmpeg."""
    
    # Output audio format
    SAMPLE_RATE = 16000  # Whisper expects 16kHz
    CHANNELS = 1         # Mono
    
    def __init__(self):
        """Initialize and verify FFmpeg is available."""
        self._ffmpeg_path = shutil.which("ffmpeg")
        if not self._ffmpeg_path:
            raise ProcessingError(
                "FFmpeg not found. Please install FFmpeg and ensure it's in PATH.",
                permanent=True
            )
    
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
            # FFmpeg extraction using subprocess
            cmd = [
                self._ffmpeg_path,
                "-y",  # Overwrite output
                "-i", str(video_path),
                "-vn",  # No video
                "-acodec", "pcm_s16le",  # 16-bit PCM
                "-ar", str(self.SAMPLE_RATE),
                "-ac", str(self.CHANNELS),
                str(output_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                stderr = result.stderr
                
                # Check for unsupported codec
                if "codec" in stderr.lower() or "codec not found" in stderr.lower():
                    raise ProcessingError(
                        f"Audio codec not supported: {stderr}",
                        permanent=True
                    )
                
                raise ProcessingError(f"Audio extraction failed: {stderr}")
            
            logger.info(f"Audio extracted: {video_path} -> {output_path}")
            return output_path
            
        except ProcessingError:
            raise
        
        except Exception as e:
            raise ProcessingError(f"Audio extraction failed: {e}")


# Global instance
_audio_extractor_instance = None


def get_audio_extractor() -> AudioExtractor:
    """Get audio extractor instance."""
    global _audio_extractor_instance
    if _audio_extractor_instance is None:
        _audio_extractor_instance = AudioExtractor()
    return _audio_extractor_instance
