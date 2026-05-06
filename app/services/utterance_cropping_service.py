"""
Background service for physical utterance cropping.

Supports Boundary Cross-Cropping & Merging on CV2 Utterance Videos:
When an utterance's requested end_time exceeds its original CV2 video boundary,
the service crops the overflow from the NEXT utterance's CV2 video,
merges both clips, and cascade-updates the next utterance's start time.
"""
import logging
import os
import uuid

from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy import select

from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import run_ffmpeg_crop, run_ffmpeg_concat, FFmpegConfig

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
        Background task to crop the utterance video and upload it to MinIO.
        
        Uses the CV2 utterance video (PipelineTranscript.video_path) as the source.
        If end_time > original_end, it overlaps into the next utterance.
        """
        minio_service = get_minio_service()
        
        async with async_session_maker() as db:
            try:
                # 1. Fetch Segment
                segment_result = await db.execute(
                    select(PipelineSegment).where(PipelineSegment.id == segment_id)
                )
                segment = segment_result.scalar_one_or_none()
                if not segment:
                    logger.error(f"Segment {segment_id} not found.")
                    return
                
                # 2. Fetch Current Transcript (CV2 source of truth)
                curr_transcript_result = await db.execute(
                    select(PipelineTranscript).where(
                        PipelineTranscript.segment_id == segment_id,
                        PipelineTranscript.utterance_index == utterance_index
                    )
                )
                curr_transcript = curr_transcript_result.scalar_one_or_none()
                if not curr_transcript or not curr_transcript.video_path:
                    logger.error(f"Transcript/CV2 Video not found for {segment_id} utt {utterance_index}.")
                    return
                
                # 3. Fetch active edit
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
                
                utt_list = list(edit.utterance_corrections)
                utt_idx_in_array = None
                for i, utt in enumerate(utt_list):
                    if utt.get("utterance_index") == utterance_index:
                        utt_idx_in_array = i
                        break
                
                if utt_idx_in_array is None:
                    return
                
                curr_video_url = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)
                
                # 4. Calculate crop parameters.
                #
                # Key facts:
                # - CV2 video always starts at 0.0 physically (already cropped from CV1 by pipeline)
                # - PipelineTranscript.start/end are ASR absolute timestamps (e.g. 414.8, 418.0)
                # - The FE sends start_time/end_time that may be in either ASR-absolute or
                #   global-continuous space. Either way, what matters is DURATION.
                # - orig_duration = ASR-declared duration of this utterance
                # - requested_duration = what the annotator wants (end_time - start_time)
                # - If requested_duration > orig_duration → must merge with next utterance
                # - relative_start into CV2 video = 0.0 always (FE cannot seek into middle
                #   of CV2 because CV2 is already a single-utterance clip)
                
                orig_start = curr_transcript.start
                orig_end = curr_transcript.end
                orig_duration = max(0.01, orig_end - orig_start)  # ASR-declared duration
                
                requested_duration = abs(end_time - start_time)   # always positive
                relative_start = 0.0                               # CV2 always starts at 0
                
                # right_overlap: duration that exceeds what this CV2 video can provide
                right_overlap = requested_duration - orig_duration
                
                config = FFmpegConfig(video_preset="ultrafast")
                
                if right_overlap <= 0:
                    # ══════════════════════════════════════════════
                    # NORMAL CASE: fits within this CV2 video
                    # ══════════════════════════════════════════════
                    tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                    
                    success = await run_ffmpeg_crop(
                        input_path=curr_video_url,
                        output_path=tmp_output,
                        start_time=0.0,
                        end_time=requested_duration,
                        use_input_seeking=True,
                        config=config
                    )
                    
                    if not success:
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return
                else:
                    # ══════════════════════════════════════════════
                    # BOUNDARY CROSS-CROPPING & MERGING
                    # ══════════════════════════════════════════════
                    logger.info(f"Cross-segment merge for utt {utterance_index}: overlap={right_overlap:.2f}s")
                    
                    # Find next transcript (can be same segment or next segment)
                    next_result = await db.execute(
                        select(PipelineTranscript)
                        .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
                        .where(PipelineSegment.job_id == segment.job_id)
                        .where(
                            (PipelineSegment.segment_index > segment.segment_index) |
                            ((PipelineSegment.segment_index == segment.segment_index) & 
                             (PipelineTranscript.utterance_index > curr_transcript.utterance_index))
                        )
                        .order_by(PipelineSegment.segment_index.asc(), PipelineTranscript.utterance_index.asc())
                        .limit(1)
                    )
                    next_transcript = next_result.scalar_one_or_none()
                    
                    if not next_transcript or not next_transcript.video_path:
                        logger.error("Next utterance video not found. Cannot merge.")
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return
                    
                    next_video_url = await minio_service.generate_presigned_url(
                        next_transcript.video_path, expiry=3600
                    )
                    
                    # Part A: Crop ENTIRE current CV2 video (from 0 to end)
                    tmp_part_a = f"/tmp/{segment_id}_utt_{utterance_index}_partA.mp4"
                    success_a = await run_ffmpeg_crop(
                        input_path=curr_video_url,
                        output_path=tmp_part_a,
                        start_time=0.0,
                        end_time=orig_duration,   # Full CV2 video, not 9999
                        use_input_seeking=True,
                        config=config
                    )
                    
                    # Part B: Crop next video from 0 to right_overlap
                    tmp_part_b = f"/tmp/{segment_id}_utt_{utterance_index}_partB.mp4"
                    success_b = await run_ffmpeg_crop(
                        input_path=next_video_url,
                        output_path=tmp_part_b,
                        start_time=0.0,
                        end_time=right_overlap,
                        use_input_seeking=True,
                        config=config
                    )
                    
                    if not (success_a and success_b):
                        _cleanup_tmp(tmp_part_a, tmp_part_b)
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return
                    
                    # Merge
                    tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                    success_merge = await run_ffmpeg_concat(
                        input_paths=[tmp_part_a, tmp_part_b],
                        output_path=tmp_output,
                        config=config
                    )
                    
                    _cleanup_tmp(tmp_part_a, tmp_part_b)
                    
                    if not success_merge:
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return
                    
                    # Cascade update the next utterance
                    await _cascade_update_next_utterance(
                        db, next_transcript.segment_id, next_transcript.utterance_index, right_overlap
                    )
                
                # Upload video
                upload_key = f"jobs/{segment.job_id}/utterances_synced/{segment_id}_utt_{utterance_index}.mp4"
                with open(tmp_output, "rb") as f:
                    await minio_service.upload_file(f, upload_key)
                
                _cleanup_tmp(tmp_output)
                
                utt_list[utt_idx_in_array]["cropped_video_path"] = upload_key
                utt_list[utt_idx_in_array]["status"] = "OK"
                
                edit.utterance_corrections = utt_list
                flag_modified(edit, "utterance_corrections")
                await db.commit()
                
            except Exception as e:
                logger.exception(f"Error in crop_and_upload: {e}")
                # Attempt to mark as failed
                try:
                    await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                except Exception:
                    pass

async def _mark_failed(db, edit, utt_list, utt_idx):
    utt_list[utt_idx]["status"] = "FAILED"
    edit.utterance_corrections = utt_list
    flag_modified(edit, "utterance_corrections")
    await db.commit()

async def _cascade_update_next_utterance(
    db, segment_id: uuid.UUID, utterance_index: int, right_overlap: float
):
    edit_result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    next_edit = edit_result.scalars().first()
    
    if not next_edit or not next_edit.utterance_corrections:
        return
    
    next_utt_list = list(next_edit.utterance_corrections)
    
    for i, utt in enumerate(next_utt_list):
        if utt.get("utterance_index") == utterance_index:
            old_start = utt.get("start", 0.0)
            
            # Get original start from transcript
            transcript_result = await db.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id == segment_id,
                    PipelineTranscript.utterance_index == utterance_index
                )
            )
            transcript = transcript_result.scalar_one_or_none()
            if transcript:
                # Add overlap to the ORIGINAL start to push it forward
                new_start = max(old_start, transcript.start + right_overlap)
                
                if new_start > old_start:
                    next_utt_list[i]["start"] = new_start
                    if next_utt_list[i]["start"] >= next_utt_list[i].get("end", 999):
                        next_utt_list[i]["start"] = next_utt_list[i]["end"] - 0.1
                    
                    next_edit.utterance_corrections = next_utt_list
                    flag_modified(next_edit, "utterance_corrections")
            break

def _cleanup_tmp(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
