#!/usr/bin/env python3
"""Build one WAV per kalimat for an imported TVRI dataset.

Why this is not just "cut the clip's audio"
-------------------------------------------
The workbook carries two different time ranges per row:

    Rentang Waktu Audio : 21.98s -> 25.14s      <- what was SPOKEN
    Rentang Waktu JBI   : 22.98  -> 26.50       <- what the clip CONTAINS

They differ because CV2 shifted every non-first clip forward by one second
(``S_i = A_i + 1.0``, see cropping_worker) to catch the interpreter's lag. In
this dataset that offset is exactly 1.00s for 95% of rows. So slicing a clip's
own audio start-to-end would drop the first second of speech — usually the
first word or two — on almost every sentence.

The missing second is not lost, though. CV2 also tiles consecutive clips
without a hole (``E_i = A_{i+1} + 1.0 = S_{i+1}``), so the audio that belongs to
sentence N sits at the tail of clip N-1. Walking back along the chain
reconstructs the exact spoken window for **99.8%** of sentences (7185/7200
BISINDO, 6125/6141 SIBI) from the clips alone — no source broadcast needed.

How it works
------------
Per segment, in one pass:

1. ``ffmpeg -vn`` each clip once  -> 16 kHz mono PCM (matches VideoProcessor)
2. lay those buffers on the segment's own timeline, padding any gap between
   consecutive clips with digital silence so local time == segment time
3. slice ``[audio_start, audio_end]`` per kalimat straight out of that buffer
4. upload to ``jobs/{job}/audio/{segment_id}_utt_{i}.wav`` and set
   ``pipeline_transcripts.audio_path``

Step 3 is pure byte slicing, so the cost is one ffmpeg call per clip and
nothing else — roughly 13.3k short decodes for the whole dataset.

Prerequisite: the clips MUST carry an audio track. Check before running:

    ffprobe -v error -select_streams a -show_entries stream=codec_name \
      -of csv=p=0 "<salah satu klip>.mp4"

Empty output means the clips are silent, and this approach cannot work — you
would need the original broadcast recordings instead (see --report-only).

Usage
-----
    # Dry check: what would be produced, and can every window be covered?
    python scripts/generate_tvri_wav.py \
        --xlsx "dataset TVRI/…BISINDO.xlsx" --dataset-name "TVRI BISINDO" \
        --clips-dir /srv/tvri/clips_bisindo --report-only

    # Real run
    python scripts/generate_tvri_wav.py \
        --xlsx "dataset TVRI/…BISINDO.xlsx" --dataset-name "TVRI BISINDO" \
        --clips-dir /srv/tvri/clips_bisindo
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import selectinload  # noqa: E402

from app.db.session import async_session_maker  # noqa: E402
from app.db.models.dataset import Dataset  # noqa: E402
from app.db.models.pipeline import (  # noqa: E402
    PipelineJob,
    PipelineSegment,
    PipelineTranscript,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from import_tvri_dataset import CLIP_RE, parse_workbook  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("tvri_wav")

# Whisper's format, and what VideoProcessor already writes for iNews audio.
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # pcm_s16le
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH

AUDIO_RANGE_RE = re.compile(r"^\s*([\d.]+)\s*s?\s*->\s*([\d.]+)\s*s?\s*$")

# Two clip boundaries that line up to the millisecond still differ by a sample
# or two after decoding; treat anything under a frame as contiguous.
EPS = 0.005


def parse_audio_range(raw) -> Optional[tuple[float, float]]:
    m = AUDIO_RANGE_RE.match(str(raw or ""))
    if not m:
        return None
    start, end = float(m.group(1)), float(m.group(2))
    return (start, end) if end > start else None


def probe_has_audio(path: Path) -> bool:
    """True when the file carries at least one audio stream."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise SystemExit("ffprobe not found in PATH")
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return bool(out.stdout.strip())


def decode_pcm(path: Path) -> bytes:
    """Decode a clip's audio to raw 16 kHz mono PCM. Empty bytes on failure."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg not found in PATH")
    proc = subprocess.run(
        [ffmpeg, "-v", "error", "-i", str(path),
         "-vn", "-ac", str(CHANNELS), "-ar", str(SAMPLE_RATE),
         "-f", "s16le", "-acodec", "pcm_s16le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        logger.warning("ffmpeg failed on %s: %s", path.name, proc.stderr.decode()[:200])
        return b""
    return proc.stdout


def _byte_offset(seconds: float) -> int:
    """Segment-relative seconds -> sample-aligned byte offset."""
    offset = int(round(seconds * BYTES_PER_SECOND))
    return offset - offset % SAMPLE_WIDTH


def build_segment_pcm(
    clips: list[tuple[float, float, Path]],
) -> tuple[bytes, float, list[tuple[float, float]]]:
    """Lay every clip of one segment onto the segment's own timeline.

    ``clips`` is (start, end, path) ordered by start. Returns ``(pcm, origin,
    holes)`` where ``origin`` is the segment time of byte 0 and ``holes`` are the
    stretches left as silence because no clip covered them.

    Each clip is written at the byte offset its **nominal** range dictates, not
    appended end-to-end. AAC decodes a few tens of milliseconds longer than the
    nominal range (encoder padding), and appending would let that error
    accumulate — measured at ~19 ms per clip, which over a 341-clip TVRI segment
    would drag the timeline several seconds out and misalign every later cut.
    Anchoring on the nominal offset caps the error at one clip, no matter how
    many clips the segment holds.
    """
    origin = clips[0][0]
    span_end = max(end for _, end, _ in clips)
    buf = bytearray(_byte_offset(span_end - origin))
    holes: list[tuple[float, float]] = []
    prev_end = origin

    for start, end, path in clips:
        if start - prev_end > EPS:
            holes.append((prev_end, start))
        prev_end = max(prev_end, end)

        pcm = decode_pcm(path)
        if not pcm:
            holes.append((start, end))
            continue

        at = _byte_offset(start - origin)
        room = min(_byte_offset(end - start), len(buf) - at)
        if room <= 0:
            continue
        chunk = pcm[:room]
        buf[at:at + len(chunk)] = chunk

    return bytes(buf), origin, holes


def slice_wav(
    pcm: bytes,
    origin: float,
    start: float,
    end: float,
    holes: Optional[list[tuple[float, float]]] = None,
) -> tuple[bytes, float]:
    """Cut [start, end] in segment time out of the buffer.

    Returns ``(wav, missing_seconds)``. ``missing`` counts both the part of the
    window that falls outside the buffer and the part that lands in a silent
    hole — the hole is real audio nobody has, and reporting it as covered just
    because the buffer holds zeros would hide the loss.
    """
    total = len(pcm) / BYTES_PER_SECOND
    lo = max(0.0, start - origin)
    hi = min(total, end - origin)
    missing = max(0.0, (end - start) - max(0.0, hi - lo))
    for h_start, h_end in (holes or []):
        overlap = min(end, h_end) - max(start, h_start)
        if overlap > 0:
            missing += overlap

    b0 = _byte_offset(lo)
    b1 = _byte_offset(hi)
    chunk = pcm[b0:max(b0, b1)]

    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(SAMPLE_WIDTH)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(chunk)
    return out.getvalue(), missing


async def run(args: argparse.Namespace) -> int:
    xlsx_path = Path(args.xlsx)
    if not xlsx_path.is_file():
        raise SystemExit(f"XLSX not found: {xlsx_path}")
    clips_dir = Path(args.clips_dir)
    if not clips_dir.is_dir():
        raise SystemExit(f"--clips-dir not found: {clips_dir}")

    recordings, skipped = parse_workbook(xlsx_path)
    if skipped:
        logger.warning("Ignoring %d unparseable rows from the workbook", len(skipped))

    # The workbook's audio column is not carried by the importer's Utterance
    # dataclass, so re-read just that column, keyed by clip filename.
    import openpyxl
    audio_ranges: dict[str, tuple[float, float]] = {}
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows(min_row=2, values_only=True):
            if not row or not row[0]:
                continue
            name = str(row[0]).strip()
            if not CLIP_RE.match(name):
                continue
            rng = parse_audio_range(row[1] if len(row) > 1 else None)
            if rng:
                audio_ranges[name] = rng
    wb.close()
    logger.info("Read %d audio ranges from the workbook", len(audio_ranges))

    # Audio-track sanity check on a real file before doing any work.
    sample = next(
        (clips_dir / u.filename
         for r in recordings.values() for s in r.segments.values() for u in s.utterances
         if (clips_dir / u.filename).is_file()),
        None,
    )
    if sample is None:
        raise SystemExit(f"No clip from the workbook found in {clips_dir}")
    if not probe_has_audio(sample):
        raise SystemExit(
            f"{sample.name} has no audio stream. The clips are silent, so per-kalimat "
            "WAV cannot be rebuilt from them — the original broadcast recordings are "
            "needed instead. Nothing was written."
        )
    logger.info("Audio track present in %s — proceeding", sample.name)

    if args.report_only:
        return report(recordings, audio_ranges, clips_dir)

    from app.services.minio_service import get_minio_service
    minio_service = get_minio_service()

    written = 0
    skipped_no_clip = 0
    incomplete: list[tuple[str, float]] = []

    async with async_session_maker() as db:
        dataset = (
            await db.execute(select(Dataset).where(Dataset.name == args.dataset_name))
        ).scalars().first()
        if not dataset:
            raise SystemExit(f"Dataset {args.dataset_name!r} not found — run the importer first")

        jobs = (
            await db.execute(
                select(PipelineJob).where(PipelineJob.dataset_id == dataset.id)
            )
        ).scalars().all()
        jobs_by_name = {j.original_filename: j for j in jobs}
        logger.info("Dataset %r has %d jobs", args.dataset_name, len(jobs))

        for rec_id in sorted(recordings):
            recording = recordings[rec_id]
            job = jobs_by_name.get(f"{rec_id}.mp4")
            if not job:
                logger.warning("No imported job for recording %s — skipping", rec_id)
                continue

            segments = (
                await db.execute(
                    select(PipelineSegment)
                    .options(selectinload(PipelineSegment.transcripts))
                    .where(PipelineSegment.job_id == job.id)
                )
            ).scalars().all()
            segments_by_index = {s.segment_index: s for s in segments}

            for seg_index in sorted(recording.segments):
                seg_data = recording.segments[seg_index]
                segment = segments_by_index.get(seg_index)
                if not segment:
                    logger.warning("Job %s has no segment %d — skipping", rec_id, seg_index)
                    continue

                present = [
                    (u.start, u.end, clips_dir / u.filename)
                    for u in seg_data.utterances
                    if (clips_dir / u.filename).is_file()
                ]
                missing_here = len(seg_data.utterances) - len(present)
                skipped_no_clip += missing_here
                if not present:
                    logger.warning("No clips on disk for %s segment %d", rec_id, seg_index)
                    continue

                pcm, origin, holes = build_segment_pcm(present)
                if holes:
                    logger.info(
                        "%s seg %d: %d silent gap(s) padded (%.1fs total)",
                        rec_id, seg_index, len(holes), sum(b - a for a, b in holes),
                    )

                transcripts = {t.utterance_index: t for t in segment.transcripts}

                for idx, utt in enumerate(seg_data.utterances):
                    transcript = transcripts.get(idx)
                    if not transcript:
                        continue
                    rng = audio_ranges.get(utt.filename)
                    # No usable audio range in the sheet: fall back to the clip's
                    # own window. Slightly late, but never silent.
                    a_start, a_end = rng if rng else (utt.start, utt.end)

                    wav_bytes, missing = slice_wav(pcm, origin, a_start, a_end, holes)
                    if missing > EPS:
                        incomplete.append((utt.filename, missing))
                    if len(wav_bytes) <= 44:  # header only
                        continue

                    key = f"jobs/{job.id}/audio/{segment.id}_utt_{idx}.wav"
                    await minio_service.upload_file(wav_bytes, key, content_type="audio/wav")
                    transcript.audio_path = key
                    written += 1

                await db.commit()
                logger.info("%s seg %d: %d WAV written", rec_id, seg_index, len(present))

    logger.info(
        "Done. %d WAV written, %d kalimat had no clip on disk, %d windows incomplete",
        written, skipped_no_clip, len(incomplete),
    )
    if incomplete:
        incomplete.sort(key=lambda x: -x[1])
        logger.warning("Longest missing stretches (kalimat, seconds):")
        for name, sec in incomplete[:15]:
            logger.warning("  %.2fs  %s", sec, name)
    return 0


def report(recordings, audio_ranges, clips_dir: Path) -> int:
    """Dry analysis: coverage of every spoken window, without touching anything."""
    total = full = partial = on_disk = 0
    lost_total = 0.0
    worst: list[tuple[float, str]] = []

    for recording in recordings.values():
        for seg in recording.segments.values():
            rows = seg.utterances
            for i, utt in enumerate(rows):
                total += 1
                if (clips_dir / utt.filename).is_file():
                    on_disk += 1
                rng = audio_ranges.get(utt.filename)
                a_start, a_end = rng if rng else (utt.start, utt.end)

                covered_from = utt.start
                j = i - 1
                while covered_from - a_start > EPS and j >= 0:
                    if rows[j].end < covered_from - EPS:
                        break
                    covered_from = rows[j].start
                    j -= 1

                covered_to = utt.end
                k = i + 1
                while a_end - covered_to > EPS and k < len(rows):
                    if rows[k].start > covered_to + EPS:
                        break
                    covered_to = rows[k].end
                    k += 1

                lost = max(0.0, covered_from - a_start) + max(0.0, a_end - covered_to)
                if lost <= EPS:
                    full += 1
                else:
                    partial += 1
                    lost_total += lost
                    worst.append((lost, utt.filename))

    logger.info("Kalimat total                     : %d", total)
    logger.info("Klip tersedia di --clips-dir      : %d", on_disk)
    logger.info("Jendela audio tercakup penuh      : %d (%.1f%%)", full, full / total * 100)
    logger.info("Jendela audio tidak penuh         : %d (total %.1fs hilang)", partial, lost_total)
    worst.sort(reverse=True)
    for sec, name in worst[:15]:
        logger.info("   %.2fs  %s", sec, name)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--xlsx", required=True, help="The same workbook used for the import")
    p.add_argument("--dataset-name", required=True, help="Dataset the recordings were imported into")
    p.add_argument("--clips-dir", required=True, help="Folder holding the .mp4 clips")
    p.add_argument("--report-only", action="store_true", help="Analyse coverage, write nothing")
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
