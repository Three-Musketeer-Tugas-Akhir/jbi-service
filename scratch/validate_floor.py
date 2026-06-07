"""Validate the floor / recoverable-gray-head feature on job 011ccdc5.

A. Own trim-in head: merge crops at FLOOR (not start) -> full tape kept,
   head_offset = start - floor returned.
B. Cascade pins floor idempotently while preserving the annotator's own delta
   across re-trims (larger / smaller / no-spill).
C. merge(utt1) hides the cascade floor (prev's consumed head) but keeps utt1's
   own trim-in head as head_offset.

Snapshots + restores the draft and transcript merge caches.
"""
import asyncio, os, tempfile, uuid
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.utterance_cropping_service import UtteranceCroppingService
from app.services.utterance_merge_service import UtteranceMergeService
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import get_video_duration

JOB = uuid.UUID("011ccdc5-f88b-4e06-bf3d-62ce41433b09")
SEG = uuid.UUID("1e62c53e-5aec-4938-a234-cc2e8c2c8f5b")
P, F = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
res = []
def chk(n, c, d=""):
    res.append(c); print(f"  [{P if c else F}] {n}{(' — '+d) if d else ''}")

async def clip_dur(minio, key):
    data = await minio.download_file(key); fd,p=tempfile.mkstemp(suffix=".mp4"); os.write(fd,data); os.close(fd)
    try: return await get_video_duration(p)
    finally: os.remove(p)

async def set_utts(edit_id, updates):
    """updates: {idx: {field:val,...}}; setting a field to None deletes the key."""
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        corr = [dict(u) for u in edit.utterance_corrections]
        for u in corr:
            up = updates.get(u["utterance_index"])
            if up:
                for k, v in up.items():
                    if v is None: u.pop(k, None)
                    else: u[k] = v
        edit.utterance_corrections = corr; flag_modified(edit,"utterance_corrections")
        await db.commit()

async def clear_merge(*idxs):
    async with async_session_maker() as db:
        for i in idxs:
            t = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==i))).scalar_one()
            t.merged_video_path=None; t.merged_video_duration=None; t.video_n_duration=None
        await db.commit()

async def get_utt(edit_id, idx):
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        return next(u for u in edit.utterance_corrections if u["utterance_index"]==idx)

async def main():
    minio = get_minio_service()
    v1 = await clip_dur(minio, f"jobs/{JOB}/utterances/{SEG}_utt_0.mp4")
    v2 = await clip_dur(minio, f"jobs/{JOB}/utterances/{SEG}_utt_1.mp4")
    print(f"\nclips: V1={v1:.2f}s V2={v2:.2f}s")
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id==SEG, AnnotationEdit.status.in_(["DRAFT","PENDING"]),
            AnnotationEdit.is_deleted==False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()
        edit_id = edit.id
        ts = {i:(await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==i))).scalar_one() for i in (0,1,2)}
        snap_corr = [dict(u) for u in edit.utterance_corrections]
        snap_casc = edit.cascade_info
        snap_m = {i:(ts[i].merged_video_path, ts[i].merged_video_duration, ts[i].video_n_duration) for i in (0,1,2)}
    base1 = ts[1].start

    print("\nA. Own trim-in head stays in the tape (merge crops at FLOOR, not start)")
    await set_utts(edit_id, {0: {"start":2.0, "floor":None, "status":"DRAFT"}})  # floor absent => 0
    await clear_merge(0,1)
    m0 = await UtteranceMergeService.get_or_create_merged_video(JOB, SEG, 0)
    chk("head_offset == own trim-in (start-floor=2.0)", abs(m0.get("head_offset",0)-2.0)<0.15, f"{m0.get('head_offset',0):.2f}")
    chk("tape keeps FULL Video1 (video_n≈V1, head NOT cropped)", abs(m0["video_n_duration"]-v1)<0.6, f"{m0['video_n_duration']:.2f} vs {v1:.2f}")
    chk("total ≈ V1+V2 (full tape)", abs(m0["total_duration"]-(v1+v2))<0.8, f"{m0['total_duration']:.2f} vs {v1+v2:.2f}")

    print("\nB. Cascade pins floor idempotently AND preserves annotator's own delta (0.5s)")
    await set_utts(edit_id, {1: {"floor":base1, "start":base1+0.5, "end":23.8, "status":"DRAFT", "cropped_video_path":None}})
    for label, end, exp_overlap in [("trim-out 2.0", v1+2.0, 2.0), ("re-trim 1.0", v1+1.0, 1.0), ("no-spill", v1-0.9, 0.0)]:
        await set_utts(edit_id, {0:{"start":0.0,"end":end,"status":"DRAFT"}})
        await UtteranceCroppingService.crop_and_upload(segment_id=SEG, utterance_index=0, start_time=0.0, end_time=end, edit_id=edit_id)
        u1 = await get_utt(edit_id, 1)
        exp_floor = base1 + exp_overlap
        ok = abs(u1.get("floor", base1)-exp_floor)<0.06 and abs(u1.get("start")-(exp_floor+0.5))<0.06
        chk(f"{label}: floor={u1.get('floor',base1):.2f}(exp {exp_floor:.2f}), start={u1.get('start'):.2f}(exp {exp_floor+0.5:.2f}) delta kept", ok)

    print("\nC. merge(utt1) hides cascade floor (prev's head) but keeps utt1's own head")
    await set_utts(edit_id, {1: {"floor":base1+2.0, "start":base1+2.0+0.5, "end":23.8}})  # floor 15.7, own +0.5
    await clear_merge(1,2)
    m1 = await UtteranceMergeService.get_or_create_merged_video(JOB, SEG, 1)
    chk("floor head HIDDEN (video_n≈V2-2.0)", abs(m1["video_n_duration"]-(v2-2.0))<0.6, f"{m1['video_n_duration']:.2f} vs {v2-2.0:.2f}")
    chk("own head KEPT (head_offset≈0.5)", abs(m1.get("head_offset",0)-0.5)<0.15, f"{m1.get('head_offset',0):.2f}")

    # restore
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        edit.utterance_corrections = snap_corr; flag_modified(edit,"utterance_corrections")
        edit.cascade_info = snap_casc; flag_modified(edit,"cascade_info")
        for i in (0,1,2):
            t = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==i))).scalar_one()
            t.merged_video_path, t.merged_video_duration, t.video_n_duration = snap_m[i]
        await db.commit()
    print("\nDB restored to snapshot.")
    print(f"\n==== {sum(res)}/{len(res)} checks passed ====")

asyncio.run(main())
