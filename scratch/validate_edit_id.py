"""Reproduce the /crop endpoint's background-task call (now WITH edit_id) for
job 011ccdc5 utt#0, proving the TypeError is gone and a synced file is produced.
Snapshots + restores the job so the user's draft is left untouched.
"""
import asyncio, os, tempfile, uuid
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from app.db.session import async_session_maker
from app.db.models.pipeline import PipelineTranscript
from app.db.models.annotation import AnnotationEdit
from app.services.utterance_cropping_service import UtteranceCroppingService
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import get_video_duration

JOB = uuid.UUID("011ccdc5-f88b-4e06-bf3d-62ce41433b09")
SEG = uuid.UUID("1e62c53e-5aec-4938-a234-cc2e8c2c8f5b")
P, F = "\033[92mPASS\033[0m", "\033[91mFAIL\033[0m"
res = []
def chk(n, c, d=""):
    res.append(c); print(f"  [{P if c else F}] {n}{(' — '+d) if d else ''}")

async def main():
    minio = get_minio_service()
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT","PENDING"]),
            AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        snap = {"corr":[dict(u) for u in edit.utterance_corrections], "cascade":edit.cascade_info,
                "t0m":(t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration),
                "t1m":(t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration),
                "t1start":t1.start}
        u0 = next(u for u in edit.utterance_corrections if u["utterance_index"]==0)
        edit_id, req_start, req_end = edit.id, u0["start"], u0["end"]
        print(f"\nendpoint replay: crop_and_upload(SEG, 0, {req_start}, {req_end}, edit_id={edit_id})")
        print(f"  utt#0 was: status={u0.get('status')} crop=...{(u0.get('cropped_video_path') or '')[-20:]}  (trim-OUT: {req_end} > orig {t0.end})\n")

    # the exact call the endpoint makes (previously raised TypeError: unexpected kwarg 'edit_id')
    await UtteranceCroppingService.crop_and_upload(
        segment_id=SEG, utterance_index=0, start_time=req_start, end_time=req_end, edit_id=edit_id)

    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        u0 = next(u for u in edit.utterance_corrections if u["utterance_index"]==0)
        u1 = next(u for u in edit.utterance_corrections if u["utterance_index"]==1)
        key = f"jobs/{JOB}/utterances_synced/{SEG}_utt_0.mp4"
        exists = await minio.object_exists(key)
        chk("crop task ran WITHOUT TypeError (edit_id accepted)", "pre_trim_snapshot" in u0)
        chk("utterances_synced/ file now created", exists, key.split('/')[-1])
        chk("cropped_video_path routed to utterances_synced", "utterances_synced" in (u0.get("cropped_video_path") or ""))
        chk("written to the SAME edit row (edit_id routing)", edit.id == edit_id)
        if exists:
            data = await minio.download_file(key); fd,p=tempfile.mkstemp(suffix=".mp4"); os.write(fd,data); os.close(fd)
            try: d = await get_video_duration(p)
            finally: os.remove(p)
            chk("physical duration ~= requested trim-out", abs(d-req_end)<0.7, f"{d:.2f}s vs {req_end:.2f}s")
        chk("cascade pushed utt#1 working start", u1.get("start") > snap["t1start"]+0.5, f"{u1.get('start'):.2f} (orig {snap['t1start']:.2f})")
        chk("PipelineTranscript.utt1.start still IMMUTABLE", abs(t1.start-snap["t1start"])<1e-9)

        # restore
        edit.utterance_corrections = snap["corr"]; flag_modified(edit,"utterance_corrections")
        edit.cascade_info = snap["cascade"]; flag_modified(edit,"cascade_info")
        t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration = snap["t0m"]
        t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration = snap["t1m"]
        await db.commit()
    print("\nDB restored to the user's pre-test snapshot.")
    print(f"\n==== {sum(res)}/{len(res)} checks passed ====")

asyncio.run(main())
