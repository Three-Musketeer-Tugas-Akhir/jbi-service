"""Serialize / deserialize PipelineResult ↔ JSONB-compatible dict."""

from app.services.pipeline import PipelineResult
from app.services.detector import DetectionResult, VideoMetadata
from app.services.segmenter import SegmentationResult, Segment
from app.services.cropper import CropResult, CroppedSegment


def serialize_pipeline_result(r: PipelineResult) -> dict:
    """Convert a PipelineResult dataclass into a JSON-serializable dict."""
    return {
        "video_path": r.video_path,
        "output_dir": r.output_dir,
        "detection_times_path": r.detection_times_path,
        "detection": {
            "metadata": {
                "fps": r.detection.metadata.fps,
                "frame_count": r.detection.metadata.frame_count,
                "duration_seconds": r.detection.metadata.duration_seconds,
            },
            "total_detections": sum(r.detection.detections),
            "total_seconds": len(r.detection.detections),
        },
        "segmentation": {
            "total_seconds_scanned": r.segmentation.total_seconds_scanned,
            "seconds_with_detection": r.segmentation.seconds_with_detection,
            "segments": [
                {
                    "index": s.index,
                    "start_seconds": s.start_seconds,
                    "end_seconds": s.end_seconds,
                    "duration_seconds": s.duration_seconds,
                    "start_time": s.start_time,
                    "end_time": s.end_time,
                    "bbox": s.bbox,
                }
                for s in r.segmentation.segments
            ],
        },
        "crop": {
            "output_dir": r.crop.output_dir,
            "segments": [
                {
                    "index": cs.index,
                    "file_path": cs.file_path,
                    "file_name": cs.file_name,
                    "start_seconds": cs.start_seconds,
                    "end_seconds": cs.end_seconds,
                    "duration_seconds": cs.duration_seconds,
                    "bbox": cs.bbox,
                }
                for cs in r.crop.segments
            ],
        },
    }


def deserialize_pipeline_result(job_id: str, data: dict) -> PipelineResult:
    """Reconstruct a PipelineResult from a stored JSONB dict."""
    meta = data["detection"]["metadata"]
    return PipelineResult(
        job_id=job_id,
        video_path=data["video_path"],
        output_dir=data["output_dir"],
        detection_times_path=data["detection_times_path"],
        detection=DetectionResult(
            metadata=VideoMetadata(
                fps=meta["fps"],
                frame_count=meta["frame_count"],
                duration_seconds=meta["duration_seconds"],
            ),
        ),
        segmentation=SegmentationResult(
            total_seconds_scanned=data["segmentation"]["total_seconds_scanned"],
            seconds_with_detection=data["segmentation"]["seconds_with_detection"],
            segments=[
                Segment(**s) for s in data["segmentation"]["segments"]
            ],
        ),
        crop=CropResult(
            output_dir=data["crop"]["output_dir"],
            segments=[
                CroppedSegment(**cs) for cs in data["crop"]["segments"]
            ],
        ),
    )
