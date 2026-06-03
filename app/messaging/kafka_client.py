"""
Kafka client factory and pipeline producer.

Provides singleton-pattern access to Kafka producer and
helper methods for publishing pipeline messages.
"""

import json
import logging
from typing import Any, Dict, Optional

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaError

from app.core.config import settings
from app.messaging.topics import PipelineTopics
from app.messaging.schemas import PipelineMessage, PipelineEvent, DeadLetterMessage

logger = logging.getLogger(__name__)


class KafkaProducer:
    """Async Kafka producer wrapper with lazy initialization."""
    
    _instance: Optional[AIOKafkaProducer] = None
    
    @classmethod
    async def get_instance(cls) -> AIOKafkaProducer:
        """Get or create the singleton producer instance."""
        if cls._instance is None:
            cls._instance = AIOKafkaProducer(
                bootstrap_servers=settings.kafka_brokers_list,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                key_serializer=lambda k: k.encode("utf-8") if k else None,
                acks="all",
                enable_idempotence=True,
                retry_backoff_ms=1000,
            )
            await cls._instance.start()
            logger.info(f"Kafka producer started: {settings.kafka_brokers}")
        return cls._instance
    
    @classmethod
    async def close(cls):
        """Gracefully stop the producer."""
        if cls._instance is not None:
            await cls._instance.stop()
            cls._instance = None
            logger.info("Kafka producer stopped")


class PipelineProducer:
    """High-level producer for pipeline messages."""
    
    async def publish_detection_job(
        self,
        job_id: str,
        video_key: str,
        category: str,
        upload_id: Optional[str] = None,
    ) -> None:
        """Publish a detection job to Kafka."""
        message = PipelineMessage(
            job_id=job_id,
            stage="detection",
            payload={
                "job_id": job_id,
                "video_key": video_key,
                "category": category,
                "upload_id": upload_id,
            },
        )
        await self._send(PipelineTopics.DETECTION.value, message, key=job_id)
    
    async def publish_asr_job(
        self,
        job_id: str,
        segment_count: int,
        segment_ids: Optional[list] = None,
    ) -> None:
        """Publish an ASR job to Kafka."""
        message = PipelineMessage(
            job_id=job_id,
            stage="asr",
            payload={
                "job_id": job_id,
                "segment_count": segment_count,
                "segment_ids": segment_ids or [],
            },
        )
        await self._send(PipelineTopics.ASR.value, message, key=job_id)
    
    async def publish_cropping_job(
        self,
        job_id: str,
        transcript_count: Optional[int] = None,
        mode: str = "full",
    ) -> None:
        """Publish a cropping job to Kafka."""
        message = PipelineMessage(
            job_id=job_id,
            stage="cropping",
            payload={
                "job_id": job_id,
                "transcript_count": transcript_count,
                "mode": mode,
            },
        )
        await self._send(PipelineTopics.CROPPING.value, message, key=job_id)
    
    async def publish_event(
        self,
        event_type: str,
        job_id: str,
        stage: str,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Publish a pipeline event."""
        event = PipelineEvent(
            event_type=event_type,
            job_id=job_id,
            stage=stage,
            status=status,
            metadata=metadata or {},
        )
        await self._send(
            PipelineTopics.EVENTS.value,
            event.model_dump(mode="json"),
            key=job_id,
        )
    
    async def publish_dlq(
        self,
        original_message: Dict[str, Any],
        error: str,
        retry_count: int,
        stage: str,
        job_id: str,
    ) -> None:
        """Publish a failed message to the Dead Letter Queue."""
        dlq = DeadLetterMessage(
            original_message=original_message,
            error=error,
            retry_count=retry_count,
            stage=stage,
            job_id=job_id,
        )
        await self._send(
            PipelineTopics.DLQ.value,
            dlq.model_dump(mode="json"),
            key=job_id,
        )
    
    async def publish_asr_job_partial(
        self,
        job_id: str,
        segment_ids: list,
        segment_count: int,
    ) -> None:
        """Publish a partial ASR retry job to Kafka.
        
        Only processes specific segments that are missing transcripts.
        """
        message = PipelineMessage(
            job_id=job_id,
            stage="asr",
            payload={
                "job_id": job_id,
                "segment_count": segment_count,
                "segment_ids": segment_ids,
                "mode": "partial",
            },
        )
        await self._send(PipelineTopics.ASR.value, message, key=job_id)
    
    async def _send(
        self,
        topic: str,
        message: Any,
        key: Optional[str] = None,
    ) -> None:
        """Send message to Kafka topic."""
        try:
            producer = await KafkaProducer.get_instance()
            
            if isinstance(message, PipelineMessage):
                value = message.to_kafka_dict()
            else:
                value = message
            
            await producer.send(topic, value=value, key=key)
            logger.debug(f"Published to {topic}: job_id={key}")
            
        except KafkaError as e:
            logger.error(f"Kafka publish failed to {topic}: {e}")
            raise


# Global instances for convenience
kafka_producer = KafkaProducer()
pipeline_producer = PipelineProducer()
