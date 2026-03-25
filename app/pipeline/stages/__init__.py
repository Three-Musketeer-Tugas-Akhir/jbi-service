"""
Pipeline stages for JBI processing.

Stages:
- Stage 1: Detection (YOLOv8-based JBI detection)
- Stage 2: ASR (faster-whisper transcription)
- Stage 3: Cropping (timestamp-based re-cropping with JBI buffer)
"""

from app.pipeline.stages.stage1_detection import (
    JBIDetector,
    JBISegment,
    JBIDetection,
)
from app.pipeline.stages.stage2_asr import (
    run_asr,
    ASRSegmentInput,
    ASRResult,
)
from app.pipeline.stages.stage3_cropping import (
    run_cropping,
    TimestampBasedCropper,
    CroppingInput,
    CroppingResult,
    SegmentProgressCallback,
    BatchProgressCallback,
)

__all__ = [
    # Stage 1 - Detection
    "JBIDetector",
    "JBISegment",
    "JBIDetection",
    # Stage 2 - ASR
    "run_asr",
    "ASRSegmentInput",
    "ASRResult",
    # Stage 3 - Cropping
    "run_cropping",
    "TimestampBasedCropper",
    "CroppingInput",
    "CroppingResult",
    "SegmentProgressCallback",
    "BatchProgressCallback",
]
