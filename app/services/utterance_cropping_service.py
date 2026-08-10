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
from app.services.utterance_merge_service import _prev_orphan_geometry
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
                # BACKWARD TRIM-IN (lookback)
                # A start before this clip's head can only be honoured from the
                # ORPHAN TAIL of utterance N-1 — the stretch N-1 released when its
                # own annotator trimmed in. Anything beyond that still belongs to
                # N-1, so it stays off limits and start_time is clamped to it.
                # The reclaimed piece is prepended as Part Z after the normal crop
                # below has produced this clip's own contribution.
                # ══════════════════════════════════════════════════════════
                prev_transcript = None
                prev_effective_end = 0.0
                prev_orphan = 0.0
                clamped_left = 0.0
                if start_time < orig_start:
                    left_overlap = orig_start - start_time
                    prev_transcript, prev_effective_end, prev_orphan = await _prev_orphan_geometry(
                        db, segment, utterance_index
                    )
                    clamped_left = min(left_overlap, prev_orphan)
                    if clamped_left > 0.0:
                        logger.info(
                            f"Backward trim-in for utt {utterance_index}: requested "
                            f"{left_overlap:.3f}s before orig_start, reclaiming "
                            f"{clamped_left:.3f}s of orphan tail from utt "
                            f"{prev_transcript.utterance_index}"
                        )
                    else:
                        logger.warning(
                            f"Trim-in before orig_start for utt {utterance_index}: "
                            f"start={start_time:.3f} but orig_start={orig_start:.3f} and no "
                            f"orphan tail is available. Clamping to orig_start."
                        )
                    # Downstream math stays anchored on this clip's own head.
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
                final_overlap = 0.0    # Seconds this crop consumed from the head of the NEXT video

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
                        logger.error("Next utterance video not found. Cannot merge.")
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
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
                    
                    # This crop consumed clamped_overlap seconds from the head of
                    # the next video. The unified idempotent cascade below applies it.
                    final_overlap = clamped_overlap

                # ══════════════════════════════════════════════════════════
                # PART Z: prepend the reclaimed orphan tail of utterance N-1.
                # Mirror of the Part A / Part B forward cross-crop above, running
                # after it so both directions can apply to the same crop.
                # N-1's own record is never touched: this only takes back what it
                # already released, so there is no cascade and no duplication.
                # ══════════════════════════════════════════════════════════
                if clamped_left > 0.0 and prev_transcript is not None:
                    prev_video_url = await minio_service.generate_presigned_url(
                        prev_transcript.video_path, expiry=3600
                    )
                    # Take the LAST clamped_left seconds of N-1's clip — the piece
                    # physically adjacent to this clip's head. Never earlier than
                    # the orphan boundary, which is still N-1's own material.
                    prev_clip_duration = max(0.01, prev_transcript.end - prev_transcript.start)
                    tail_local_start = max(0.0, prev_effective_end - prev_transcript.start)
                    z_start = max(tail_local_start, prev_clip_duration - clamped_left)

                    tmp_part_z = f"/tmp/{segment_id}_utt_{utterance_index}_partZ.mp4"
                    success_z = await run_ffmpeg_crop(
                        input_path=prev_video_url,
                        output_path=tmp_part_z,
                        start_time=z_start,
                        end_time=prev_clip_duration,
                        use_input_seeking=False,
                        config=config
                    )

                    if success_z:
                        tmp_with_z = f"/tmp/{segment_id}_utt_{utterance_index}_withZ.mp4"
                        success_z_merge = await run_ffmpeg_concat(
                            input_paths=[tmp_part_z, tmp_output],
                            output_path=tmp_with_z,
                            config=config
                        )
                        _cleanup_tmp(tmp_part_z)
                        if success_z_merge:
                            _cleanup_tmp(tmp_output)
                            tmp_output = tmp_with_z
                        else:
                            _cleanup_tmp(tmp_with_z)
                            logger.warning(
                                "Part Z concat failed; saving crop without the reclaimed lookback"
                            )
                            clamped_left = 0.0
                    else:
                        _cleanup_tmp(tmp_part_z)
                        logger.warning("Part Z crop failed; saving crop without the reclaimed lookback")
                        clamped_left = 0.0

                # Upload video
                upload_key = f"jobs/{segment.job_id}/utterances_synced/{segment_id}_utt_{utterance_index}.mp4"
                with open(tmp_output, "rb") as f:
                    await minio_service.upload_file(f, upload_key)
                
                _cleanup_tmp(tmp_output)
                
                utt_list[utt_idx_in_array]["cropped_video_path"] = upload_key
                utt_list[utt_idx_in_array]["status"] = "OK"
                # Record how much orphan tail this crop reclaimed, so a revert can
                # tell an ordinary trim apart from one that reached backwards.
                utt_list[utt_idx_in_array]["pre_trim_snapshot"]["consumed_from_prev"] = clamped_left

                edit.utterance_corrections = utt_list
                flag_modified(edit, "utterance_corrections")

                # ══════════════════════════════════════════════════════════
                # RESPONSIVE MERGE REGENERATION (this utterance)
                # Invalidate THIS utterance's own look-ahead merge cache so that
                # re-opening it rebuilds from the latest annotated state (e.g. the
                # user goes back to Kalimat N, trims its front, and presses Save —
                # the merge must reflect the new start offset, not the stale clip).
                # The cascade clears N+1..N+k; this covers N itself.
                # ══════════════════════════════════════════════════════════
                curr_transcript.merged_video_path = None
                curr_transcript.merged_video_duration = None
                curr_transcript.video_n_duration = None

                # ══════════════════════════════════════════════════════════
                # IDEMPOTENT CASCADE (REPLACE semantics)
                # Pin the next utterance's working start to exactly the head this
                # crop consumed (final_overlap). final_overlap == 0 resets it to
                # base — so re-trimming N smaller, even down to no spill, always
                # pulls N+1 back and never strands a gap of lost content.
                # ══════════════════════════════════════════════════════════
                cascade_affected = await _cascade_set_next_start(
                    db, segment, utterance_index, final_overlap
                )

                # ══════════════════════════════════════════════════════════
                # IMPROVEMENT 3: Record cascade audit trail
                # ══════════════════════════════════════════════════════════
                if cascade_affected:
                    cascade_entry = {
                        "source_utterance": utterance_index,
                        "source_segment_id": str(segment_id),
                        "affected_utterances": cascade_affected,
                        "shift_amount": final_overlap,
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


async def _cascade_set_next_start(
    db, segment: PipelineSegment, curr_utterance_index: int, final_overlap: float
) -> list:
    """Idempotent cascade (REPLACE semantics) on the next utterance's FLOOR.

    After utterance N is cropped consuming ``final_overlap`` seconds from the head
    of the next video, pin the NEXT utterance's ``floor`` to exactly
    ``transcript_base + final_overlap`` and carry its annotation ``start`` along
    while preserving the annotator's own head trim-in (``start - floor``).

    Because the floor is computed from the immutable transcript base (never from
    the previous floor), this is fully idempotent in BOTH directions:
      - re-trim N larger  -> N+1 floor moves further forward
      - re-trim N smaller -> N+1 floor moves back
      - re-trim N to no spill (final_overlap == 0) -> N+1 floor resets to base
    so a shrink never strands a gap of lost content between N and N+1.

    The floor is what the look-ahead merge physically crops from N+1's head (the
    region owned by N, hidden from N+1). The annotator's own trim-in beyond the
    floor stays as a recoverable gray head. PipelineTranscript.start is never
    mutated. Returns the list of affected utterances for the audit trail.
    """
    affected = []

    # Find the next utterance in the chain (same segment, else next segment).
    next_result = await db.execute(
        select(PipelineTranscript)
        .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
        .where(PipelineSegment.job_id == segment.job_id)
        .where(
            (PipelineSegment.segment_index > segment.segment_index) |
            ((PipelineSegment.segment_index == segment.segment_index) &
             (PipelineTranscript.utterance_index > curr_utterance_index))
        )
        .order_by(PipelineSegment.segment_index.asc(), PipelineTranscript.utterance_index.asc())
        .limit(1)
    )
    transcript = next_result.scalar_one_or_none()
    if not transcript:
        return affected

    next_segment_id = transcript.segment_id
    next_utterance_index = transcript.utterance_index
    base_start = transcript.start                      # immutable original
    # The cascade owns the FLOOR (how much of N+1's head this sentence consumed),
    # not the annotation start. The annotator's own head trim-in (start - floor)
    # is preserved on top, so it survives N being re-trimmed.
    new_floor = base_start + max(0.0, final_overlap)

    edit_result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == next_segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    next_edit = edit_result.scalars().first()

    changed = False
    if next_edit and next_edit.utterance_corrections:
        next_utt_list = list(next_edit.utterance_corrections)
        for i, utt in enumerate(next_utt_list):
            if utt.get("utterance_index") == next_utterance_index:
                old_floor = utt.get("floor", base_start)
                old_start = utt.get("start", base_start)
                # Preserve the annotator's own head trim-in (the part of start
                # beyond the floor) while re-pinning the cascade floor.
                user_delta = max(0.0, old_start - old_floor)
                new_start = new_floor + user_delta
                # Keep start strictly before end.
                end_val = utt.get("end", transcript.end)
                if new_start >= end_val:
                    new_start = end_val - 0.1
                if abs(new_floor - old_floor) > 1e-6 or abs(new_start - old_start) > 1e-6:
                    next_utt_list[i]["floor"] = new_floor
                    next_utt_list[i]["start"] = new_start
                    # The head of N+1 changed -> its physical crop is stale.
                    next_utt_list[i]["cropped_video_path"] = None
                    if next_utt_list[i].get("status") == "OK":
                        next_utt_list[i]["status"] = "DRAFT"
                    next_edit.utterance_corrections = next_utt_list
                    flag_modified(next_edit, "utterance_corrections")
                    changed = True
                    affected.append({
                        "utterance_index": next_utterance_index,
                        "segment_id": str(next_segment_id),
                        "old_start": old_start,
                        "new_start": new_start,
                        "new_floor": new_floor,
                        "action": "floor_set",
                    })
                break

    # N+1's head changed -> its own look-ahead merge (N+1 + N+2) is stale.
    # (N's merge, which also contains N+1, is cleared by the caller.) Downstream
    # merges (N+2 + N+3, ...) do not contain N+1, so they stay valid.
    if changed and transcript.merged_video_path:
        transcript.merged_video_path = None
        transcript.merged_video_duration = None
        transcript.video_n_duration = None

    await db.commit()
    return affected


def _cleanup_tmp(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
