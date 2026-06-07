"""Validate idempotent (REPLACE) cascade on job ef725e85.

Runs three crops of utt#0 in SEQUENCE (no manual reset of utt#1 between them)
and checks utt#1's working start tracks utt#0's CURRENT overlap each time:
  1. trim-out large  (end 9.92, overlap ~2.0) -> utt1.start = base + 2.0
  2. trim-out smaller(end 8.92, overlap ~1.0) -> utt1.start = base + 1.0  (REPLACE, not max)
  3. no spill        (end 7.00, fits)         -> utt1.start = base        (RESET)
Snapshots + restores the draft + transcript merge caches.
"""
import asyncio, uuid
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.utterance_cropping_service import UtteranceCroppingService

SEG = uuid.UUID("1e62c53e-5aec-4938-a234-cc2e8c2c8f5b")
P, F = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
res = []
def chk(n, c, d=""):
    res.append(c); print(f"  [{P if c else F}] {n}{(' — '+d) if d else ''}")

async def get_edit(db):
    return (await db.execute(select(AnnotationEdit).where(
        AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT","PENDING"]),
        AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()

async def set_utt0_end(edit_id, end):
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        corr = [dict(u) for u in edit.utterance_corrections]
        for u in corr:
            if u["utterance_index"] == 0:
                u.update(start=0.0, end=end, status="DRAFT")
        edit.utterance_corrections = corr; flag_modified(edit,"utterance_corrections")
        await db.commit()

async def utt1_start(edit_id):
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        u1 = next(u for u in edit.utterance_corrections if u["utterance_index"]==1)
        return u1.get("start"), u1.get("status"), u1.get("cropped_video_path")

async def main():
    async with async_session_maker() as db:
        edit = await get_edit(db)
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        edit_id = edit.id
        base = t1.start
        snap = {"corr":[dict(u) for u in edit.utterance_corrections], "cascade":edit.cascade_info,
                "t0m":(t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration),
                "t1m":(t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration)}
    print(f"\nutt#1 immutable base start = {base:.2f}  (orig utt#0 dur = {t0.end-t0.start:.2f}s)\n")

    cases = [("trim-out LARGE",  9.92, base + 2.0),
             ("trim-out SMALLER",8.92, base + 1.0),
             ("NO spill (reset)",7.00, base)]
    for label, end, expected in cases:
        await set_utt0_end(edit_id, end)
        await UtteranceCroppingService.crop_and_upload(segment_id=SEG, utterance_index=0,
            start_time=0.0, end_time=end, edit_id=edit_id)
        s, st, crop = await utt1_start(edit_id)
        print(f"{label}: utt0.end={end} -> utt1.start={s:.2f} (expect {expected:.2f})")
        chk(f"{label}: utt1.start tracks current overlap", abs(s-expected) < 0.05, f"{s:.2f} vs {expected:.2f}")
        if abs(s-base) > 0.05:
            chk(f"{label}: utt1 crop invalidated when shifted", crop in (None,""))

    # restore
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        edit.utterance_corrections = snap["corr"]; flag_modified(edit,"utterance_corrections")
        edit.cascade_info = snap["cascade"]; flag_modified(edit,"cascade_info")
        t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration = snap["t0m"]
        t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration = snap["t1m"]
        await db.commit()
    print("\nDB restored to snapshot.")
    print(f"\n==== {sum(res)}/{len(res)} checks passed ====")

asyncio.run(main())
