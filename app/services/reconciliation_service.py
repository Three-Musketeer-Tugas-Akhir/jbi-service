"""
Pipeline Reconciliation Service.

Periodically checks for jobs stuck in intermediate pipeline stages
and republishes them to Kafka if needed. This acts as a safety net
for the rare case where a worker crashes after DB commit but before
publishing the next stage message.

This service is ONLY for pipeline stages (CV1/ASR/CV2).
It does NOT interact with annotation, voice annotation, or curation.
"""

import logging
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.models.pipeline import PipelineJob, JobStatus, PipelineSegment, PipelineTranscript
from app.messaging.kafka_client import pipeline_producer
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository

logger = logging.getLogger(__name__)


class ReconciliationService:
    """
    Service to reconcile pipeline jobs stuck in intermediate states.
    
    Scenarios handled:
    1. Job stuck in DETECTING > 30 min: segments exist but ASR not queued
    2. Job stuck in ASR_COMPLETED > 30 min: transcripts exist but cropping not queued
    3. Job stuck in TRANSCRIBING > 60 min: no transcripts exist
    """
    
    # Time thresholds for considering a job "stuck"
    DETECTING_THRESHOLD_MINUTES = 30
    ASR_COMPLETED_THRESHOLD_MINUTES = 30
    TRANSCRIBING_THRESHOLD_MINUTES = 60
    CROPPING_THRESHOLD_MINUTES = 60
    
    async def run_reconciliation(self) -> dict:
        """
        Run full reconciliation check.
        
        Returns:
            Dict with counts of actions taken
        """
        results = {
            "stuck_detecting_fixed": 0,
            "stuck_asr_completed_fixed": 0,
            "stuck_transcribing_failed": 0,
            "stuck_cropping_failed": 0,
            "checked_at": datetime.utcnow().isoformat(),
        }
        
        async with async_session() as session:
            # 1. Check jobs stuck in DETECTING
            detecting_fixed = await self._reconcile_detecting(session)
            results["stuck_detecting_fixed"] = detecting_fixed
            
            # 2. Check jobs stuck in ASR_COMPLETED
            asr_fixed = await self._reconcile_asr_completed(session)
            results["stuck_asr_completed_fixed"] = asr_fixed
            
            # 3. Check jobs stuck in TRANSCRIBING for too long
            transcribing_failed = await self._reconcile_transcribing(session)
            results["stuck_transcribing_failed"] = transcribing_failed
            
            # 4. Check jobs stuck in CROPPING for too long
            cropping_failed = await self._reconcile_cropping(session)
            results["stuck_cropping_failed"] = cropping_failed
        
        total_actions = sum([
            detecting_fixed,
            asr_fixed,
            transcribing_failed,
            cropping_failed,
        ])
        
        if total_actions > 0:
            logger.info(f"Reconciliation completed: {results}")
        else:
            logger.debug("Reconciliation completed: no stuck jobs found")
        
        return results
    
    async def _reconcile_detecting(self, session) -> int:
        """
        Find jobs stuck in DETECTING and republish ASR if segments exist.
        
        This handles the case where DetectionWorker crashed after
        storing segments but before publishing to ASR topic.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=self.DETECTING_THRESHOLD_MINUTES)
        
        result = await session.execute(
            select(PipelineJob).where(
                and_(
                    PipelineJob.status == JobStatus.DETECTING,
                    PipelineJob.updated_at < cutoff,
                    PipelineJob.is_cancelled == False,
                )
            )
        )
        stuck_jobs = result.scalars().all()
        
        fixed_count = 0
        for job in stuck_jobs:
            # Check if segments exist (detection actually succeeded)
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job.id)
            
            if segments:
                # Detection succeeded but ASR not queued → republish ASR
                await pipeline_producer.publish_asr_job(
                    job_id=str(job.id),
                    segment_count=len(segments),
                    segment_ids=[str(s.id) for s in segments],
                )
                logger.warning(
                    f"RECONCILED: Job {job.id} stuck in DETECTING, "
                    f"republished ASR job with {len(segments)} segments"
                )
                fixed_count += 1
            else:
                # No segments → detection genuinely stuck
                # Don't fail automatically, give it more time or let retry handle it
                logger.info(
                    f"RECONCILE: Job {job.id} stuck in DETECTING, "
                    f"but no segments yet. Waiting for worker retry."
                )
        
        return fixed_count
    
    async def _reconcile_asr_completed(self, session) -> int:
        """
        Find jobs stuck in ASR_COMPLETED and republish cropping if transcripts exist.
        
        This handles the case where ASRWorker crashed after
        storing transcripts but before publishing to crop topic.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=self.ASR_COMPLETED_THRESHOLD_MINUTES)
        
        result = await session.execute(
            select(PipelineJob).where(
                and_(
                    PipelineJob.status == JobStatus.ASR_COMPLETED,
                    PipelineJob.updated_at < cutoff,
                    PipelineJob.is_cancelled == False,
                )
            )
        )
        stuck_jobs = result.scalars().all()
        
        fixed_count = 0
        for job in stuck_jobs:
            # Check if transcripts exist (ASR actually succeeded)
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job.id)
            
            if segments:
                segment_ids = [s.id for s in segments]
                transcript_result = await session.execute(
                    select(PipelineTranscript).where(
                        PipelineTranscript.segment_id.in_(segment_ids)
                    )
                )
                transcripts = transcript_result.scalars().all()
                
                if transcripts:
                    # ASR succeeded but cropping not queued → republish cropping
                    await pipeline_producer.publish_cropping_job(
                        job_id=str(job.id),
                        transcript_count=len(transcripts),
                    )
                    logger.warning(
                        f"RECONCILED: Job {job.id} stuck in ASR_COMPLETED, "
                        f"republished cropping job with {len(transcripts)} transcripts"
                    )
                    fixed_count += 1
                else:
                    # No transcripts → ASR genuinely stuck
                    logger.info(
                        f"RECONCILE: Job {job.id} in ASR_COMPLETED but no transcripts. "
                        f"ASR may still be processing."
                    )
        
        return fixed_count
    
    async def _reconcile_transcribing(self, session) -> int:
        """
        Find jobs stuck in TRANSCRIBING for too long and mark as FAILED.
        
        This handles the case where ASRWorker crashed and Kafka
        redelivery is not working (e.g., consumer group issue).
        """
        cutoff = datetime.utcnow() - timedelta(minutes=self.TRANSCRIBING_THRESHOLD_MINUTES)
        
        result = await session.execute(
            select(PipelineJob).where(
                and_(
                    PipelineJob.status == JobStatus.TRANSCRIBING,
                    PipelineJob.updated_at < cutoff,
                    PipelineJob.is_cancelled == False,
                )
            )
        )
        stuck_jobs = result.scalars().all()
        
        failed_count = 0
        for job in stuck_jobs:
            # Check if transcripts exist (maybe ASR succeeded but status not updated)
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job.id)
            
            if segments:
                segment_ids = [s.id for s in segments]
                transcript_result = await session.execute(
                    select(PipelineTranscript).where(
                        PipelineTranscript.segment_id.in_(segment_ids)
                    )
                )
                transcripts = transcript_result.scalars().all()
                
                if transcripts:
                    # Transcripts exist → just update status, don't fail
                    job.status = JobStatus.ASR_COMPLETED
                    job.updated_at = datetime.utcnow()
                    await session.commit()
                    
                    # Also queue cropping
                    await pipeline_producer.publish_cropping_job(
                        job_id=str(job.id),
                        transcript_count=len(transcripts),
                    )
                    logger.warning(
                        f"RECONCILED: Job {job.id} had transcripts but wrong status. "
                        f"Fixed to ASR_COMPLETED and queued cropping."
                    )
                    continue
            
            # Genuinely stuck → mark as failed
            job.status = JobStatus.FAILED
            job.error_message = "ASR stage timed out (reconciliation)"
            job.updated_at = datetime.utcnow()
            await session.commit()
            
            logger.error(
                f"RECONCILED: Job {job.id} stuck in TRANSCRIBING for > "
                f"{self.TRANSCRIBING_THRESHOLD_MINUTES}min, marked as FAILED"
            )
            failed_count += 1
        
        return failed_count
    
    async def _reconcile_cropping(self, session) -> int:
        """
        Find jobs stuck in CROPPING_IN_PROGRESS for too long and mark as FAILED.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=self.CROPPING_THRESHOLD_MINUTES)
        
        result = await session.execute(
            select(PipelineJob).where(
                and_(
                    PipelineJob.status == JobStatus.CROPPING_IN_PROGRESS,
                    PipelineJob.updated_at < cutoff,
                    PipelineJob.is_cancelled == False,
                )
            )
        )
        stuck_jobs = result.scalars().all()
        
        failed_count = 0
        for job in stuck_jobs:
            # Check if some utterances were already cropped
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job.id)
            
            if segments:
                segment_ids = [s.id for s in segments]
                transcript_result = await session.execute(
                    select(PipelineTranscript).where(
                        and_(
                            PipelineTranscript.segment_id.in_(segment_ids),
                            PipelineTranscript.status == "cropped"
                        )
                    )
                )
                cropped = transcript_result.scalars().all()
                
                if cropped:
                    # Some utterances cropped → don't fail, just log
                    logger.info(
                        f"RECONCILE: Job {job.id} in CROPPING_IN_PROGRESS with "
                        f"{len(cropped)} cropped utterances. May still be processing."
                    )
                    continue
            
            # Genuinely stuck → mark as failed
            job.status = JobStatus.CROPPING_FAILED
            job.error_message = "Cropping stage timed out (reconciliation)"
            job.updated_at = datetime.utcnow()
            await session.commit()
            
            logger.error(
                f"RECONCILED: Job {job.id} stuck in CROPPING_IN_PROGRESS for > "
                f"{self.CROPPING_THRESHOLD_MINUTES}min, marked as CROPPING_FAILED"
            )
            failed_count += 1
        
        return failed_count


# Global instance
reconciliation_service = ReconciliationService()
