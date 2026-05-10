"""
Kafka-based base worker for pipeline stages.

Replaces the PostgreSQL polling queue with Kafka consumer groups.
Each worker type consumes from its designated topic and publishes
to the next stage topic upon successful completion.
"""

import asyncio
import json
import logging
import signal
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition
from aiokafka.errors import KafkaError, ConsumerStoppedError

from app.core.config import settings
from app.core.exceptions import ProcessingError
from app.db.session import async_session
from app.repositories.job_repository import JobRepository
from app.messaging.topics import PipelineTopics
from app.messaging.schemas import PipelineMessage
from app.messaging.kafka_client import pipeline_producer

logger = logging.getLogger(__name__)


class KafkaPipelineWorker(ABC):
    """
    Abstract base class for Kafka-based pipeline workers.
    
    Implementations must define:
    - topic: The Kafka topic to consume from
    - consumer_group: The consumer group ID
    - next_stage_topic: Optional next topic to publish to
    - process(): The actual work method
    """
    
    topic: str = ""
    consumer_group: str = ""
    next_stage_topic: Optional[str] = None
    max_retries: int = 3
    retry_base_delay: int = 5  # seconds
    
    def __init__(self):
        if not self.topic or not self.consumer_group:
            raise ValueError(
                f"{self.__class__.__name__} must define topic and consumer_group"
            )
        
        self._shutdown_event = asyncio.Event()
        self._consumer: Optional[AIOKafkaConsumer] = None
        
        # Handle shutdown signals
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)
    
    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(
            f"Shutdown signal received for {self.__class__.__name__}, "
            "finishing current job..."
        )
        self._shutdown_event.set()
    
    async def run(self) -> None:
        """
        Main worker loop.
        
        Connects to Kafka, consumes messages, and processes them.
        Runs indefinitely until interrupted.
        """
        logger.info(
            f"Starting {self.__class__.__name__} "
            f"[topic={self.topic}, group={self.consumer_group}]"
        )
        
        self._consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=settings.kafka_brokers_list,
            group_id=self.consumer_group,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            max_poll_records=1,
            max_poll_interval_ms=600000,      # 10 min for long GPU inference
            session_timeout_ms=45000,          # 45s before consumer considered dead
            heartbeat_interval_ms=15000,       # Heartbeat every 15s
            request_timeout_ms=120000,         # 2 min request timeout
        )
        
        await self._consumer.start()
        logger.info(f"Kafka consumer started for topic: {self.topic}")
        
        try:
            async for msg in self._consumer:
                if self._shutdown_event.is_set():
                    break
                
                await self._process_message(msg)
        
        except ConsumerStoppedError:
            logger.info("Consumer stopped")
        except Exception as e:
            logger.exception(f"Error in worker loop: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _process_message(self, msg) -> None:
        """Process a single Kafka message with retry logic."""
        try:
            data = json.loads(msg.value.decode("utf-8"))
            message = PipelineMessage.from_kafka_dict(data)
            job_id = str(message.job_id)
            
            logger.info(
                f"Processing {message.stage} job: {job_id} "
                f"[msg_id={message.message_id}]"
            )
            
            # Check cancellation
            if await self.is_job_cancelled(job_id):
                logger.warning(f"Job {job_id} was cancelled, skipping")
                await self._commit(msg)
                return
            
            # Check idempotency
            if await self.is_already_processed(job_id):
                logger.info(f"Job {job_id} already processed, skipping")
                if self.next_stage_topic:
                    await self._ensure_next_stage_queued(message)
                await self._commit(msg)
                return
            
            # Process with retry
            result = await self._process_with_retry(message)
            
            if result is not None:
                # Publish next stage
                if self.next_stage_topic:
                    await self._publish_next_stage(message, result)
                
                # Commit offset only after everything succeeds
                await self._commit(msg)
                logger.info(f"Job {job_id} completed and committed")
            
        except Exception as e:
            logger.exception(f"Failed to process message: {e}")
            # Don't commit → message will be redelivered
            # But we need to avoid infinite loop for non-retryable errors
            if isinstance(e, ProcessingError) and e.permanent:
                logger.error(f"Permanent error, sending to DLQ: {e}")
                await self._send_to_dlq(msg, e)
                await self._commit(msg)
    
    async def _process_with_retry(self, message: PipelineMessage) -> Optional[Dict[str, Any]]:
        """Process message with automatic retry."""
        job_id = str(message.job_id)
        attempts = 0
        last_error = None
        
        while attempts < self.max_retries:
            try:
                result = await self.process(message.payload)
                return result
            except Exception as e:
                attempts += 1
                last_error = e
                logger.warning(
                    f"Job {job_id} failed (attempt {attempts}/{self.max_retries}): {e}"
                )
                
                if attempts < self.max_retries:
                    delay = min(2 ** (attempts - 1) * self.retry_base_delay, 300)
                    logger.info(f"Retrying in {delay}s...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Job {job_id} failed after {self.max_retries} attempts")
                    raise last_error
        
        return None
    
    async def _commit(self, msg) -> None:
        """Commit Kafka offset for a message."""
        try:
            tp = TopicPartition(msg.topic, msg.partition)
            await self._consumer.commit({tp: msg.offset + 1})
        except KafkaError as e:
            logger.error(f"Failed to commit offset: {e}")
            raise
    
    async def _publish_next_stage(
        self,
        message: PipelineMessage,
        result: Dict[str, Any],
    ) -> None:
        """Publish message to next stage topic."""
        try:
            if self.next_stage_topic == PipelineTopics.ASR:
                await pipeline_producer.publish_asr_job(
                    job_id=str(message.job_id),
                    segment_count=result.get("segments_detected", 0),
                    segment_ids=result.get("segment_ids", []),
                )
            elif self.next_stage_topic == PipelineTopics.CROPPING:
                await pipeline_producer.publish_cropping_job(
                    job_id=str(message.job_id),
                    transcript_count=result.get("transcripts_count"),
                )
            
            logger.info(
                f"Queued next stage {self.next_stage_topic} for job {message.job_id}"
            )
        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to queue next stage for job {message.job_id}: {e}"
            )
            raise
    
    async def _ensure_next_stage_queued(
        self,
        message: PipelineMessage,
    ) -> None:
        """Ensure next stage is queued for idempotent reprocessing."""
        try:
            if self.next_stage_topic == PipelineTopics.ASR:
                # Check if segments exist but ASR not started
                async with async_session() as session:
                    from app.repositories.segment_repository import SegmentRepository
                    segment_repo = SegmentRepository(session)
                    segments = await segment_repo.get_by_job_id(message.job_id)
                    if segments:
                        await pipeline_producer.publish_asr_job(
                            job_id=str(message.job_id),
                            segment_count=len(segments),
                            segment_ids=[str(s.id) for s in segments],
                        )
            elif self.next_stage_topic == PipelineTopics.CROPPING:
                # Check if transcripts exist but cropping not started
                async with async_session() as session:
                    from app.repositories.segment_repository import SegmentRepository
                    from sqlalchemy import select
                    from app.db.models.pipeline import PipelineTranscript
                    segment_repo = SegmentRepository(session)
                    segments = await segment_repo.get_by_job_id(message.job_id)
                    if segments:
                        segment_ids = [s.id for s in segments]
                        result = await session.execute(
                            select(PipelineTranscript).where(
                                PipelineTranscript.segment_id.in_(segment_ids)
                            )
                        )
                        transcripts = result.scalars().all()
                        if transcripts:
                            await pipeline_producer.publish_cropping_job(
                                job_id=str(message.job_id),
                                transcript_count=len(transcripts),
                            )
        except Exception as e:
            logger.warning(f"Failed to ensure next stage: {e}")
    
    async def _send_to_dlq(self, msg, error: Exception) -> None:
        """Send failed message to Dead Letter Queue."""
        try:
            data = json.loads(msg.value.decode("utf-8"))
            job_id = data.get("payload", {}).get("job_id", "unknown")
            stage = data.get("stage", "unknown")
            
            await pipeline_producer.publish_dlq(
                original_message=data,
                error=str(error),
                retry_count=self.max_retries,
                stage=stage,
                job_id=job_id,
            )
            logger.warning(f"Sent job {job_id} to DLQ")
        except Exception as e:
            logger.error(f"Failed to send to DLQ: {e}")
    
    async def _cleanup(self) -> None:
        """Gracefully cleanup resources."""
        logger.info(f"Cleaning up {self.__class__.__name__}...")
        if self._consumer:
            await self._consumer.stop()
        from app.messaging.kafka_client import KafkaProducer
        await KafkaProducer.close()
    
    async def is_job_cancelled(self, job_id: str) -> bool:
        """Check if a job has been cancelled."""
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return False
        
        async with async_session() as session:
            job_repo = JobRepository(session)
            return await job_repo.is_job_cancelled(job_uuid)
    
    async def is_already_processed(self, job_id: str) -> bool:
        """
        Check if job was already processed (idempotency).
        
        Override in subclasses for stage-specific checks.
        """
        return False
    
    @abstractmethod
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Implement this with the actual stage processing logic.
        
        Args:
            payload: The message payload
            
        Returns:
            Dict with results (used for next stage publishing)
            
        Raises:
            Exception: If processing fails (triggers retry)
        """
        pass
    
    async def check_cancellation(self, job_id: str, checkpoint: str = "") -> None:
        """Check for cancellation and raise if cancelled."""
        if await self.is_job_cancelled(job_id):
            msg = f"Job {job_id} was cancelled"
            if checkpoint:
                msg += f" at checkpoint: {checkpoint}"
            raise ProcessingError(msg, permanent=True)
