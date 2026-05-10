"""
Kafka messaging infrastructure for pipeline automation.

This module provides Kafka-based asynchronous message brokering
for the CV1 → ASR → CV2 pipeline. It is strictly isolated from
annotation, voice annotation, and other non-pipeline features.
"""

from app.messaging.kafka_client import kafka_producer, pipeline_producer
from app.messaging.topics import PipelineTopics

__all__ = ["kafka_producer", "pipeline_producer", "PipelineTopics"]
