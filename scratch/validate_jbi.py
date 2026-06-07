"""End-to-end validation for the restored JBI annotation fixes.

Exercises, against the live test job:
  1. Trim-Out on utt0 -> physical file in utterances_synced/ (Trim Out -> new file)
  2. Cascade pushes utt1's WORKING start, leaves PipelineTranscript.start IMMUTABLE
  3. Responsive merge regeneration: opening utt1's merge applies the cascaded
     front offset and shrinks the merged duration accordingly.

Snapshots and restores the DB rows it touches. Leaves regenerable MinIO objects.
"""
import asyncio
import os
import tempfile
import uuid

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.utterance_cropping_service import UtteranceCroppingService
from app.services.utterance_merge_service import UtteranceMergeService
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import get_video_duration

JOB = uuid.UUID("ef725e85-0846-4bc5-b712-d7c71d30558f")
SEG = uuid.UUID("89631678-d720-405a-96dc-660b8e93ffe9")

PASS, FAIL = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
results = []
def check(name, cond, detail=""):
    results.append(cond)
    print(f"  [{PASS if cond else FAIL}] {name}{(' — ' + detail) if detail else ''}")

async def minio_duration(key):
    minio = get_minio_service()
    data = await minio.download_file(key)
    fd, p = tempfile.mkstemp(suffix=".mp4"); os.write(fd, data); os.close(fd)
    try:
        return await get_video_duration(p)
    finally:
        os.remove(p)

async def main():
    minio = get_minio_service()
    async with async_session_maker() as db:
        # ---- snapshot ----
        t0 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 1))).scalar_one()
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()

        snap = {
            "edit_corr": [dict(u) for u in edit.utterance_corrections],
            "edit_cascade": edit.cascade_info,
            "t0_merged": (t0.merged_video_path, t0.merged_video_duration, t0.video_n_duration),
            "t1_merged": (t1.merged_video_path, t1.merged_video_duration, t1.video_n_duration),
            "t1_start": t1.start,
        }
        t0_orig_dur, t1_orig_dur = (t0.end - t0.start), (t1.end - t1.start)
        print(f"\nORIGINAL transcript (immutable truth): "
              f"utt0[start={t0.start} end={t0.end} dur={t0_orig_dur:.3f}]  "
              f"utt1[start={t1.start} end={t1.end} dur={t1_orig_dur:.3f}]")

        # ---- arrange: simulate FE saveDraft of a TRIM-OUT on utt0 ----
        # request end = 9.92s -> requested 9.92 > utt0 video 7.92 -> overlap ~2.0s from utt1
        REQ_END = round(t0_orig_dur + 2.0, 3)
        EXP_OVERLAP = REQ_END - t0_orig_dur
        corr = [dict(u) for u in edit.utterance_corrections]
        for u in corr:
            if u["utterance_index"] == 0:
                u.update(start=0.0, end=REQ_END, status="DRAFT", cropped_video_path=None)
        edit.utterance_corrections = corr
        flag_modified(edit, "utterance_corrections")
        await db.commit()
        print(f"\nARRANGE: trim-OUT utt0 -> request [0, {REQ_END}] (expect overlap {EXP_OVERLAP:.2f}s into utt1)\n")

    # ---- act: physical crop (the real background task) ----
    await UtteranceCroppingService.crop_and_upload(
        segment_id=SEG, utterance_index=0, start_time=0.0, end_time=REQ_END)

    # ---- assert ----
    async with async_session_maker() as db:
        t0 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 1))).scalar_one()
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()
        u0 = next(u for u in edit.utterance_corrections if u["utterance_index"] == 0)
        u1 = next(u for u in edit.utterance_corrections if u["utterance_index"] == 1)

        print("REQ 1 — Trim-Out produces a NEW physical file")
        synced_key = f"jobs/{JOB}/utterances_synced/{SEG}_utt_0.mp4"
        exists = await minio.object_exists(synced_key)
        check("new file written to utterances_synced/", exists, synced_key.split('/')[-1])
        check("edit.utt0.cropped_video_path -> utterances_synced", "utterances_synced" in (u0.get("cropped_video_path") or ""), u0.get("cropped_video_path","").split("/")[-1])
        check("edit.utt0.status == OK", u0.get("status") == "OK")
        if exists:
            d = await minio_duration(synced_key)
            check("physical duration ~= requested (video0 + overlap of video1)", abs(d - REQ_END) < 0.6, f"{d:.3f}s vs {REQ_END}s")

        print("\nREQ — original folder is IMMUTABLE")
        check("PipelineTranscript.utt1.start UNCHANGED", abs(t1.start - snap["t1_start"]) < 1e-9, f"{t1.start} (was {snap['t1_start']})")
        orig_obj = await minio.object_exists(f"jobs/{JOB}/utterances/{SEG}_utt_1.mp4")
        check("original utterances/ clip untouched/present", orig_obj)

        print("\nREQ 2 — Cascading update onto Kalimat 2 (utt1) working state")
        exp_new_start = snap["t1_start"] + EXP_OVERLAP
        check("edit.utt1.start pushed forward by overlap", abs(u1.get("start") - exp_new_start) < 0.05, f"{u1.get('start'):.3f} (expected {exp_new_start:.3f})")
        check("edit.utt1.cropped_video_path cleared", u1.get("cropped_video_path") in (None, ""))
        check("utt0 own merge cache cleared", t0.merged_video_path is None)
        check("utt1 merge cache cleared (will regen)", t1.merged_video_path is None)
        cascade_hist = (edit.cascade_info or {}).get("history", [])
        check("cascade audit trail recorded", any(h.get("action") == "trim_crop" for h in cascade_hist))

    print("\nREQ 3 — Responsive merge regeneration for Kalimat 2 (utt1)")
    merged = await UtteranceMergeService.get_or_create_merged_video(job_id=JOB, segment_id=SEG, utterance_index=1)
    check("merge endpoint returns a video", bool(merged and merged.get("merged_video_path")))
    if merged:
        exp_n = t1_orig_dur - EXP_OVERLAP          # utt1 clip minus consumed head
        async with async_session_maker() as db:
            t2 = (await db.execute(select(PipelineTranscript).where(
                PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 2))).scalar_one()
        exp_total = exp_n + (t2.end - t2.start)
        vn, tot = merged.get("video_n_duration", 0), merged.get("total_duration", 0)
        print(f"    regenerated: video_n_duration={vn:.3f}s (expect ~{exp_n:.3f}), total={tot:.3f}s (expect ~{exp_total:.3f})")
        check("merged video_n reflects cascaded front-trim of utt1", abs(vn - exp_n) < 0.6, f"{vn:.3f} vs {exp_n:.3f}")
        check("merged total shrank by the consumed head", abs(tot - exp_total) < 0.8, f"{tot:.3f} vs {exp_total:.3f}")

    # ---- restore DB to snapshot ----
    async with async_session_maker() as db:
        t0 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(
            PipelineTranscript.segment_id == SEG, PipelineTranscript.utterance_index == 1))).scalar_one()
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT", "PENDING"]),
            AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()
        edit.utterance_corrections = snap["edit_corr"]; flag_modified(edit, "utterance_corrections")
        edit.cascade_info = snap["edit_cascade"]; flag_modified(edit, "cascade_info")
        t0.merged_video_path, t0.merged_video_duration, t0.video_n_duration = snap["t0_merged"]
        t1.merged_video_path, t1.merged_video_duration, t1.video_n_duration = snap["t1_merged"]
        await db.commit()
    print("\nDB restored to pre-validation snapshot.")
    print(f"\n==== {sum(results)}/{len(results)} checks passed ====")

asyncio.run(main())
