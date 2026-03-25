from dataclasses import dataclass, field
from pathlib import Path
import logging

from moviepy import VideoFileClip

from app.core.config import settings
from app.services.segmenter import Segment

logger = logging.getLogger(__name__)


@dataclass
class CroppedSegment:
    """Metadata for a single exported segment file."""
    index: int
    file_path: str
    file_name: str
    start_seconds: int
    end_seconds: int
    duration_seconds: int
    bbox: list[float]


@dataclass
class CropResult:
    """Complete output of the cropping phase."""
    segments: list[CroppedSegment] = field(default_factory=list)
    output_dir: str = ""


def crop_segments(
    video_path: str,
    segments: list[Segment],
    output_dir: str,
) -> CropResult:
    """Crop and export each segment from the source video."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    source_video = VideoFileClip(video_path)
    max_duration = source_video.duration
    source_video.close()

    result = CropResult(output_dir=output_dir)

    for segment in segments:
        try:
            cropped = _export_segment(
                video_path=video_path,
                segment=segment,
                output_dir=output_path,
                max_duration=max_duration,
            )
            result.segments.append(cropped)
        except Exception:
            logger.exception(
                "Failed to export segment %d (%s → %s)",
                segment.index, segment.start_time, segment.end_time,
            )

    logger.info(
        "Cropping complete — %d/%d segments exported to %s",
        len(result.segments), len(segments), output_dir,
    )

    return result


def _export_segment(
    video_path: str,
    segment: Segment,
    output_dir: Path,
    max_duration: float,
) -> CroppedSegment:
    """Export a single cropped segment as MP4."""
    file_name = f"segment_{segment.index:06d}.mp4"
    file_path = output_dir / file_name

    logger.info(
        "Exporting segment %d: %s → %s (%ds)",
        segment.index, segment.start_time, segment.end_time,
        segment.duration_seconds,
    )

    video = VideoFileClip(video_path)

    try:
        end_time = min(segment.end_seconds, max_duration)
        subclip = video.subclipped(segment.start_seconds, end_time)

        bbox = segment.bbox

        def crop_frame(frame):
            return _crop_frame_by_bbox(frame, bbox)

        cropped_subclip = subclip.image_transform(crop_frame)

        temp_audio = str(file_path) + "_temp_audio.m4a"

        cropped_subclip.write_videofile(
            str(file_path),
            codec=settings.video_codec,
            audio_codec=settings.audio_codec,
            preset=settings.ffmpeg_preset,
            threads=settings.ffmpeg_threads,
            temp_audiofile=temp_audio,
            remove_temp=True,
            ffmpeg_params=["-crf", str(settings.crf_value)],
            logger=None,
        )

    finally:
        video.close()

    logger.info("Exported: %s (segment %d)", file_name, segment.index)

    return CroppedSegment(
        index=segment.index,
        file_path=str(file_path),
        file_name=file_name,
        start_seconds=segment.start_seconds,
        end_seconds=segment.end_seconds,
        duration_seconds=segment.duration_seconds,
        bbox=segment.bbox,
    )


def _crop_frame_by_bbox(frame, bbox: list[float]):
    """Crop a single video frame to the bounding box."""
    x_min, y_min, w, h = [int(coord) for coord in bbox]

    x_min = max(0, x_min)
    y_min = max(0, y_min)

    if w % 2 != 0:
        w -= 1
    if h % 2 != 0:
        h -= 1

    x_max = min(frame.shape[1], x_min + w)
    y_max = min(frame.shape[0], y_min + h)

    return frame[y_min:y_max, x_min:x_max]
