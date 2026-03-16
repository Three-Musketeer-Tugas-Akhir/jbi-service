"""Transcode videos to H.264 when OpenCV's bundled FFmpeg can't decode them.

Uses imageio-ffmpeg's bundled FFmpeg binary, which is cross-platform
(Linux, macOS, Windows) and doesn't require a system FFmpeg install.
"""

import logging
import subprocess
from pathlib import Path
from typing import Callable, Optional

import cv2
from imageio_ffmpeg import get_ffmpeg_exe

logger = logging.getLogger(__name__)

# Progress callback: (current_step, total_steps) -> None
TranscodeProgressCallback = Callable[[int, int], None]


class TranscodeError(Exception):
    """Raised when FFmpeg transcoding fails."""
    pass


def needs_transcoding(video_path: str) -> bool:
    """Check whether OpenCV can decode frames from this video.

    Returns True if transcoding is needed (OpenCV can't read frames).
    """
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return True
        ret, frame = cap.read()
        return not ret or frame is None
    finally:
        cap.release()


def transcode_to_h264(
    video_path: str,
    on_progress: Optional[TranscodeProgressCallback] = None,
) -> str:
    """Transcode a video to H.264/AAC MP4 if OpenCV can't decode it.

    - If the video is already decodable by OpenCV, returns the original path.
    - Otherwise, transcodes to an H.264 file alongside the original and
      returns the new path.

    Args:
        video_path: Path to the source video file.
        on_progress: Optional callback for progress reporting.

    Returns:
        Path to the (possibly transcoded) video file.

    Raises:
        TranscodeError: If FFmpeg transcoding fails.
    """
    if not needs_transcoding(video_path):
        logger.debug("Video is already OpenCV-compatible: %s", video_path)
        return video_path

    logger.info(
        "Video codec unsupported by OpenCV — transcoding to H.264: %s",
        video_path,
    )

    src = Path(video_path)
    dest = src.with_stem(src.stem + "_h264").with_suffix(".mp4")

    ffmpeg = get_ffmpeg_exe()
    logger.debug("Using FFmpeg binary: %s", ffmpeg)

    cmd = [
        ffmpeg,
        "-i", video_path,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",        # visually lossless
        "-c:a", "aac",
        "-movflags", "+faststart",
        "-y",                # overwrite if exists
        str(dest),
    ]

    if on_progress:
        on_progress(0, 1)

    logger.info("Transcoding started: %s → %s", src.name, dest.name)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2-hour timeout for very long videos
        )
    except subprocess.TimeoutExpired:
        dest.unlink(missing_ok=True)
        raise TranscodeError("Transcoding timed out (exceeded 2 hours)")

    if result.returncode != 0:
        dest.unlink(missing_ok=True)
        stderr_tail = result.stderr[-500:] if result.stderr else "(no stderr)"
        logger.error("FFmpeg failed (exit %d): %s", result.returncode, stderr_tail)
        raise TranscodeError(
            f"FFmpeg transcoding failed (exit code {result.returncode})"
        )

    if not dest.exists():
        raise TranscodeError("Transcoded file was not created")

    if on_progress:
        on_progress(1, 1)

    size_mb = dest.stat().st_size / (1024 * 1024)
    logger.info(
        "Transcoding complete: %s (%.1f MB)", dest.name, size_mb,
    )

    return str(dest)
