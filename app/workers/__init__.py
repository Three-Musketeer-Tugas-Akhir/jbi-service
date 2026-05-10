"""
Kafka-based pipeline workers for CV1 → ASR → CV2 automation.

Workers:
- DetectionWorker: Stage 1 (JBI detection and bbox-based cropping)
- ASRWorker: Stage 2 (ASR transcription)
- CroppingWorker: Stage 3 (timestamp-based re-cropping with JBI buffer)

Base Classes:
- KafkaPipelineWorker: Async Kafka consumer base for all pipeline workers
- BaseWorker: Legacy PostgreSQL queue base (kept for non-pipeline features)
"""

from app.workers.base import BaseWorker
from app.workers.kafka_base import KafkaPipelineWorker
from app.workers.detection_worker import DetectionWorker
from app.workers.asr_worker import ASRWorker
from app.workers.cropping_worker import CroppingWorker

__all__ = [
    "BaseWorker",
    "KafkaPipelineWorker",
    "DetectionWorker",
    "ASRWorker",
    "CroppingWorker",
]
