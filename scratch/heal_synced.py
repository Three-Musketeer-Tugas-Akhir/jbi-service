"""Regenerate utterances_synced/utt_0.mp4 to match the user's draft utt0 = [0, 8.81]
(V1 full + 0.89s head of V2). Pure object fix — no DB writes, no cascade.
"""
import asyncio, os, uuid
from app.services.minio_service import get_minio_service
from app.pipeline.utils.video import run_ffmpeg_crop, run_ffmpeg_concat, get_video_duration, FFmpegConfig

JOB = "011ccdc5-f88b-4e06-bf3d-62ce41433b09"
SEG = "1e62c53e-5aec-4938-a234-cc2e8c2c8f5b"
END = 8.81

async def main():
    minio = get_minio_service()
    v1k = f"jobs/{JOB}/utterances/{SEG}_utt_0.mp4"
    v2k = f"jobs/{JOB}/utterances/{SEG}_utt_1.mp4"
    synced = f"jobs/{JOB}/utterances_synced/{SEG}_utt_0.mp4"
    u1 = await minio.generate_presigned_url(v1k, expiry=3600)
    u2 = await minio.generate_presigned_url(v2k, expiry=3600)
    cfg = FFmpegConfig(video_preset="ultrafast")
    import httpx
    async def dl(url, p):
        async with httpx.AsyncClient(timeout=120) as c:
            async with c.stream("GET", url, follow_redirects=True) as r:
                r.raise_for_status()
                with open(p,"wb") as f:
                    async for ch in r.aiter_bytes(8192): f.write(ch)
    a="/tmp/h_v1.mp4"; b="/tmp/h_v2.mp4"; pb="/tmp/h_pb.mp4"; out="/tmp/h_out.mp4"
    await dl(u1,a); await dl(u2,b)
    v1d = await get_video_duration(a)
    overlap = max(0.0, END - v1d)
    await run_ffmpeg_crop(b, pb, start_time=0.0, end_time=overlap, use_input_seeking=False, config=cfg)
    await run_ffmpeg_concat(input_paths=[a, pb], output_path=out, config=cfg)
    d = await get_video_duration(out)
    with open(out,"rb") as f:
        await minio.upload_file(f, synced)
    print(f"healed {synced}: V1={v1d:.2f}+{overlap:.2f} -> {d:.2f}s (target {END})")
    for p in (a,b,pb,out):
        try: os.remove(p)
        except OSError: pass

asyncio.run(main())
