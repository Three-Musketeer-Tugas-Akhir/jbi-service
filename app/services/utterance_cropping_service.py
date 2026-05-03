"""
Background service for physical utterance cropping.
"""
import logging
import os
import uuid

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select

from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineSegment
from app.db.models.annotation import AnnotationEdit
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import run_ffmpeg_crop, FFmpegConfig

logger = logging.getLogger(__name__)


class UtteranceCroppingService:
    @staticmethod
    async def crop_and_upload(
        segment_id: uuid.UUID,
        utterance_index: int,
        start_time: float,
        end_time: float
    ):
        """
        Background task to crop the master video for a specific utterance
        and upload it to MinIO.
        """
        minio_service = get_minio_service()
        
        # We need a new session since this runs in the background after the API response
        async with async_session_maker() as db:
            try:
                # 1. Fetch Segment
                segment_result = await db.execute(
                    select(PipelineSegment).where(PipelineSegment.id == segment_id)
                )
                segment = segment_result.scalar_one_or_none()
                if not segment:
                    logger.error(f"Segment {segment_id} not found in background crop task.")
                    return
                
                # 2. Fetch active edit
                edit_result = await db.execute(
                    select(AnnotationEdit).where(
                        AnnotationEdit.segment_id == segment_id,
                        AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
                        AnnotationEdit.is_deleted == False
                    ).order_by(AnnotationEdit.edited_at.desc())
                )
                edit = edit_result.scalars().first()
                if not edit or not edit.utterance_corrections:
                    logger.error(f"No active edit found for segment {segment_id}.")
                    return
                
                # Verify the utterance exists in the edit
                utt_list = list(edit.utterance_corrections)
                utt_idx_in_array = None
                for i, utt in enumerate(utt_list):
                    if utt.get("utterance_index") == utterance_index:
                        utt_idx_in_array = i
                        break
                
                if utt_idx_in_array is None:
                    logger.error(f"Utterance index {utterance_index} not found in edit.")
                    return
                
                # 3. Get Presigned URL for Master Video
                # In jbi-service, PipelineSegment uses `cropped_video_path` for the stage 2 video
                master_video_key = segment.cropped_video_path
                if not master_video_key:
                    logger.error(f"Segment {segment_id} has no master video (cropped_video_path).")
                    return
                
                # Get a temporary presigned URL valid for 1 hour to feed into FFmpeg
                master_url = await minio_service.generate_presigned_url(master_video_key, expiry=3600)
                
                # 4. Crop using FFmpeg
                # Save locally to /tmp first
                tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                
                # Fast FFmpeg crop config
                config = FFmpegConfig(video_preset="ultrafast")
                
                success = await run_ffmpeg_crop(
                    input_path=master_url,
                    output_path=tmp_output,
                    start_time=start_time,
                    end_time=end_time,
                    use_input_seeking=True,
                    config=config
                )
                
                if not success:
                    logger.error(f"FFmpeg crop failed for {segment_id} utt {utterance_index}.")
                    utt_list[utt_idx_in_array]["status"] = "FAILED"
                    edit.utterance_corrections = utt_list
                    flag_modified(edit, "utterance_corrections")
                    await db.commit()
                    return
                
                # 5. Upload to MinIO (upload_file accepts a file path or bytes)
                upload_key = f"jobs/{segment.job_id}/utterances_synced/{segment_id}_utt_{utterance_index}.mp4"
                with open(tmp_output, "rb") as f:
                    await minio_service.upload_file(f, upload_key)

                # Cleanup local files
                if os.path.exists(tmp_output):
                    os.remove(tmp_output)
                
                # 6. Update DB
                utt_list[utt_idx_in_array]["cropped_video_path"] = upload_key
                utt_list[utt_idx_in_array]["status"] = "OK"
                
                edit.utterance_corrections = utt_list
                flag_modified(edit, "utterance_corrections")
                await db.commit()
                
                logger.info(f"Successfully cropped and uploaded {upload_key}.")
                
            except Exception as e:
                logger.exception(f"Error in crop_and_upload background task: {str(e)}")
                # Revert status if possible
                try:
                    utt_list[utt_idx_in_array]["status"] = "FAILED"
                    edit.utterance_corrections = utt_list
                    flag_modified(edit, "utterance_corrections")
                    await db.commit()
                except Exception:
                    pass
