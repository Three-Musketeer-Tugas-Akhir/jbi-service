# Cropping Worker vs cv_asr_annotation.ipynb - Comprehensive Analysis

## Executive Summary

This document compares two approaches to video cropping for sign language annotation:

| Aspect | Cropping Worker (Pipeline) | cv_asr_annotation.ipynb (Notebook) |
|--------|---------------------------|-----------------------------------|
| **Architecture** | Server-side automated pipeline | Client-side manual notebook |
| **Granularity** | Segment-level (entire JBI segment) | Utterance-level (individual sentences) |
| **Buffer Logic** | Fixed 2-second JBI buffer | Dynamic gap-based adjustment |
| **Output Count** | 1-2 videos per job | 30-600+ videos per job |
| **Target User** | Automated/Annotators | Researchers/Annotators |

---

## 1. Input Comparison

### 1.1 Cropping Worker Input

```python
# From pipeline_segments table
{
    "segment_id": "543f4d5b-8d03-4795-acb3-0318fe1637bc",
    "cropped_video_path": "jobs/{job_id}/segments/segment_0001.mp4",
    "asr_start": 0.0,
    "asr_end": 400.04,
    "asr_text": "Yang ini kami awali dari informasi..."
}
```

**Source:** Stage 1 bbox-cropped videos + ASR segment-level timestamps

### 1.2 Notebook Input

```python
# From cv_asr_annotation.ipynb
video_path = f"{BASE_DIR}/videos_sibi/{video_name}/result_{segment}.mp4"
transcript_path = f"{BASE_DIR}/transcripts/{video_name}/{segment}/segmented/segments.txt"

# Example transcript line:
# [0.00s -> 6.46s] Sejumlah pedagang mengamuk dan terus memaki petugas dengan nada tinggi
```

**Source:** Original bbox-cropped videos + ASR utterance-level timestamps

### Input Comparison Table

| Feature | Cropping Worker | Notebook |
|---------|----------------|----------|
| **Video Source** | Stage 1 (bbox-cropped from MinIO) | Original bbox-cropped (local) |
| **Timestamp Source** | ASR segment-level (asr_start/end) | ASR utterance-level (segments.txt) |
| **Granularity** | Coarse (1 timestamp per JBI segment) | Fine (multiple timestamps per segment) |
| **Transcript Format** | Concatenated string | Timestamped lines `[start -> end] text` |

---

## 2. Cropping Logic Comparison

### 2.1 Cropping Worker Algorithm

```python
# From stage3_cropping.py
class TimestampBasedCropper:
    BUFFER_SECONDS = 2.0  # Fixed buffer
    
    def calculate_jbi_timestamps(self, asr_start, asr_end, video_duration):
        jbi_start = max(0.0, asr_start - self.BUFFER_SECONDS)  # Always -2s
        jbi_end = min(video_duration, asr_end + self.BUFFER_SECONDS)  # Always +2s
        
        # Ensure minimum duration
        if jbi_end - jbi_start < self.MIN_CLIP_DURATION:
            jbi_end = min(video_duration, jbi_start + self.MIN_CLIP_DURATION)
        
        return jbi_start, jbi_end
```

**Characteristics:**
- **Fixed 2-second buffer** before ASR start and after ASR end
- **Single crop per segment** (coarse granularity)
- **Output:** 1 video per JBI segment

### 2.2 Notebook Algorithm

```python
# From cv_asr_annotation.ipynb (process_transcripts function)
for i, line in enumerate(transcript_lines):
    # Parse timestamps from transcript
    start_time = float(start_time_str.replace('s', ''))
    if not is_start:
        start_time += 1  # Add 1s offset after first clip
    end_time = float(end_time_str.replace('s', ''))
    
    # Dynamic end time adjustment based on next utterance gap
    if next_start_time is not None:
        if next_start_time - end_time > 2:
            end_time += 2  # Large gap: add 2s buffer
            is_start = True
        else:
            end_time = next_start_time + 1  # Small gap: extend to next + 1s
            is_start = False
    else:  # Last segment
        end_time = video_duration if video_duration - end_time <= 1 else end_time + 1
```

**Characteristics:**
- **Dynamic buffer** based on gap to next utterance
- **Utterance-level cropping** (fine granularity)
- **Gap analysis:**
  - Gap > 2s: Add 2s buffer
  - Gap ≤ 2s: Extend to next utterance + 1s
- **Output:** 1 video per utterance (30-600+ videos)

### Algorithm Comparison Table

| Aspect | Cropping Worker | Notebook |
|--------|----------------|----------|
| **Buffer Strategy** | Fixed (2s before, 2s after) | Dynamic (gap-dependent) |
| **Granularity** | Per JBI segment | Per utterance |
| **Start Time Logic** | `max(0, asr_start - 2)` | `start + 1s` (if not first) |
| **End Time Logic** | `min(duration, asr_end + 2)` | Gap-based adjustment |
| **Videos per Segment** | 1 | 30-600+ |
| **Total Videos per Job** | 1-2 | 100-1000+ |

---

## 3. Output Comparison

### 3.1 Cropping Worker Output

**Database:**
```sql
SELECT 
    segment_index,
    asr_start, asr_end,      -- ASR timestamps
    jbi_start, jbi_end,      -- JBI buffer timestamps
    stage2_video_path,       -- MinIO key
    status
FROM pipeline_segments
WHERE job_id = '5b0fd5f5-f873-46c4-96dc-0570a1c60c8d';
```

| segment_index | asr_start | asr_end | jbi_start | jbi_end | stage2_video_path |
|--------------|-----------|---------|-----------|---------|-------------------|
| 0 | 0 | 187 | 0 | 188 | `jobs/.../segment_0_stage2.mp4` |
| 1 | 0 | 400 | 0 | 400 | `jobs/.../segment_1_stage2.mp4` |

**MinIO Storage:**
```
jobs/{job_id}/stage2/
├── {segment_id}_stage2.mp4   (188s video)
└── {segment_id}_stage2.mp4   (400s video)
```

### 3.2 Notebook Output

**File Structure:**
```
annotation/jbi_sibi/{video_name}/
├── {segment}_{start}_{end}.mp4       # Example: 000008_0.00_7.46.mp4
├── {segment}_{start}_{end}.mp4       # Example: 000008_7.46_10.64.mp4
└── ... (35-600+ clips)

csv_sibi/
└── {video_name}_{segment}_transcripts.csv
```

**CSV Format:**
```csv
Audio Time Range,JBI Time Range,Transcript,Video Path,Processing Time (s)
0.00s -> 6.46s,0.00 -> 7.46,Sejumlah pedagang mengamuk...,.../000008_0.00_7.46.mp4,0.50
6.46s -> 9.64s,7.46 -> 10.64,Lantaran tak terima...,.../000008_7.46_10.64.mp4,0.24
```

### Output Comparison Table

| Feature | Cropping Worker | Notebook |
|---------|----------------|----------|
| **Output Count** | 1-2 videos | 30-600+ videos |
| **Video Duration** | 100-400s (entire segment) | 3-10s (per utterance) |
| **Storage** | MinIO (cloud) | Local filesystem |
| **Metadata** | Database (PostgreSQL) | CSV files |
| **Naming** | `{segment_id}_stage2.mp4` | `{segment}_{start}_{end}.mp4` |
| **Transcript Link** | Indirect (via segment) | Direct (in filename/CSV) |

---

## 4. Use Case Analysis

### 4.1 Cropping Worker - Best For

1. **Automated Pipelines:** Server-side processing without manual intervention
2. **Storage Efficiency:** Fewer files to manage (1-2 per job)
3. **Streaming Applications:** Larger clips suitable for video players
4. **Segment-level Annotation:** When annotation happens at JBI segment level

### 4.2 Notebook - Best For

1. **Fine-grained Annotation:** Utterance-level annotation tasks
2. **Research/Analysis:** When precise timing alignment is critical
3. **Manual Review:** Smaller clips are easier to review and validate
4. **CSV Integration:** When working with spreadsheet-based workflows

---

## 5. Technical Implementation Differences

### 5.1 Cropping Worker

```python
# FFmpeg-based cropping (fast, stream copy)
ffmpeg -y -ss {jbi_start} -to {jbi_end} -i {input} -c copy {output}

# Storage: MinIO (S3-compatible)
minio_client.upload_file(file_bytes, object_key)

# Database: PostgreSQL (persistent)
UPDATE pipeline_segments SET stage2_video_path = ..., jbi_start = ..., jbi_end = ...
```

**Pros:**
- Fast (stream copy, no re-encoding)
- Cloud-native (MinIO)
- Database-backed (queryable)
- Scalable (worker queue)

**Cons:**
- Coarse granularity
- No utterance-level metadata
- Requires database for metadata

### 5.2 Notebook

```python
# MoviePy-based cropping (slower, re-encodes)
with VideoFileClip(video_path) as video:
    cropped = video.subclipped(start_time, end_time)
    cropped.write_videofile(output_path, codec='libx264', audio_codec='aac')

# Storage: Local filesystem
os.makedirs(annotation_dir, exist_ok=True)

# Metadata: CSV files
df.to_csv(csv_path, index=False)
```

**Pros:**
- Fine granularity
- Utterance-level timestamps
- Human-readable filenames
- CSV export for analysis

**Cons:**
- Slow (re-encoding)
- Local storage only
- File-based metadata (harder to query)
- Manual execution

---

## 6. Data Flow Comparison

### 6.1 Cropping Worker Flow

```
┌──────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ Stage 2: ASR     │────►│ Stage 3: Cropping    │────►│   MinIO         │
│                  │     │   Worker             │     │   Storage       │
│ pipeline_segments│     │                      │     │                 │
│ .asr_start       │     │ 1. Download Stage 1  │────►│ jobs/{id}/stage2│
│ .asr_end         │     │ 2. Apply JBI buffer  │     │ /{id}_stage2.mp4│
│ .cropped_video_  │     │    (start-2, end+2)  │     │                 │
│   path           │     │ 3. FFmpeg crop       │     └─────────────────┘
└──────────────────┘     │ 4. Upload Stage 2    │              │
                         │ 5. Update DB         │              │
                         └──────────────────────┘              │
                                      │                        │
                                      ▼                        ▼
                         ┌──────────────────────┐     ┌─────────────────┐
                         │   PostgreSQL         │     │   Annotation    │
                         │   pipeline_segments  │────►│   UI            │
                         │   .stage2_video_path │     │   (video player)│
                         │   .jbi_start/end     │     │                 │
                         └──────────────────────┘     └─────────────────┘
```

### 6.2 Notebook Flow

```
┌──────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ ASR Output       │────►│ cv_asr_annotation    │────►│   Local FS      │
│                  │     │   .ipynb             │     │                 │
│ transcripts/     │     │                      │     │ annotation/     │
│ {video}/         │     │ 1. Read segments.txt │────►│ jbi_sibi/       │
│ segmented/       │     │ 2. Parse utterances  │     │ {video}/        │
│ segments.txt     │     │ 3. Dynamic buffer    │     │ {seg}_{s}_{e}.  │
└──────────────────┘     │ 4. MoviePy crop      │     │    mp4          │
                         │ 5. Save CSV          │     │                 │
                         └──────────────────────┘     └─────────────────┘
                                      │                        │
                                      ▼                        ▼
                         ┌──────────────────────┐     ┌─────────────────┐
                         │   CSV Files          │     │   Manual        │
                         │   csv_sibi/          │────►│   Annotation    │
                         │   {video}_transcript │     │   (per clip)    │
                         │   .csv               │     │                 │
                         └──────────────────────┘     └─────────────────┘
```

---

## 7. Recommendations

### 7.1 For Production Pipeline (Current)

**Keep if:**
- You need automated, server-side processing
- Storage efficiency is priority (fewer files)
- You're building a streaming/video player application
- Annotation happens at segment level

**Improve by adding:**
```python
# Option 1: Add utterance-level cropping to pipeline
class UtteranceBasedCropper:
    def crop_utterances(self, segment_id, utterances, video_path):
        for idx, utt in enumerate(utterances):
            # Apply notebook-style dynamic buffer
            start, end = self.calculate_dynamic_buffer(utt, utterances, idx)
            output = f"{segment_id}_utt_{idx}.mp4"
            self.crop_video(video_path, start, end, output)

# Option 2: Store utterance timestamps in database
ALTER TABLE pipeline_transcripts ADD COLUMN jbi_start FLOAT;
ALTER TABLE pipeline_transcripts ADD COLUMN jbi_end FLOAT;
ALTER TABLE pipeline_transcripts ADD COLUMN cropped_video_path VARCHAR(500);
```

### 7.2 For Research/Annotation (Notebook)

**Keep if:**
- You need utterance-level precision
- You're doing manual annotation/review
- You need CSV exports for analysis
- You have local storage capacity

**Improve by:**
- Migrating to server-side processing
- Adding MinIO upload
- Creating a web UI for the notebook functionality

---

## 8. Summary Table

| Dimension | Cropping Worker | cv_asr_annotation.ipynb | Winner |
|-----------|----------------|------------------------|--------|
| **Automation** | Fully automated | Manual execution | Pipeline |
| **Granularity** | Segment-level | Utterance-level | Notebook |
| **Speed** | Fast (FFmpeg copy) | Slow (MoviePy re-encode) | Pipeline |
| **Storage** | Cloud (MinIO) | Local filesystem | Depends |
| **Metadata** | Database (queryable) | CSV (portable) | Depends |
| **Scalability** | High (worker queue) | Low (single machine) | Pipeline |
| **Annotation UX** | Video player friendly | Clip-by-clip friendly | Notebook |
| **Timestamp Precision** | Coarse (±2s) | Fine (utterance-level) | Notebook |
| **Total Videos** | 1-2 per job | 30-600+ per job | Depends |

---

## Conclusion

The **Cropping Worker** and **cv_asr_annotation.ipynb** serve different purposes:

- **Cropping Worker** is optimized for **production deployment** with automated, efficient segment-level processing suitable for streaming applications.

- **cv_asr_annotation.ipynb** is optimized for **research and fine-grained annotation** with utterance-level precision and CSV-based workflows.

**Recommendation:** Consider implementing utterance-level cropping in the pipeline while keeping segment-level summaries for backward compatibility. This hybrid approach would provide both automation and fine-grained annotation capabilities.
