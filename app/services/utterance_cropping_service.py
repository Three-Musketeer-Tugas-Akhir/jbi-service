"""
Background service for physical utterance cropping.

Supports Boundary Cross-Cropping & Merging on CV2 Utterance Videos:
When an utterance's requested end_time exceeds its original CV2 video boundary,
the service crops the overflow from the NEXT utterance's CV2 video,
merges both clips, and cascade-updates the next utterance's start time.

IMPROVEMENTS OVER VIDEO-EDITOR-SIBI:
1. Pre-trim snapshot stored per-utterance for granular undo/revert
2. Deep cascade invalidation (N+1, N+2, ... merged videos cleared)
3. Cascade audit trail (cascade_info on AnnotationEdit)
4. Trim-in supported (start_time can differ from orig_start)
"""
import logging
import os
import uuid
from datetime import datetime
from typing import Optional

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
        end_time: float,
        edit_id: Optional[uuid.UUID] = None
    ):
        """
        Background task to crop the utterance video and upload it to MinIO.
        
        Uses the CV2 utterance video (PipelineTranscript.video_path) as the source.
        If end_time > original_end, it overlaps into the next utterance.
        
        IMPROVEMENTS:
        - Saves pre_trim_snapshot before cropping (for granular undo)
        - Supports trim-in (start_time != orig_start)
        - Records cascade_info audit trail
        - Deep cascade invalidation beyond N+1
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
                
                # 3. Fetch active edit.
                # Prefer the exact edit the crop endpoint operated on (edit_id) so the
                # cropped_video_path is written to the SAME row, even if a concurrent
                # draft save created a newer edit in the meantime. Fall back to the
                # latest DRAFT/PENDING edit for backward compatibility.
                edit = None
                if edit_id is not None:
                    edit_by_id = await db.execute(
                        select(AnnotationEdit).where(
                            AnnotationEdit.id == edit_id,
                            AnnotationEdit.is_deleted == False
                        )
                    )
                    edit = edit_by_id.scalars().first()
                if edit is None:
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
                
                # ══════════════════════════════════════════════════════════
                # IMPROVEMENT 1: Save pre-trim snapshot for granular undo
                # ══════════════════════════════════════════════════════════
                # Find next utterance info for snapshot
                next_utt_snapshot = None
                for utt in utt_list:
                    if utt.get("utterance_index") == utterance_index + 1:
                        next_utt_snapshot = {
                            "start": utt.get("start"),
                            "end": utt.get("end"),
                            "cropped_video_path": utt.get("cropped_video_path"),
                            "status": utt.get("status"),
                        }
                        break
                
                utt_list[utt_idx_in_array]["pre_trim_snapshot"] = {
                    "start": utt_list[utt_idx_in_array].get("start"),
                    "end": utt_list[utt_idx_in_array].get("end"),
                    "cropped_video_path": utt_list[utt_idx_in_array].get("cropped_video_path"),
                    "next_utterance": next_utt_snapshot,
                    "trimmed_at": datetime.utcnow().isoformat(),
                }
                
                curr_video_url = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)
                
                # 4. Calculate crop parameters.
                #
                # Key facts:
                # - CV2 video always starts at 0.0 physically
                # - PipelineTranscript.start/end are ASR absolute timestamps
                # - FE sends start_time/end_time in ASR space (preserved by offset fix)
                # - relative_start = how far into CV2 video to seek (trim-in from left)
                # - right_overlap = how much extra we need from the next video (trim-out)
                
                orig_start = curr_transcript.start
                orig_end = curr_transcript.end
                orig_duration = max(0.01, orig_end - orig_start)
                
                # ══════════════════════════════════════════════════════════
                # IMPROVEMENT 4: Allow trim-in (start_time != orig_start)
                # No longer clamp start_time to orig_start. Instead, compute
                # relative_start naturally so FFmpeg seeks into the video.
                # ══════════════════════════════════════════════════════════
                if start_time < orig_start:
                    logger.warning(
                        f"Trim-in before orig_start for utt {utterance_index}: "
                        f"start={start_time:.3f} but orig_start={orig_start:.3f}. "
                        f"Clamping to orig_start."
                    )
                    start_time = orig_start
                
                requested_duration = abs(end_time - start_time)
                relative_start = max(0.0, start_time - orig_start)  # seek into CV2
                remaining_in_video = max(0.01, orig_duration - relative_start)
                
                # How much exceeds what this CV2 video can provide after seeking
                right_overlap = requested_duration - remaining_in_video
                
                config = FFmpegConfig(video_preset="ultrafast")
                
                logger.info(
                    f"Crop utt {utterance_index}: orig=[{orig_start:.2f},{orig_end:.2f}] "
                    f"req=[{start_time:.2f},{end_time:.2f}] rel_start={relative_start:.2f} "
                    f"req_dur={requested_duration:.2f} overlap={right_overlap:.2f}"
                )
                
                # Edge case: if relative_start already at or past the end of the CV2 video,
                # we need to pull everything from the next video (skip Part A)
                skip_part_a = relative_start >= orig_duration - 0.001
                
                cascade_affected = []  # Track affected utterances for audit trail
                
                if right_overlap <= 0 and not skip_part_a:
                    # ══════════════════════════════════════════════
                    # NORMAL CASE: fits within this CV2 video
                    # Handles: no-trim, trim-in-left, trim-in-right, or both
                    # ══════════════════════════════════════════════
                    tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                    
                    success = await run_ffmpeg_crop(
                        input_path=curr_video_url,
                        output_path=tmp_output,
                        start_time=relative_start,
                        end_time=relative_start + requested_duration,
                        use_input_seeking=False,
                        config=config
                    )
                    
                    if not success:
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return
                else:
                    # ══════════════════════════════════════════════
                    # BOUNDARY CROSS-CROPPING & MERGING
                    # Trim-out to right (possibly with trim-in from left too)
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
                        logger.warning("Next utterance video not found. Clamping to end of current video (likely the last utterance).")
                        
                        if relative_start >= orig_duration - 0.001:
                            # Already at/past the end of the video — use original as-is
                            utt_list[utt_idx_in_array]["cropped_video_path"] = curr_transcript.video_path
                            utt_list[utt_idx_in_array]["status"] = "OK"
                        else:
                            # Fallback: Just crop what we have left in the current video
                            tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                            success = await run_ffmpeg_crop(
                                input_path=curr_video_url,
                                output_path=tmp_output,
                                start_time=relative_start,
                                end_time=orig_duration,
                                use_input_seeking=False,
                                config=config
                            )
                            if not success:
                                await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                                return
                            
                            upload_key = f"jobs/{segment.job_id}/utterances_synced/{segment_id}_utt_{utterance_index}.mp4"
                            with open(tmp_output, "rb") as f:
                                await minio_service.upload_file(f, upload_key)
                            
                            _cleanup_tmp(tmp_output)
                            
                            utt_list[utt_idx_in_array]["cropped_video_path"] = upload_key
                            utt_list[utt_idx_in_array]["status"] = "OK"
                        
                        edit.utterance_corrections = utt_list
                        flag_modified(edit, "utterance_corrections")
                        await db.commit()
                        return
                    
                    # Clamp right_overlap to next video's duration
                    next_duration = max(0.01, next_transcript.end - next_transcript.start)
                    clamped_overlap = min(right_overlap, next_duration)
                    
                    next_video_url = await minio_service.generate_presigned_url(
                        next_transcript.video_path, expiry=3600
                    )
                    
                    # Edge case: if remaining Part A is too small to be a valid video,
                    # use video-editor-sibi approach: merge full videos first, then crop.
                    # This avoids concatenating a tiny partial clip which FFmpeg rejects.
                    part_a_duration = orig_duration - relative_start
                    MIN_PART_A_DURATION = 0.05  # ~1.5 frames at 30fps
                    
                    if part_a_duration < MIN_PART_A_DURATION:
                        logger.info(
                            f"Part A too short ({part_a_duration:.3f}s < {MIN_PART_A_DURATION}s), "
                            f"using merge-then-crop approach (video-editor-sibi style)"
                        )
                        
                        # Approach: concat FULL current + FULL next video, then crop from merged.
                        # This is how video-editor-sibi handles cross-video trim seamlessly.
                        tmp_merged = f"/tmp/{segment_id}_utt_{utterance_index}_merged.mp4"
                        success_merge = await run_ffmpeg_concat(
                            input_paths=[curr_video_url, next_video_url],
                            output_path=tmp_merged,
                            config=config
                        )
                        
                        tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                        if success_merge:
                            # Crop from the merged file: [relative_start, relative_start + requested]
                            # Cap at what merged can provide (part_a_duration + next_duration)
                            crop_end = min(
                                relative_start + requested_duration,
                                part_a_duration + next_duration
                            )
                            success = await run_ffmpeg_crop(
                                input_path=tmp_merged,
                                output_path=tmp_output,
                                start_time=relative_start,
                                end_time=crop_end,
                                use_input_seeking=False,
                                config=config
                            )
                            _cleanup_tmp(tmp_merged)
                            if not success:
                                await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                                return
                        else:
                            # Fallback: if even full-video concat fails, use next video only
                            _cleanup_tmp(tmp_merged)
                            logger.warning(
                                "Merge-then-crop failed for tiny Part A, "
                                "falling back to next video only"
                            )
                            success = await run_ffmpeg_crop(
                                input_path=next_video_url,
                                output_path=tmp_output,
                                start_time=0.0,
                                end_time=min(requested_duration, next_duration),
                                use_input_seeking=False,
                                config=config
                            )
                            if not success:
                                await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                                return
                    else:
                        # Part A: Current video from relative_start to end
                        tmp_part_a = f"/tmp/{segment_id}_utt_{utterance_index}_partA.mp4"
                        success_a = await run_ffmpeg_crop(
                            input_path=curr_video_url,
                            output_path=tmp_part_a,
                            start_time=relative_start,
                            end_time=orig_duration,
                            use_input_seeking=False,
                            config=config
                        )
                        
                        # Part B: Next video from 0 to clamped_overlap
                        tmp_part_b = f"/tmp/{segment_id}_utt_{utterance_index}_partB.mp4"
                        success_b = await run_ffmpeg_crop(
                            input_path=next_video_url,
                            output_path=tmp_part_b,
                            start_time=0.0,
                            end_time=clamped_overlap,
                            use_input_seeking=False,
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
                    
                    # ══════════════════════════════════════════════════════════
                    # IMPROVEMENT 2 + 3: Deep cascade + audit trail
                    # ══════════════════════════════════════════════════════════
                    cascade_affected = await _cascade_update_next_utterance(
                        db, segment, next_transcript.segment_id, 
                        next_transcript.utterance_index, clamped_overlap
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
                
                # ══════════════════════════════════════════════════════════
                # IMPROVEMENT 3: Record cascade audit trail
                # ══════════════════════════════════════════════════════════
                if cascade_affected:
                    cascade_entry = {
                        "source_utterance": utterance_index,
                        "source_segment_id": str(segment_id),
                        "affected_utterances": cascade_affected,
                        "shift_amount": right_overlap if right_overlap > 0 else 0,
                        "timestamp": datetime.utcnow().isoformat(),
                        "action": "trim_crop",
                    }
                    # Append to existing cascade_info or create new
                    existing_cascade = edit.cascade_info or {}
                    history = existing_cascade.get("history", [])
                    history.append(cascade_entry)
                    edit.cascade_info = {"history": history}
                    flag_modified(edit, "cascade_info")
                
                await db.commit()
                
            except Exception as e:
                logger.exception(f"Error in crop_and_upload: {e}")
                # Attempt to mark as failed
                try:
                    await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                except Exception:
                    pass

    @staticmethod
    async def revert_utterance(
        segment_id: uuid.UUID,
        utterance_index: int
    ) -> dict:
        """
        IMPROVEMENT 1: Revert a previously-trimmed utterance to its pre-trim state.
        
        Reads the pre_trim_snapshot stored in utterance_corrections and restores:
        1. The current utterance's start/end/cropped_video_path/status
        2. The next utterance's start (if it was shifted by cascade)
        3. Clears merged_video_path for both utterances
        
        Returns dict with revert details.
        """
        async with async_session_maker() as db:
            # 1. Fetch active edit
            edit_result = await db.execute(
                select(AnnotationEdit).where(
                    AnnotationEdit.segment_id == segment_id,
                    AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
                    AnnotationEdit.is_deleted == False
                ).order_by(AnnotationEdit.edited_at.desc())
            )
            edit = edit_result.scalars().first()
            if not edit or not edit.utterance_corrections:
                return {"error": "No active edit found"}
            
            utt_list = list(edit.utterance_corrections)
            
            # Find the target utterance
            target_idx = None
            target_utt = None
            for i, utt in enumerate(utt_list):
                if utt.get("utterance_index") == utterance_index:
                    target_idx = i
                    target_utt = utt
                    break
            
            if target_utt is None:
                return {"error": "Utterance not found"}
            
            snapshot = target_utt.get("pre_trim_snapshot")
            if not snapshot:
                return {"error": "No pre-trim snapshot available for this utterance"}
            
            # 2. Restore current utterance from snapshot
            old_start = target_utt.get("start")
            old_end = target_utt.get("end")
            
            utt_list[target_idx]["start"] = snapshot["start"]
            utt_list[target_idx]["end"] = snapshot["end"]
            utt_list[target_idx]["cropped_video_path"] = snapshot.get("cropped_video_path")
            utt_list[target_idx]["status"] = "DRAFT"
            # Remove the snapshot after using it
            utt_list[target_idx].pop("pre_trim_snapshot", None)
            
            # 3. Restore next utterance if it was affected
            next_snapshot = snapshot.get("next_utterance")
            if next_snapshot:
                for i, utt in enumerate(utt_list):
                    if utt.get("utterance_index") == utterance_index + 1:
                        utt_list[i]["start"] = next_snapshot["start"]
                        # Clear the next utterance's cropped video since its start changed
                        utt_list[i]["cropped_video_path"] = None
                        if utt_list[i].get("status") == "OK":
                            utt_list[i]["status"] = "DRAFT"
                        break
            
            edit.utterance_corrections = utt_list
            flag_modified(edit, "utterance_corrections")
            
            # 4. Record revert in cascade_info audit trail
            revert_entry = {
                "source_utterance": utterance_index,
                "source_segment_id": str(segment_id),
                "action": "revert",
                "reverted_from": {"start": old_start, "end": old_end},
                "reverted_to": {"start": snapshot["start"], "end": snapshot["end"]},
                "timestamp": datetime.utcnow().isoformat(),
            }
            existing_cascade = edit.cascade_info or {}
            history = existing_cascade.get("history", [])
            history.append(revert_entry)
            edit.cascade_info = {"history": history}
            flag_modified(edit, "cascade_info")
            
            # 5. Clear merged videos for affected utterances
            for utt_index in [utterance_index, utterance_index + 1]:
                transcript_result = await db.execute(
                    select(PipelineTranscript).where(
                        PipelineTranscript.segment_id == segment_id,
                        PipelineTranscript.utterance_index == utt_index
                    )
                )
                transcript = transcript_result.scalar_one_or_none()
                if transcript and transcript.merged_video_path:
                    transcript.merged_video_path = None
                    transcript.merged_video_duration = None
                    transcript.video_n_duration = None
            
            await db.commit()
            
            return {
                "status": "reverted",
                "utterance_index": utterance_index,
                "reverted_start": snapshot["start"],
                "reverted_end": snapshot["end"],
                "message": f"Kalimat {utterance_index + 1} berhasil dikembalikan ke kondisi sebelum trim."
            }


async def _mark_failed(db, edit, utt_list, utt_idx):
    utt_list[utt_idx]["status"] = "FAILED"
    edit.utterance_corrections = utt_list
    flag_modified(edit, "utterance_corrections")
    await db.commit()


async def _cascade_update_next_utterance(
    db, segment: PipelineSegment, next_segment_id: uuid.UUID, 
    next_utterance_index: int, right_overlap: float
) -> list:
    """Cascade update next utterance after trim — IMPROVED.
    
    IMPROVEMENT 2: Deep cascade invalidation.
    After updating N+1, continues to invalidate merged videos for N+2, N+3, etc.
    
    IMPROVEMENT 3: Returns list of affected utterances for audit trail.
    
    1. Push next utterance's start forward by the overlap amount
    2. Clear cropped_video_path so next utterance will be re-cropped
    3. Clear merged_video_path for N+1, N+2, ... (deep cascade)
    """
    affected = []
    
    # Get the transcript for next utterance
    transcript_result = await db.execute(
        select(PipelineTranscript).where(
            PipelineTranscript.segment_id == next_segment_id,
            PipelineTranscript.utterance_index == next_utterance_index
        )
    )
    transcript = transcript_result.scalar_one_or_none()
    if not transcript:
        return affected
    
    # Push start forward logically (calculate new start)
    old_start = transcript.start
    new_start = old_start + right_overlap
    
    if new_start > old_start:
        # Clear merged video so next load re-merges
        transcript.merged_video_path = None
        transcript.merged_video_duration = None
        transcript.video_n_duration = None
        
        affected.append({
            "utterance_index": next_utterance_index,
            "segment_id": str(next_segment_id),
            "old_start": old_start,
            "new_start": new_start,
            "action": "start_shifted",
        })
    
    # Also update AnnotationEdit (draft corrections) if exists
    edit_result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == next_segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    next_edit = edit_result.scalars().first()
    
    if next_edit and next_edit.utterance_corrections:
        next_utt_list = list(next_edit.utterance_corrections)
        
        for i, utt in enumerate(next_utt_list):
            if utt.get("utterance_index") == next_utterance_index:
                old_start_edit = utt.get("start", 0.0)
                # Cap the edit at transcript.end - 0.1 so we don't have invalid intervals
                new_start_edit = max(old_start_edit, new_start)
                
                if new_start_edit > old_start_edit:
                    next_utt_list[i]["start"] = new_start_edit
                    # Clear cropped_video_path so it will be re-cropped
                    next_utt_list[i]["cropped_video_path"] = None
                    # Clear status so it can be edited again
                    if next_utt_list[i].get("status") == "OK":
                        next_utt_list[i]["status"] = "DRAFT"
                    
                    if next_utt_list[i]["start"] >= next_utt_list[i].get("end", 999):
                        next_utt_list[i]["start"] = next_utt_list[i]["end"] - 0.1
                    
                    next_edit.utterance_corrections = next_utt_list
                    flag_modified(next_edit, "utterance_corrections")
                break
    
    # ══════════════════════════════════════════════════════════════════
    # IMPROVEMENT 2: Deep cascade — invalidate merged videos for
    # N+2, N+3, ... because their cached merge may contain stale data
    # from the video that just changed.
    # ══════════════════════════════════════════════════════════════════
    deep_result = await db.execute(
        select(PipelineTranscript)
        .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
        .where(PipelineSegment.job_id == segment.job_id)
        .where(
            (PipelineSegment.segment_index > segment.segment_index) |
            ((PipelineSegment.segment_index == segment.segment_index) & 
             (PipelineTranscript.utterance_index > next_utterance_index))
        )
        .order_by(PipelineSegment.segment_index.asc(), PipelineTranscript.utterance_index.asc())
        .limit(5)  # Invalidate up to 5 downstream merges
    )
    downstream_transcripts = deep_result.scalars().all()
    
    for dt in downstream_transcripts:
        if dt.merged_video_path:
            dt.merged_video_path = None
            dt.merged_video_duration = None
            dt.video_n_duration = None
            affected.append({
                "utterance_index": dt.utterance_index,
                "segment_id": str(dt.segment_id),
                "action": "merged_video_invalidated",
            })
    
    await db.commit()
    return affected


def _cleanup_tmp(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
