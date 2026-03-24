"""
Video processing utilities for pipeline.

FFmpeg operations - no database access, no business logic.
"""

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Dict

from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


class VideoProcessor:
    """Video processing using FFmpeg."""
    
    # Audio settings for ASR
    SAMPLE_RATE = 16000  # Whisper expects 16kHz
    AUDIO_CHANNELS = 1   # Mono
    
    def __init__(self):
        """Initialize and verify FFmpeg is available."""
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._ffprobe_path = shutil.which("ffprobe")
        
        if not self._ffmpeg_path:
            raise ProcessingError(
                "FFmpeg not found. Please install FFmpeg and ensure it's in PATH.",
                permanent=True
            )
    
    async def extract_audio(
        self,
        video_path: str,
        output_path: Optional[str] = None
    ) -> str:
        """
        Extract audio from video file.
        
        Args:
            video_path: Path to video file
            output_path: Optional output path (creates temp file if None)
            
        Returns:
            Path to extracted WAV file
        """
        if output_path is None:
            temp_file = tempfile.NamedTemporaryFile(
                suffix=".wav",
                delete=False,
                prefix="asr_audio_"
            )
            output_path = temp_file.name
            temp_file.close()
        
        try:
            cmd = [
                self._ffmpeg_path,
                "-y",  # Overwrite output
                "-i", str(video_path),
                "-vn",  # No video
                "-acodec", "pcm_s16le",  # 16-bit PCM
                "-ar", str(self.SAMPLE_RATE),
                "-ac", str(self.AUDIO_CHANNELS),
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                stderr = result.stderr
                if "codec" in stderr.lower():
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
    
    async def transcode_video(
        self,
        input_path: str,
        output_path: str,
        video_codec: str = "libx264",
        audio_codec: str = "aac",
        crf: int = 16
    ) -> str:
        """
        Transcode video to standard format.
        
        Args:
            input_path: Input video file
            output_path: Output video file
            video_codec: Video codec
            audio_codec: Audio codec
            crf: Constant rate factor (quality)
            
        Returns:
            Path to transcoded video
        """
        try:
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-i", str(input_path),
                "-c:v", video_codec,
                "-crf", str(crf),
                "-c:a", audio_codec,
                str(output_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise ProcessingError(f"Transcoding failed: {result.stderr}")
            
            logger.info(f"Video transcoded: {input_path} -> {output_path}")
            return output_path
            
        except Exception as e:
            raise ProcessingError(f"Transcoding failed: {e}")
    
    async def get_video_info(self, video_path: str) -> Dict:
        """
        Get video metadata.
        
        Args:
            video_path: Path to video file
            
        Returns:
            Dict with duration, fps, width, height
        """
        if not self._ffprobe_path:
            raise ProcessingError("ffprobe not found")
        
        try:
            cmd = [
                self._ffprobe_path,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=duration,r_frame_rate,width,height",
                "-show_entries", "format=duration",
                "-of", "json",
                str(video_path)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                raise ProcessingError(f"Failed to get video info: {result.stderr}")
            
            import json
            data = json.loads(result.stdout)
            
            stream = data.get("streams", [{}])[0]
            format_info = data.get("format", {})
            
            # Parse frame rate (e.g., "30/1" -> 30.0)
            fps_str = stream.get("r_frame_rate", "30/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                fps = float(num) / float(den)
            else:
                fps = float(fps_str)
            
            return {
                "duration": float(stream.get("duration") or format_info.get("duration", 0)),
                "fps": fps,
                "width": int(stream.get("width", 0)),
                "height": int(stream.get("height", 0))
            }
            
        except Exception as e:
            raise ProcessingError(f"Failed to get video info: {e}")


# Global instance
_video_processor_instance = None


def get_video_processor() -> VideoProcessor:
    """Get video processor instance."""
    global _video_processor_instance
    if _video_processor_instance is None:
        _video_processor_instance = VideoProcessor()
    return _video_processor_instance


# Convenience functions for direct use
async def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """Extract audio from video."""
    processor = get_video_processor()
    return await processor.extract_audio(video_path, output_path)


async def transcode_video(
    input_path: str,
    output_path: str,
    video_codec: str = "libx264",
    audio_codec: str = "aac",
    crf: int = 16
) -> str:
    """Transcode video."""
    processor = get_video_processor()
    return await processor.transcode_video(input_path, output_path, video_codec, audio_codec, crf)


async def get_video_info(video_path: str) -> Dict:
    """Get video metadata."""
    processor = get_video_processor()
    return await processor.get_video_info(video_path)
