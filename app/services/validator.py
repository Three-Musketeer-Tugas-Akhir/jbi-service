import os
import json
import subprocess
import logging
from pathlib import Path

import cv2

from app.config import settings

logger = logging.getLogger(__name__)


class VideoValidationError(Exception):
    """Raised when a video file fails validation."""
    pass


def validate_upload(file_name: str, file_size: int) -> None:
    """Validate file extension and size before saving."""
    ext = Path(file_name).suffix.lower()
    if ext not in settings.allowed_extensions_list:
        raise VideoValidationError(
            f"File extension '{ext}' not allowed. "
            f"Accepted: {', '.join(settings.allowed_extensions_list)}"
        )

    if file_size > settings.max_upload_size_bytes:
        max_mb = settings.max_upload_size_mb
        actual_mb = round(file_size / (1024 * 1024), 1)
        raise VideoValidationError(
            f"File size {actual_mb} MB exceeds maximum {max_mb} MB"
        )


def validate_video_file(file_path: str) -> None:
    """Probe a saved file to verify it's a valid video.

    Uses ffprobe (system FFmpeg) first for broad codec support (including AV1).
    Falls back to OpenCV if ffprobe is not available.
    """
    if _ffprobe_available():
        _validate_with_ffprobe(file_path)
    else:
        logger.warning("ffprobe not found — falling back to OpenCV validation")
        _validate_with_opencv(file_path)


def _ffprobe_available() -> bool:
    """Check if ffprobe is available on the system."""
    try:
        subprocess.run(
            ["ffprobe", "-version"],
            capture_output=True, timeout=5,
        )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _validate_with_ffprobe(file_path: str) -> None:
    """Validate a video file using ffprobe (system FFmpeg)."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,r_frame_rate,nb_frames,duration",
                "-show_entries", "format=duration",
                "-of", "json",
                file_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise VideoValidationError("Video probe timed out — file may be corrupt")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        logger.debug("ffprobe stderr: %s", stderr)
        raise VideoValidationError(
            "File is not a valid video or cannot be opened"
        )

    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError:
        raise VideoValidationError("Could not parse video metadata")

    streams = probe.get("streams", [])
    if not streams:
        raise VideoValidationError("No video stream found in file")

    stream = streams[0]

    # Check frame rate
    r_frame_rate = stream.get("r_frame_rate", "0/1")
    try:
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 0
    except (ValueError, ZeroDivisionError):
        fps = 0

    if fps == 0:
        raise VideoValidationError("Could not read FPS from video")

    # Check duration
    duration = stream.get("duration") or probe.get("format", {}).get("duration")
    if duration is not None:
        try:
            dur = float(duration)
            if dur <= 0:
                raise VideoValidationError("Video has zero duration")
        except ValueError:
            pass

    logger.debug(
        "ffprobe validation passed — codec=%s, fps=%.2f, duration=%s",
        stream.get("codec_name"), fps, duration,
    )


def _validate_with_opencv(file_path: str) -> None:
    """Validate a video file using OpenCV (fallback)."""
    cap = cv2.VideoCapture(file_path)

    try:
        if not cap.isOpened():
            raise VideoValidationError(
                "File is not a valid video or cannot be opened"
            )

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if fps == 0:
            raise VideoValidationError("Could not read FPS from video")

        if frame_count == 0:
            raise VideoValidationError("Video has zero frames")

        ret, frame = cap.read()
        if not ret or frame is None:
            raise VideoValidationError("Cannot decode first frame of video")

    finally:
        cap.release()
