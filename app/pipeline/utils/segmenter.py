from dataclasses import dataclass, field
from datetime import timedelta
import logging

from app.core.config import settings
from app.pipeline.models.detector import DetectionResult

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    """A single contiguous time range where the target object was detected."""
    index: int
    start_seconds: int
    end_seconds: int
    duration_seconds: int
    start_time: str    # formatted, e.g. "0:02:52"
    end_time: str      # formatted, e.g. "0:03:25"
    bbox: list[float]  # [x_min, y_min, width, height] from first detected frame


@dataclass
class SegmentationResult:
    """Complete output of the segmentation phase."""
    segments: list[Segment] = field(default_factory=list)
    total_seconds_scanned: int = 0
    seconds_with_detection: int = 0


def identify_segments(detection_result: DetectionResult) -> SegmentationResult:
    """Identify contiguous detection segments from per-second detection data."""
    detections = detection_result.detections
    bboxes = detection_result.bboxes
    min_duration = settings.min_segment_duration

    # Find contiguous True runs
    raw_segments: list[tuple[int, int]] = []
    start = None

    for second, present in enumerate(detections):
        if present and start is None:
            start = second
        elif not present and start is not None:
            raw_segments.append((start, second))
            start = None

    if start is not None:
        raw_segments.append((start, len(detections)))

    # Filter by minimum duration
    filtered = [
        (s, e) for s, e in raw_segments
        if (e - s) >= min_duration
    ]

    logger.info(
        "Segmentation: %d raw segments → %d after min_duration=%ds filter",
        len(raw_segments), len(filtered), min_duration,
    )

    # Build Segment objects with bbox
    segments: list[Segment] = []

    for idx, (seg_start, seg_end) in enumerate(filtered):
        bbox = _find_segment_bbox(seg_start, seg_end, bboxes)

        segment = Segment(
            index=idx,
            start_seconds=seg_start,
            end_seconds=seg_end,
            duration_seconds=seg_end - seg_start,
            start_time=_seconds_to_time(seg_start),
            end_time=_seconds_to_time(seg_end),
            bbox=bbox,
        )
        segments.append(segment)

        logger.debug(
            "Segment %d: %s → %s (%ds), bbox=%s",
            idx, segment.start_time, segment.end_time,
            segment.duration_seconds, bbox,
        )

    return SegmentationResult(
        segments=segments,
        total_seconds_scanned=len(detections),
        seconds_with_detection=sum(detections),
    )


def format_detection_times(segments: list[Segment]) -> str:
    """Generate detection_times.txt content as a string."""
    lines = []
    for seg in segments:
        lines.append(f"{seg.start_time} - {seg.end_time}")
    return "\n".join(lines)


def _find_segment_bbox(
    start: int,
    end: int,
    bboxes: dict[int, list[float]],
) -> list[float]:
    """Find the bbox for a segment by checking the first available second."""
    for second in range(start, end):
        if second in bboxes:
            return bboxes[second]

    logger.warning("No bbox found for segment %d-%d", start, end)
    return [0.0, 0.0, 0.0, 0.0]


def _seconds_to_time(seconds: int) -> str:
    """Convert seconds to human-readable time string."""
    return str(timedelta(seconds=seconds))
