from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from enum import Enum
import logging

from app.config import settings
from app.services.detector import DetectionResult, get_detector
from app.services.segmenter import (
    SegmentationResult,
    identify_segments,
    format_detection_times,
)
from app.services.cropper import CropResult, crop_segments
from app.services.transcoder import transcode_to_h264, TranscodeError

logger = logging.getLogger(__name__)


class PipelinePhase(str, Enum):
    TRANSCODING = "transcoding"
    DETECTION = "detection"
    SEGMENTATION = "segmentation"
    CROPPING = "cropping"


# Progress callback: (phase, current_step, total_steps) -> None
PipelineProgressCallback = Callable[[str, int, int], None]


class PipelineError(Exception):
    """Raised when a pipeline phase fails."""

    def __init__(self, phase: PipelinePhase, message: str):
        self.phase = phase
        super().__init__(f"[{phase.value}] {message}")


@dataclass
class PipelineResult:
    """Complete output of the full detect → segment → crop pipeline."""
    job_id: str
    video_path: str
    output_dir: str
    detection: DetectionResult
    segmentation: SegmentationResult
    crop: CropResult
    detection_times_path: str


def run_pipeline(
    job_id: str,
    video_path: str,
    on_progress: Optional[PipelineProgressCallback] = None,
) -> PipelineResult:
    """Execute the full detection → segmentation → cropping pipeline."""
    output_dir = str(Path(settings.output_dir) / job_id)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    logger.info("Pipeline started — job=%s, video=%s", job_id, video_path)

    # Phase 0: Transcode if needed (e.g. AV1 → H.264)
    video_path = _run_transcoding(video_path, on_progress)

    # Phase 1: Detection
    detection_result = _run_detection(video_path, on_progress)

    # Phase 2: Segmentation
    segmentation_result = _run_segmentation(detection_result, on_progress)

    # Phase 3: Cropping
    crop_result = _run_cropping(
        video_path, segmentation_result, output_dir, on_progress,
    )

    # Write detection_times.txt
    detection_times_path = _write_detection_times(
        segmentation_result, output_dir,
    )

    result = PipelineResult(
        job_id=job_id,
        video_path=video_path,
        output_dir=output_dir,
        detection=detection_result,
        segmentation=segmentation_result,
        crop=crop_result,
        detection_times_path=detection_times_path,
    )

    logger.info(
        "Pipeline complete — job=%s, segments=%d, output=%s",
        job_id, len(segmentation_result.segments), output_dir,
    )

    return result


def _run_transcoding(
    video_path: str,
    on_progress: Optional[PipelineProgressCallback],
) -> str:
    """Phase 0: Transcode video to H.264 if OpenCV can't decode it."""
    logger.info("Phase 0: Transcode check — starting")

    def transcode_progress(current: int, total: int):
        if on_progress:
            on_progress(PipelinePhase.TRANSCODING, current, total)

    try:
        new_path = transcode_to_h264(video_path, on_progress=transcode_progress)
    except TranscodeError as exc:
        raise PipelineError(PipelinePhase.TRANSCODING, str(exc)) from exc

    if new_path != video_path:
        logger.info("Phase 0: Transcode — done (transcoded to %s)", new_path)
    else:
        logger.info("Phase 0: Transcode — skipped (codec already compatible)")

    return new_path


def _run_detection(
    video_path: str,
    on_progress: Optional[PipelineProgressCallback],
) -> DetectionResult:
    """Phase 1: Run YOLO detection on every second of the video."""
    logger.info("Phase 1/3: Detection — starting")

    def detection_progress(current_second: int, total_seconds: int):
        if on_progress:
            on_progress(PipelinePhase.DETECTION, current_second, total_seconds)

    try:
        detector = get_detector()
        result = detector.detect(video_path, on_progress=detection_progress)
    except Exception as exc:
        raise PipelineError(PipelinePhase.DETECTION, str(exc)) from exc

    logger.info(
        "Phase 1/3: Detection — done (%d/%d seconds with detections)",
        sum(result.detections), len(result.detections),
    )
    return result


def _run_segmentation(
    detection_result: DetectionResult,
    on_progress: Optional[PipelineProgressCallback],
) -> SegmentationResult:
    """Phase 2: Identify contiguous detection segments."""
    logger.info("Phase 2/3: Segmentation — starting")

    if on_progress:
        on_progress(PipelinePhase.SEGMENTATION, 0, 1)

    try:
        result = identify_segments(detection_result)
    except Exception as exc:
        raise PipelineError(PipelinePhase.SEGMENTATION, str(exc)) from exc

    if on_progress:
        on_progress(PipelinePhase.SEGMENTATION, 1, 1)

    logger.info(
        "Phase 2/3: Segmentation — done (%d segments found)",
        len(result.segments),
    )
    return result


def _run_cropping(
    video_path: str,
    segmentation_result: SegmentationResult,
    output_dir: str,
    on_progress: Optional[PipelineProgressCallback],
) -> CropResult:
    """Phase 3: Crop and export each segment as MP4."""
    segments = segmentation_result.segments

    if not segments:
        logger.info("Phase 3/3: Cropping — skipped (no segments)")
        if on_progress:
            on_progress(PipelinePhase.CROPPING, 0, 0)
        return CropResult(output_dir=output_dir)

    logger.info("Phase 3/3: Cropping — starting (%d segments)", len(segments))

    if on_progress:
        on_progress(PipelinePhase.CROPPING, 0, len(segments))

    try:
        result = crop_segments(video_path, segments, output_dir)
    except Exception as exc:
        raise PipelineError(PipelinePhase.CROPPING, str(exc)) from exc

    if on_progress:
        on_progress(PipelinePhase.CROPPING, len(segments), len(segments))

    logger.info("Phase 3/3: Cropping — done (%d files)", len(result.segments))
    return result


def _write_detection_times(
    segmentation_result: SegmentationResult,
    output_dir: str,
) -> str:
    """Write the detection_times.txt summary file."""
    content = format_detection_times(segmentation_result.segments)
    file_path = Path(output_dir) / "detection_times.txt"
    file_path.write_text(content, encoding="utf-8")
    logger.debug("Wrote detection_times.txt to %s", file_path)
    return str(file_path)
