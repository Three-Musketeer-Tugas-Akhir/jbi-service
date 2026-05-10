"""
Message schemas for Kafka pipeline messaging.

All messages use a standard envelope with stage-specific payloads.
"""

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field


class PipelineMessage(BaseModel):
    """Standard envelope for all pipeline Kafka messages."""
    
    message_id: UUID = Field(default_factory=uuid4)
    """Unique message identifier."""
    
    job_id: UUID
    """Associated pipeline job ID."""
    
    trace_id: UUID = Field(default_factory=uuid4)
    """Tracing ID for request correlation across stages."""
    
    stage: str
    """Pipeline stage: detection, asr, cropping."""
    
    version: str = "1.0"
    """Message schema version."""
    
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    """UTC timestamp when message was created."""
    
    payload: Dict[str, Any]
    """Stage-specific payload data."""
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }
    
    def to_kafka_dict(self) -> dict:
        """Serialize to dict for Kafka (UUIDs and datetimes as strings)."""
        return {
            "message_id": str(self.message_id),
            "job_id": str(self.job_id),
            "trace_id": str(self.trace_id),
            "stage": self.stage,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "payload": self.payload,
        }
    
    @classmethod
    def from_kafka_dict(cls, data: dict) -> "PipelineMessage":
        """Deserialize from Kafka dict."""
        return cls(**data)


class DetectionPayload(BaseModel):
    """Payload for detection stage messages."""
    
    job_id: str
    video_key: str
    category: str
    upload_id: Optional[str] = None


class ASRPayload(BaseModel):
    """Payload for ASR stage messages."""
    
    job_id: str
    segment_count: int
    segment_ids: list[str] = []


class CroppingPayload(BaseModel):
    """Payload for cropping stage messages."""
    
    job_id: str
    transcript_count: Optional[int] = None


class PipelineEvent(BaseModel):
    """Event message for pipeline monitoring."""
    
    event_type: str
    """Event type: stage.started, stage.completed, stage.failed, job.cancelled."""
    
    job_id: str
    stage: str
    status: Optional[str] = None
    metadata: Dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class DeadLetterMessage(BaseModel):
    """Message format for Dead Letter Queue."""
    
    original_message: Dict[str, Any]
    error: str
    failed_at: datetime = Field(default_factory=datetime.utcnow)
    retry_count: int
    stage: str
    job_id: str
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }
