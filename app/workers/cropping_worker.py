"""
Cropping Worker - Stage 2: Timestamp-based re-cropping with JBI buffer.

Consumes from 'cropping' queue and creates final JBI clips using ASR timestamps.
JBI Buffer Formula: jbi_start = max(0, asr_start - 2), jbi_end = min(duration, asr_end + 2)
"""

import logging
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from app.db.models.pipeline import JobStatus, PipelineSegment
from app.db.session import async_session
from app.pipeline.stages.stage3_cropping import (
    CroppingInput,
    CroppingResult,
    TimestampBasedCropper,
)
from app.pipeline.utils.storage import StorageManager
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.workers.base import BaseWorker

logger = logging.getLogger(__name__)


class CroppingWorker(BaseWorker):
    """
    Worker for Stage 2 cropping: timestamp-based re-cropping with JBI buffer.
    
    Input: Stage 1 cropped videos + ASR timestamps
    Output: Stage 2 final clips with _stage2.mp4 suffix
    
    JBI Buffer (FR6a):
    - jbi_start = max(0, asr_start - 2)
    - jbi_end = min(video_duration, asr_end + 2)
    """
    
    queue_name = "cropping"
    max_retries = 3
    
    def __init__(self):
        super().__init__()
        self.cropper = TimestampBasedCropper()
        self.storage = StorageManager()
    
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process cropping job.
        
        Payload:
            job_id: str - Pipeline job ID
            
        Returns:
            Dict with results and status
        """
        job_id = payload.get("job_id")
        if not job_id:
            raise ValueError("Missing job_id in payload")
        
        logger.info(f"Starting cropping stage for job {job_id}")
        
        async with async_session() as session:
            job_repo = JobRepository(session)
            segment_repo = SegmentRepository(session)
            
            # Get job and validate state
            job = await job_repo.get_by_id(UUID(job_id))
            
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            if job.status != JobStatus.ASR_COMPLETED:
                logger.warning(
                    f"Job {job_id} has status {job.status}, expected ASR_COMPLETED"
                )
            
            # Get all segments with ASR data
            segments = await segment_repo.get_by_job_id(UUID(job_id))
            
            # Filter segments that have ASR data
            segments_to_crop = [
                seg for seg in segments
                if seg.asr_start is not None and seg.asr_end is not None
            ]
            
            if not segments_to_crop:
                logger.warning(f"No segments with ASR data found for job {job_id}")
                return await self._finalize_job_no_segments(session, job_repo, job)
            
            logger.info(
                f"Processing {len(segments_to_crop)} segments for cropping"
            )
            
            # Update job status
            await job_repo.update_status(UUID(job_id), JobStatus.CROPPING_IN_PROGRESS)
            await session.commit()
        
        # Process segments outside transaction to avoid long-running transactions
        results = await self._process_segments(
            job_id=job_id,
            segments=segments_to_crop
        )
        
        # Update job with results
        async with async_session() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get_by_id(UUID(job_id))
            
            success_count = sum(1 for r in results if r.success)
            failure_count = len(results) - success_count
            
            if failure_count == 0:
                await job_repo.update_status(UUID(job_id), JobStatus.READY_FOR_ANNOTATION)
                logger.info(
                    f"Job {job_id} cropping complete: {success_count}/{len(results)} segments"
                )
            else:
                await job_repo.update_status(
                    UUID(job_id), 
                    JobStatus.CROPPING_FAILED,
                    error_message=f"Cropping failed for {failure_count} segments"
                )
                logger.error(
                    f"Job {job_id} cropping failed: {failure_count}/{len(results)} segments failed"
                )
            
            await session.commit()
        
        return {
            "job_id": job_id,
            "success": failure_count == 0,
            "total_segments": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "results": [
                {
                    "segment_id": r.segment_id,
                    "success": r.success,
                    "stage2_path": r.stage2_video_path,
                    "jbi_start": r.jbi_start,
                    "jbi_end": r.jbi_end,
                    "error": r.error
                }
                for r in results
            ]
        }
    
    async def _process_segments(
        self,
        job_id: str,
        segments: List[PipelineSegment]
    ) -> List[CroppingResult]:
        """
        Process all segments for cropping.
        
        Args:
            job_id: Pipeline job ID
            segments: List of segments with ASR data
            
        Returns:
            List of CroppingResult
        """
        results: List[CroppingResult] = []
        
        # Create output directory for this job
        output_dir = self.storage.get_stage2_output_dir(job_id)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        for i, segment in enumerate(segments):
            logger.debug(
                f"Processing segment {segment.id} ({i+1}/{len(segments)})"
            )
            
            # Check if Stage 1 video exists
            stage1_path = segment.cropped_video_path
            if not stage1_path or not Path(stage1_path).exists():
                logger.error(f"Stage 1 video not found: {stage1_path}")
                results.append(CroppingResult(
                    segment_id=str(segment.id),
                    success=False,
                    stage2_video_path=None,
                    jbi_start=0.0,
                    jbi_end=0.0,
                    transcript=segment.asr_text or "",
                    error=f"Stage 1 video not found: {stage1_path}"
                ))
                continue
            
            # Create cropping input
            cropping_input = CroppingInput(
                segment_id=str(segment.id),
                stage1_video_path=stage1_path,
                asr_start=segment.asr_start,
                asr_end=segment.asr_end,
                transcript=segment.asr_text or ""
            )
            
            # Process cropping
            result = await self.cropper.crop_segment(
                input_data=cropping_input,
                output_dir=output_dir
            )
            
            results.append(result)
            
            # Update segment in database
            async with async_session() as session:
                segment_repo = SegmentRepository(session)
                db_segment = await session.get(PipelineSegment, segment.id)
                
                if result.success:
                    db_segment.stage2_video_path = result.stage2_video_path
                    db_segment.jbi_start = result.jbi_start
                    db_segment.jbi_end = result.jbi_end
                    db_segment.status = "cropped"
                else:
                    db_segment.status = "cropping_failed"
                    # Note: error_message field doesn't exist on PipelineSegment
                    # Storing error in logs instead
                    logger.error(f"Segment {segment.id} cropping failed: {result.error}")
                
                await session.commit()
            
            if result.success:
                logger.info(
                    f"Segment {segment.id} cropped: "
                    f"JBI [{result.jbi_start:.2f} -> {result.jbi_end:.2f}] -> "
                    f"{result.stage2_video_path}"
                )
            else:
                logger.error(
                    f"Segment {segment.id} cropping failed: {result.error}"
                )
        
        return results
    
    async def _finalize_job_no_segments(
        self,
        session,
        job_repo: JobRepository,
        job: Any
    ) -> Dict[str, Any]:
        """Finalize job when no segments need cropping."""
        await job_repo.update_status(
            job.id,
            JobStatus.CROPPING_FAILED,
            error_message="No segments with ASR data found"
        )
        await session.commit()
        
        return {
            "job_id": str(job.id),
            "success": False,
            "error": "No segments with ASR data found",
            "total_segments": 0,
            "success_count": 0,
            "failure_count": 0,
            "results": []
        }
