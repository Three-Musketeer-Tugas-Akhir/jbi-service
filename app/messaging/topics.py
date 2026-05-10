"""
Kafka topic definitions for pipeline messaging.

Topics are prefixed with 'pipeline.' to isolate pipeline messages
from any future messaging needs.
"""

from enum import Enum


class PipelineTopics(str, Enum):
    """Kafka topics for pipeline stage automation."""
    
    DETECTION = "pipeline.jobs.detect"
    """Topic for Stage 1 (CV1/Detection) jobs."""
    
    ASR = "pipeline.jobs.asr"
    """Topic for Stage 2 (ASR/Transcription) jobs."""
    
    CROPPING = "pipeline.jobs.crop"
    """Topic for Stage 3 (CV2/Cropping) jobs."""
    
    EVENTS = "pipeline.events"
    """Topic for pipeline status events (monitoring, WebSocket push)."""
    
    DLQ = "pipeline.dlq"
    """Dead Letter Queue for permanently failed jobs."""
    
    @classmethod
    def all_topics(cls) -> list[str]:
        """Return all pipeline topic names."""
        return [
            cls.DETECTION,
            cls.ASR,
            cls.CROPPING,
            cls.EVENTS,
            cls.DLQ,
        ]
    
    @classmethod
    def worker_topics(cls) -> list[str]:
        """Return topics consumed by pipeline workers."""
        return [
            cls.DETECTION,
            cls.ASR,
            cls.CROPPING,
        ]
