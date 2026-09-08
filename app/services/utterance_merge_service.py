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
import asyncio
import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any, NamedTuple

import httpx

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineJob, PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import run_ffmpeg_concat, run_ffmpeg_crop, FFmpegConfig
from app.core.config import settings

logger = logging.getLogger(__name__)

# A sentence lent to its neighbour must keep at least this much of itself, so a
# backward trim-in can never reduce the previous sentence to an empty clip.
MIN_PREV_KEEP_SECONDS = 0.5

# Upper bound on how many following clips a tape may contain besides N itself.
# The annotator asks for depth explicitly; this only stops a runaway request
# from concatenating an entire segment.
MAX_LOOKAHEAD = 3


class PrevGeometry(NamedTuple):
    """What utterance N-1 holds that N could reach backwards into.

    ``orphan`` is free (N-1 already released it); ``borrowable`` still belongs to
    N-1 and taking it shortens N-1. See ``_prev_orphan_geometry``.
    """
    transcript: Optional[PipelineTranscript]
    effective_start: float
    effective_end: float
    orphan: float
    borrowable: float
    locked: bool

    @property
    def reach(self) -> float:
        """Total seconds before N's own head that the start handle may cover."""
        return self.orphan + self.borrowable


class UtteranceMergeService:
    """Service for merging adjacent utterance videos (look-ahead merge)."""

    @staticmethod
    async def get_or_create_merged_video(
        job_id: uuid.UUID,
        segment_id: uuid.UUID,
        utterance_index: int,
        include_prev: bool = False,
        lookahead: int = 1,
    ) -> Optional[dict]:
        """
        Get existing merged video or create a new one.

        The canonical tape is ``[N | N+1]``. Two opt-in extensions widen it when
        the sign the annotator needs does not fit inside it:

        ``include_prev`` prepends what utterance N-1 holds — its released orphan
        tail plus (marked separately) the material it still owns — so the start
        handle can trim in backwards. Reaching past the orphan shortens N-1, and
        the crop service is what actually pays that cost.

        ``lookahead`` appends N+2 … N+k, for the case where the needed footage is
        not in the next clip but two or three rows further on and the row in
        between is too short to work with.

        Neither variant is persisted in the transcript columns — those belong to
        the canonical two-clip tape — so each is regenerated per request and
        stored under its own MinIO key suffix.

        Returns dict with:
            merged_video_url: str — presigned URL for playback
            merged_video_path: str — MinIO key
            video_n_duration: float — duration of utterance N (for marker)
            total_duration: float — total duration of merged video
            head_offset: float — annotator's own recoverable head trim-in
            prev_offset: float — total seconds of N-1 actually prepended
            prev_orphan_offset: float — the free (orphan) part of prev_offset
            prev_available: float — orphan available to prepend, no cost
            prev_borrowable: float — extra available by shortening N-1
            lookahead_used: int — clips after N actually in the tape
            lookahead_available: int — clips after N that exist
            segment_durations: list[float] — duration of each clip in tape order
        """
        lookahead = max(1, min(int(lookahead or 1), MAX_LOOKAHEAD))
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

            # 1b. Segment is needed by both the orphan lookup and the next lookup
            segment_result = await db.execute(
                select(PipelineSegment).where(PipelineSegment.id == segment_id)
            )
            segment = segment_result.scalar_one_or_none()
            if not segment:
                logger.error(f"Segment {segment_id} not found")
                return None

            # 1c. What utterance N-1 holds behind this one. Reported on every call
            # so the FE can enable its lookback button without a second round trip.
            prev_geom = await _prev_orphan_geometry(db, segment, utterance_index)
            prev_transcript = prev_geom.transcript
            prev_available = prev_geom.orphan

            # Nothing behind to prepend — fall back to the canonical tape.
            if include_prev and prev_geom.reach <= 0.0:
                logger.info(
                    f"Lookback requested for {segment_id} utt {utterance_index} "
                    f"but nothing is reachable behind it; serving canonical tape"
                )
                include_prev = False

            # 2. Find the following utterances (same segment or later, same job).
            # Fetched before the cache check so every response — cached or not —
            # can tell the FE how much deeper the tape could still go.
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
                .limit(MAX_LOOKAHEAD)
            )
            following = [t for t in next_result.scalars().all() if t.video_path]
            lookahead_available = len(following)
            next_transcripts = following[:lookahead]
            has_next = bool(next_transcripts)

            # 3. Check if merged video already exists.
            # The cache holds the canonical [N | N+1] tape only — both the lookback
            # and the deeper-lookahead variants differ from it, so they bypass this.
            if curr_transcript.merged_video_path and not include_prev and lookahead == 1:
                try:
                    url = await minio_service.generate_presigned_url(
                        curr_transcript.merged_video_path, expiry=3600
                    )
                    logger.info(f"Returning existing merged video: {curr_transcript.merged_video_path}")
                    # head_offset reflects the CURRENT edit (start - floor); the cached
                    # tape itself starts at the floor, which only changes via the
                    # cascade (which clears this cache), so reading it fresh is safe.
                    _, head_offset = await _edit_front_geometry(
                        db, segment_id, utterance_index, curr_transcript.start
                    )
                    n_dur = curr_transcript.video_n_duration or 0.0
                    total_dur = curr_transcript.merged_video_duration or 0.0
                    return {
                        "merged_video_url": url,
                        "merged_video_path": curr_transcript.merged_video_path,
                        "video_n_duration": n_dur,
                        "total_duration": total_dur,
                        "head_offset": head_offset,
                        "prev_offset": 0.0,
                        "prev_orphan_offset": 0.0,
                        "prev_available": prev_available,
                        "prev_borrowable": prev_geom.borrowable,
                        "lookahead_used": 1 if has_next else 0,
                        "lookahead_available": lookahead_available,
                        "segment_durations": [n_dur, max(0.0, total_dur - n_dur)] if has_next else [n_dur],
                    }
                except Exception as e:
                    logger.warning(f"Failed to generate URL for existing merged video: {e}")
                    # Fall through to recreate

            # 4. No next utterance and nothing to prepend — the raw clip is the tape
            if not has_next and not include_prev:
                logger.info(f"No next utterance found for {segment_id} utt {utterance_index}, returning single video")
                curr_url = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)
                single_duration = curr_transcript.end - curr_transcript.start
                return {
                    "merged_video_url": curr_url,
                    "merged_video_path": curr_transcript.video_path,
                    "video_n_duration": 0.0,
                    "total_duration": single_duration,
                    "is_single_video": True,
                    "head_offset": 0.0,
                    "prev_offset": 0.0,
                    "prev_orphan_offset": 0.0,
                    "prev_available": prev_available,
                    "prev_borrowable": prev_geom.borrowable,
                    "lookahead_used": 0,
                    "lookahead_available": lookahead_available,
                    "segment_durations": [single_duration],
                }

            # 5. Download the clips this tape is built from.
            # Temp names carry a per-request nonce: get_video_duration caches by
            # path and never invalidates, so a fixed name would serve the previous
            # merge's duration after a re-trim changed the file underneath it.
            nonce = uuid.uuid4().hex[:8]
            base_tmp = f"{segment_id}_utt_{utterance_index}_{nonce}"
            curr_presigned = await minio_service.generate_presigned_url(curr_transcript.video_path, expiry=3600)

            tmp_dir = tempfile.gettempdir()
            curr_tmp = os.path.join(tmp_dir, f"{base_tmp}_curr.mp4")
            next_tmps = [
                os.path.join(tmp_dir, f"{base_tmp}_next{i}.mp4")
                for i in range(len(next_transcripts))
            ]
            prev_tmp = os.path.join(tmp_dir, f"{base_tmp}_prev.mp4")
            prev_tail_tmp = os.path.join(tmp_dir, f"{base_tmp}_prevtail.mp4")
            merged_tmp = os.path.join(tmp_dir, f"{base_tmp}_merged.mp4")

            try:
                await _download_file(curr_presigned, curr_tmp)
                for nt, nt_tmp in zip(next_transcripts, next_tmps):
                    next_presigned = await minio_service.generate_presigned_url(
                        nt.video_path, expiry=3600
                    )
                    await _download_file(next_presigned, nt_tmp)

                # ══════════════════════════════════════════════════════════
                # RESPONSIVE MERGE REGENERATION
                # The look-ahead merge is a continuous tape [Video N | Video N+1]
                # so the annotator can drag the trim boundary anywhere within it.
                # It must reflect the latest annotated state — but only for the
                # part this utterance OWNS, i.e. utterance N's own front.
                #
                # Crop ONLY the FLOOR off N's head — the region owned by the
                # PREVIOUS sentence (cascade). This stays hidden from N because it
                # is not N's to annotate. The annotator's OWN head trim-in
                # (head_offset = start - floor) is deliberately KEPT in the tape as
                # a recoverable gray region the FE renders before the start handle,
                # so an over-aggressive left trim-in can be dragged back.
                #
                # Do NOT apply the next utterance's front offset. When N trims out,
                # the cascade pushes N+1's floor forward by exactly the amount N
                # consumed from the head of Video N+1 — but that consumed head is
                # part of N's result and MUST stay visible in N's tape. The "N+1
                # head is gone" view is rendered correctly when N+1 is itself the
                # curr of its own merge (its floor crops Video N+1's head).
                # ══════════════════════════════════════════════════════════
                config = FFmpegConfig(video_preset="ultrafast")

                curr_floor_offset, head_offset = await _edit_front_geometry(
                    db, segment_id, utterance_index, curr_transcript.start
                )

                if curr_floor_offset > 0:
                    logger.info(f"Applying {curr_floor_offset:.2f}s floor offset to curr_tmp before merge")
                    tmp_cropped = curr_tmp + "_cropped.mp4"
                    ok = await run_ffmpeg_crop(
                        curr_tmp, tmp_cropped,
                        start_time=curr_floor_offset, end_time=9999,
                        use_input_seeking=False, config=config
                    )
                    if ok and os.path.exists(tmp_cropped):
                        os.remove(curr_tmp)
                        curr_tmp = tmp_cropped

                # ══════════════════════════════════════════════════════════
                # LOOKBACK PREPEND — what utterance N-1 holds behind this one.
                # Two regions, prepended as one continuous strip:
                #   [ borrowable (N-1 still owns) | orphan (N-1 released) | N … ]
                # CV2 tiles consecutive clips exactly, so both sit physically
                # adjacent to N's head. The orphan is free; reaching into the
                # borrowable part shortens N-1, which only happens when the
                # annotator actually drags there and is paid for by the crop
                # service — building the tape never modifies N-1.
                # ══════════════════════════════════════════════════════════
                prev_offset = 0.0
                prev_orphan_offset = 0.0
                if include_prev and prev_transcript is not None and prev_geom.reach > 0.0:
                    prev_presigned = await minio_service.generate_presigned_url(
                        prev_transcript.video_path, expiry=3600
                    )
                    await _download_file(prev_presigned, prev_tmp)

                    # Start of the strip inside N-1's own clip: back off the
                    # borrowable stretch from where N-1's annotated end sits.
                    # end_time=9999 runs to the physical end so a clip slightly
                    # longer than its nominal range is not truncated.
                    orphan_local_start = max(0.0, prev_geom.effective_end - prev_transcript.start)
                    strip_local_start = max(0.0, orphan_local_start - prev_geom.borrowable)
                    ok = await run_ffmpeg_crop(
                        prev_tmp, prev_tail_tmp,
                        start_time=strip_local_start, end_time=9999,
                        use_input_seeking=False, config=config
                    )
                    if ok and os.path.exists(prev_tail_tmp):
                        from app.pipeline.utils.video import get_video_duration
                        # Report the PHYSICAL strip length — the FE anchors the tape's
                        # left edge on it, so a nominal value would misplace the ruler.
                        prev_offset = await get_video_duration(prev_tail_tmp) or 0.0
                        # The free part is whatever of the strip lies past N-1's end;
                        # never more than the strip actually produced.
                        prev_orphan_offset = min(prev_geom.orphan, prev_offset)
                        logger.info(
                            f"Prepending {prev_offset:.2f}s from utt "
                            f"{prev_transcript.utterance_index} of segment "
                            f"{prev_transcript.segment_id} "
                            f"({prev_orphan_offset:.2f}s orphan + "
                            f"{max(0.0, prev_offset - prev_orphan_offset):.2f}s borrowable)"
                        )
                    else:
                        logger.warning("Failed to crop lookback strip; serving tape without lookback")

                # 6. Merge using FFmpeg
                concat_inputs = []
                if prev_offset > 0.0:
                    concat_inputs.append(prev_tail_tmp)
                concat_inputs.append(curr_tmp)
                concat_inputs.extend(next_tmps)

                # Lookback was requested but the tail could not be cut and there is
                # no N+1 either — the tape is just clip N. Fall back to the plain
                # single-video response instead of caching a one-clip "merge".
                if len(concat_inputs) == 1:
                    logger.warning(
                        f"Nothing to concat for {segment_id} utt {utterance_index}; "
                        f"returning single video"
                    )
                    curr_url = await minio_service.generate_presigned_url(
                        curr_transcript.video_path, expiry=3600
                    )
                    single_duration = curr_transcript.end - curr_transcript.start
                    return {
                        "merged_video_url": curr_url,
                        "merged_video_path": curr_transcript.video_path,
                        "video_n_duration": 0.0,
                        "total_duration": single_duration,
                        "is_single_video": True,
                        "head_offset": 0.0,
                        "prev_offset": 0.0,
                        "prev_orphan_offset": 0.0,
                        "prev_available": prev_available,
                        "prev_borrowable": prev_geom.borrowable,
                        "lookahead_used": 0,
                        "lookahead_available": lookahead_available,
                        "segment_durations": [single_duration],
                    }
                else:
                    success = await run_ffmpeg_concat(
                        input_paths=concat_inputs,
                        output_path=merged_tmp,
                        config=config
                    )
                    if not success or not os.path.exists(merged_tmp):
                        logger.error("FFmpeg concat failed for merge")
                        return None

                # 7. Upload merged video to MinIO.
                # Each tape shape lives under its own key: the lookback variant has
                # a different left edge and a deeper lookahead a different right one,
                # so neither may overwrite the canonical cached tape.
                lookahead_used = len(next_tmps)
                variant = f"{'_lb' if prev_offset > 0.0 else ''}{f'_la{lookahead_used}' if lookahead_used > 1 else ''}"
                merged_key = (
                    f"jobs/{job_id}/utterances_merged/"
                    f"{segment_id}_utt_{utterance_index}{variant}.mp4"
                )
                with open(merged_tmp, "rb") as f:
                    await minio_service.upload_file(f, merged_key)

                # 8. Calculate durations
                from app.pipeline.utils.video import get_video_duration
                curr_duration = await get_video_duration(curr_tmp)
                merged_duration = await get_video_duration(merged_tmp)
                # Per-clip lengths let the FE draw a boundary marker per joint
                # rather than assuming the single [N | N+1] seam.
                segment_durations = [curr_duration or 0.0]
                for nt_tmp in next_tmps:
                    segment_durations.append(await get_video_duration(nt_tmp) or 0.0)

                # 9. Update database — canonical tape only. Both variants are
                # regenerated per request, so persisting either would poison the
                # cache that the normal [N | N+1] view reads.
                if prev_offset <= 0.0 and lookahead_used <= 1:
                    curr_transcript.merged_video_path = merged_key
                    curr_transcript.merged_video_duration = merged_duration
                    curr_transcript.video_n_duration = curr_duration
                    await db.commit()

                # 10. Generate presigned URL
                merged_url = await minio_service.generate_presigned_url(merged_key, expiry=3600)

                logger.info(
                    f"Created merged video for {segment_id} utt {utterance_index}: "
                    f"duration={merged_duration:.2f}s, n_duration={curr_duration:.2f}s, "
                    f"prev_offset={prev_offset:.2f}s, lookahead={lookahead_used}"
                )

                return {
                    "merged_video_url": merged_url,
                    "merged_video_path": merged_key,
                    "video_n_duration": curr_duration,
                    "total_duration": merged_duration,
                    "is_single_video": False,
                    "head_offset": head_offset,
                    "prev_offset": prev_offset,
                    "prev_orphan_offset": prev_orphan_offset,
                    "prev_available": prev_available,
                    "prev_borrowable": prev_geom.borrowable,
                    "lookahead_used": lookahead_used,
                    "lookahead_available": lookahead_available,
                    "segment_durations": segment_durations,
                }

            finally:
                # Cleanup temp files
                for path in [curr_tmp, prev_tmp, prev_tail_tmp, merged_tmp, *next_tmps]:
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
        
        Uses per-segment batching with configurable concurrency:
        - Each segment = one batch (or sub-batches for large segments)
        - Process up to N segments concurrently (config: premerge_max_concurrent_segments)
        - Wait interval between waves (config: premerge_segment_interval_seconds)
        - Progress tracked in PipelineJob.premerge_* fields
        
        Args:
            job_id: The pipeline job ID
            
        Returns:
            dict with total, created, skipped, failed counts
        """
        logger.info(f"Starting pre-merge for job {job_id}")
        
        try:
            return await UtteranceMergeService._premerge_all_for_job_impl(job_id)
        except Exception as e:
            logger.exception(f"Pre-merge fatal error for job {job_id}: {e}")
            # Ensure status is FAILED even if the crash happened before RUNNING was set
            try:
                async with async_session_maker() as db:
                    from app.repositories.job_repository import JobRepository
                    job_repo = JobRepository(db)
                    await job_repo.update_premerge_progress(
                        job_id=job_id,
                        status="FAILED",
                        error=str(e),
                    )
                    await db.commit()
            except Exception as cleanup_err:
                logger.error(
                    f"Job {job_id} failed to write pre-merge failure status: {cleanup_err}"
                )
            raise

    @staticmethod
    async def _premerge_all_for_job_impl(job_id: uuid.UUID) -> dict:
        
        from app.repositories.job_repository import JobRepository
        
        # Config
        max_concurrent = settings.premerge_max_concurrent_segments
        interval_seconds = settings.premerge_segment_interval_seconds
        large_threshold = settings.premerge_large_segment_threshold
        subbatch_size = settings.premerge_large_segment_subbatch_size
        
        async with async_session_maker() as db:
            job_repo = JobRepository(db)
            
            # Initialize premerge status
            await job_repo.update_premerge_progress(
                job_id=job_id,
                status="RUNNING",
                total_pairs=0,
                completed_pairs=0,
                failed_pairs=0,
                batches=[],
                error=None,
            )
            await db.commit()
            
            # Fetch all segments with transcripts
            result = await db.execute(
                select(PipelineSegment)
                .where(PipelineSegment.job_id == job_id)
                .order_by(PipelineSegment.segment_index.asc())
            )
            segments = result.scalars().all()
            
            # Build batches: each segment = one or more batches
            # First pass: count pairs per segment to determine total_batches
            seg_batch_counts: Dict[int, int] = {}  # segment_index -> total_batches
            
            for seg in segments:
                seg_transcripts = await db.execute(
                    select(PipelineTranscript)
                    .where(PipelineTranscript.segment_id == seg.id)
                    .order_by(PipelineTranscript.utterance_index.asc())
                )
                transcripts = seg_transcripts.scalars().all()
                
                seg_pairs = []
                for i in range(len(transcripts)):
                    if i < len(transcripts) - 1:
                        seg_pairs.append({
                            "segment_id": str(transcripts[i].segment_id),
                            "utterance_index": transcripts[i].utterance_index,
                        })
                
                if seg_pairs:
                    if len(seg_pairs) > large_threshold:
                        seg_batch_counts[seg.segment_index] = max(1, (len(seg_pairs) + subbatch_size - 1) // subbatch_size)
                    else:
                        seg_batch_counts[seg.segment_index] = 1
                else:
                    seg_batch_counts[seg.segment_index] = 0
            
            # Second pass: build batch metadata
            batches: List[Dict[str, Any]] = []
            batch_index = 0
            total_pairs = 0
            
            for seg in segments:
                seg_transcripts = await db.execute(
                    select(PipelineTranscript)
                    .where(PipelineTranscript.segment_id == seg.id)
                    .order_by(PipelineTranscript.utterance_index.asc())
                )
                transcripts = seg_transcripts.scalars().all()
                
                seg_pairs = []
                for i in range(len(transcripts)):
                    if i < len(transcripts) - 1:
                        seg_pairs.append({
                            "segment_id": str(transcripts[i].segment_id),
                            "utterance_index": transcripts[i].utterance_index,
                        })
                
                total_seg_batches = seg_batch_counts.get(seg.segment_index, 0)
                
                if len(seg_pairs) > large_threshold:
                    sub_idx = 0
                    for start in range(0, len(seg_pairs), subbatch_size):
                        end = min(start + subbatch_size, len(seg_pairs))
                        sub_pairs = seg_pairs[start:end]
                        batches.append({
                            "segment_id": str(seg.id),
                            "segment_code": f"S{seg.segment_index + 1}",
                            "batch_index": sub_idx,
                            "total_batches": total_seg_batches,
                            "utterance_indices": [p["utterance_index"] for p in sub_pairs],
                            "status": "PENDING",
                            "pairs": sub_pairs,
                            "pairs_count": len(sub_pairs),
                            "merged_count": 0,
                            "failed_count": 0,
                            "error": None,
                            "started_at": None,
                            "completed_at": None,
                        })
                        total_pairs += len(sub_pairs)
                        batch_index += 1
                        sub_idx += 1
                else:
                    if seg_pairs:
                        batches.append({
                            "segment_id": str(seg.id),
                            "segment_code": f"S{seg.segment_index + 1}",
                            "batch_index": 0,
                            "total_batches": total_seg_batches,
                            "utterance_indices": [p["utterance_index"] for p in seg_pairs],
                            "status": "PENDING",
                            "pairs": seg_pairs,
                            "pairs_count": len(seg_pairs),
                            "merged_count": 0,
                            "failed_count": 0,
                            "error": None,
                            "started_at": None,
                            "completed_at": None,
                        })
                        total_pairs += len(seg_pairs)
                        batch_index += 1
            
            logger.info(
                f"Job {job_id}: {len(segments)} segments, {total_pairs} pairs, "
                f"{len(batches)} batches, max_concurrent={max_concurrent}"
            )
            
            # Save initial batch plan
            await job_repo.update_premerge_progress(
                job_id=job_id,
                status="RUNNING",
                total_pairs=total_pairs,
                completed_pairs=0,
                failed_pairs=0,
                batches=batches,
            )
            await db.commit()
        
        # Process batches with semaphore-controlled concurrency
        semaphore = asyncio.Semaphore(max_concurrent)
        completed_pairs = 0
        failed_pairs = 0
        progress_lock = asyncio.Lock()  # Guards counter updates + DB writes
        
        async def process_batch(batch: Dict[str, Any]) -> None:
            nonlocal completed_pairs, failed_pairs
            async with semaphore:
                batch["status"] = "RUNNING"
                batch["started_at"] = datetime.utcnow().isoformat()
                
                merged_count = 0
                failed_count = 0
                errors = []
                
                for pair in batch["pairs"]:
                    try:
                        result = await UtteranceMergeService.get_or_create_merged_video(
                            job_id=job_id,
                            segment_id=uuid.UUID(pair["segment_id"]),
                            utterance_index=pair["utterance_index"],
                        )
                        if result:
                            merged_count += 1
                        else:
                            failed_count += 1
                            errors.append(f"utt_{pair['utterance_index']}: returned None")
                    except Exception as e:
                        failed_count += 1
                        errors.append(f"utt_{pair['utterance_index']}: {str(e)}")
                        logger.warning(
                            f"Pre-merge failed for job {job_id} "
                            f"segment {batch['segment_code']} utt {pair['utterance_index']}: {e}"
                        )
                    
                    # Update batch-level counts after each pair (for live polling)
                    batch["merged_count"] = merged_count
                    batch["failed_count"] = failed_count
                    
                    # Write per-pair progress to DB under lock
                    async with progress_lock:
                        completed_pairs_snapshot = completed_pairs + merged_count
                        failed_pairs_snapshot = failed_pairs + failed_count
                        try:
                            async with async_session_maker() as pair_db:
                                pair_repo = JobRepository(pair_db)
                                await pair_repo.update_premerge_progress(
                                    job_id=job_id,
                                    status="RUNNING",
                                    total_pairs=total_pairs,
                                    completed_pairs=completed_pairs_snapshot,
                                    failed_pairs=failed_pairs_snapshot,
                                    batches=batches,
                                )
                                await pair_db.commit()
                        except Exception as db_err:
                            logger.warning(
                                f"Job {job_id} per-pair progress write failed (non-critical): {db_err}"
                            )
                
                batch["status"] = "COMPLETED" if failed_count == 0 else "FAILED"
                batch["completed_at"] = datetime.utcnow().isoformat()
                batch["merged_count"] = merged_count
                batch["failed_count"] = failed_count
                batch["error"] = "; ".join(errors) if errors else None
                
                # Finalize counters under lock
                async with progress_lock:
                    completed_pairs += merged_count
                    failed_pairs += failed_count
                    
                    try:
                        async with async_session_maker() as progress_db:
                            progress_repo = JobRepository(progress_db)
                            await progress_repo.update_premerge_progress(
                                job_id=job_id,
                                status="RUNNING",
                                total_pairs=total_pairs,
                                completed_pairs=completed_pairs,
                                failed_pairs=failed_pairs,
                                batches=batches,
                            )
                            await progress_db.commit()
                    except Exception as db_err:
                        logger.warning(
                            f"Job {job_id} batch-final progress write failed (non-critical): {db_err}"
                        )
                
                logger.info(
                    f"Job {job_id} batch {batch['batch_index']} (seg {batch['segment_code']}): "
                    f"{merged_count}/{batch['pairs_count']} done, {failed_count} failed"
                )
        
        try:
            # Process all batches with optional interval between waves
            if interval_seconds > 0:
                # Process in waves of max_concurrent batches
                for i in range(0, len(batches), max_concurrent):
                    wave = batches[i:i + max_concurrent]
                    await asyncio.gather(*[process_batch(b) for b in wave])
                    if i + max_concurrent < len(batches):
                        logger.info(
                            f"Job {job_id}: wave complete, sleeping {interval_seconds}s "
                            f"before next wave"
                        )
                        await asyncio.sleep(interval_seconds)
            else:
                # No interval — process all with semaphore limiting
                await asyncio.gather(*[process_batch(b) for b in batches])
            
            # Mark completed
            async with async_session_maker() as db:
                job_repo = JobRepository(db)
                final_status = "COMPLETED" if failed_pairs == 0 else "COMPLETED_WITH_ERRORS"
                await job_repo.update_premerge_progress(
                    job_id=job_id,
                    status=final_status,
                    total_pairs=total_pairs,
                    completed_pairs=completed_pairs,
                    failed_pairs=failed_pairs,
                    batches=batches,
                )
                await db.commit()
            
            logger.info(
                f"Pre-merge complete for job {job_id}: "
                f"{completed_pairs} merged, {failed_pairs} failed"
            )
            
            return {
                "job_id": str(job_id),
                "total_pairs": total_pairs,
                "completed": completed_pairs,
                "failed": failed_pairs,
                "batches": len(batches),
            }
            
        except Exception as e:
            logger.exception(f"Pre-merge crashed for job {job_id}: {e}")
            async with async_session_maker() as db:
                job_repo = JobRepository(db)
                await job_repo.update_premerge_progress(
                    job_id=job_id,
                    status="FAILED",
                    total_pairs=total_pairs,
                    completed_pairs=completed_pairs,
                    failed_pairs=failed_pairs,
                    batches=batches,
                    error=str(e),
                )
                await db.commit()
            raise


async def _edit_front_geometry(
    db,
    segment_id: uuid.UUID,
    utterance_index: int,
    transcript_start: float,
) -> tuple:
    """Front geometry of an utterance for the look-ahead merge, read from the
    latest annotation edit (the transcript stays immutable, so the working values
    live only in AnnotationEdit). Returns ``(floor_offset, head_offset)``:

    - ``floor_offset`` = seconds of the head OWNED BY THE PREVIOUS sentence
      (the cascade ``floor``), measured from the original transcript start. The
      merge physically crops this away so it stays hidden from this utterance.
    - ``head_offset`` = seconds the annotator trimmed off this utterance's OWN
      head (``start - floor``). KEPT in the tape as a recoverable gray region the
      FE renders before the start handle.

    Defaults to ``(0.0, 0.0)`` when there is no active edit (full tape, no gray).
    """
    result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    edit = result.scalars().first()
    if not edit or not edit.utterance_corrections:
        return 0.0, 0.0

    for utt in edit.utterance_corrections:
        if utt.get("utterance_index") == utterance_index:
            edit_start = utt.get("start", transcript_start)
            floor = utt.get("floor", transcript_start)
            floor_offset = max(0.0, floor - transcript_start)
            head_offset = max(0.0, edit_start - floor)
            return floor_offset, head_offset
    return 0.0, 0.0


async def _prev_orphan_geometry(
    db,
    segment: PipelineSegment,
    utterance_index: int,
) -> "PrevGeometry":
    """Geometry of the material behind utterance N, held by utterance N-1.

    Two distinct regions sit before N's own clip head, and they cost different
    things to take:

    ``orphan`` — ALREADY RELEASED, free to take.
        When the annotator shortens utterance N-1 (drags its end handle to the
        left), the region ``[new_end, prev_transcript.end]`` belongs to nobody:
        N-1 gave it up and N cannot reach it, because N's tape floor sits at N's
        own CV2 clip head. Since CV2 tiles consecutive clips exactly in the
        common case (``E_i = A_{i+1} + 1.0 = S_{i+1}``, see cropping_worker),
        that orphan sits physically adjacent to N's head. Taking it modifies
        nothing — N-1 already wrote it off.

    ``borrowable`` — STILL OWNED by N-1, costs a left cascade.
        Everything N-1 currently keeps, minus ``MIN_PREV_KEEP_SECONDS`` so N-1
        can never be reduced to nothing. Taking any of it must shorten N-1's own
        ``end`` and invalidate its crop, which is why the crop service treats it
        separately from the orphan.

    Returned as a NamedTuple so adding a region does not silently reshuffle
    positional unpacking at the two call sites.
    """
    prev_result = await db.execute(
        select(PipelineTranscript)
        .join(PipelineSegment, PipelineTranscript.segment_id == PipelineSegment.id)
        .where(PipelineSegment.job_id == segment.job_id)
        .where(
            (PipelineSegment.segment_index < segment.segment_index) |
            ((PipelineSegment.segment_index == segment.segment_index) &
             (PipelineTranscript.utterance_index < utterance_index))
        )
        .order_by(PipelineSegment.segment_index.desc(), PipelineTranscript.utterance_index.desc())
        .limit(1)
    )
    prev_transcript = prev_result.scalar_one_or_none()
    if not prev_transcript or not prev_transcript.video_path:
        return PrevGeometry(None, 0.0, 0.0, 0.0, 0.0, False)

    # The annotated start/end live in N-1's own AnnotationEdit, which may belong
    # to a different segment than N when N is the first utterance of its segment.
    prev_effective_start = prev_transcript.start
    prev_effective_end = prev_transcript.end
    prev_locked = False
    edit_result = await db.execute(
        select(AnnotationEdit).where(
            AnnotationEdit.segment_id == prev_transcript.segment_id,
            AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False
        ).order_by(AnnotationEdit.edited_at.desc())
    )
    prev_edit = edit_result.scalars().first()
    if prev_edit and prev_edit.utterance_corrections:
        for utt in prev_edit.utterance_corrections:
            if utt.get("utterance_index") == prev_transcript.utterance_index:
                prev_effective_end = utt.get("end", prev_transcript.end)
                # The floor is what the PREVIOUS-previous sentence consumed; N-1
                # only really owns what sits at or after it.
                prev_effective_start = max(
                    utt.get("floor", prev_transcript.start),
                    utt.get("start", prev_transcript.start),
                )
                prev_locked = utt.get("status") == "MERGED"
                break

    prev_duration = max(0.0, prev_transcript.end - prev_transcript.start)
    orphan = max(0.0, prev_transcript.end - prev_effective_end)
    orphan = min(orphan, prev_duration)

    # What N-1 still keeps, less the floor it must retain. A sentence already
    # swallowed by an earlier one (MERGED) has nothing left to lend.
    kept = max(0.0, prev_effective_end - prev_effective_start)
    borrowable = 0.0 if prev_locked else max(0.0, kept - MIN_PREV_KEEP_SECONDS)

    return PrevGeometry(
        prev_transcript, prev_effective_start, prev_effective_end,
        orphan, borrowable, prev_locked,
    )


async def _download_file(url: str, dest_path: str) -> None:
    """Download file from URL to local path using streaming to avoid OOM."""
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async with client.stream("GET", url, follow_redirects=True) as response:
            response.raise_for_status()
            with open(dest_path, "wb") as f:
                async for chunk in response.aiter_bytes(chunk_size=8192):
                    f.write(chunk)
