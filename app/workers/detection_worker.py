"""
Detection Worker - Stage 1 Queue Consumer

Processes detection jobs from the queue using YOLOv8.
"""

import asyncio
import logging
import tempfile
from pathlib import Path
from uuid import UUID
from typing import Dict, Any

from app.workers.base import BaseWorker
from app.pipeline.stages.stage1_detection import JBIDetector
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.queue_service import queue_service
from app.services.minio_service import get_minio_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus, PipelineSegment

logger = logging.getLogger(__name__)


class DetectionWorker(BaseWorker):
    """
    Worker that processes detection jobs from the queue.
    
    Consumes jobs from 'detection' queue, runs YOLO inference,
    creates segments, and queues next stage (ASR).
    """
    
    queue_name = "detection"
    max_retries = 3
    
    def __init__(self):
        super().__init__()
        self.minio_service = get_minio_service()
        self.detector = JBIDetector()
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a detection job.
        
        Args:
            payload: {"job_id": str, "video_path": str, "video_key": str}
            
        Returns:
            {"segments_detected": int, "confidence": float}
        """
        job_id = UUID(payload["job_id"])
        video_key = payload.get("video_key")
        
        logger.info(f"Processing detection job: {job_id}")
        
        # Update status to DETECTING
        async with async_session() as session:
            job_repo = JobRepository(session)
            await job_repo.update_status(job_id, "DETECTING")
            await session.commit()
        
        # Download video from MinIO
        temp_video = None
        try:
            if video_key:
                video_data = await self.minio_service.download_file(video_key)
                temp_video = self._save_temp_video(video_data, job_id)
                video_path = str(temp_video)
            else:
                video_path = payload.get("video_path")
            
            # Run detection (pure ML, no DB)
            segments = await self._run_detection(video_path, job_id)
            
            # Store segments in database
            async with async_session() as session:
                segment_repo = SegmentRepository(session)
                db_segments = []
                for i, segment in enumerate(segments):
                    db_segment = PipelineSegment(
                        job_id=job_id,
                        segment_index=i,
                        bbox_data=segment.bbox_data if hasattr(segment, 'bbox_data') else None,
                        jbi_start=segment.start_time if hasattr(segment, 'start_time') else None,
                        jbi_end=segment.end_time if hasattr(segment, 'end_time') else None,
                        detection_confidence=segment.confidence if hasattr(segment, 'confidence') else None
                    )
                    db_segments.append(db_segment)
                await segment_repo.create_many(db_segments)
                await session.commit()
            
            # Queue next stage
            await self._queue_next_stage(job_id, segments)
            
            avg_confidence = sum(s.confidence for s in segments) / len(segments) if segments else 0
            
            return {
                "segments_detected": len(segments),
                "confidence": avg_confidence
            }
            
        finally:
            # Cleanup temp file
            if temp_video and temp_video.exists():
                try:
                    temp_video.unlink()
                except OSError:
                    pass
    
    async def _run_detection(self, video_path: str, job_id: UUID):
        """Run detection on video."""
        # Use the detector from pipeline stage
        from pathlib import Path
        jbi_segments = await self.detector.detect(Path(video_path))
        return jbi_segments
    
    async def _queue_next_stage(self, job_id: UUID, segments):
        """Queue ASR stage after detection."""
        async with async_session() as session:
            await queue_service.enqueue(session, "asr", {
                "job_id": str(job_id),
                "segment_count": len(segments)
            })
            await session.commit()
    
    def _save_temp_video(self, video_data: bytes, job_id: UUID) -> Path:
        """Save video data to temporary file."""
        temp_file = tempfile.NamedTemporaryFile(
            suffix=".mp4",
            delete=False,
            prefix=f"detect_{job_id}_"
        )
        temp_file.write(video_data)
        temp_file.close()
        return Path(temp_file.name)
