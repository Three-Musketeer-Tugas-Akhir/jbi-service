import os
import logging
from pathlib import Path

import cv2

from app.core.config import settings

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
    """Probe a saved file with OpenCV to verify it's a valid video.

    Only checks metadata (fps, frame count). Does NOT attempt to decode
    frames, since some codecs (e.g. AV1) are not supported by OpenCV's
    bundled FFmpeg. Codec compatibility is handled later by the transcoder.
    """
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

        logger.debug(
            "Video validation passed — fps=%.2f, frames=%d, path=%s",
            fps, frame_count, file_path,
        )

    finally:
        cap.release()
