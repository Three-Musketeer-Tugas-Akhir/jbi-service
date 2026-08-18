#!/usr/bin/env python3
"""Fetch the TVRI clips that the workbooks point at on Google Drive.

The clip filenames in column A are not plain text — every one of the 13,341
rows carries an **embedded hyperlink** holding a direct Drive file id:

    cell.value          MEM001M-20191111Z103928_0_0.40_7.66.mp4
    cell.hyperlink      https://drive.google.com/file/d/1vptZrYn7vxMiRpG8KcoA4wR5oEKFy8bW

So there is no folder to browse and no Drive API to authenticate against: each
file is fetched by id. The clips are world-readable, which is why this needs no
credentials.

Two modes, deliberately split so the download half runs anywhere:

    # 1. Extract the id map from the workbooks (needs openpyxl)
    python scripts/download_tvri_clips.py \
        --xlsx "…BISINDO.xlsx" --category BISINDO \
        --xlsx "…SIBI.xlsx"    --category SIBI \
        --write-manifest /srv/tvri/manifest.tsv

    # 2. Download from the manifest (Python stdlib only — runs on the bare host)
    python scripts/download_tvri_clips.py \
        --manifest /srv/tvri/manifest.tsv --out-dir /srv/tvri/clips

Resumable: a file already on disk that looks like a valid MP4 is skipped, so
re-running after an interruption only fetches what is missing.
"""
from __future__ import annotations

import argparse
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CLIP_RE = re.compile(r"^(?P<rec>.+?)_(?P<seg>\d+)_(?P<start>[\d.]+)_(?P<end>[\d.]+)\.mp4$")
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={fid}"

# Drive serves an HTML interstitial instead of the file when it wants a
# virus-scan confirmation. These clips are far too small to trigger it, but the
# check keeps a stray HTML page from being written out as a .mp4.
HTML_SNIFF = (b"<!DOCTYPE", b"<html", b"<HTML")

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def looks_like_mp4(data: bytes) -> bool:
    """An ISO base-media file carries the 'ftyp' box type at offset 4."""
    return len(data) > 12 and data[4:8] == b"ftyp"


# ── Manifest extraction ────────────────────────────────────────────────────


def write_manifest(pairs: list[tuple[str, str]], out_path: Path) -> int:
    """pairs = [(xlsx_path, category)] -> TSV of category, filename, drive id."""
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("openpyxl needed for --write-manifest: pip install openpyxl")

    rows: list[tuple[str, str, str]] = []
    seen_ids: dict[str, str] = {}
    for xlsx_path, category in pairs:
        # Not read_only: hyperlinks are dropped in read-only mode.
        wb = openpyxl.load_workbook(xlsx_path)
        found = 0
        for ws in wb.worksheets:
            for row in ws.iter_rows(min_row=2):
                cell = row[0]
                if not cell.value:
                    continue
                name = str(cell.value).strip()
                if not CLIP_RE.match(name):
                    continue
                if not (cell.hyperlink and cell.hyperlink.target):
                    log(f"WARN no hyperlink: {category} {ws.title} {name}")
                    continue
                fid = cell.hyperlink.target.rstrip("/").split("/")[-1]
                if fid in seen_ids:
                    log(f"WARN duplicate drive id {fid}: {seen_ids[fid]} / {name}")
                seen_ids[fid] = name
                rows.append((category, name, fid))
                found += 1
        wb.close()
        log(f"{Path(xlsx_path).name}: {found} clips")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        for category, name, fid in rows:
            fh.write(f"{category}\t{name}\t{fid}\n")
    log(f"Wrote {len(rows)} rows to {out_path}")
    return len(rows)


# ── Download ───────────────────────────────────────────────────────────────


def fetch_one(fid: str, dest: Path, retries: int, timeout: int) -> tuple[str, str]:
    """Returns (status, detail). status in skip/ok/fail."""
    if dest.exists() and dest.stat().st_size > 1000:
        try:
            with open(dest, "rb") as fh:
                if looks_like_mp4(fh.read(16)):
                    return "skip", ""
        except OSError:
            pass  # unreadable -> re-fetch

    url = DOWNLOAD_URL.format(fid=fid)
    last = ""
    for attempt in range(retries):
        if attempt:
            time.sleep(min(2 ** attempt, 20))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            continue

        if any(data[:64].lstrip().startswith(sig) for sig in HTML_SNIFF):
            last = "got HTML (permission or quota page), not a video"
            continue
        if not looks_like_mp4(data):
            last = f"not an MP4 (first bytes {data[:12]!r}, {len(data)} B)"
            continue

        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)  # atomic: a killed run never leaves a half file
        return "ok", str(len(data))

    return "fail", last


def download(manifest: Path, out_dir: Path, workers: int, retries: int,
             timeout: int, limit: int | None, flat: bool) -> int:
    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != 3:
            log(f"WARN malformed manifest line: {line[:80]!r}")
            continue
        rows.append(tuple(parts))
    if limit:
        rows = rows[:limit]
    log(f"{len(rows)} clips to fetch -> {out_dir} ({workers} workers)")

    counts = Counter()
    failures: list[tuple[str, str]] = []
    done = 0
    total = len(rows)

    def work(row):
        nonlocal done
        category, name, fid = row
        target_dir = out_dir if flat else out_dir / category
        target_dir.mkdir(parents=True, exist_ok=True)
        status, detail = fetch_one(fid, target_dir / name, retries, timeout)
        with _print_lock:
            counts[status] += 1
            done += 1
            if status == "fail":
                failures.append((name, detail))
            if done % 250 == 0 or done == total:
                log(f"  {done}/{total}  ok={counts['ok']} skip={counts['skip']} fail={counts['fail']}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(work, rows))

    log(f"Done. ok={counts['ok']} skip={counts['skip']} fail={counts['fail']}")
    if failures:
        log(f"{len(failures)} failed; first 20:")
        for name, detail in failures[:20]:
            log(f"  {name}: {detail}")
        log("Re-run the same command to retry only these (finished files are skipped).")
    return 1 if failures else 0


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--xlsx", action="append", default=[], help="Workbook (repeatable)")
    p.add_argument("--category", action="append", default=[],
                   help="Category for the matching --xlsx, in the same order")
    p.add_argument("--write-manifest", help="Write the id map here and exit")
    p.add_argument("--manifest", help="Manifest to download from")
    p.add_argument("--out-dir", help="Where clips land")
    p.add_argument("--workers", type=int, default=8,
                   help="Parallel downloads (default 8; Drive throttles above ~16)")
    p.add_argument("--retries", type=int, default=4)
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--limit", type=int, help="Only the first N rows — for a pilot run")
    p.add_argument("--flat", action="store_true",
                   help="All clips in one folder instead of per-category subfolders")
    args = p.parse_args()

    if args.write_manifest:
        if len(args.xlsx) != len(args.category) or not args.xlsx:
            p.error("--write-manifest needs matching --xlsx/--category pairs")
        write_manifest(list(zip(args.xlsx, args.category)), Path(args.write_manifest))
        return 0

    if not args.manifest or not args.out_dir:
        p.error("need --manifest and --out-dir (or --write-manifest)")
    return download(
        Path(args.manifest), Path(args.out_dir), args.workers,
        args.retries, args.timeout, args.limit, args.flat,
    )


if __name__ == "__main__":
    sys.exit(main())
