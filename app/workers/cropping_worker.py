"""
Cropping Worker - Stage 3 Queue Consumer

Processes cropping jobs from the queue.
"""

import logging
from uuid import UUID
from typing import Dict, Any

from app.workers.base import BaseWorker
from app.pipeline.stages.stage3_cropping import run_cropping, CroppingInput
from app.services.job_service import job_service
from app.services.queue_service import queue_service
from app.db.session import async_session
from app.db.models.pipeline import JobStatus
from app.core.config import settings

logger = logging.getLogger(__name__)


class CroppingWorker(BaseWorker):
    """
    Worker that processes cropping jobs from the queue.
    
    Consumes jobs from 'cropping' queue, crops video segments,
    uploads to MinIO, and marks job complete.
    """
    
    queue_name = "cropping"
    max_retries = 2  # Lower retries for resource-intensive operations
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a cropping job.
        
        Args:
            payload: {"job_id": str}
            
        Returns:
            {"segments_cropped": int}
        """
        job_id = UUID(payload["job_id"])
        
        logger.info(f"Processing cropping job: {job_id}")
        
        # Get job details
        async with async_session() as session:
            job = await job_service.get_job(session, str(job_id))
            segments = await job_service.get_segments(session, str(job_id))
            
            # Update status
            await job_service.update_status(session, str(job_id), JobStatus.CROPPING)
            await session.commit()
        
        # Prepare inputs for pipeline stage
        cropping_inputs = [
            CroppingInput(
                segment_index=seg.segment_index,
                video_path=job.video_path,
                bbox_data=seg.bbox_data,
                jbi_start=seg.jbi_start or 0.0,
                jbi_end=seg.jbi_end or 0.0
            )
            for seg in segments
        ]
        
        # Run cropping (pure ML)
        output_dir = f"{settings.output_dir}/{job_id}"
        results = await run_cropping(
            segments=cropping_inputs,
            output_dir=output_dir,
            progress_callback=lambda c, t: logger.info(f"Cropping progress: {c}/{t}")
        )
        
        # Update segments with cropped paths
        async with async_session() as session:
            for result in results:
                if result.success:
                    await job_service.update_segment_cropped_path(
                        session,
                        segment_index=result.segment_index,
                        job_id=str(job_id),
                        cropped_path=result.cropped_video_path
                    )
            await session.commit()
        
        # Mark job as complete
        async with async_session() as session:
            await job_service.update_status(
                session,
                str(job_id),
                JobStatus.READY_FOR_ANNOTATION
            )
            await session.commit()
        
        successful = sum(1 for r in results if r.success)
        return {"segments_cropped": successful}
