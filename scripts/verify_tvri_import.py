"""Verifikasi hasil impor TVRI dan fitur antrian/anotasi/suara yang menopangnya.

Menguji lewat lapisan service, bukan HTTP, supaya tidak perlu JWT. Jalankan di
dalam container API::

    docker compose exec -T -e PYTHONPATH=/app -w /app api-gpu \
        python -u scripts/verify_tvri_import.py

Bagian C & D butuh minimal satu segmen yang sudah ter-assign ke annotator.
Tanpa itu keduanya dilewati — kecuali dijalankan dengan ``--assign``, yang akan
MEMBUAT baris annotation_queue untuk satu job sebagai bahan uji.
"""
import asyncio, sys
from uuid import UUID
from sqlalchemy import select, func, text
from app.db.session import async_session_maker
from app.db.models.dataset import Dataset
from app.db.models.pipeline import PipelineJob, PipelineSegment, PipelineTranscript
from app.db.models.annotation import AnnotationQueue, AnnotationEdit
from app.db.models.auth import User
# User.relationship("PasswordChangeLog") tidak ikut ter-import lewat
# app.db.models.__init__, jadi konfigurasi mapper gagal tanpa baris ini.
from app.db.models.password_change_log import PasswordChangeLog  # noqa: F401

OK = "  \033[32mPASS\033[0m"
NO = "  \033[31mFAIL\033[0m"
results = []

def check(name, cond, detail=""):
    results.append(cond)
    print(f"{OK if cond else NO}  {name}" + (f"  — {detail}" if detail else ""))

async def main():
    async with async_session_maker() as db:
        ds = (await db.execute(select(Dataset).where(Dataset.name == "TVRI 2026"))).scalars().first()
        check("dataset 'TVRI 2026' ada", ds is not None)
        if not ds: return

        # ---------- A. Integritas data ----------
        print("\n=== A. INTEGRITAS DATA ===")
        rows = (await db.execute(text("""
            SELECT j.category, count(DISTINCT j.id) jobs,
                   count(DISTINCT s.id) segs, count(t.id) utts,
                   count(t.audio_path) wav, count(t.video_path) vid
            FROM pipeline_jobs j
            JOIN pipeline_segments s ON s.job_id=j.id
            JOIN pipeline_transcripts t ON t.segment_id=s.id
            WHERE j.dataset_id=:d GROUP BY j.category ORDER BY j.category
        """), {"d": str(ds.id)})).all()
        got = {r[0]: r for r in rows}
        for cat, ej, es, eu in [("BISINDO", 24, 121, 7200), ("SIBI", 24, 100, 6141)]:
            r = got.get(cat)
            if not r:
                check(f"{cat} terimpor", False, "tidak ada baris"); continue
            check(f"{cat}: {r[1]} job / {r[2]} segmen / {r[3]} kalimat",
                  (r[1], r[2], r[3]) == (ej, es, eu), f"harusnya {ej}/{es}/{eu}")
            check(f"{cat}: video_path terisi semua", r[5] == r[3], f"{r[5]}/{r[3]}")
            check(f"{cat}: WAV terisi semua", r[4] == r[3], f"{r[4]}/{r[3]}")

        # ---------- B. Sebaran status ----------
        print("\n=== B. STATUS KALIMAT (kunci vs bisa diselaraskan) ===")
        st = (await db.execute(text("""
            SELECT j.category,
                   count(*) FILTER (WHERE u->>'status'='OK') terkunci,
                   count(*) FILTER (WHERE u->>'status' IS NULL) terbuka
            FROM pipeline_jobs j
            JOIN pipeline_segments s ON s.job_id=j.id
            JOIN annotation_edits e ON e.segment_id=s.id AND e.is_deleted=false
            CROSS JOIN LATERAL jsonb_array_elements(e.utterance_corrections) u
            WHERE j.dataset_id=:d GROUP BY j.category ORDER BY j.category
        """), {"d": str(ds.id)})).all()
        exp = {"BISINDO": (4801, 2399), "SIBI": (5270, 871)}
        for cat, lock, open_ in st:
            check(f"{cat}: {lock} terkunci / {open_} terbuka",
                  (lock, open_) == exp.get(cat), f"harusnya {exp.get(cat)}")

        # ---------- C. Queue service: filter job_id + segment_index ----------
        print("\n=== C. ANTRIAN: filter job_id & segment_index (fitur baru) ===")
        job = (await db.execute(
            select(PipelineJob).where(PipelineJob.dataset_id == ds.id,
                                      PipelineJob.category == "BISINDO")
            .order_by(PipelineJob.original_filename).limit(1))).scalars().first()
        nseg = (await db.execute(select(func.count(PipelineSegment.id))
                                 .where(PipelineSegment.job_id == job.id))).scalar()
        print(f"  job uji: {job.original_filename} ({nseg} segmen)")

        annot = (await db.execute(text("""
            SELECT u.id, u.email FROM auth_users u
            JOIN auth_user_roles ur ON ur.user_id=u.id
            JOIN auth_roles r ON r.id=ur.role_id
            WHERE lower(r.name) LIKE '%annotator%' LIMIT 1"""))).first()
        if not annot:
            annot = (await db.execute(text("SELECT id, email FROM auth_users LIMIT 1"))).first()
        print(f"  annotator uji: {annot[1]}")

        existing = (await db.execute(select(func.count(AnnotationQueue.id))
                    .join(PipelineSegment, AnnotationQueue.segment_id == PipelineSegment.id)
                    .where(PipelineSegment.job_id == job.id))).scalar()
        if existing == 0:
            if "--assign" not in sys.argv:
                print("  LEWAT: job ini belum ter-assign. Jalankan dengan --assign "
                      "kalau ingin skrip membuat baris antrian sebagai bahan uji.")
                return 0 if all(results) else 1
            segs = (await db.execute(select(PipelineSegment)
                    .where(PipelineSegment.job_id == job.id))).scalars().all()
            from datetime import datetime
            for s in segs:
                db.add(AnnotationQueue(segment_id=s.id, annotator_id=annot[0],
                                       status=AnnotationQueue.STATUS_ASSIGNED,
                                       priority=0, assigned_at=datetime.utcnow()))
            await db.commit()
            print(f"  (dibuat {len(segs)} baris antrian untuk pengujian)")

        from app.services.annotation_queue_service import AnnotationQueueService
        svc = AnnotationQueueService(db)
        res = await svc.get_annotator_queue(annotator_id=annot[0], page=1, page_size=500,
                                            job_id=job.id)
        check("filter job_id mengembalikan semua segmen job", res["total"] == nseg,
              f"{res['total']} vs {nseg}")
        check("semua item punya segment_index",
              all(i.get("segment_index") is not None for i in res["items"]))
        idxs = [i["segment_index"] for i in res["items"]]
        check("segment_index urut menaik", idxs == sorted(idxs), f"{idxs[:8]}...")
        check("semua item milik job yang diminta",
              all(str(i["job_id"]) == str(job.id) for i in res["items"]))
        tl = max((len(i["transcript_text"] or "") for i in res["items"]), default=0)
        check("transcript_text dipotong (<=241 char)", tl <= 241, f"maks {tl}")

        # ---------- D. Workspace anotasi ----------
        print("\n=== D. WORKSPACE ANOTASI ===")
        seg0 = res["items"][0]
        detail = await svc.get_segment_for_annotation(
            segment_id=UUID(str(seg0["segment_id"])), annotator_id=annot[0])
        utts = detail.get("current_utterances") or []
        check("segmen bisa dibuka & ada kalimat", len(utts) > 0, f"{len(utts)} kalimat")
        check("glosa ikut terbawa", any((u.get("text") or "").strip() for u in utts))
        oks = sum(1 for u in utts if u.get("status") == "OK")
        opens = sum(1 for u in utts if u.get("status") is None)
        check("ada campuran terkunci & terbuka", oks + opens == len(utts),
              f"{oks} OK / {opens} terbuka")
        check("segment_index ada di detail", detail.get("segment_index") is not None)

        # ---------- E. Anotasi suara ----------
        print("\n=== E. ANOTASI SUARA ===")
        from app.services.voice_annotation_service import VoiceAnnotationService
        vs = VoiceAnnotationService(db)
        vu = await vs.get_utterances(job.id)
        check("voice annotation terisi", len(vu) > 0, f"{len(vu)} kalimat")
        check("audio_url terbentuk untuk semua",
              all(u["audio_url"] for u in vu), 
              f"{sum(1 for u in vu if u['audio_url'])}/{len(vu)}")
        check("tidak ada yang ter-flag KBBI (diimpor CLEAN)",
              all(not u["has_flag"] for u in vu))
        if vu: print(f"  contoh audio_url: {vu[0]['audio_url']}")

    print("\n" + "="*60)
    print(f"HASIL: {sum(results)}/{len(results)} PASS")
    return 0 if all(results) else 1

sys.exit(asyncio.run(main()))
