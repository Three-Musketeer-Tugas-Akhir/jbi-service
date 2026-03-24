from dataclasses import dataclass, field
from typing import Callable, Optional
import math
import logging

import cv2
import torch
from ultralytics import YOLO

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    """Metadata extracted from a video file via OpenCV."""
    fps: float
    frame_count: int
    duration_seconds: float


@dataclass
class DetectionResult:
    """Complete output of the detection phase."""
    metadata: VideoMetadata
    detections: list[bool] = field(default_factory=list)
    bboxes: dict[int, list[float]] = field(default_factory=dict)
    # bboxes key = second index, value = [x_min, y_min, width, height]


# Type alias for progress callback: (current_second, total_seconds) -> None
ProgressCallback = Callable[[int, int], None]


class DetectorService:
    """Handles YOLO model loading and per-second video detection."""

    def __init__(self):
        self._device = self._resolve_device()
        self._model = self._load_model()
        logger.info(
            "DetectorService initialized — device=%s, model=%s",
            self._device, settings.model_path,
        )

    @staticmethod
    def _resolve_device() -> torch.device:
        """Resolve processing device based on settings.processing_mode."""
        mode = settings.processing_mode.lower()

        if mode == "gpu":
            if torch.cuda.is_available():
                device = torch.device("cuda")
                logger.info("GPU mode: using CUDA (%s)", torch.cuda.get_device_name(0))
            else:
                device = torch.device("cpu")
                logger.warning("GPU mode requested but CUDA not available — falling back to CPU")
        elif mode == "cpu":
            device = torch.device("cpu")
            logger.info("CPU mode: forced by config")
        else:  # "auto"
            if torch.cuda.is_available():
                device = torch.device("cuda")
                logger.info("Auto mode: CUDA available, using GPU (%s)", torch.cuda.get_device_name(0))
            else:
                device = torch.device("cpu")
                logger.info("Auto mode: CUDA not available, using CPU")

        return device

    def _load_model(self) -> YOLO:
        """Load YOLO model from configured path and move to device."""
        model_path = settings.model_path
        logger.info("Loading YOLO model from %s", model_path)
        model = YOLO(model_path)
        model.to(self._device)
        return model

    def detect(
        self,
        video_path: str,
        on_progress: Optional[ProgressCallback] = None,
    ) -> DetectionResult:
        """Run per-second object detection on a video file."""
        metadata, cap = self._open_video(video_path)
        total_seconds = math.floor(metadata.duration_seconds)
        batch_size = settings.batch_size

        detections: list[bool] = []
        bboxes: dict[int, list[float]] = {}

        try:
            second = 0
            while second < total_seconds:
                frames, timestamps = self._read_batch(
                    cap, second, batch_size, total_seconds,
                )

                if not frames:
                    logger.warning("No frames read at second %d — stopping", second)
                    break

                batch_detected, batch_bboxes = self._detect_batch(frames, second)

                detections.extend(batch_detected)
                bboxes.update(batch_bboxes)

                current = min(second + batch_size, total_seconds)
                if on_progress:
                    on_progress(current, total_seconds)

                second += batch_size

        finally:
            cap.release()
            logger.debug("VideoCapture released for %s", video_path)

        result = DetectionResult(
            metadata=metadata,
            detections=detections,
            bboxes=bboxes,
        )

        logger.info(
            "Detection complete — %d seconds scanned, %d with detections",
            len(detections), sum(detections),
        )

        return result

    @staticmethod
    def _open_video(video_path: str) -> tuple[VideoMetadata, cv2.VideoCapture]:
        """Open video and extract metadata."""
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        if fps == 0:
            cap.release()
            raise ValueError(f"Could not read FPS from video: {video_path}")

        duration = frame_count / fps

        metadata = VideoMetadata(
            fps=fps,
            frame_count=frame_count,
            duration_seconds=duration,
        )

        logger.info(
            "Opened video: fps=%.2f, frames=%d, duration=%.1fs",
            fps, frame_count, duration,
        )

        return metadata, cap

    @staticmethod
    def _read_batch(
        cap: cv2.VideoCapture,
        second_start: int,
        batch_size: int,
        total_seconds: int,
    ) -> tuple[list, list[int]]:
        """Read one frame per second for a batch window."""
        frames = []
        timestamps = []

        for i in range(batch_size):
            target_second = second_start + i
            if target_second >= total_seconds:
                break

            cap.set(cv2.CAP_PROP_POS_MSEC, target_second * 1000)
            ret, frame = cap.read()

            if not ret or frame is None:
                logger.debug("Failed to read frame at second %d", target_second)
                continue

            frames.append(frame)
            timestamps.append(target_second)

        return frames, timestamps

    def _detect_batch(
        self,
        frames: list,
        second_start: int,
    ) -> tuple[list[bool], dict[int, list[float]]]:
        """Run YOLO inference on a batch of frames."""
        results = self._model(frames, verbose=False)

        detected: list[bool] = []
        bboxes: dict[int, list[float]] = {}

        for idx, result in enumerate(results):
            has_detection = len(result.boxes) > 0
            detected.append(has_detection)

            if has_detection:
                yolo_bbox = result.boxes[0].xywh.cpu().numpy()[0]
                bbox = self._rescale_bbox(yolo_bbox)

                current_second = second_start + idx
                bboxes[current_second] = bbox

        return detected, bboxes

    @staticmethod
    def _rescale_bbox(bbox) -> list[float]:
        """Convert YOLO xywh (center-based) to [x_min, y_min, w, h]."""
        x_center, y_center, w, h = bbox
        x_min = x_center - (w / 2)
        y_min = y_center - (h / 2)
        return [float(x_min), float(y_min), float(w), float(h)]


# Lazy singleton
_detector: Optional[DetectorService] = None


def get_detector() -> DetectorService:
    """Get or create the singleton DetectorService instance."""
    global _detector
    if _detector is None:
        _detector = DetectorService()
    return _detector
