"""
Cropping Worker - Stage 2: Timestamp-based re-cropping with JBI buffer.

Consumes from 'cropping' queue and creates final JBI clips using ASR timestamps.
JBI Buffer Formula: jbi_start = max(0, asr_start - 2), jbi_end = min(duration, asr_end + 2)
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
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
from app.services.minio_service import get_minio_service
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
        self.minio_service = get_minio_service()
    
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
        
        logger.info("Starting cropping stage for job %s", job_id)
        
        async with async_session() as session:
            job_repo = JobRepository(session)
            segment_repo = SegmentRepository(session)
            
            # Get job and validate state
            job = await job_repo.get_by_id(UUID(job_id))
            
            if not job:
                raise ValueError(f"Job {job_id} not found")
            
            if job.status != JobStatus.ASR_COMPLETED:
                logger.warning(
                    "Job %s has status %s, expected ASR_COMPLETED",
                    job_id, job.status
                )
            
            # Get all segments with ASR data
            segments = await segment_repo.get_by_job_id(UUID(job_id))
            
            # Filter segments that have ASR data
            segments_to_crop = [
                seg for seg in segments
                if seg.asr_start is not None and seg.asr_end is not None
            ]
            
            if not segments_to_crop:
                logger.warning("No segments with ASR data found for job %s", job_id)
                return await self._finalize_job_no_segments(session, job_repo, job)
            
            logger.info(
                "Processing %d segments for cropping", len(segments_to_crop)
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
                    "Job %s cropping complete: %d/%d segments",
                    job_id, success_count, len(results)
                )
            else:
                await job_repo.update_status(
                    UUID(job_id), 
                    JobStatus.CROPPING_FAILED,
                    error_message=f"Cropping failed for {failure_count} segments"
                )
                logger.error(
                    "Job %s cropping failed: %d/%d segments failed",
                    job_id, failure_count, len(results)
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
        segment_updates: List[tuple[UUID, CroppingResult]] = []
        
        # Create output directory for this job
        output_dir = self.storage.get_stage2_output_dir(job_id)
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        
        # Process all segments first (I/O operations)
        for i, segment in enumerate(segments):
            logger.debug("Processing segment %s (%d/%d)", segment.id, i + 1, len(segments))
            
            # Download Stage 1 video from MinIO
            stage1_key = segment.cropped_video_path
            stage1_local_path = None
            
            if not stage1_key:
                logger.error("Stage 1 video key is None for segment %s", segment.id)
                result = CroppingResult(
                    segment_id=str(segment.id),
                    success=False,
                    stage2_video_path=None,
                    jbi_start=0.0,
                    jbi_end=0.0,
                    transcript=segment.asr_text or "",
                    error="Stage 1 video key is None"
                )
                results.append(result)
                segment_updates.append((segment.id, result))
                continue
            
            try:
                # Download from MinIO to local temp file
                stage1_data = await self.minio_service.download_file(stage1_key)
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(stage1_data)
                    stage1_local_path = tmp.name
                logger.debug("Downloaded stage1 video for segment %s: %s", segment.id, stage1_local_path)
            except Exception as e:
                logger.error("Failed to download stage1 video for segment %s: %s", segment.id, e)
                result = CroppingResult(
                    segment_id=str(segment.id),
                    success=False,
                    stage2_video_path=None,
                    jbi_start=0.0,
                    jbi_end=0.0,
                    transcript=segment.asr_text or "",
                    error=f"Failed to download stage1 video: {e}"
                )
                results.append(result)
                segment_updates.append((segment.id, result))
                continue
            
            try:
                # Create cropping input
                cropping_input = CroppingInput(
                    segment_id=str(segment.id),
                    stage1_video_path=stage1_local_path,
                    asr_start=segment.asr_start,
                    asr_end=segment.asr_end,
                    transcript=segment.asr_text or ""
                )
                
                # Process cropping
                result = await self.cropper.crop_segment(
                    input_data=cropping_input,
                    output_dir=output_dir
                )
                
                # If successful, upload to MinIO and update result
                if result.success and result.stage2_video_path:
                    try:
                        # Upload to MinIO
                        stage2_key = f"jobs/{job_id}/stage2/{segment.id}_stage2.mp4"
                        await self.minio_service.upload_file(result.stage2_video_path, stage2_key)
                        logger.info("Uploaded stage2 video for segment %s: %s", segment.id, stage2_key)
                        
                        # Update result with MinIO key
                        result = CroppingResult(
                            segment_id=result.segment_id,
                            success=result.success,
                            stage2_video_path=stage2_key,
                            jbi_start=result.jbi_start,
                            jbi_end=result.jbi_end,
                            transcript=result.transcript,
                            error=result.error
                        )
                    except Exception as e:
                        logger.error("Failed to upload stage2 video for segment %s: %s", segment.id, e)
                        result = CroppingResult(
                            segment_id=str(segment.id),
                            success=False,
                            stage2_video_path=None,
                            jbi_start=result.jbi_start,
                            jbi_end=result.jbi_end,
                            transcript=result.transcript,
                            error=f"Failed to upload stage2 video: {e}"
                        )
                
                results.append(result)
                segment_updates.append((segment.id, result))
                
                if result.success:
                    logger.info(
                        "Segment %s cropped: JBI [%.2f -> %.2f] -> %s",
                        segment.id, result.jbi_start, result.jbi_end, result.stage2_video_path
                    )
                else:
                    logger.error("Segment %s cropping failed: %s", segment.id, result.error)
                    
            finally:
                # Clean up temp file
                if stage1_local_path and Path(stage1_local_path).exists():
                    try:
                        Path(stage1_local_path).unlink()
                    except OSError:
                        pass
        
        # Batch update all segments in a single database transaction
        await self._batch_update_segments(segment_updates)
        
        return results
    
    async def _batch_update_segments(
        self,
        updates: List[tuple[UUID, CroppingResult]]
    ) -> None:
        """
        Batch update segments in a single database transaction.
        
        Args:
            updates: List of (segment_id, result) tuples
        """
        if not updates:
            return
        
        async with async_session() as session:
            try:
                for segment_id, result in updates:
                    db_segment = await session.get(PipelineSegment, segment_id)
                    if db_segment is None:
                        logger.warning("Segment %s not found for update", segment_id)
                        continue
                    
                    if result.success:
                        db_segment.stage2_video_path = result.stage2_video_path
                        db_segment.jbi_start = result.jbi_start
                        db_segment.jbi_end = result.jbi_end
                        db_segment.status = "cropped"
                    else:
                        db_segment.status = "cropping_failed"
                
                await session.commit()
                logger.debug("Batch updated %d segments", len(updates))
            except Exception as e:
                await session.rollback()
                logger.error("Failed to batch update segments: %s", e)
                raise
    
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
