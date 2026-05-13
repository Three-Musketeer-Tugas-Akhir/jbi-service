"""
Cropping Worker - Stage 3: Utterance-level cropping with dynamic buffer.

Consumes from 'pipeline.jobs.crop' topic and creates final annotation clips.
Uses the same algorithm as cv_asr_annotation.ipynb:
- Dynamic buffer based on gap to next utterance
- One video per utterance
- Videos stored in MinIO
"""

import logging
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.db.models.pipeline import JobStatus, PipelineSegment, PipelineTranscript
from app.db.session import async_session
from app.pipeline.utils.storage import StorageManager
from app.repositories.job_repository import JobRepository
from app.repositories.segment_repository import SegmentRepository
from app.services.minio_service import get_minio_service
from app.workers.kafka_base import KafkaPipelineWorker
from app.messaging.topics import PipelineTopics

logger = logging.getLogger(__name__)


class CroppingWorker(KafkaPipelineWorker):
    """
    Worker for Stage 3 cropping: utterance-level with dynamic buffer.
    
    Input: Stage 1 cropped videos + pipeline_transcripts (utterances)
    Output: Individual utterance videos stored in MinIO
    
    Algorithm (matching cv_asr_annotation.ipynb):
    - For each utterance, calculate dynamic buffer based on gap to next utterance
    - Gap > 2s: add 2s buffer
    - Gap <= 2s: extend to next utterance + 1s
    - First utterance: no start offset
    - Last utterance: extend to video duration or +1s
    """
    
    topic = PipelineTopics.CROPPING.value
    consumer_group = "cropping-workers"
    next_stage_topic = None  # Last stage in pipeline
    max_retries = 3
    
    def __init__(self):
        super().__init__()
        self.storage = StorageManager()
        self.minio_service = get_minio_service()
    
    async def is_already_processed(self, job_id: str) -> bool:
        """Check if cropping was already done for this job."""
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            return False
        
        async with async_session() as session:
            segment_repo = SegmentRepository(session)
            segments = await segment_repo.get_by_job_id(job_uuid)
            if not segments:
                return False
            
            segment_ids = [s.id for s in segments]
            from sqlalchemy import select
            result = await session.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id.in_(segment_ids),
                    PipelineTranscript.status == "cropped"
                )
            )
            cropped = result.scalars().all()
            return len(cropped) > 0
    
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
            
            # Get all segments with transcripts
            segments = await segment_repo.get_by_job_id(UUID(job_id))
            
            # Get all transcripts for these segments
            all_transcripts = []
            for seg in segments:
                transcripts = await self._get_transcripts_for_segment(session, seg.id)
                if transcripts:
                    all_transcripts.append((seg, transcripts))
            
            if not all_transcripts:
                logger.warning("No transcripts found for job %s", job_id)
                return await self._finalize_job_no_segments(session, job_repo, job)
            
            total_utterances = sum(len(t) for _, t in all_transcripts)
            logger.info(
                "Processing %d segments with %d total utterances for cropping",
                len(all_transcripts), total_utterances
            )
            
            # Update job status
            await job_repo.update_status(UUID(job_id), JobStatus.CROPPING_IN_PROGRESS)
            await session.commit()
        
        # Process utterances outside transaction
        results = await self._process_utterances(
            job_id=job_id,
            segment_transcripts=all_transcripts
        )
        
        # Update job with results
        async with async_session() as session:
            job_repo = JobRepository(session)
            job = await job_repo.get_by_id(UUID(job_id))
            
            success_count = sum(1 for r in results if r["success"])
            failure_count = len(results) - success_count
            
            if failure_count == 0:
                # CV2 complete — move to voice annotation (human loop).
                await job_repo.update_status(UUID(job_id), JobStatus.NEEDS_VOICE_ANNOTATION)
                logger.info(
                    "Job %s cropping complete: %d/%d utterances → NEEDS_VOICE_ANNOTATION",
                    job_id, success_count, len(results)
                )
            else:
                await job_repo.update_status(
                    UUID(job_id), 
                    JobStatus.CROPPING_FAILED,
                    error_message=f"Cropping failed for {failure_count} utterances"
                )
                logger.error(
                    "Job %s cropping failed: %d/%d utterances failed",
                    job_id, failure_count, len(results)
                )
            
            await session.commit()
        
        # After CV2 is committed successfully, initialize voice annotations
        # (Sastrawi KBBI validation). This runs separately so it NEVER blocks
        # or fails the CV2 pipeline. If it crashes, job stays in
        # NEEDS_VOICE_ANNOTATION and admin can re-trigger via API.
        if failure_count == 0:
            try:
                async with async_session() as va_session:
                    from app.services.voice_annotation_service import VoiceAnnotationService
                    va_service = VoiceAnnotationService(va_session)
                    va_result = await va_service.initialize_for_job(UUID(job_id))
                    await va_session.commit()
                    logger.info(
                        "Job %s voice annotation init: %d clean, %d flagged",
                        job_id,
                        va_result.get("clean", 0),
                        va_result.get("flagged", 0),
                    )
            except Exception as e:
                logger.warning(
                    "Job %s voice annotation init failed (non-blocking): %s",
                    job_id, str(e)
                )
            
            # Pre-merge all utterance pairs (N + N+1) in background.
            # This ensures merged videos are ready before annotators open the job.
            # Non-blocking: if it fails, on-demand merge in annotation still works.
            try:
                import asyncio
                from app.services.utterance_merge_service import UtteranceMergeService
                from app.repositories.job_repository import JobRepository
                
                # Mark pre-merge as PENDING immediately so it shows up in the queue
                # even before the background task starts.
                async with async_session() as pm_session:
                    pm_repo = JobRepository(pm_session)
                    await pm_repo.update_premerge_progress(
                        job_id=UUID(job_id),
                        status="PENDING",
                        total_pairs=0,
                        completed_pairs=0,
                        failed_pairs=0,
                        batches=[],
                        error=None,
                    )
                    await pm_session.commit()
                    logger.info("Job %s pre-merge marked PENDING", job_id)
                
                async def _premerge_with_cleanup():
                    try:
                        await UtteranceMergeService.premerge_all_for_job(UUID(job_id))
                    except Exception as exc:
                        logger.exception(
                            "Job %s pre-merge background task failed: %s",
                            job_id, exc
                        )
                        # Mark as failed so admin can see it
                        try:
                            async with async_session() as fail_session:
                                fail_repo = JobRepository(fail_session)
                                await fail_repo.update_premerge_progress(
                                    job_id=UUID(job_id),
                                    status="FAILED",
                                    error=str(exc),
                                )
                                await fail_session.commit()
                        except Exception as cleanup_err:
                            logger.warning(
                                "Job %s failed to write pre-merge failure status: %s",
                                job_id, cleanup_err
                            )
                
                asyncio.create_task(_premerge_with_cleanup())
                logger.info("Job %s pre-merge task spawned in background", job_id)
            except Exception as e:
                logger.warning(
                    "Job %s pre-merge spawn failed (non-blocking): %s",
                    job_id, str(e)
                )
        
        return {
            "job_id": job_id,
            "success": failure_count == 0,
            "total_utterances": len(results),
            "success_count": success_count,
            "failure_count": failure_count,
            "results": results
        }
    
    async def _get_transcripts_for_segment(
        self, 
        session, 
        segment_id: UUID
    ) -> List[PipelineTranscript]:
        """Get all transcripts for a segment, ordered by utterance_index."""
        from sqlalchemy import select
        
        query = select(PipelineTranscript).where(
            PipelineTranscript.segment_id == segment_id
        ).order_by(PipelineTranscript.utterance_index)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def _process_utterances(
        self,
        job_id: str,
        segment_transcripts: List[Tuple[PipelineSegment, List[PipelineTranscript]]]
    ) -> List[Dict]:
        """
        Process all utterances for cropping using notebook algorithm.
        
        Args:
            job_id: Pipeline job ID
            segment_transcripts: List of (segment, transcripts) tuples
            
        Returns:
            List of result dicts
        """
        results = []
        
        for segment, transcripts in segment_transcripts:
            # Download Stage 1 video once per segment
            stage1_key = segment.cropped_video_path
            if not stage1_key:
                logger.error("Stage 1 video key is None for segment %s", segment.id)
                for utt in transcripts:
                    results.append({
                        "transcript_id": str(utt.id),
                        "utterance_index": utt.utterance_index,
                        "success": False,
                        "error": "Stage 1 video key is None"
                    })
                continue
            
            stage1_local_path = None
            try:
                # Download from MinIO
                stage1_data = await self.minio_service.download_file(stage1_key)
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(stage1_data)
                    stage1_local_path = tmp.name
                
                # Get video duration
                video_duration = await self._get_video_duration(stage1_local_path)
                
                # Process each utterance with dynamic buffer
                for i, utterance in enumerate(transcripts):
                    result = await self._process_single_utterance(
                        job_id=job_id,
                        segment=segment,
                        utterance=utterance,
                        utterance_index=i,
                        total_utterances=len(transcripts),
                        video_path=stage1_local_path,
                        video_duration=video_duration
                    )
                    results.append(result)
                    
            except Exception as e:
                logger.error("Failed to process segment %s: %s", segment.id, e)
                for utt in transcripts:
                    results.append({
                        "transcript_id": str(utt.id),
                        "utterance_index": utt.utterance_index,
                        "success": False,
                        "error": str(e)
                    })
            finally:
                # Clean up temp file
                if stage1_local_path and Path(stage1_local_path).exists():
                    try:
                        Path(stage1_local_path).unlink()
                    except OSError:
                        pass
        
        return results
    
    async def _process_single_utterance(
        self,
        job_id: str,
        segment: PipelineSegment,
        utterance: PipelineTranscript,
        utterance_index: int,
        total_utterances: int,
        video_path: str,
        video_duration: float
    ) -> Dict:
        """
        Process a single utterance with dynamic buffer (matching notebook algorithm).
        
        Algorithm from cv_asr_annotation.ipynb:
        - First utterance: use original start
        - Subsequent: start += 1s offset
        - Calculate end based on next utterance gap
        - Last utterance: extend to video duration or +1s
        """
        from app.pipeline.utils.video import run_ffmpeg_crop
        
        utterance_id = str(utterance.id)
        
        try:
            # Get current and next utterance times
            current_start = utterance.start
            current_end = utterance.end
            
            # Validate original utterance timestamps
            if current_start >= current_end:
                logger.warning(
                    "Skipping utterance %s with invalid original timestamps: %.2f -> %.2f",
                    utterance_id, current_start, current_end
                )
                return {
                    "transcript_id": utterance_id,
                    "utterance_index": utterance.utterance_index,
                    "success": False,
                    "error": f"Invalid original timestamps: {current_start:.2f} >= {current_end:.2f}"
                }
            
            # Skip utterances that start after video ends
            if current_start >= video_duration:
                logger.warning(
                    "Utterance %s starts after video ends (%.2f >= %.2f) - Clamping to end of video",
                    utterance_id, current_start, video_duration
                )
                current_start = max(0.0, video_duration - 1.0)
            
            # Apply notebook algorithm for start time
            is_first = utterance_index == 0
            if not is_first:
                current_start += 1.0  # Add 1s offset after first clip
            
            # Clamp start to video duration (can't start after video ends)
            current_start = min(current_start, video_duration)
            
            # Calculate end time based on next utterance (dynamic buffer)
            next_start = None
            if utterance_index + 1 < total_utterances:
                # Get next utterance from database
                next_utt = await self._get_next_utterance(utterance)
                if next_utt:
                    next_start = next_utt.start
            
            if next_start is not None:
                gap = next_start - current_end
                if gap > 2.0:
                    # Large gap: add 2s buffer
                    current_end = current_end + 2.0
                else:
                    # Small gap: extend to next utterance + 1s
                    current_end = next_start + 1.0
            else:
                # Last utterance: extend to video duration or +1s
                if video_duration - current_end <= 1.0:
                    current_end = video_duration
                else:
                    current_end = current_end + 1.0
            
            # Clamp to video duration
            current_end = min(current_end, video_duration)
            
            # Ensure valid range after adjustments (Safeguard against Whisper overlaps/zero-duration)
            if current_start >= current_end:
                logger.warning(
                    "Adjusting invalid time range for utterance %s: %.2f -> %.2f",
                    utterance_id, current_start, current_end
                )
                # Enforce at least 0.5s duration
                current_end = min(current_start + 0.5, video_duration)
                if current_start >= current_end:
                    current_start = max(0.0, current_end - 0.5)
            
            # Create output directory
            output_dir = self.storage.get_stage2_output_dir(job_id)
            output_path = Path(output_dir) / f"{segment.id}_utt_{utterance.utterance_index}.mp4"
            
            # Run FFmpeg crop
            success = await run_ffmpeg_crop(
                input_path=video_path,
                output_path=str(output_path),
                start_time=current_start,
                end_time=current_end,
                use_input_seeking=True
            )
            
            if not success:
                raise RuntimeError("FFmpeg cropping failed")
            
            # Upload to MinIO
            minio_key = f"jobs/{job_id}/utterances/{segment.id}_utt_{utterance.utterance_index}.mp4"
            with open(output_path, "rb") as f:
                file_bytes = f.read()
            await self.minio_service.upload_file(file_bytes, minio_key)
            
            # Update database
            await self._update_transcript_video_path(utterance_id, minio_key, current_start, current_end)
            
            logger.info(
                "Utterance %s cropped: [%.2f -> %.2f] -> %s",
                utterance_id, current_start, current_end, minio_key
            )
            
            return {
                "transcript_id": utterance_id,
                "utterance_index": utterance.utterance_index,
                "success": True,
                "video_path": minio_key,
                "start": current_start,
                "end": current_end
            }
            
        except Exception as e:
            logger.error("Failed to crop utterance %s: %s", utterance_id, e)
            await self._update_transcript_status(utterance_id, "failed")
            return {
                "transcript_id": utterance_id,
                "utterance_index": utterance.utterance_index,
                "success": False,
                "error": str(e)
            }
    
    async def _get_next_utterance(
        self, 
        current: PipelineTranscript
    ) -> Optional[PipelineTranscript]:
        """Get the next utterance in sequence."""
        from sqlalchemy import select
        
        async with async_session() as session:
            query = select(PipelineTranscript).where(
                PipelineTranscript.segment_id == current.segment_id,
                PipelineTranscript.utterance_index == current.utterance_index + 1
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()
    
    async def _update_transcript_video_path(
        self,
        transcript_id: str,
        video_path: str,
        start: float,
        end: float
    ):
        """Update transcript with video path and cropped timestamps."""
        from sqlalchemy import update
        
        async with async_session() as session:
            stmt = update(PipelineTranscript).where(
                PipelineTranscript.id == UUID(transcript_id)
            ).values(
                video_path=video_path,
                start=start,
                end=end,
                status="cropped"
            )
            await session.execute(stmt)
            await session.commit()
    
    async def _update_transcript_status(self, transcript_id: str, status: str):
        """Update transcript status."""
        from sqlalchemy import update
        
        async with async_session() as session:
            stmt = update(PipelineTranscript).where(
                PipelineTranscript.id == UUID(transcript_id)
            ).values(status=status)
            await session.execute(stmt)
            await session.commit()
    
    async def _get_video_duration(self, video_path: str) -> float:
        """Get video duration using ffprobe."""
        import asyncio
        
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            return float(stdout.decode().strip())
        else:
            raise RuntimeError(f"Failed to get video duration: {stderr.decode()}")
    
    async def _finalize_job_no_segments(
        self,
        session,
        job_repo: JobRepository,
        job: Any
    ) -> Dict[str, Any]:
        """Finalize job when no transcripts need cropping."""
        await job_repo.update_status(
            job.id,
            JobStatus.CROPPING_FAILED,
            error_message="No transcripts found for cropping"
        )
        await session.commit()
        
        return {
            "job_id": str(job.id),
            "success": False,
            "error": "No transcripts found for cropping",
            "total_utterances": 0,
            "success_count": 0,
            "failure_count": 0,
            "results": []
        }
