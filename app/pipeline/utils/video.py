"""
Video processing utilities for pipeline.

FFmpeg operations - no database access, no business logic.
"""

import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict

from app.core.exceptions import ProcessingError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FFmpegConfig:
    """Configuration for FFmpeg video encoding.
    
    Attributes:
        video_codec: Video codec to use (default: libx264)
        video_crf: Constant rate factor for quality (0-51, lower is better, default: 16)
        video_preset: Encoding speed preset (default: fast)
        audio_codec: Audio codec to use (default: aac)
        audio_bitrate: Audio bitrate in kbps (default: 128)
    """
    video_codec: str = "libx264"
    video_crf: int = 16
    video_preset: str = "fast"
    audio_codec: str = "aac"
    audio_bitrate: int = 128
    
    def validate(self) -> None:
        """Validate configuration values."""
        if not 0 <= self.video_crf <= 51:
            raise ValueError(f"video_crf must be 0-51, got {self.video_crf}")
        if self.video_preset not in ("ultrafast", "superfast", "veryfast", "faster", 
                                      "fast", "medium", "slow", "slower", "veryslow"):
            raise ValueError(f"Invalid video_preset: {self.video_preset}")


class VideoProcessor:
    """Video processing using FFmpeg.
    
    This class provides methods for video processing operations including
    audio extraction, transcoding, and video info retrieval.
    
    Attributes:
        SAMPLE_RATE: Audio sample rate for ASR (16kHz)
        AUDIO_CHANNELS: Number of audio channels (1 = mono)
        DEFAULT_FFMPEG_CONFIG: Default FFmpeg encoding configuration
    """
    
    # Audio settings for ASR
    SAMPLE_RATE: int = 16000  #: Whisper expects 16kHz
    AUDIO_CHANNELS: int = 1   #: Mono audio
    
    # Default FFmpeg configuration
    DEFAULT_FFMPEG_CONFIG: FFmpegConfig = FFmpegConfig()
    
    def __init__(self):
        """Initialize and verify FFmpeg is available."""
        self._ffmpeg_path = shutil.which("ffmpeg")
        self._ffprobe_path = shutil.which("ffprobe")
        
        if not self._ffmpeg_path:
            raise ProcessingError(
                "FFmpeg not found. Please install FFmpeg and ensure it's in PATH.",
                permanent=True
            )
        
        # Cache for video duration to avoid repeated ffprobe calls
        self._duration_cache: Dict[str, float] = {}
    
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
            
    async def crop_audio(
        self,
        input_path: str,
        output_path: str,
        start_time: float,
        end_time: float
    ) -> str:
        """
        Crop an audio file using FFmpeg.
        
        Args:
            input_path: Input audio file
            output_path: Output audio file
            start_time: Start time in seconds
            end_time: End time in seconds
            
        Returns:
            Path to cropped audio file
        """
        duration = end_time - start_time
        try:
            cmd = [
                self._ffmpeg_path,
                "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
                "-t", str(duration),
                "-acodec", "pcm_s16le",
                "-ar", str(self.SAMPLE_RATE),
                "-ac", str(self.AUDIO_CHANNELS),
                str(output_path)
            ]
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            
            if proc.returncode != 0:
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                raise ProcessingError(f"Audio crop failed: {stderr_text}")
                
            return output_path
            
        except Exception as e:
            raise ProcessingError(f"Audio crop failed: {e}")
    
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


async def crop_audio(input_path: str, output_path: str, start_time: float, end_time: float) -> str:
    """Crop audio file."""
    processor = get_video_processor()
    return await processor.crop_audio(input_path, output_path, start_time, end_time)


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


class TranscodeError(Exception):
    """Raised when video transcoding fails."""
    pass


async def get_video_duration(video_path: str) -> float:
    """
    Get video duration in seconds (with caching).
    
    Args:
        video_path: Path to video file
        
    Returns:
        Duration in seconds
    """
    processor = get_video_processor()
    
    # Check cache first
    if video_path in processor._duration_cache:
        return processor._duration_cache[video_path]
    
    info = await get_video_info(video_path)
    duration = info.get("duration", 0)
    if duration <= 0:
        raise ProcessingError(f"Invalid video duration: {duration}")
    
    # Cache the result
    processor._duration_cache[video_path] = duration
    return duration


async def run_ffmpeg_crop(
    input_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    use_input_seeking: bool = True,
    timeout_seconds: int = 300,
    config: Optional[FFmpegConfig] = None
) -> bool:
    """
    Crop video segment using FFmpeg (async with timeout).
    
    Uses precise seeking with -ss before -i for input seeking (faster, more accurate).
    
    Args:
        input_path: Source video file
        output_path: Output cropped video file
        start_time: Start time in seconds
        end_time: End time in seconds
        use_input_seeking: If True, use input seeking (-ss before -i) for speed
        timeout_seconds: Maximum time to wait for FFmpeg (default 5 minutes)
        config: FFmpeg encoding configuration (uses default if None)
        
    Returns:
        True if successful
    """
    # Validate inputs
    if start_time < 0:
        logger.error("Invalid start_time: %s (must be >= 0)", start_time)
        return False
    if end_time <= start_time:
        logger.error("Invalid time range: start=%s, end=%s", start_time, end_time)
        return False
    
    processor = get_video_processor()
    duration = end_time - start_time
    # Enforce minimum crop duration to avoid unplayable sub-frame videos
    MIN_CROP_DURATION = 0.067  # 2 frames at 30fps
    if duration < MIN_CROP_DURATION:
        logger.warning(
            "Crop duration %.3fs below minimum %.3fs; clamping to minimum",
            duration, MIN_CROP_DURATION
        )
        duration = MIN_CROP_DURATION
        end_time = start_time + duration
    output_file = Path(output_path)
    
    # Use provided config or default
    cfg = config or processor.DEFAULT_FFMPEG_CONFIG
    cfg.validate()
    
    # Clean up any existing partial output
    if output_file.exists():
        try:
            output_file.unlink()
        except OSError as e:
            logger.warning("Failed to remove existing output file: %s", e)
    
    try:
        # Build FFmpeg command with configurable parameters
        base_cmd = [
            processor._ffmpeg_path,
            "-y",  # Overwrite output
            "-c:v", cfg.video_codec,
            "-crf", str(cfg.video_crf),
            "-preset", cfg.video_preset,
            "-c:a", cfg.audio_codec,
            "-b:a", f"{cfg.audio_bitrate}k",
        ]
        
        if use_input_seeking:
            # Input seeking: -ss before -i (fast, accurate)
            cmd = [
                processor._ffmpeg_path,
                "-y",
                "-ss", str(start_time),
                "-i", str(input_path),
                "-t", str(duration),
                "-c:v", cfg.video_codec,
                "-crf", str(cfg.video_crf),
                "-preset", cfg.video_preset,
                "-c:a", cfg.audio_codec,
                "-b:a", f"{cfg.audio_bitrate}k",
                "-avoid_negative_ts", "make_zero",
                str(output_path)
            ]
        else:
            # Output seeking: -ss after -i (slower but frame-accurate)
            cmd = [
                processor._ffmpeg_path,
                "-y",
                "-i", str(input_path),
                "-ss", str(start_time),
                "-t", str(duration),
                "-c:v", cfg.video_codec,
                "-crf", str(cfg.video_crf),
                "-preset", cfg.video_preset,
                "-c:a", cfg.audio_codec,
                "-b:a", f"{cfg.audio_bitrate}k",
                str(output_path)
            ]
        
        # Use asyncio subprocess for non-blocking execution
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error("FFmpeg timed out after %s seconds", timeout_seconds)
            proc.kill()
            await proc.wait()
            # Clean up partial output
            _cleanup_file(output_path)
            return False
        
        if proc.returncode != 0:
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
            logger.error("FFmpeg crop failed: %s", stderr_text)
            _cleanup_file(output_path)
            return False
        
        # Verify output file exists and has size
        if not output_file.exists() or output_file.stat().st_size == 0:
            logger.error("FFmpeg output file is empty or missing: %s", output_path)
            return False
        
        logger.info(
            "Video cropped: %s [%.2f -> %.2f] -> %s",
            input_path, start_time, end_time, output_path
        )
        return True
        
    except Exception as e:
        logger.error("FFmpeg crop error: %s", e)
        _cleanup_file(output_path)
        return False


async def run_ffmpeg_strip_audio(
    input_path: str,
    output_path: str,
    timeout_seconds: int = 300,
) -> bool:
    """
    Produce a silent copy of a video (no audio track) using FFmpeg.

    First tries a lossless stream copy (`-c:v copy -an`) which is fast and keeps
    the exact video bytes. If that fails (some containers reject a bare copy),
    falls back to a quick re-encode (`-c:v libx264 -an`). Either way the result
    has NO audio. Used by dataset export so downloaded clips are guaranteed silent.

    Returns:
        True if a valid muted output file was produced.
    """
    processor = get_video_processor()
    output_file = Path(output_path)

    async def _run(cmd) -> bool:
        if output_file.exists():
            try:
                output_file.unlink()
            except OSError as e:
                logger.warning("Failed to remove existing output file: %s", e)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error("FFmpeg strip-audio timed out after %s seconds", timeout_seconds)
            proc.kill()
            await proc.wait()
            _cleanup_file(output_path)
            return False
        if proc.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else "Unknown error"
            logger.warning("FFmpeg strip-audio command failed: %s", stderr_text)
            _cleanup_file(output_path)
            return False
        if not output_file.exists() or output_file.stat().st_size == 0:
            logger.warning("FFmpeg strip-audio output is empty or missing: %s", output_path)
            return False
        return True

    try:
        # 1) Lossless copy, drop audio
        copy_cmd = [
            processor._ffmpeg_path, "-y",
            "-i", str(input_path),
            "-c:v", "copy", "-an",
            str(output_path),
        ]
        if await _run(copy_cmd):
            return True

        # 2) Fallback: re-encode video, drop audio
        reencode_cmd = [
            processor._ffmpeg_path, "-y",
            "-i", str(input_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an",
            str(output_path),
        ]
        return await _run(reencode_cmd)
    except Exception as e:
        logger.error("FFmpeg strip-audio error: %s", e)
        _cleanup_file(output_path)
        return False


def _cleanup_file(path: str) -> None:
    """Clean up a file if it exists (synchronous helper)."""
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("Cleaned up file: %s", path)
    except OSError as e:
        logger.warning("Failed to clean up file %s: %s", path, e)


async def transcode_to_h264(
    input_path: str,
    output_path: Optional[str] = None,
    on_progress=None
) -> str:
    """
    Transcode video to H.264 format.
    
    Args:
        input_path: Input video file
        output_path: Optional output path
        on_progress: Optional progress callback(percent)
        
    Returns:
        Path to transcoded video
    """
    if output_path is None:
        output_path = str(Path(input_path).with_suffix('.h264.mp4'))
    
    try:
        result = await transcode_video(
            input_path=input_path,
            output_path=output_path,
            video_codec="libx264",
            audio_codec="aac",
            crf=16
        )
        
        if on_progress:
            on_progress(100)
        
        return result
        
    except ProcessingError as e:
        raise TranscodeError(f"Transcoding failed: {e}") from e


async def run_ffmpeg_concat(
    input_paths: list,
    output_path: str,
    timeout_seconds: int = 300,
    config: Optional[FFmpegConfig] = None
) -> bool:
    """
    Concatenate multiple video files into one using FFmpeg concat demuxer.
    
    Used by Boundary Cross-Cropping & Merging when an utterance spans
    across two segment videos.
    
    Args:
        input_paths: List of video file paths to concatenate (in order)
        output_path: Output merged video file
        timeout_seconds: Maximum time to wait for FFmpeg
        config: FFmpeg encoding configuration
        
    Returns:
        True if successful
    """
    if not input_paths or len(input_paths) < 2:
        logger.error("run_ffmpeg_concat requires at least 2 input files")
        return False
    
    processor = get_video_processor()
    cfg = config or processor.DEFAULT_FFMPEG_CONFIG
    cfg.validate()
    
    # Create a temporary concat list file
    concat_list_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', delete=False, prefix='concat_'
        ) as f:
            concat_list_path = f.name
            for path in input_paths:
                f.write(f"file '{path}'\n")
        
        cmd = [
            processor._ffmpeg_path,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list_path,
            "-c:v", cfg.video_codec,
            "-crf", str(cfg.video_crf),
            "-preset", cfg.video_preset,
            "-c:a", cfg.audio_codec,
            "-b:a", f"{cfg.audio_bitrate}k",
            str(output_path)
        ]
        
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_seconds
            )
        except asyncio.TimeoutError:
            logger.error("FFmpeg concat timed out after %s seconds", timeout_seconds)
            proc.kill()
            await proc.wait()
            _cleanup_file(output_path)
            return False
        
        if proc.returncode != 0:
            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
            logger.warning("FFmpeg concat demuxer failed: %s", stderr_text)
            
            # Fallback: use filter_complex concat (more robust for mixed streams)
            logger.info("Trying filter_complex concat fallback...")
            _cleanup_file(output_path)
            
            # Build filter_complex concat command without audio
            # (avoids audio stream mismatch issues)
            filter_cmd = [
                processor._ffmpeg_path,
                "-y",
            ]
            for path in input_paths:
                filter_cmd.extend(["-i", str(path)])
            
            n = len(input_paths)
            video_inputs = "".join(f"[{i}:v]" for i in range(n))
            filter_complex = f"{video_inputs}concat=n={n}:v=1:a=0[outv]"
            
            filter_cmd.extend([
                "-filter_complex", filter_complex,
                "-map", "[outv]",
                "-c:v", cfg.video_codec,
                "-crf", str(cfg.video_crf),
                "-preset", cfg.video_preset,
                "-an",  # No audio
                str(output_path)
            ])
            
            proc2 = await asyncio.create_subprocess_exec(
                *filter_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                stdout2, stderr2 = await asyncio.wait_for(
                    proc2.communicate(),
                    timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                logger.error("FFmpeg filter_complex concat timed out")
                proc2.kill()
                await proc2.wait()
                _cleanup_file(output_path)
                return False
            
            if proc2.returncode != 0:
                stderr2_text = stderr2.decode('utf-8', errors='replace') if stderr2 else "Unknown error"
                logger.error("FFmpeg filter_complex concat also failed: %s", stderr2_text)
                _cleanup_file(output_path)
                return False
        
        output_file = Path(output_path)
        if not output_file.exists() or output_file.stat().st_size == 0:
            logger.error("FFmpeg concat output is empty or missing: %s", output_path)
            return False
        
        logger.info("Videos concatenated: %s -> %s", input_paths, output_path)
        return True
        
    except Exception as e:
        logger.error("FFmpeg concat error: %s", e)
        _cleanup_file(output_path)
        return False
    finally:
        if concat_list_path:
            _cleanup_file(concat_list_path)
