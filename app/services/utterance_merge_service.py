"""
Utterance merge service — video-editor-sibi style.

Merges utterance N video with utterance N+1 video to create a seamless
look-ahead merged video for annotation. The merged video is cached in MinIO
and its path is stored in PipelineTranscript.merged_video_path.

When an annotator trims utterance N:
  - Keep (0 → end_time) → overwrite utterance N video
  - Remainder (end_time → end) → overwrite utterance N+1 video
  - Clear merged_video_path from utterance N so next load re-merges
"""
import logging
import os
import tempfile
import uuid
from typing import Optional, Tuple

import httpx

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineJob, PipelineSegment, PipelineTranscript
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import run_ffmpeg_concat, FFmpegConfig

logger = logging.getLogger(__name__)


class UtteranceMergeService:
    """Service for merging adjacent utterance videos (look-ahead merge)."""

    @staticmethod
    async def get_or_create_merged_video(
        job_id: uuid.UUID,
        segment_id: uuid.UUID,
        utterance_index: int
    ) -> Optional[dict]:
        """
        Get existing merged video or create a new one.
        
        Returns dict with:
            merged_video_url: str — presigned URL for playback
            merged_video_path: str — MinIO key
            video_n_duration: float — duration of utterance N (for marker)
            total_duration: float — total duration of merged video
        """
        minio_service = get_minio_service()

        async with async_session_maker() as db:
            # 1. Fetch current utterance
            curr_result = await db.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id == segment_id,
                    PipelineTranscript.utterance_index == utterance_index
                )
            )
            curr_transcript = curr_result.scalar_one_or_none()
            if not curr_transcript or not curr_transcript.video_path:
                logger.error(f"Current transcript/video not found for {segment_id} utt {utterance_index}")
                return None

            # 2. Check if merged video already exists
            if curr_transcript.merged_video_path:
                try:
                    url = await minio_service.generate_presigned_url(
                        curr_transcript.merged_video_path, expiry=3600
                    )
                    logger.info(f"Returning existing merged video: {curr_transcript.merged_video_path}")
                    return {
                        "merged_video_url": url,
                        "merged_video_path": curr_transcript.merged_video_path,
                        "video_n_duration": curr_transcript.video_n_duration or 0.0,
                        "total_duration": curr_transcript.merged_video_duration or 0.0,
                    }
                except Exception as e:
                    logger.warning(f"Failed to generate URL for existing merged video: {e}")
                    # Fall through to recreate

            # 3. Find next utterance (same segment or next segment, same job)
            segment_result = await db.execute(
                select(PipelineSegment).where(PipelineSegment.id == segment_id)
            )
            segment = segment_result.scalar_one_or_none()
            if not segment:
                logger.error(f"Segment {segment_id} not found")
                return None

            next_result = await db.execute(
                select(PipelineTranscript)
                .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
                .where(PipelineSegment.job_id == segment.job_id)
                .where(
                    (PipelineSegment.segment_index > segment.segment_index) |
                    ((PipelineSegment.segment_index == segment.segment_index) &
                     (PipelineTranscript.utterance_index > utterance_index))
                )
                .order_by(PipelineSegment.segment_index.asc(), PipelineTranscript.utterance_index.asc())
                .limit(1)
            )
            next_transcript = next_result.scalar_one_or_none()

            # 4. If no next utterance, return current video only (single video)
            if not next_transcript or not next_transcript.video_path:
                logger.info(f"No next utterance found for {segment_id} utt {utterance_index}, returning single video")
                curr_url = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)
                return {
                    "merged_video_url": curr_url,
                    "merged_video_path": curr_transcript.video_path,
                    "video_n_duration": 0.0,
                    "total_duration": (curr_transcript.end - curr_transcript.start),
                    "is_single_video": True,
                }

            # 5. Download both videos to temp files
            curr_presigned = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)
            next_presigned = await minio_service.generate_presigned_url(next_transcript.video_path, expiry=3600)

            tmp_dir = tempfile.gettempdir()
            curr_tmp = os.path.join(tmp_dir, f"{segment_id}_utt_{utterance_index}_curr.mp4")
            next_tmp = os.path.join(tmp_dir, f"{segment_id}_utt_{utterance_index}_next.mp4")
            merged_tmp = os.path.join(tmp_dir, f"{segment_id}_utt_{utterance_index}_merged.mp4")

            try:
                await _download_file(curr_presigned, curr_tmp)
                await _download_file(next_presigned, next_tmp)

                # 6. Merge using FFmpeg
                config = FFmpegConfig(video_preset="ultrafast")
                success = await run_ffmpeg_concat(
                    input_paths=[curr_tmp, next_tmp],
                    output_path=merged_tmp,
                    config=config
                )

                if not success or not os.path.exists(merged_tmp):
                    logger.error("FFmpeg concat failed for merge")
                    return None

                # 7. Upload merged video to MinIO
                merged_key = f"jobs/{job_id}/utterances_merged/{segment_id}_utt_{utterance_index}.mp4"
                with open(merged_tmp, "rb") as f:
                    await minio_service.upload_file(f, merged_key)

                # 8. Calculate durations
                from app.pipeline.utils.video import get_video_duration
                curr_duration = await get_video_duration(curr_tmp)
                merged_duration = await get_video_duration(merged_tmp)

                # 9. Update database
                curr_transcript.merged_video_path = merged_key
                curr_transcript.merged_video_duration = merged_duration
                curr_transcript.video_n_duration = curr_duration
                await db.commit()

                # 10. Generate presigned URL
                merged_url = await minio_service.generate_presigned_url(merged_key, expiry=3600)

                logger.info(
                    f"Created merged video for {segment_id} utt {utterance_index}: "
                    f"duration={merged_duration:.2f}s, n_duration={curr_duration:.2f}s"
                )

                return {
                    "merged_video_url": merged_url,
                    "merged_video_path": merged_key,
                    "video_n_duration": curr_duration,
                    "total_duration": merged_duration,
                    "is_single_video": False,
                }

            finally:
                # Cleanup temp files
                for path in [curr_tmp, next_tmp, merged_tmp]:
                    try:
                        if os.path.exists(path):
                            os.remove(path)
                    except OSError:
                        pass

    @staticmethod
    async def clear_merged_video(segment_id: uuid.UUID, utterance_index: int) -> None:
        """Clear merged_video_path so next load re-merges (after trim)."""
        async with async_session_maker() as db:
            result = await db.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id == segment_id,
                    PipelineTranscript.utterance_index == utterance_index
                )
            )
            transcript = result.scalar_one_or_none()
            if transcript and transcript.merged_video_path:
                transcript.merged_video_path = None
                transcript.merged_video_duration = None
                transcript.video_n_duration = None
                await db.commit()
                logger.info(f"Cleared merged video for {segment_id} utt {utterance_index}")


    @staticmethod
    async def premerge_all_for_job(job_id: uuid.UUID) -> dict:
        """Pre-merge all utterance pairs (N + N+1) for a job after CV2 completes.
        
        This is a background task that iterates all utterances in a job
        and calls get_or_create_merged_video() for each pair.
        
        Args:
            job_id: The pipeline job ID
            
        Returns:
            dict with total, created, skipped counts
        """
        logger.info(f"Starting pre-merge for job {job_id}")
        
        async with async_session_maker() as db:
            from app.db.models.pipeline import PipelineSegment, PipelineTranscript
            
            # Fetch all segments with transcripts for this job
            result = await db.execute(
                select(PipelineSegment)
                .where(PipelineSegment.job_id == job_id)
                .order_by(PipelineSegment.segment_index.asc())
            )
            segments = result.scalars().all()
            
            # Flatten all transcripts ordered by segment_index, utterance_index
            all_transcripts = []
            for seg in segments:
                seg_transcripts = await db.execute(
                    select(PipelineTranscript)
                    .where(PipelineTranscript.segment_id == seg.id)
                    .order_by(PipelineTranscript.utterance_index.asc())
                )
                all_transcripts.extend(seg_transcripts.scalars().all())
            
            total_pairs = max(0, len(all_transcripts) - 1)
            created = 0
            skipped = 0
            failed = 0
            
            logger.info(f"Job {job_id}: {len(all_transcripts)} utterances, {total_pairs} pairs to pre-merge")
            
            for i, transcript in enumerate(all_transcripts):
                # Skip the last utterance (no N+1 to merge with)
                if i >= len(all_transcripts) - 1:
                    break
                    
                try:
                    result = await UtteranceMergeService.get_or_create_merged_video(
                        job_id=job_id,
                        segment_id=transcript.segment_id,
                        utterance_index=transcript.utterance_index
                    )
                    if result:
                        if result.get("is_single_video"):
                            skipped += 1
                        else:
                            created += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.warning(
                        f"Pre-merge failed for job {job_id} utt {transcript.utterance_index}: {e}"
                    )
                    failed += 1
            
            logger.info(
                f"Pre-merge complete for job {job_id}: "
                f"{created} created, {skipped} skipped (single), {failed} failed"
            )
            
            return {
                "job_id": str(job_id),
                "total_pairs": total_pairs,
                "created": created,
                "skipped": skipped,
                "failed": failed,
            }


async def _download_file(url: str, dest_path: str) -> None:
    """Download file from URL to local path."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url, follow_redirects=True)
        response.raise_for_status()
        with open(dest_path, "wb") as f:
            f.write(response.content)
