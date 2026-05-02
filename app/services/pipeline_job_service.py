"""
Pipeline job creation service.

Automatically creates pipeline jobs and queue jobs after upload completion.
Integrates with existing worker infrastructure.
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import (
    Upload, 
    PipelineJob, 
    QueueJob, 
    JobStatus,
    User
)
from app.services.minio_service import MinIOService

logger = logging.getLogger(__name__)


class PipelineJobService:
    """
    Service for creating pipeline jobs after upload completion.
    
    Creates:
    - PipelineJob record (main job tracking)
    - QueueJob records for each stage (detection → ASR → cropping)
    - Establishes dependencies between stages
    """
    
    def __init__(self, db: AsyncSession):
        """
        Initialize service.
        
        Args:
            db: Database session (async)
        """
        self.db = db
        self.minio = MinIOService()
    
    async def create_pipeline_job(self, upload: Upload, user: User, job_id: Optional[UUID] = None) -> PipelineJob:
        """
        Create a pipeline job record WITHOUT starting processing.
        
        The job is created with status=UPLOADED and no queue jobs.
        Processing must be triggered separately via start_pipeline_processing().
        
        Called after file assembly is complete.
        
        Args:
            upload: Completed upload record
            user: Uploading user
            job_id: Optional pre-generated job ID
            
        Returns:
            Created PipelineJob (status=UPLOADED, no queue jobs)
        """
        logger.info(
            f"Creating pipeline job for upload {upload.upload_id}: "
            f"{upload.filename} ({upload.file_size} bytes)"
        )
        
        # Use provided job_id, upload's job_id, or generate new
        target_job_id = job_id or upload.job_id or uuid4()
        
        # 1. Create main PipelineJob record (NO queue jobs)
        job = PipelineJob(
            id=target_job_id,
            video_path=upload.final_key,  # Just the key, bucket is implicit based on settings
            original_filename=upload.filename,
            status=JobStatus.UPLOADED,  # Stays UPLOADED until user triggers processing
            current_stage=None,
            category=upload.category,
            file_size=upload.file_size,
            created_by=user.id,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            is_cancelled=False,
        )
        self.db.add(job)
        await self.db.flush()  # Get job.id without full commit
        
        # 2. Link upload to job (no queue jobs created here)
        upload.job_id = job.id
        upload.status = "complete"
        upload.completed_at = datetime.utcnow()
        
        await self.db.flush()
        
        logger.info(
            f"Created pipeline job {job.id} for upload {upload.upload_id} "
            f"(status=UPLOADED, awaiting manual trigger)"
        )
        
        # 3. Publish event (if message bus available)
        await self._publish_job_created_event(job, upload)
        
        return job
    
    async def start_pipeline_processing(self, job_id: UUID) -> PipelineJob:
        """
        Start pipeline processing for a job by creating queue jobs.
        
        Requires the job to be in UPLOADED status and have a category set.
        Creates detection → ASR → cropping queue jobs and sets status to QUEUED.
        
        Args:
            job_id: Pipeline job ID
            
        Returns:
            Updated PipelineJob (status=QUEUED)
            
        Raises:
            ValueError: If job not found, not in correct status, or not classified
        """
        result = await self.db.execute(
            select(PipelineJob).where(PipelineJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        if job.status != JobStatus.UPLOADED:
            raise ValueError(
                f"Job {job_id} cannot be started: status is {job.status}, expected UPLOADED"
            )
        
        if not job.category:
            raise ValueError(
                f"Job {job_id} must be classified before processing can start"
            )
        
        # Find the associated upload record for payload data
        upload_result = await self.db.execute(
            select(Upload).where(Upload.job_id == job_id)
        )
        upload = upload_result.scalar_one_or_none()
        
        # Create queue jobs for each pipeline stage
        queue_jobs = await self._create_queue_jobs(job, upload)
        
        # Update job status to QUEUED
        job.status = JobStatus.QUEUED
        job.updated_at = datetime.utcnow()
        
        await self.db.flush()
        
        logger.info(
            f"Started pipeline processing for job {job.id} "
            f"with {len(queue_jobs)} queue jobs"
        )
        
        return job
    
    async def _create_queue_jobs(
        self, 
        job: PipelineJob, 
        upload: Upload
    ) -> List[QueueJob]:
        """
        Create QueueJob records for each pipeline stage.
        
        Establishes dependencies:
        detection → ASR → cropping
        
        Args:
            job: PipelineJob record
            upload: Upload record with metadata
            
        Returns:
            List of created QueueJob records
        """
        queue_jobs = []
        
        # Stage 1: Detection (YOLO inference)
        detection_job = QueueJob(
            id=uuid4(),
            job_id=job.id,
            queue_name="detection",
            stage="detection",
            status="pending",
            priority=1,
            payload={
                "job_id": str(job.id),
                "video_path": job.video_path,
                "category": job.category,
                "stage": "detection",
                "upload_id": str(upload.id),
            },
            depends_on=None,  # First stage - no dependency
            attempts=0,
            max_attempts=3,
            created_at=datetime.utcnow(),
            scheduled_at=datetime.utcnow(),
        )
        self.db.add(detection_job)
        queue_jobs.append(detection_job)
        await self.db.flush()  # Get ID for dependency
        
        logger.debug(
            f"Created queue job for pipeline job {job.id}: "
            f"detection={detection_job.id}"
        )
        
        return queue_jobs
    
    async def _publish_job_created_event(
        self, 
        job: PipelineJob, 
        upload: Upload
    ) -> None:
        """
        Publish job.created event to message bus.
        
        Frontend can subscribe to this for real-time updates.
        
        Args:
            job: Created PipelineJob
            upload: Source upload
        """
        event = {
            "event": "job.created",
            "timestamp": datetime.utcnow().isoformat(),
            "data": {
                "job_id": str(job.id),
                "upload_id": str(upload.id),
                "user_id": str(job.created_by),
                "status": job.status,
                "video_title": job.original_filename,
                "category": job.category,
                "file_size": job.file_size,
            }
        }
        
        try:
            # Try to publish to Redis if available
            from app.services.queue_service import QueueService
            queue_service = QueueService()
            
            await queue_service.publish_event("job.created", event)
            logger.info(f"Published job.created event for job {job.id}")
            
        except Exception as e:
            # Log but don't fail job creation if event publishing fails
            logger.warning(f"Failed to publish job.created event: {e}")
    
    async def trigger_next_stage(
        self, 
        current_queue_job: QueueJob
    ) -> Optional[QueueJob]:
        """
        Trigger the next stage in the pipeline.
        
        Called by workers when they complete a stage.
        
        Args:
            current_queue_job: Completed queue job
            
        Returns:
            Next QueueJob if found, None otherwise
        """
        # Find the next job that depends on this one
        result = await self.db.execute(
            select(QueueJob).where(
                QueueJob.depends_on == current_queue_job.id,
                QueueJob.status == "pending"
            )
        )
        next_job = result.scalar_one_or_none()
        
        if next_job:
            # Keep it pending - worker will pick it up
            logger.info(
                f"Stage {current_queue_job.stage} complete for job {current_queue_job.job_id}, "
                f"next stage {next_job.stage} ready"
            )
            return next_job
        
        # No next stage - pipeline complete
        logger.info(
            f"Pipeline complete for job {current_queue_job.job_id} "
            f"after stage {current_queue_job.stage}"
        )
        return None
    
    async def get_pipeline_status(self, job_id: UUID) -> dict:
        """
        Get complete pipeline status including all stages.
        
        Args:
            job_id: Pipeline job ID
            
        Returns:
            Status dictionary with all stages
        """
        result = await self.db.execute(
            select(PipelineJob).where(PipelineJob.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            return {"error": "Job not found"}
        
        queue_result = await self.db.execute(
            select(QueueJob).where(QueueJob.job_id == job_id).order_by(QueueJob.priority)
        )
        queue_jobs = queue_result.scalars().all()
        
        stages = []
        for qj in queue_jobs:
            stages.append({
                "stage": qj.stage,
                "status": qj.status,
                "attempts": qj.attempts,
                "max_attempts": qj.max_attempts,
                "error": qj.error_message,
                "created_at": qj.created_at.isoformat() if qj.created_at else None,
                "processed_at": qj.processed_at.isoformat() if qj.processed_at else None,
            })
        
        return {
            "job_id": str(job.id),
            "status": job.status,
            "current_stage": job.current_stage,
            "category": job.category,
            "file_size": job.file_size,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "stages": stages,
        }
