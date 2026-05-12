# Comparison Report: JBI Service vs Video Editor SIBI

> **Date:** 2026-05-12  
> **Scope:** Business logic & trim/crop mechanism comparison  
> **Reference:** video-editor-sibi is the "source of truth" (approved by dosen/tim SIBI)

---

## Executive Summary

**Verdict:** JBI Service's trim/crop mechanism is **conceptually aligned** with video-editor-sibi for the core cross-boundary trim flow. There is **one architectural divergence** (Part-A-then-Part-B concat vs merge-then-subclip) that causes edge-case fragility on sub-frame clips, but this is **fixable without changing business logic**.

**No fundamental melenceng found.** JBI Service correctly implements:
- Temporal trimming (cut start/end) ✅
- Cross-segment boundary extension (N → N+1) ✅
- Cascade update of next utterance/video timestamps ✅

---

## 1. Video Architecture

| Aspect | Video Editor SIBI | JBI Service |
|--------|-------------------|-------------|
| **Unit of video** | 1 file = 1 kalimat SIBI (pre-segmented) | 1 segment file = N utterances (post-ASR segmented) |
| **Video source** | Uploaded raw files per sentence | Auto-cropped from longer segment video per utterance |
| **Cross-video relation** | Sequential filenames (`_0052.mp4` → `_0053.mp4`) | Same job, ordered by `(segment_index, utterance_index)` |
| **Merged preview** | Yes — merges N + N+1 for editor timeline | No — FE shows individual utterance video only |

**Evaluation:** Different by necessity. Video-editor-sibi works on pre-segmented sentence videos. JBI Service segments a longer video into utterances. Both are valid for their respective data pipelines.

---

## 2. Trim Mechanism

### 2.1 Trim Direction

| | Video Editor SIBI | JBI Service |
|---|---|---|
| **Trim start** | Hardcoded to `0` (fixed) | Configurable (trim-in / shrink from left) |
| **Trim end** | User-adjustable slider | Configurable (trim-in / shrink from right) |
| **Extend beyond boundary** | Implicit — user trims merged N+N+1 | Explicit — user edits `end_time` > original end |

**Evaluation:** JBI Service allows bidirectional trimming (start & end), which is an **improvement** over video-editor-sibi's fixed-start-only approach. This is acceptable and does not melenceng.

### 2.2 Core Trim Algorithm

**Video Editor SIBI (merge-then-subclip):**
```
1. Source = merged video (N + N+1 concatenated)
2. trimmed   = subclip(source, 0, end_time)     → overwrite video N
3. remainder = subclip(source, end_time, end)   → overwrite video N+1
4. Clear merged_video_path cache
```

**JBI Service (Part-A + Part-B concat):**
```
1. Source N  = utterance N video (crop from segment)
2. Source N+1 = utterance N+1 video (crop from segment)
3. Part A = crop(source N,  relative_start, end_of_N)
4. Part B = crop(source N+1, 0, overlap)
5. result = concat(Part A, Part B)
6. Cascade-update next utterance start += overlap
```

**Evaluation:** Two valid approaches to the same problem:
- **Video-editor-sibi** merges first, then cuts. More robust for tiny clips because you never concat a sub-frame partial.
- **JBI Service** cuts first, then merges. Faster for normal cases but fragile when Part A < 2 frames.

**This is an implementation difference, not a business-logic melenceng.** Both produce the same conceptual result: the utterance/video spans across the boundary.

---

## 3. Cross-Boundary Edge Case Handling

### 3.1 Tiny Part A (sub-frame clip < 0.05s)

**Video Editor SIBI:**
- Never encounters this because the source is already a **merged full video**.
- Even if the trim point is 1 frame into video N, the subclip comes from the merged file directly.

**JBI Service (before fix):**
- Concat Part A (0.031s) + Part B → FFmpeg rejects sub-frame clip → **FAIL**

**JBI Service (after fix, ab672b2):**
- Detects Part A < 0.05s → attempts **merge-then-crop** (video-editor-sibi style)
- Falls back to "next video only" if merge fails
- **Result: PASS** (tested TC5 2026-05-12)

**Known limitation:** The merge-then-crop fallback currently fails in Docker because FFmpeg 4.4.2's `concat` demuxer does not allow `http://` URLs by default (whitelist: `file,crypto,data`). The fallback-to-next-video path succeeds, so TC5 passes, but the ideal merge-then-crop path is blocked by this FFmpeg configuration issue.

**Recommendation (not urgent):** Add `-protocol_whitelist file,http,https,tcp,tls,crypto` to `run_ffmpeg_concat` to enable the ideal path.

---

## 4. Data Model & Persistence

| Aspect | Video Editor SIBI | JBI Service |
|--------|-------------------|-------------|
| **Edit storage** | Overwrite video file directly | Create new cropped video in MinIO, keep edit history |
| **History** | None — destructive edit | Full history (`AnnotationEdit` rows, `utterance_corrections` JSONB) |
| **Cascade update** | Implicit — next video overwritten | Explicit — next utterance `start` timestamp updated in DB |
| **Reversibility** | No (unless raw backup exists) | Yes — can revert to earlier DRAFT edit |

**Evaluation:** JBI Service's non-destructive edit history with cascade updates is an **improvement** over video-editor-sibi's destructive overwrite. This is correct and does not melenceng.

---

## 5. What is Different but OK (Improvements)

1. **Bidirectional trimming** — JBI allows trimming start & end; SIBI only end. ✅ Improvement.
2. **Non-destructive edits** — JBI keeps history; SIBI overwrites. ✅ Improvement.
3. **Explicit cascade updates** — JBI updates next utterance timestamps in DB; SIBI implicitly overwrites next video file. ✅ Improvement.
4. **Async background cropping** — JBI crops in background task; SIBI trims synchronously. ✅ Improvement for scalability.

---

## 6. What Needs Attention (Not Melenceng, But Fragile)

1. **FFmpeg concat whitelist** — `http://` presigned URLs blocked by FFmpeg 4.4.2 concat demuxer. Fix: add protocol whitelist flag.
2. **Minimum crop duration** — Both systems handle this, but JBI enforces it at 0.067s (2 frames @ 30fps) which is reasonable.
3. **Extend-left (TC6)** — JBI Service cannot extend start to the left (pull from previous utterance). This is an **architectural limitation**, not a melenceng. Video-editor-sibi also cannot do this (start is hardcoded to 0). However, since JBI Service allows editing `start_time` freely, users might expect extend-left to work. **Won't fix for now** — focus remains N → N+1 as specified.

---

## 7. Test Results

| Test Case | Description | JBI Service Result |
|-----------|-------------|-------------------|
| TC1 | Trim-in start (shrink left) | ✅ PASS |
| TC2 | Trim-in end (shrink right) | ✅ PASS |
| TC3 | Trim-in both sides | ✅ PASS |
| TC4 | Trim-out end, cross-utterance (normal Part A) | ✅ PASS |
| TC5 | Trim-out end, cross-segment, tiny Part A (0.031s → 2.0s) | ✅ PASS (with fallback) |
| TC6 | Trim-out start, extend left | ❌ Not supported (by design) |

---

## 8. Conclusion

**JBI Service does not melenceng from video-editor-sibi.** The core business logic of cross-boundary trimming is correctly implemented. The architectural differences (pre-segmented vs post-ASR, destructive vs non-destructive) are **improvements**, not deviations.

The only remaining item is the FFmpeg `http` protocol whitelist in `run_ffmpeg_concat`, which blocks the ideal merge-then-crop path for sub-frame edge cases. The fallback path handles it correctly, so functionality is intact. Fixing the whitelist is a **nice-to-have** polish, not a correctness issue.

**Bottom line:** If video-editor-sibi is the "correct" implementation, JBI Service follows the same principles with sensible enhancements. ✅
