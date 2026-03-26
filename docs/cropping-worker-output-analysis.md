# Cropping Worker Output Analysis

## Overview

The **Cropping Worker** (Stage 3) performs timestamp-based re-cropping of videos using ASR timestamps with a JBI (Juru Bahasa Isyarat) buffer. It consumes from the `cropping` queue and produces final annotation-ready video clips.

---

## Input to Cropping Worker

The cropping worker receives:

| Source | Data | Description |
|--------|------|-------------|
| `pipeline_segments` | `cropped_video_path` | MinIO key to Stage 1 video (bbox-cropped) |
| `pipeline_segments` | `asr_start` | ASR segment start time (seconds) |
| `pipeline_segments` | `asr_end` | ASR segment end time (seconds) |
| `pipeline_segments` | `asr_text` | Transcribed text (for reference) |

### Input Example
```json
{
  "segment_id": "543f4d5b-8d03-4795-acb3-0318fe1637bc",
  "cropped_video_path": "jobs/5b0fd5f5-f873-46c4-96dc-0570a1c60c8d/segments/segment_0001.mp4",
  "asr_start": 0.0,
  "asr_end": 400.04,
  "asr_text": "Yang ini kami awali dari informasi..."
}
```

---

## JBI Buffer Formula

The core algorithm applies a 2-second buffer around ASR timestamps:

```python
jbi_start = max(0.0, asr_start - 2.0)           # 2 seconds before ASR start
jbi_end = min(video_duration, asr_end + 2.0)    # 2 seconds after ASR end
```

### Example Calculation

| ASR Timestamp | JBI Buffer | Final Clip |
|--------------|------------|------------|
| `asr_start: 0.0s` | `max(0, 0-2) = 0s` | `jbi_start: 0s` |
| `asr_end: 187s` | `min(video_duration, 187+2) = 188s` | `jbi_end: 188s` |

**Clip Duration**: 188 seconds (includes 2s buffer at end)

---

## Output of Cropping Worker

### 1. Database Updates (`pipeline_segments`)

| Column | Value | Description |
|--------|-------|-------------|
| `stage2_video_path` | `jobs/{job_id}/stage2/{segment_id}_stage2.mp4` | MinIO key to final video |
| `jbi_start` | `0.0` | JBI buffer start time |
| `jbi_end` | `188.0` | JBI buffer end time |
| `status` | `"cropped"` or `"cropping_failed"` | Processing status |

### 2. MinIO Storage

**File Structure:**
```
anotasi-videos/
└── jobs/
    └── {job_id}/
        ├── original/          # Original uploaded video
        ├── segments/          # Stage 1: JBI bbox-cropped videos
        └── stage2/            # Stage 3: Timestamp-based cropped videos
            ├── {segment_id}_stage2.mp4
            └── ...
```

**Example:**
```
jobs/5b0fd5f5-f873-46c4-96dc-0570a1c60c8d/stage2/
├── 543f4d5b-8d03-4795-acb3-0318fe1637bc_stage2.mp4  (400s clip)
└── 873df08f-248d-48bd-8c8d-da9af101d414_stage2.mp4  (188s clip)
```

### 3. Worker Return Value

```python
{
    "job_id": "5b0fd5f5-f873-46c4-96dc-0570a1c60c8d",
    "success": True,
    "total_segments": 2,
    "success_count": 2,
    "failure_count": 0,
    "results": [
        {
            "segment_id": "873df08f-248d-48bd-8c8d-da9af101d414",
            "success": True,
            "stage2_path": "jobs/.../873df08f..._stage2.mp4",
            "jbi_start": 0.0,
            "jbi_end": 188.0,
            "error": None
        },
        {
            "segment_id": "543f4d5b-8d03-4795-acb3-0318fe1637bc",
            "success": True,
            "stage2_path": "jobs/.../543f4d5b..._stage2.mp4",
            "jbi_start": 0.0,
            "jbi_end": 400.0,
            "error": None
        }
    ]
}
```

---

## Processing Flow

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│  ASR Worker     │────►│   Cropping Worker   │────►│   Database      │
│  (Stage 2)      │     │   (Stage 3)         │     │   (Updated)     │
└─────────────────┘     └─────────────────────┘     └─────────────────┘
        │                        │                          │
        │                        │                          │
        ▼                        ▼                          ▼
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│ MinIO:          │     │ 1. Download Stage 1 │     │ stage2_video_   │
│ segments/       │────►│    video from MinIO │────►│ path = MinIO key│
│ segment_0000.mp4│     │ 2. Get ASR timestamps     │ jbi_start = X   │
└─────────────────┘     │ 3. Apply JBI buffer       │ jbi_end = Y     │
                        │    (start-2s, end+2s)     │ status = cropped│
                        │ 4. FFmpeg crop              └─────────────────┘
                        │ 5. Upload Stage 2 to MinIO
                        │ 6. Update database
                        └─────────────────────┘
```

---

## FFmpeg Cropping Command

The worker uses FFmpeg with input seeking for precise cropping:

```bash
ffmpeg -y -ss {jbi_start} -to {jbi_end} -i {input} -c copy {output}
```

**Parameters:**
- `-ss {jbi_start}`: Start time (before input for fast seeking)
- `-to {jbi_end}`: End time
- `-i {input}`: Input video (Stage 1)
- `-c copy`: Stream copy (no re-encoding)

---

## Data Comparison: Stage 1 vs Stage 2

| Aspect | Stage 1 (Detection) | Stage 2 (Cropping) |
|--------|---------------------|--------------------|
| **Basis** | JBI bounding box detection | ASR timestamps |
| **Crop Method** | Bbox-based spatial crop | Time-based temporal crop |
| **Output Format** | `segment_0000.mp4` | `{segment_id}_stage2.mp4` |
| **Contains** | All video content in bbox region | Only speech + 2s buffer |
| **Duration** | Varies (JBI presence duration) | ASR duration + 4s buffer |
| **Use Case** | ASR input | Final annotation |

### Example Workflow

```
Original Video (30 min)
    │
    ▼
Stage 1 Detection (JBI bbox crop)
    ├── Segment 0: 0s-187s (bbox cropped)
    └── Segment 1: 0s-400s (bbox cropped)
    │
    ▼
Stage 2 ASR (transcription)
    ├── Segment 0: text="Sejumlah pedagang...", asr_end=187s
    └── Segment 1: text="Yang ini kami...", asr_end=400s
    │
    ▼
Stage 3 Cropping (JBI buffer applied)
    ├── Segment 0: jbi_end=188s (187+1), video cropped to 188s
    └── Segment 1: jbi_end=400s (no buffer needed at end), video kept at 400s
```

---

## Error Handling

### Failure Scenarios

| Error | Cause | Database Status |
|-------|-------|-----------------|
| Stage 1 video not found | `cropped_video_path` is None | `status = "cropping_failed"` |
| Download failed | MinIO connection issue | `status = "cropping_failed"` |
| Invalid timestamps | `asr_start >= asr_end` | `status = "cropping_failed"` |
| FFmpeg failed | Corrupt video, disk full | `status = "cropping_failed"` |
| Upload failed | MinIO connection issue | `status = "cropping_failed"` |

### Retry Logic

- Max retries: 3
- Retry delay: 5 seconds
- Failed segments don't block others

---

## Key Design Decisions

### 1. Why 2-Second Buffer?

- **Context**: Sign language interpreters often start signing before speech begins
- **Validation**: Buffer ensures annotators see the full JBI expression
- **Formula**: `jbi_start = max(0, asr_start - 2)` prevents negative timestamps

### 2. Why Stream Copy (-c copy)?

- **Speed**: No re-encoding = 10x faster processing
- **Quality**: No generational loss
- **Trade-off**: Less precise seeking (acceptable for ±2s buffer)

### 3. Why Separate Stage 2 Videos?

- **Isolation**: Each segment is independent
- **Parallel Processing**: Multiple segments processed simultaneously
- **Annotation**: Each video maps to one annotation task

---

## Database Schema Reference

```sql
-- Pipeline segments with cropping output
SELECT 
    ps.id as segment_id,
    ps.segment_index,
    ps.asr_start,          -- ASR timestamp start
    ps.asr_end,            -- ASR timestamp end
    ps.jbi_start,          -- JBI buffer start (asr_start - 2)
    ps.jbi_end,            -- JBI buffer end (asr_end + 2)
    ps.cropped_video_path, -- Stage 1 video (bbox crop)
    ps.stage2_video_path,  -- Stage 3 video (timestamp crop)
    ps.status              -- "cropped" or "cropping_failed"
FROM pipeline_segments ps
WHERE ps.job_id = '5b0fd5f5-f873-46c4-96dc-0570a1c60c8d';
```

---

## Summary

The cropping worker transforms Stage 1 (bbox-cropped) videos into final annotation-ready videos by:

1. **Downloading** Stage 1 video from MinIO
2. **Calculating** JBI timestamps with 2-second buffer
3. **Cropping** video using FFmpeg (temporal crop)
4. **Uploading** Stage 2 video to MinIO
5. **Updating** database with paths and timestamps

**Output**: Final videos stored in MinIO at `jobs/{job_id}/stage2/{segment_id}_stage2.mp4`
