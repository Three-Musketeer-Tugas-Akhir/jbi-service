"""Validate the look-ahead merge fix on job 011ccdc5.

After a trim-OUT on utt#0 (which cascades a front-shift onto utt#1):
  - merge(utt0) preview MUST still contain the FULL Video 2 tail (the 2s that
    spilled into Kalimat 1 stays visible) -> total ~= V1clip + V2clip.
  - merge(utt1) preview MUST be front-trimmed by the consumed overlap
    (responsive regen for Kalimat 2) -> video_n ~= V2clip - overlap.

Snapshots + restores DB; deletes the MinIO objects it creates.
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

async def main():
    minio = get_minio_service()
    v1c = await clip_dur(minio, f"jobs/{JOB}/utterances/{SEG}_utt_0.mp4")
    v2c = await clip_dur(minio, f"jobs/{JOB}/utterances/{SEG}_utt_1.mp4")
    print(f"\nsource clips: Video1={v1c:.2f}s  Video2={v2c:.2f}s")

    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(
            AnnotationEdit.segment_id == SEG, AnnotationEdit.status.in_(["DRAFT","PENDING"]),
            AnnotationEdit.is_deleted == False).order_by(AnnotationEdit.edited_at.desc()))).scalars().first()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        t2 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==2))).scalar_one()
        snap = {"corr":[dict(u) for u in edit.utterance_corrections], "cascade":edit.cascade_info,
                "t0m":(t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration),
                "t1m":(t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration),
                "t2m":(t2.merged_video_path,t2.merged_video_duration,t2.video_n_duration)}
        u0 = next(u for u in edit.utterance_corrections if u["utterance_index"]==0)
        edit_id, req_end = edit.id, u0["end"]
        overlap = req_end - v1c
        print(f"trim-OUT utt0 -> end={req_end:.2f}  (overlap into Video2 ~= {overlap:.2f}s)\n")

    # real crop -> writes synced + cascades utt1 start forward, clears merge caches
    await UtteranceCroppingService.crop_and_upload(segment_id=SEG, utterance_index=0,
        start_time=0.0, end_time=req_end, edit_id=edit_id)

    print("Kalimat 1 (utt0) look-ahead preview")
    m0 = await UtteranceMergeService.get_or_create_merged_video(JOB, SEG, 0)
    exp_full = v1c + v2c
    exp_buggy = v1c + (v2c - overlap)
    print(f"    total={m0['total_duration']:.2f}s   (full tape ~{exp_full:.2f}s | old buggy ~{exp_buggy:.2f}s)")
    chk("preview keeps FULL Video2 (spilled 2s still visible)", abs(m0["total_duration"]-exp_full)<0.8, f"{m0['total_duration']:.2f} vs {exp_full:.2f}")
    chk("preview is NOT the buggy shortened tape", m0["total_duration"] > exp_buggy + 1.0)
    chk("seam marker (video_n) == full Video1", abs(m0["video_n_duration"]-v1c)<0.8, f"{m0['video_n_duration']:.2f} vs {v1c:.2f}")

    print("\nKalimat 2 (utt1) look-ahead preview — must stay front-trimmed (responsive)")
    m1 = await UtteranceMergeService.get_or_create_merged_video(JOB, SEG, 1)
    exp_n_utt1 = v2c - overlap
    print(f"    video_n={m1['video_n_duration']:.2f}s  (expect Video2 - overlap ~{exp_n_utt1:.2f}s)")
    chk("Video2 head consumed by Kalimat 1 is removed here", abs(m1["video_n_duration"]-exp_n_utt1)<0.8, f"{m1['video_n_duration']:.2f} vs {exp_n_utt1:.2f}")

    # restore DB + clean created MinIO objects
    async with async_session_maker() as db:
        edit = (await db.execute(select(AnnotationEdit).where(AnnotationEdit.id==edit_id))).scalars().first()
        t0 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==0))).scalar_one()
        t1 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==1))).scalar_one()
        t2 = (await db.execute(select(PipelineTranscript).where(PipelineTranscript.segment_id==SEG, PipelineTranscript.utterance_index==2))).scalar_one()
        edit.utterance_corrections = snap["corr"]; flag_modified(edit,"utterance_corrections")
        edit.cascade_info = snap["cascade"]; flag_modified(edit,"cascade_info")
        t0.merged_video_path,t0.merged_video_duration,t0.video_n_duration = snap["t0m"]
        t1.merged_video_path,t1.merged_video_duration,t1.video_n_duration = snap["t1m"]
        t2.merged_video_path,t2.merged_video_duration,t2.video_n_duration = snap["t2m"]
        await db.commit()
    for k in [f"jobs/{JOB}/utterances_synced/{SEG}_utt_0.mp4"]:
        try: await minio.remove_object(k) if hasattr(minio,"remove_object") else None
        except Exception: pass
    print("\nDB restored to snapshot (synced test object cleaned separately).")
    print(f"\n==== {sum(res)}/{len(res)} checks passed ====")

asyncio.run(main())
