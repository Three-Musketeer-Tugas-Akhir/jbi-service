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
from app.services.utterance_merge_service import (
    _prev_orphan_geometry,
    MAX_LOOKAHEAD,
    PrevGeometry,
)
from app.pipeline.utils.video import run_ffmpeg_crop, run_ffmpeg_concat, FFmpegConfig

logger = logging.getLogger(__name__)


class UtteranceCroppingService:
    @staticmethod
    async def crop_and_upload(
        segment_id: uuid.UUID,
        utterance_index: int,
        start_time: float,
        end_time: float,
        edit_id: Optional[uuid.UUID] = None,
        cascade: bool = True
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

        ``cascade=False`` suppresses the neighbour updates. It is used for the
        re-cut of a sentence that was just shortened to feed the one after it:
        that sentence's neighbours were already settled by the crop that
        triggered it, and running the cascade again would undo them.
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
                
                # The draft-save that necessarily preceded this crop (the /crop
                # endpoint takes no start/end of its own -- it only crops to
                # whatever the latest draft already holds) already stashed the
                # true PRE-trim start/end in create_draft, since by the time
                # THIS code runs those fields have already been overwritten
                # with the new target values. Reuse that snapshot and just fill
                # in next_utterance, which only becomes knowable here. The
                # inline fallback below only fires for a crop triggered without
                # a preceding draft-save (not the normal FE flow).
                existing_snapshot = utt_list[utt_idx_in_array].get("pre_trim_snapshot")
                if existing_snapshot:
                    # Only fill next_utterance if create_draft could not. The value
                    # computed above is read from utt_list, which the preceding
                    # draft-save has ALREADY cascaded, so it holds N+1's post-trim
                    # start — restoring from it is a no-op. create_draft captures
                    # the genuine pre-trim neighbour, so never clobber that.
                    if existing_snapshot.get("next_utterance") is None:
                        existing_snapshot["next_utterance"] = next_utt_snapshot
                    utt_list[utt_idx_in_array]["pre_trim_snapshot"] = existing_snapshot
                else:
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
                # A start before this clip's head is served from utterance N-1, in
                # two tiers. First the ORPHAN TAIL — the stretch N-1 released when
                # its own annotator trimmed in — which costs nothing because N-1
                # already wrote it off. Past that comes material N-1 still OWNS:
                # taking it is allowed, but it must be paid for by shortening N-1's
                # own end and re-cropping it (the left cascade below). Beyond
                # ``reach`` (which always leaves N-1 a minimum) the request is
                # clamped. The reclaimed piece is prepended as Part Z after the
                # normal crop has produced this clip's own contribution.
                # ══════════════════════════════════════════════════════════
                prev_geom = None
                prev_transcript = None
                clamped_left = 0.0
                borrowed_from_prev = 0.0
                if start_time < orig_start:
                    left_overlap = orig_start - start_time
                    prev_geom = await _prev_orphan_geometry(db, segment, utterance_index)
                    prev_transcript = prev_geom.transcript
                    clamped_left = min(left_overlap, prev_geom.reach)
                    # Anything past the free orphan is borrowed from N-1 itself.
                    borrowed_from_prev = max(0.0, clamped_left - prev_geom.orphan)
                    if clamped_left > 0.0:
                        logger.info(
                            f"Backward trim-in for utt {utterance_index}: requested "
                            f"{left_overlap:.3f}s before orig_start, reclaiming "
                            f"{clamped_left:.3f}s from utt "
                            f"{prev_transcript.utterance_index} "
                            f"({min(clamped_left, prev_geom.orphan):.3f}s orphan + "
                            f"{borrowed_from_prev:.3f}s borrowed)"
                        )
                    else:
                        logger.warning(
                            f"Trim-in before orig_start for utt {utterance_index}: "
                            f"start={start_time:.3f} but orig_start={orig_start:.3f} and "
                            f"nothing is reachable behind it. Clamping to orig_start."
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
                consumed: list = []    # Following clips this crop ate into, in order

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

                    # Which following clips this spill reaches, and how deeply. More
                    # than one can be involved because the footage the annotator
                    # needs is sometimes not in the very next row but two or three
                    # further on, with rows in between too short to work with. Those
                    # in-between rows get swallowed whole (see the cascade below).
                    consumed = await _plan_forward_consumption(
                        db, segment, curr_transcript.utterance_index, right_overlap
                    )

                    if not consumed:
                        logger.error("Next utterance video not found. Cannot merge.")
                        await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                        return

                    # Total actually obtainable — the request is clamped to it when
                    # the annotator drags past the last available clip.
                    clamped_overlap = sum(c["taken"] for c in consumed)
                    next_transcript = consumed[0]["transcript"]
                    next_duration = consumed[0]["duration"]

                    next_video_urls = []
                    for c in consumed:
                        next_video_urls.append(
                            await minio_service.generate_presigned_url(
                                c["transcript"].video_path, expiry=3600
                            )
                        )
                    next_video_url = next_video_urls[0]

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
                        
                        # Approach: concat FULL current + every consumed video, then
                        # crop from merged. This is how video-editor-sibi handles
                        # cross-video trim seamlessly.
                        tmp_merged = f"/tmp/{segment_id}_utt_{utterance_index}_merged.mp4"
                        success_merge = await run_ffmpeg_concat(
                            input_paths=[curr_video_url, *next_video_urls],
                            output_path=tmp_merged,
                            config=config
                        )

                        tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                        if success_merge:
                            # Crop from the merged file: [relative_start, relative_start + requested]
                            # Cap at what merged can actually provide.
                            crop_end = min(
                                relative_start + requested_duration,
                                part_a_duration + sum(c["duration"] for c in consumed)
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
                        
                        # Part B: one piece per consumed clip. A clip taken whole is
                        # used as-is; only the final, partly-taken one is cropped.
                        part_b_paths = []
                        success_b = True
                        for i, c in enumerate(consumed):
                            if c["fully"]:
                                part_b_paths.append(next_video_urls[i])
                                continue
                            tmp_part_b = f"/tmp/{segment_id}_utt_{utterance_index}_partB{i}.mp4"
                            success_b = await run_ffmpeg_crop(
                                input_path=next_video_urls[i],
                                output_path=tmp_part_b,
                                start_time=0.0,
                                end_time=c["taken"],
                                use_input_seeking=False,
                                config=config
                            )
                            if not success_b:
                                break
                            part_b_paths.append(tmp_part_b)

                        # Only the cropped pieces are ours to delete; the rest are URLs.
                        tmp_b_files = [p for p in part_b_paths if p.startswith("/tmp/")]

                        if not (success_a and success_b):
                            _cleanup_tmp(tmp_part_a, *tmp_b_files)
                            await _mark_failed(db, edit, utt_list, utt_idx_in_array)
                            return

                        # Merge
                        tmp_output = f"/tmp/{segment_id}_utt_{utterance_index}.mp4"
                        success_merge = await run_ffmpeg_concat(
                            input_paths=[tmp_part_a, *part_b_paths],
                            output_path=tmp_output,
                            config=config
                        )

                        _cleanup_tmp(tmp_part_a, *tmp_b_files)

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
                    # physically adjacent to this clip's head. Never earlier than the
                    # borrow floor, which is the minimum N-1 must keep for itself.
                    prev_clip_duration = max(0.01, prev_transcript.end - prev_transcript.start)
                    orphan_local_start = max(0.0, prev_geom.effective_end - prev_transcript.start)
                    borrow_floor = max(0.0, orphan_local_start - prev_geom.borrowable)
                    z_start = max(borrow_floor, prev_clip_duration - clamped_left)

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
                            # Nothing was reclaimed, so N-1 must not be charged for it.
                            clamped_left = 0.0
                            borrowed_from_prev = 0.0
                    else:
                        _cleanup_tmp(tmp_part_z)
                        logger.warning("Part Z crop failed; saving crop without the reclaimed lookback")
                        clamped_left = 0.0
                        borrowed_from_prev = 0.0

                # Upload video
                upload_key = f"jobs/{segment.job_id}/utterances_synced/{segment_id}_utt_{utterance_index}.mp4"

                # ══════════════════════════════════════════════════════════
                # BACK UP WHATEVER IS CURRENTLY AT upload_key BEFORE OVERWRITING
                # For a bulk-imported dataset (TVRI), that key already holds the
                # delivered clip from import time, not a blank slot -- and every
                # crop (this one included) always writes to this SAME
                # deterministic key, so without a backup the previous content is
                # gone the instant this upload lands. /revert restores the
                # utterance_corrections row, but with nothing backed up it would
                # keep pointing at this same key while its bytes now hold the
                # WRONG (just-cropped) footage. One backup slot is enough since
                # revert only ever steps back a single crop.
                # ══════════════════════════════════════════════════════════
                backup_key = None
                if await minio_service.object_exists(upload_key):
                    backup_key = (
                        f"jobs/{segment.job_id}/utterances_synced_backup/"
                        f"{segment_id}_utt_{utterance_index}.mp4"
                    )
                    try:
                        await minio_service.copy_object(upload_key, backup_key)
                    except Exception as e:
                        logger.warning(
                            f"Could not back up {upload_key} before crop; revert will "
                            f"only be able to restore metadata, not video content: {e}"
                        )
                        backup_key = None

                with open(tmp_output, "rb") as f:
                    await minio_service.upload_file(f, upload_key)

                _cleanup_tmp(tmp_output)

                utt_list[utt_idx_in_array]["cropped_video_path"] = upload_key
                utt_list[utt_idx_in_array]["status"] = "OK"
                # Record how much orphan tail this crop reclaimed, so a revert can
                # tell an ordinary trim apart from one that reached backwards.
                utt_list[utt_idx_in_array]["pre_trim_snapshot"]["consumed_from_prev"] = clamped_left
                utt_list[utt_idx_in_array]["pre_trim_snapshot"]["backup_video_path"] = backup_key

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
                # Pin each following utterance's working start to exactly the head
                # this crop consumed. An empty ``consumed`` resets them to base — so
                # re-trimming N smaller, even down to no spill, always pulls the
                # neighbours back and never strands a gap of lost content, and a row
                # that was swallowed whole is un-swallowed the same way.
                # ══════════════════════════════════════════════════════════
                cascade_affected = []
                if cascade:
                    cascade_affected = await _cascade_consume_forward(
                        db, segment, utterance_index, consumed
                    )

                # ══════════════════════════════════════════════════════════
                # LEFT CASCADE — pay utterance N-1 for what was borrowed from it.
                # Only the part beyond its released orphan is charged; the orphan
                # itself was already written off. N-1 loses exactly that many
                # seconds off its end and is re-cropped so its stored video matches
                # its new range. Without this the same footage would sit in BOTH
                # sentences' exported clips.
                # ══════════════════════════════════════════════════════════
                if cascade and borrowed_from_prev > 0.0 and prev_geom is not None and prev_transcript is not None:
                    left_affected = await _shorten_prev_utterance(
                        db, prev_geom, borrowed_from_prev
                    )
                    if left_affected:
                        cascade_affected.append(left_affected)

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

            # The crop being undone overwrote whatever was at cropped_video_path
            # (for a bulk-imported dataset, that was the delivered clip itself,
            # not an empty slot). Restoring start/end/status alone would leave
            # this key pointing at footage that no longer matches them. Copy the
            # pre-crop bytes back before touching the metadata below.
            backup_path = snapshot.get("backup_video_path")
            restored_video_path = snapshot.get("cropped_video_path")
            if backup_path and restored_video_path:
                minio_service = get_minio_service()
                try:
                    await minio_service.copy_object(backup_path, restored_video_path)
                    # Consumed -- and each crop only ever keeps one backup slot
                    # per utterance, so leaving it around just wastes storage.
                    await minio_service.delete_object(backup_path)
                except Exception as e:
                    logger.warning(
                        f"Revert for utt {utterance_index}: could not restore video "
                        f"bytes from backup {backup_path}: {e}"
                    )

            utt_list[target_idx]["start"] = snapshot["start"]
            utt_list[target_idx]["end"] = snapshot["end"]
            utt_list[target_idx]["cropped_video_path"] = restored_video_path
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
            await db.commit()

            # 3b. Re-settle every following row against the RESTORED range. The
            # snapshot only carries N+1, but a crop can swallow several rows whole
            # on its way to a later one, and those must be released too. Deriving
            # the claim from the restored end (rather than replaying the snapshot)
            # keeps this correct at any depth and leaves a still-legitimate spill
            # from an earlier, un-reverted crop in place.
            segment_row = (await db.execute(
                select(PipelineSegment).where(PipelineSegment.id == segment_id)
            )).scalar_one_or_none()
            curr_transcript = (await db.execute(
                select(PipelineTranscript).where(
                    PipelineTranscript.segment_id == segment_id,
                    PipelineTranscript.utterance_index == utterance_index
                )
            )).scalar_one_or_none()
            if segment_row is not None and curr_transcript is not None:
                restored_overlap = max(0.0, snapshot["end"] - curr_transcript.end)
                await _cascade_consume_forward(
                    db, segment_row, utterance_index,
                    await _plan_forward_consumption(
                        db, segment_row, utterance_index, restored_overlap
                    ),
                )
            
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


async def _plan_forward_consumption(
    db, segment: PipelineSegment, curr_utterance_index: int, overlap: float
) -> list:
    """Which following clips an ``overlap``-second spill eats into, and how deeply.

    Walks forward taking whole clips until the spill is covered; the last one is
    usually only partly taken. Shared by the crop (to build the video) and the
    revert (to work out which rows the restored range still claims), so both
    always agree on where a spill lands.
    """
    if overlap <= 1e-6:
        return []

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
        .limit(MAX_LOOKAHEAD)
    )
    following = [t for t in next_result.scalars().all() if t.video_path]

    consumed = []
    remaining = overlap
    for t in following:
        if remaining <= 1e-6:
            break
        t_duration = max(0.01, t.end - t.start)
        take = min(remaining, t_duration)
        consumed.append({
            "transcript": t,
            "taken": take,
            "fully": take >= t_duration - 1e-6,
            "duration": t_duration,
        })
        remaining -= take
    return consumed


async def _cascade_consume_forward(
    db, segment: PipelineSegment, curr_utterance_index: int, consumed: list
) -> list:
    """Idempotent cascade (REPLACE semantics) on the FLOORS of the following rows.

    After utterance N is cropped, each following utterance it ate into gets its
    ``floor`` pinned to exactly how much of its own head N took:

      - taken in part  -> ``floor = transcript_base + taken``, still annotatable
      - taken whole    -> ``floor = transcript_end`` and ``status = MERGED``; the
        row has no footage of its own left, so it is skipped on export and shown
        as absorbed in the workspace

    Rows past the consumed run are reset to base, which is what makes shrinking
    reversible: a row swallowed by an earlier crop is un-swallowed as soon as the
    crop no longer reaches it. Because every floor is computed from the immutable
    transcript base (never from the previous floor), the whole walk is idempotent
    in both directions.

    The floor is what the look-ahead merge physically crops from a row's head (the
    region owned by N, hidden from that row). The annotator's own trim-in beyond
    the floor stays as a recoverable gray head. PipelineTranscript.start is never
    mutated. Returns the list of affected utterances for the audit trail.
    """
    affected = []

    # Walk further than the crop could possibly have reached, so rows left MERGED
    # by a previous, longer crop are found and released.
    horizon = MAX_LOOKAHEAD + 3
    following_result = await db.execute(
        select(PipelineTranscript)
        .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
        .where(PipelineSegment.job_id == segment.job_id)
        .where(
            (PipelineSegment.segment_index > segment.segment_index) |
            ((PipelineSegment.segment_index == segment.segment_index) &
             (PipelineTranscript.utterance_index > curr_utterance_index))
        )
        .order_by(PipelineSegment.segment_index.asc(), PipelineTranscript.utterance_index.asc())
        .limit(horizon)
    )
    following = following_result.scalars().all()
    if not following:
        return affected

    taken_by_id = {c["transcript"].id: c for c in consumed}

    # One edit per segment; the run can span a segment boundary.
    edits_by_segment: dict = {}

    async def _edit_for(seg_id):
        if seg_id not in edits_by_segment:
            res = await db.execute(
                select(AnnotationEdit).where(
                    AnnotationEdit.segment_id == seg_id,
                    AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
                    AnnotationEdit.is_deleted == False
                ).order_by(AnnotationEdit.edited_at.desc())
            )
            edits_by_segment[seg_id] = res.scalars().first()
        return edits_by_segment[seg_id]

    for transcript in following:
        entry = taken_by_id.get(transcript.id)
        base_start = transcript.start                  # immutable original

        if entry is not None:
            fully = entry["fully"]
            new_floor = transcript.end if fully else base_start + max(0.0, entry["taken"])
        else:
            fully = False
            new_floor = base_start

        edit = await _edit_for(transcript.segment_id)
        if not edit or not edit.utterance_corrections:
            # Nothing to reset here and nothing consumed -> the run is over.
            if entry is None:
                break
            continue

        utt_list = list(edit.utterance_corrections)
        row_changed = False
        for i, utt in enumerate(utt_list):
            if utt.get("utterance_index") != transcript.utterance_index:
                continue

            old_floor = utt.get("floor", base_start)
            old_start = utt.get("start", base_start)
            old_status = utt.get("status")

            # Preserve the annotator's own head trim-in (the part of start beyond
            # the floor) while re-pinning the cascade floor.
            user_delta = max(0.0, old_start - old_floor)
            new_start = new_floor + user_delta
            end_val = utt.get("end", transcript.end)
            if not fully and new_start >= end_val:
                new_start = end_val - 0.1

            new_status = old_status
            if fully:
                new_status = "MERGED"
            elif old_status in ("MERGED", "OK"):
                # Released from an earlier swallow, or its head moved — either way
                # it needs looking at again.
                new_status = "DRAFT"

            geometry_moved = (
                abs(new_floor - old_floor) > 1e-6 or abs(new_start - old_start) > 1e-6
            )
            if geometry_moved or new_status != old_status:
                utt_list[i]["floor"] = new_floor
                utt_list[i]["start"] = new_start
                utt_list[i]["status"] = new_status
                # This row's head changed -> its physical crop is stale.
                utt_list[i]["cropped_video_path"] = None
                edit.utterance_corrections = utt_list
                flag_modified(edit, "utterance_corrections")
                row_changed = True
                affected.append({
                    "utterance_index": transcript.utterance_index,
                    "segment_id": str(transcript.segment_id),
                    "old_start": old_start,
                    "new_start": new_start,
                    "new_floor": new_floor,
                    "status": new_status,
                    "action": "merged_into_prev" if fully else "floor_set",
                })
            break

        # A row's head changed -> its own look-ahead merge is stale.
        if row_changed and transcript.merged_video_path:
            transcript.merged_video_path = None
            transcript.merged_video_duration = None
            transcript.video_n_duration = None

        # Past the consumed run, the first untouched row means everything beyond
        # it is untouched too — nothing downstream could still be stale.
        if entry is None and not row_changed:
            break

    await db.commit()
    return affected


async def _shorten_prev_utterance(
    db, prev_geom: PrevGeometry, borrowed: float
) -> Optional[dict]:
    """LEFT CASCADE — hand ``borrowed`` seconds of utterance N-1 over to N.

    The mirror of the forward cascade, and the only path that shortens a sentence
    other than the one being annotated. It runs when a backward trim-in reached
    past N-1's released orphan into footage N-1 still owned: N-1's ``end`` moves
    left by exactly that much, and its clip is re-cropped so the stored video
    matches its new range instead of still containing the handed-over footage.

    N-1 is left as DRAFT — its boundary was decided by someone annotating a
    different sentence, so it is worth a second look. Returns an audit entry, or
    None when there was nothing to charge.
    """
    prev_transcript = prev_geom.transcript
    if prev_transcript is None or borrowed <= 0.0:
        return None

    new_end = prev_geom.effective_end - borrowed
    # Never take a sentence below the floor the geometry promised to keep.
    if new_end <= prev_geom.effective_start + 1e-6:
        logger.warning(
            f"Refusing to shorten utt {prev_transcript.utterance_index} below its "
            f"own start (borrowed={borrowed:.3f}s); skipping left cascade"
        )
        return None

    edit_result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == prev_transcript.segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    prev_edit = edit_result.scalars().first()
    if not prev_edit or not prev_edit.utterance_corrections:
        logger.warning(
            f"No active edit for segment {prev_transcript.segment_id}; "
            f"cannot charge the borrowed lookback to utt {prev_transcript.utterance_index}"
        )
        return None

    prev_list = list(prev_edit.utterance_corrections)
    old_end = None
    for i, utt in enumerate(prev_list):
        if utt.get("utterance_index") != prev_transcript.utterance_index:
            continue
        old_end = utt.get("end", prev_transcript.end)
        prev_list[i]["end"] = new_end
        prev_list[i]["status"] = "DRAFT"
        # Its stored clip still holds the footage just handed over.
        prev_list[i]["cropped_video_path"] = None
        prev_edit.utterance_corrections = prev_list
        flag_modified(prev_edit, "utterance_corrections")
        break

    if old_end is None:
        return None

    # Its look-ahead tape ends at the old boundary.
    if prev_transcript.merged_video_path:
        prev_transcript.merged_video_path = None
        prev_transcript.merged_video_duration = None
        prev_transcript.video_n_duration = None

    await db.commit()

    logger.info(
        f"Left cascade: utt {prev_transcript.utterance_index} of segment "
        f"{prev_transcript.segment_id} shortened {old_end:.3f} -> {new_end:.3f} "
        f"({borrowed:.3f}s handed over); re-cropping it"
    )

    # Re-cut N-1 to its new range. cascade=False because the forward cascade from
    # N-1 would re-pin N's floor and wipe the backward start we just saved — and
    # N's geometry is already correct, having just been written by the caller.
    await UtteranceCroppingService.crop_and_upload(
        segment_id=prev_transcript.segment_id,
        utterance_index=prev_transcript.utterance_index,
        start_time=prev_geom.effective_start,
        end_time=new_end,
        cascade=False,
    )

    return {
        "utterance_index": prev_transcript.utterance_index,
        "segment_id": str(prev_transcript.segment_id),
        "old_end": old_end,
        "new_end": new_end,
        "borrowed_seconds": borrowed,
        "action": "shortened_for_next",
    }


def _cleanup_tmp(*paths):
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
