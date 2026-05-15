import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.db.models.pipeline import (
    PipelineJob, 
    JobStatus, 
    PipelineSegment, 
    PipelineTranscript,
    PipelineJobLog
)
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.minio_service import get_minio_service
from app.messaging.kafka_client import pipeline_producer

logger = logging.getLogger(__name__)


class RetryService:
    """Service to handle pipeline job retries and state cleanup."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.job_repo = JobRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.minio_service = get_minio_service()

    async def retry_full(self, job_id: UUID) -> PipelineJob:
        """
        Perform a full retry of the pipeline job from the beginning.
        Deletes all processing data (DB and MinIO) and resets the job to QUEUED.
        """
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        logger.info(f"Starting full retry for job {job_id}")

        # 1. Clean up MinIO files
        minio_prefixes = [
            f"jobs/{job_id}/stage1/",
            f"jobs/{job_id}/segments/",
            f"jobs/{job_id}/audio/",
            f"jobs/{job_id}/utterances/",
        ]
        
        for prefix in minio_prefixes:
            try:
                deleted_count = await self.minio_service.delete_objects_by_prefix(prefix)
                logger.info(f"Deleted {deleted_count} files from MinIO prefix {prefix}")
            except Exception as e:
                logger.warning(f"Failed to delete MinIO prefix {prefix}: {e}")

        # 2. Clean up DB records
        # Due to CASCADE setup on relationships, deleting segments might delete 
        # related records, but it's safer to explicitly delete from bottom up.
        
        # Get all segments to delete
        segments = await self.segment_repo.get_by_job_id(job_id)
        segment_ids = [s.id for s in segments]
        
        if segment_ids:
            # Delete Transcripts
            await self.db.execute(
                delete(PipelineTranscript).where(PipelineTranscript.segment_id.in_(segment_ids))
            )
            
            # Delete Segments
            await self.db.execute(
                delete(PipelineSegment).where(PipelineSegment.id.in_(segment_ids))
            )

        # Delete Job Logs
        await self.db.execute(
            delete(PipelineJobLog).where(PipelineJobLog.job_id == job_id)
        )

        # 3. Reset Job State
        job.status = JobStatus.QUEUED
        job.current_stage = None
        job.error_message = None
        job.completed_at = None
        job.is_cancelled = False
        
        # Reset progress counters
        job.total_segments = 0
        job.completed_segments = 0

        await self.db.flush()
        
        logger.info(f"Job {job_id} reset to QUEUED for full retry")
        
        # 4. Trigger the first stage (Detection)
        try:
            await pipeline_producer.publish_detection_job(
                job_id=str(job_id),
                video_key=job.video_path,
                category=job.category or "SIBI",
            )
            logger.info(f"Published detection job for retry {job_id}")
        except Exception as e:
            logger.error(f"Failed to publish detection job for {job_id}: {e}")
            raise RuntimeError(f"Failed to queue job: {str(e)}")

        return job

    async def retry_from_stage(self, job_id: UUID, failed_stage: str) -> PipelineJob:
        """
        Perform a partial retry from the specified failed stage.
        Cleans up data for that stage and subsequent stages, then re-queues.
        """
        job = await self.job_repo.get_by_id(job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        logger.info(f"Starting partial retry from stage '{failed_stage}' for job {job_id}")

        if failed_stage == "detection":
            # Detection failure means we have no segments anyway, just do a full retry
            return await self.retry_full(job_id)
            
        elif failed_stage == "asr":
            # ASR failed: Keep segments (Stage 1), delete transcripts and audio
            
            # Clean MinIO audio and utterances (Stage 2 & 3 outputs)
            for prefix in [f"jobs/{job_id}/audio/", f"jobs/{job_id}/utterances/"]:
                try:
                    await self.minio_service.delete_objects_by_prefix(prefix)
                except Exception as e:
                    logger.warning(f"Failed to delete MinIO prefix {prefix}: {e}")
            
            # Delete Transcripts from DB
            segments = await self.segment_repo.get_by_job_id(job_id)
            segment_ids = [s.id for s in segments]
            
            if segment_ids:
                await self.db.execute(
                    delete(PipelineTranscript).where(PipelineTranscript.segment_id.in_(segment_ids))
                )
            
            # Reset Job State
            job.status = JobStatus.QUEUED
            job.current_stage = "asr"
            job.error_message = None
            job.completed_at = None
            job.is_cancelled = False
            
            await self.db.flush()
            
            # Trigger ASR stage
            if segments:
                try:
                    await pipeline_producer.publish_asr_job(
                        job_id=str(job_id),
                        segment_count=len(segments),
                        segment_ids=[str(s.id) for s in segments]
                    )
                    logger.info(f"Published ASR job for retry {job_id}")
                except Exception as e:
                    logger.error(f"Failed to publish ASR job for {job_id}: {e}")
                    raise RuntimeError(f"Failed to queue ASR job: {str(e)}")
            else:
                # Should not happen if stage 1 completed, but fallback
                logger.warning(f"No segments found for job {job_id} during ASR retry, falling back to full retry")
                return await self.retry_full(job_id)
                
        elif failed_stage == "cropping":
            # Cropping failed: Keep segments and transcripts, just clear cropping outputs
            
            # Clean MinIO utterances (Stage 3 outputs)
            try:
                await self.minio_service.delete_objects_by_prefix(f"jobs/{job_id}/utterances/")
            except Exception as e:
                logger.warning(f"Failed to delete MinIO utterances for {job_id}: {e}")
            
            # Reset Transcripts cropping status and video path
            segments = await self.segment_repo.get_by_job_id(job_id)
            segment_ids = [s.id for s in segments]
            
            from sqlalchemy import update
            if segment_ids:
                await self.db.execute(
                    update(PipelineTranscript)
                    .where(PipelineTranscript.segment_id.in_(segment_ids))
                    .values(
                        status="pending",
                        video_path=None,
                        merged_video_path=None,
                        merged_video_duration=None,
                    )
                )
            
            # Reset Job State
            job.status = JobStatus.ASR_COMPLETED
            job.current_stage = "cropping"
            job.error_message = None
            job.completed_at = None
            job.is_cancelled = False
            
            await self.db.flush()
            
            # Count total transcripts to queue
            from sqlalchemy import select, func
            if segment_ids:
                result = await self.db.execute(
                    select(func.count(PipelineTranscript.id))
                    .where(PipelineTranscript.segment_id.in_(segment_ids))
                )
                transcript_count = result.scalar() or 0
                
                try:
                    await pipeline_producer.publish_cropping_job(
                        job_id=str(job_id),
                        transcript_count=transcript_count
                    )
                    logger.info(f"Published cropping job for retry {job_id}")
                except Exception as e:
                    logger.error(f"Failed to publish cropping job for {job_id}: {e}")
                    raise RuntimeError(f"Failed to queue cropping job: {str(e)}")
            else:
                logger.warning(f"No segments found for job {job_id} during cropping retry, falling back to full retry")
                return await self.retry_full(job_id)
                
        else:
            raise ValueError(f"Unknown failed stage: {failed_stage}")

        return job
