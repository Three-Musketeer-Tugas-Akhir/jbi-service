#!/usr/bin/env python3
"""Import the pre-annotated TVRI dataset into anotasi.ai.

The TVRI material never goes through the 3-service pipeline: it arrives already
segmented per sentence, with a human-verified transcript and a glosa. This
script writes it straight into the tables the JBI annotation workspace and the
voice annotation page read from.

Source of truth is one XLSX per sign language, with one sheet per broadcast day:

    Segmen Video Bahasa Isyarat   -> MEM001M-<recording>_<segment>_<start>_<end>.mp4
    Rentang Waktu Audio           -> "0.40s -> 5.66s"    (informational only)
    Rentang Waktu JBI             -> "0.40 -> 7.66"      (matches the filename)
    Transkripsi ... oleh Sistem   -> ASR text
    Penyelarasan ...              -> human transcript; literal "OK" = ASR was right
    Glosa Bahasa Isyarat          -> glosa           (BISINDO sheet)
    Kalimat yang Diperagakan      -> glosa           (SIBI sheet)
    Potensi Masalah               -> comma-separated issue labels
    Keterangan Annotator          -> free-text note

Mapping into the schema:

    recording  (MEM001M-…)  -> pipeline_jobs        (1 job per recording)
    segment    (_<n>_)      -> pipeline_segments    (segment_index = n)
    row                     -> pipeline_transcripts (utterance_index by start time)
                            -> voice_annotations    (ASR + ground truth)
    segment                 -> annotation_edits     (one DRAFT holding every glosa)

Timestamps in the filename are relative to the segment, which is exactly what
``PipelineTranscript.start/end`` means — the ASR worker transcribes the segment
video, not the source broadcast. No rebasing is needed.

Idempotent: each recording commits separately, and re-running skips any
recording that already has a job in the target dataset.

Usage
-----
    # 1. Dry run — parse and report, touch nothing
    python scripts/import_tvri_dataset.py \
        --xlsx "dataset TVRI/Annotator Sign Video + Transcript BISINDO.xlsx" \
        --category BISINDO --dataset-name "TVRI BISINDO" --dry-run

    # 2. Which clip files does the import need? (feed to the Drive download)
    python scripts/import_tvri_dataset.py --xlsx … --category BISINDO \
        --manifest /tmp/tvri_bisindo_clips.txt --dry-run

    # 3. Real import, uploading clips from a local folder
    python scripts/import_tvri_dataset.py --xlsx … --category BISINDO \
        --dataset-name "TVRI BISINDO" --clips-dir /data/tvri/bisindo

    # 4. Metadata only — clips uploaded separately later
    python scripts/import_tvri_dataset.py --xlsx … --category BISINDO \
        --dataset-name "TVRI BISINDO" --skip-clips
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.db.session import async_session_maker  # noqa: E402
from app.db.models.dataset import Dataset  # noqa: E402
from app.db.models.annotation import AnnotationEdit, AnnotationQueue  # noqa: E402
from app.db.models.auth import User  # noqa: E402
from app.db.models.pipeline import (  # noqa: E402
    JobStatus,
    PipelineJob,
    PipelineSegment,
    PipelineTranscript,
)
from app.db.models.voice_annotation import VoiceAnnotation  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("import_tvri")

# Filename grammar: <recording>_<segment>_<start>_<end>.mp4
CLIP_RE = re.compile(r"^(?P<rec>.+?)_(?P<seg>\d+)_(?P<start>[\d.]+)_(?P<end>[\d.]+)\.mp4$")

# Recording id carries the broadcast date: MEM001M-20191111Z103928
RELEASE_DATE_RE = re.compile(r"-(?P<date>\d{8})Z")

# The alignment problem that actually needs an annotator to move the filmstrip.
# Other labels ("kurang informasi", "salah isyarat", …) are content judgements
# the trim handles cannot fix, so those rows stay locked.
TIMING_ISSUE = "kesalahan waktu"

# Column order is identical in both workbooks; only column F is named differently
# ("Glosa Bahasa Isyarat" vs "Kalimat yang Diperagakan").
COL_FILENAME = 0
COL_AUDIO_RANGE = 1
COL_JBI_RANGE = 2
COL_ASR = 3
COL_ALIGNMENT = 4
COL_GLOSA = 5
COL_ISSUES = 6
COL_NOTE = 7
COL_ANNOTATOR = 8

# annotation_edits.utterance_corrections[].text is required and non-empty
# (schemas.annotation.UtteranceCorrection). 322 source rows have no glosa; a
# blank would make the annotator's very first draft save fail validation for the
# whole segment, so they are seeded with a visible placeholder instead.
EMPTY_GLOSA_PLACEHOLDER = "(glosa belum diisi)"


@dataclass
class Utterance:
    filename: str
    start: float
    end: float
    asr_text: str
    ground_truth: str
    glosa: str
    issues: list[str]
    note: str
    source_annotator: str
    sheet: str
    row_number: int

    @property
    def needs_alignment(self) -> bool:
        return any(TIMING_ISSUE in i for i in self.issues)


@dataclass
class Segment:
    index: int
    utterances: list[Utterance] = field(default_factory=list)


@dataclass
class Recording:
    recording_id: str
    sheet: str
    segments: dict[int, Segment] = field(default_factory=dict)

    @property
    def release_date(self) -> Optional[str]:
        m = RELEASE_DATE_RE.search(self.recording_id)
        return m.group("date") if m else None

    @property
    def utterance_count(self) -> int:
        return sum(len(s.utterances) for s in self.segments.values())


# ── Parsing ────────────────────────────────────────────────────────────────


def _clean(value) -> str:
    """Normalise a cell into a trimmed string ('' for blank)."""
    if value is None:
        return ""
    text = str(value)
    # The sheets carry non-breaking spaces and stray control chars from pasting.
    text = unicodedata.normalize("NFKC", text).replace(" ", " ")
    return text.strip()


def parse_workbook(xlsx_path: Path) -> tuple[dict[str, Recording], list[str]]:
    """Parse one workbook into recordings. Returns (recordings, skipped_rows)."""
    try:
        import openpyxl
    except ImportError:  # pragma: no cover - operator-facing
        raise SystemExit("openpyxl is required: pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    recordings: dict[str, Recording] = {}
    skipped: list[str] = []

    for ws in wb.worksheets:
        for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or not row[COL_FILENAME]:
                continue
            filename = _clean(row[COL_FILENAME])
            match = CLIP_RE.match(filename)
            if not match:
                # Two junk rows exist in the SIBI workbook (a stray "ok" and a
                # Drive URL). Report them rather than guessing.
                skipped.append(f"{ws.title}!A{row_number}: {filename[:70]!r}")
                continue

            start = float(match.group("start"))
            end = float(match.group("end"))
            if end <= start:
                skipped.append(f"{ws.title}!A{row_number}: non-positive duration {filename!r}")
                continue

            asr_text = _clean(row[COL_ASR] if len(row) > COL_ASR else "")
            alignment = _clean(row[COL_ALIGNMENT] if len(row) > COL_ALIGNMENT else "")
            # "OK" means the ASR line already matched the signing; anything else
            # in that column IS the corrected line. Blank = never reviewed, so
            # the ASR text is the best ground truth available.
            if alignment.upper() == "OK" or not alignment:
                ground_truth = asr_text
            else:
                ground_truth = alignment

            issues_raw = _clean(row[COL_ISSUES] if len(row) > COL_ISSUES else "")
            issues = [i.strip().lower() for i in re.split(r"[,;]", issues_raw) if i.strip()]

            utt = Utterance(
                filename=filename,
                start=start,
                end=end,
                asr_text=asr_text,
                ground_truth=ground_truth,
                glosa=_clean(row[COL_GLOSA] if len(row) > COL_GLOSA else ""),
                issues=issues,
                note=_clean(row[COL_NOTE] if len(row) > COL_NOTE else ""),
                source_annotator=_clean(row[COL_ANNOTATOR] if len(row) > COL_ANNOTATOR else ""),
                sheet=ws.title,
                row_number=row_number,
            )

            rec_id = match.group("rec")
            recording = recordings.get(rec_id)
            if recording is None:
                recording = Recording(recording_id=rec_id, sheet=ws.title)
                recordings[rec_id] = recording

            seg_index = int(match.group("seg"))
            segment = recording.segments.get(seg_index)
            if segment is None:
                segment = Segment(index=seg_index)
                recording.segments[seg_index] = segment
            segment.utterances.append(utt)

    wb.close()

    # utterance_index is positional within the segment, ordered by time — the
    # same contract the ASR worker produces.
    for recording in recordings.values():
        for segment in recording.segments.values():
            segment.utterances.sort(key=lambda u: (u.start, u.end))

    return recordings, skipped


# ── MinIO ──────────────────────────────────────────────────────────────────


async def upload_clip(minio_service, local_path: Path, object_keys: list[str]) -> None:
    """Upload one local clip under every key it has to be reachable by.

    TVRI clips are both the *source* the annotation workspace crops from
    (``utterances/``) and, for anything not re-aligned, the *delivered* clip that
    curation and export read (``utterances_synced/`` — see
    ``_resolve_synced_key`` in api/v1/jobs.py, which refuses any other prefix).
    Re-aligning an utterance overwrites the synced key with the real crop.
    """
    data = local_path.read_bytes()
    for key in object_keys:
        await minio_service.upload_file(data, key, content_type="video/mp4")


# ── Import ─────────────────────────────────────────────────────────────────


async def get_or_create_dataset(db, name: str, description: str) -> Dataset:
    existing = (
        await db.execute(select(Dataset).where(Dataset.name == name))
    ).scalars().first()
    if existing:
        logger.info("Dataset %r already exists (%s)", name, existing.id)
        return existing
    dataset = Dataset(name=name, description=description)
    db.add(dataset)
    await db.flush()
    logger.info("Created dataset %r (%s)", name, dataset.id)
    return dataset


async def resolve_annotator(db, email: Optional[str]) -> Optional[User]:
    if not email:
        return None
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalars().first()
    if not user:
        raise SystemExit(f"Annotator {email!r} not found in auth_users")
    return user


def build_utterance_corrections(
    segment: Segment, segment_id, job_id, lock_all: bool,
    missing_indices: Optional[set] = None,
) -> list[dict]:
    """The seeded DRAFT: one entry per utterance, carrying the glosa.

    ``status == "OK"`` is what locks the filmstrip for a processed (non-iNews)
    dataset — see ``isTrimLocked`` in the FE annotation page. Rows flagged with a
    timing problem are left unset so the annotator can still drag the handles.
    """
    missing_indices = missing_indices or set()
    corrections = []
    for idx, utt in enumerate(segment.utterances):
        needs_work = utt.needs_alignment and not lock_all
        corrections.append({
            "utterance_index": idx,
            "text": utt.glosa or EMPTY_GLOSA_PLACEHOLDER,
            "start": utt.start,
            "end": utt.end,
            # floor == transcript start: nothing of this clip's head belongs to
            # the previous sentence yet, so the whole clip is annotatable.
            "floor": utt.start,
            "status": None if needs_work else "OK",
            # The imported clip already is the delivered clip. Re-aligning
            # rewrites this same key with the annotator's crop. Left empty when
            # the source file was not on disk, so curation/export reports the
            # utterance as having no clip rather than a dead link.
            "cropped_video_path": (
                None if idx in missing_indices else synced_key(job_id, segment_id, idx)
            ),
            "tvri_source": {
                "filename": utt.filename,
                "issues": utt.issues,
                "note": utt.note,
                "annotator": utt.source_annotator,
            },
        })
    return corrections


def source_key(job_id, segment_id, idx: int) -> str:
    return f"jobs/{job_id}/utterances/{segment_id}_utt_{idx}.mp4"


def synced_key(job_id, segment_id, idx: int) -> str:
    return f"jobs/{job_id}/utterances_synced/{segment_id}_utt_{idx}.mp4"


async def import_recording(
    db,
    minio_service,
    recording: Recording,
    dataset: Dataset,
    category: str,
    clips_dir: Optional[Path],
    skip_clips: bool,
    annotator: Optional[User],
    lock_all: bool,
) -> dict:
    """Write one recording as job + segments + transcripts + edits. Returns stats."""
    job = PipelineJob(
        original_filename=f"{recording.recording_id}.mp4",
        status=JobStatus.READY_FOR_ANNOTATION,
        current_stage=None,
        category=category,
        file_size=0,
        dataset_id=dataset.id,
        release_date=recording.release_date,
        # Imported material has no pipeline history; its per-utterance clips are
        # the deliverable, so the merge cache starts empty and is built on demand.
        premerge_status=None,
        completed_at=datetime.utcnow(),
    )
    db.add(job)
    await db.flush()

    stats = {"segments": 0, "utterances": 0, "uploaded": 0, "missing_clips": [], "open": 0}

    for seg_index in sorted(recording.segments):
        segment_data = recording.segments[seg_index]
        segment = PipelineSegment(
            job_id=job.id,
            segment_index=seg_index,
            # Left as the detection worker leaves it — nothing reads this column.
            status=None,
            asr_review_flag=False,
            # No stitched segment video exists for TVRI — the dataset ships as
            # per-utterance clips. Left NULL so the workspace falls back to the
            # merged tape instead of requesting a 404 asset.
            cropped_video_path=None,
        )
        db.add(segment)
        await db.flush()
        stats["segments"] += 1

        missing_indices: set[int] = set()
        for idx, utt in enumerate(segment_data.utterances):
            object_key = source_key(job.id, segment.id, idx)

            if not skip_clips:
                local = (clips_dir / utt.filename) if clips_dir else None
                if local and local.is_file():
                    await upload_clip(
                        minio_service, local,
                        [object_key, synced_key(job.id, segment.id, idx)],
                    )
                    stats["uploaded"] += 1
                else:
                    stats["missing_clips"].append(utt.filename)
                    missing_indices.add(idx)

            transcript = PipelineTranscript(
                segment_id=segment.id,
                utterance_index=idx,
                text=utt.asr_text,
                start=utt.start,
                end=utt.end,
                # Human-reviewed material: confidence is not an ASR posterior
                # here, so 1.0 records "not machine-uncertain".
                confidence=1.0,
                video_path=object_key,
                audio_path=None,  # objectives 3 & 4 (wav per kalimat) add this later
                status="cropped",
            )
            db.add(transcript)
            await db.flush()

            # Voice annotation: the workbook's alignment column IS the verified
            # transcript, so it is imported CLEAN rather than re-run through KBBI
            # (which flags every proper noun and would gate the job shut).
            db.add(VoiceAnnotation(
                transcript_id=transcript.id,
                job_id=job.id,
                asr_text=utt.asr_text,
                ground_truth_text=utt.ground_truth,
                flagged_words=[],
                has_flag=False,
                voice_annotation_status=VoiceAnnotation.STATUS_CLEAN,
            ))
            stats["utterances"] += 1

        corrections = build_utterance_corrections(
            segment_data, segment.id, job.id, lock_all, missing_indices
        )
        stats["open"] += sum(1 for c in corrections if c["status"] != "OK")

        db.add(AnnotationEdit(
            segment_id=segment.id,
            # No editor yet when assignment is deferred. The workspace reads the
            # latest DRAFT regardless of editor; once the assigned annotator
            # saves, create_draft writes their own row which then wins on
            # edited_at. Passing --annotator-email seeds it directly instead.
            editor_id=annotator.id if annotator else None,
            old_text=None,
            old_start=None,
            old_end=None,
            new_text=" ".join(c["text"] for c in corrections),
            new_start=min((c["start"] for c in corrections), default=0.0),
            new_end=max((c["end"] for c in corrections), default=0.0),
            utterance_corrections=corrections,
            status=AnnotationEdit.STATUS_DRAFT,
            is_deleted=False,
            edited_at=datetime.utcnow(),
        ))

        if annotator:
            db.add(AnnotationQueue(
                segment_id=segment.id,
                annotator_id=annotator.id,
                status=AnnotationQueue.STATUS_ASSIGNED,
                priority=0,
                assigned_at=datetime.utcnow(),
            ))

    job.clean_utterance_count = stats["utterances"]
    job.flagged_utterance_count = 0
    return stats


async def run(args: argparse.Namespace) -> int:
    xlsx_path = Path(args.xlsx)
    if not xlsx_path.is_file():
        raise SystemExit(f"XLSX not found: {xlsx_path}")

    recordings, skipped = parse_workbook(xlsx_path)
    total_utt = sum(r.utterance_count for r in recordings.values())
    total_seg = sum(len(r.segments) for r in recordings.values())
    open_rows = sum(
        1
        for r in recordings.values()
        for s in r.segments.values()
        for u in s.utterances
        if u.needs_alignment
    )

    logger.info(
        "Parsed %s: %d recordings, %d segments, %d utterances (%d need alignment)",
        xlsx_path.name, len(recordings), total_seg, total_utt, open_rows,
    )
    if skipped:
        logger.warning("Skipped %d unparseable rows:", len(skipped))
        for line in skipped:
            logger.warning("  %s", line)

    if args.manifest:
        names = sorted(
            u.filename
            for r in recordings.values()
            for s in r.segments.values()
            for u in s.utterances
        )
        Path(args.manifest).write_text("\n".join(names) + "\n", encoding="utf-8")
        logger.info("Wrote %d clip names to %s", len(names), args.manifest)

    clips_dir = Path(args.clips_dir) if args.clips_dir else None
    if not args.skip_clips and not args.dry_run:
        if clips_dir is None:
            raise SystemExit("--clips-dir is required unless --skip-clips is given")
        if not clips_dir.is_dir():
            raise SystemExit(f"--clips-dir not found: {clips_dir}")
        present = sum(
            1
            for r in recordings.values()
            for s in r.segments.values()
            for u in s.utterances
            if (clips_dir / u.filename).is_file()
        )
        logger.info("Clip check: %d/%d present in %s", present, total_utt, clips_dir)
        if present == 0:
            raise SystemExit("No clips found in --clips-dir; refusing to import")

    if args.dry_run:
        logger.info("Dry run — nothing written.")
        for rec_id in sorted(recordings)[: args.preview]:
            rec = recordings[rec_id]
            logger.info(
                "  %s (%s): %d segments, %d utterances, release_date=%s",
                rec_id, rec.sheet, len(rec.segments), rec.utterance_count, rec.release_date,
            )
        return 0

    from app.services.minio_service import get_minio_service

    minio_service = get_minio_service()

    async with async_session_maker() as db:
        dataset = await get_or_create_dataset(
            db,
            args.dataset_name,
            args.dataset_description or f"Dataset TVRI {args.category} (pra-anotasi, impor XLSX)",
        )
        annotator = await resolve_annotator(db, args.annotator_email)

        existing_jobs = {
            name
            for (name,) in (
                await db.execute(
                    select(PipelineJob.original_filename).where(
                        PipelineJob.dataset_id == dataset.id
                    )
                )
            ).all()
        }

        totals = {"jobs": 0, "segments": 0, "utterances": 0, "uploaded": 0, "open": 0}
        missing: list[str] = []

        for rec_id in sorted(recordings):
            filename = f"{rec_id}.mp4"
            if filename in existing_jobs:
                logger.info("Skipping %s — already imported into this dataset", rec_id)
                continue

            stats = await import_recording(
                db=db,
                minio_service=minio_service,
                recording=recordings[rec_id],
                dataset=dataset,
                category=args.category,
                clips_dir=clips_dir,
                skip_clips=args.skip_clips,
                annotator=annotator,
                lock_all=args.lock_all,
            )
            await db.commit()

            totals["jobs"] += 1
            for key in ("segments", "utterances", "uploaded", "open"):
                totals[key] += stats[key]
            missing.extend(stats["missing_clips"])
            logger.info(
                "Imported %s: %d segments, %d utterances (%d open, %d clips uploaded)",
                rec_id, stats["segments"], stats["utterances"], stats["open"], stats["uploaded"],
            )

    logger.info(
        "Done. %d jobs, %d segments, %d utterances, %d clips uploaded, %d open for alignment",
        totals["jobs"], totals["segments"], totals["utterances"],
        totals["uploaded"], totals["open"],
    )
    if missing:
        logger.warning("%d clips were not found on disk. First 20:", len(missing))
        for name in missing[:20]:
            logger.warning("  %s", name)
        logger.warning(
            "Their pipeline_transcripts.video_path still points at the expected key — "
            "upload the files under that key and the workspace picks them up."
        )
    if not annotator:
        logger.warning(
            "No --annotator-email given: annotation_queue is empty, so the JBI "
            "workspace cannot open these segments yet. Assign them from "
            "Admin > Assign JBI (or re-run with --annotator-email)."
        )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xlsx", required=True, help="Path to the TVRI workbook")
    p.add_argument("--category", required=True, choices=["BISINDO", "SIBI"])
    p.add_argument("--dataset-name", help="Target dataset name (created if absent)")
    p.add_argument("--dataset-description", help="Dataset description on creation")
    p.add_argument("--clips-dir", help="Folder holding the .mp4 clips named as in column A")
    p.add_argument("--skip-clips", action="store_true", help="Write metadata only; upload clips later")
    p.add_argument("--annotator-email", help="Assign every segment to this annotator")
    p.add_argument(
        "--lock-all",
        action="store_true",
        help="Mark every utterance OK, including rows flagged 'Kesalahan Waktu'",
    )
    p.add_argument("--manifest", help="Write the expected clip filenames to this file")
    p.add_argument("--dry-run", action="store_true", help="Parse and report only")
    p.add_argument("--preview", type=int, default=5, help="Recordings to list in a dry run")
    args = p.parse_args()

    if not args.dry_run and not args.dataset_name:
        p.error("--dataset-name is required unless --dry-run is given")

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
