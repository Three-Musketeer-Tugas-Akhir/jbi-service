# ASR Output Format Comparison Analysis

## Executive Summary

This document compares the ASR transcription output formats between:
1. **Notebook Pipeline** (`asr_code.ipynb`) - Original research/prototype pipeline
2. **Production Pipeline** (Database) - Current API-based pipeline

The analysis reveals fundamental differences in how segments are defined, timestamps are calculated, and text is structured.

---

## 1. Format Comparison

### 1.1 Notebook Pipeline (`asr_code.ipynb`)

**File Structure:**
```
data/transcripts/{VIDEO_TITLE}/{TIMESTAMP}/
├── segmented/
│   └── segments.txt          # Individual utterances with timestamps
├── full/
│   └── full.txt              # Concatenated full text
└── duration/
    └── duration.txt          # Processing duration info
```

**Segment Format (`segments.txt`):**
```
[0.00s -> 6.46s]  Sejumlah pedagang mengamuk dan terus memaki petugas dengan nada tinggi
[6.46s -> 9.64s]  Lantaran tak terima barang dagangan mereka diangkut paksa
[9.64s -> 16.56s] Bahkan sempat terjadi aksi baku hantam hingga membuat seorang petugas mengalami luka lebam di pipi
...
```

**Key Characteristics:**
- **Granularity**: High - Each utterance (3-10 seconds) is a separate line
- **Timestamp Format**: `[start -> end]` relative to clip start
- **Segment Count**: 35 segments for 187-second clip (example)
- **Storage**: Multiple files per timestamp folder

### 1.2 Production Pipeline (Database)

**Database Schema (`pipeline_segments` table):**
```sql
SELECT 
    segment_index,
    asr_text,              -- Full concatenated text
    asr_confidence,        -- Average confidence score
    asr_start,             -- Segment start (seconds)
    asr_end,               -- Segment end (seconds)
    jbi_start,             -- JBI buffer start
    jbi_end,               -- JBI buffer end
    stage2_video_path      -- MinIO key for cropped video
FROM pipeline_segments 
WHERE job_id = '5b0fd5f5-f873-46c4-96dc-0570a1c60c8d';
```

**Example Output:**
| segment_index | asr_text | asr_start | asr_end | asr_confidence |
|--------------|----------|-----------|---------|----------------|
| 0 | "Sejumlah pedagang mengamuk..." (full 187s text) | 0 | 187 | 0.55 |
| 1 | "Yang ini kami awali dari informasi..." (full 400s text) | 0 | 400.04 | 0.63 |

**Key Characteristics:**
- **Granularity**: Low - One row per JBI-detected segment
- **Timestamp Format**: Absolute seconds in separate columns
- **Segment Count**: 2 segments (matches JBI detection)
- **Storage**: Single database row per segment

---

## 2. Timestamp Segmentation Analysis

### 2.1 Notebook Pipeline - Utterance-Based Segmentation

**Basis**: Whisper's natural speech segmentation

**How it works:**
```python
# From transcribe_clip() function
for segment in segments:
    start_seg = segment.start      # Whisper-provided timestamp
    end_seg = segment.end          # Whisper-provided timestamp
    segment_text = "[%.2fs -> %.2fs] %s" % (start_seg, end_seg, raw_text)
```

**Segmentation Criteria:**
- Whisper internally detects speech pauses
- Natural break points (pauses > 0.5-1s)
- Maximum segment length (typically 20-30s)
- Speaker changes (if using diarization)

**Example from 000008 clip:**
| Segment | Start | End | Duration | Content |
|---------|-------|-----|----------|---------|
| 1 | 0.00s | 6.46s | 6.46s | Breaking news intro |
| 2 | 6.46s | 9.64s | 3.18s | Context sentence |
| 3 | 9.64s | 16.56s | 6.92s | Incident description |
| ... | ... | ... | ... | ... |
| 35 | 182.56s | 187.14s | 4.58s | Reporter outro |

### 2.2 Production Pipeline - JBI Segment-Based Segmentation

**Basis**: JBI (Sign Language Interpreter) presence detection

**How it works:**
```python
# From stage1_detection.py
class JBIDetector:
    MIN_SEGMENT_DURATION = 5.0    # seconds
    MAX_GAP_SECONDS = 1.0         # merge gap
    
    def _merge_detections(self, detections):
        # Merge contiguous JBI detections
        if gap <= self.MAX_GAP_SECONDS:
            # Extend current segment
        else:
            # Start new segment
```

**Segmentation Criteria:**
- JBI presence in video frame (YOLO detection)
- Minimum 5-second duration
- Maximum 1-second gap between detections (merged)
- Based on visual cues, not audio

**Example from job 5b0fd5f5:**
| Segment | asr_start | asr_end | Duration | JBI Present |
|---------|-----------|---------|----------|-------------|
| 0 | 0 | 187 | 187s | Yes (continuous) |
| 1 | 0 | 400.04 | 400s | Yes (continuous) |

---

## 3. Text Structure Comparison

### 3.1 Notebook Pipeline - Preserves Utterance Boundaries

```
[0.00s -> 6.46s]  Sejumlah pedagang mengamuk dan terus memaki petugas dengan nada tinggi
[6.46s -> 9.64s]  Lantaran tak terima barang dagangan mereka diangkut paksa
```

**Advantages:**
- Easy to align with video at utterance level
- Natural speech boundaries preserved
- Suitable for fine-grained annotation
- Easy to spot transcription errors per utterance

### 3.2 Production Pipeline - Concatenated Text

```json
{
  "segment_index": 0,
  "asr_text": "Sejumlah pedagang mengamuk dan terus memaki petugas...",
  "asr_start": 0,
  "asr_end": 187
}
```

**Advantages:**
- Simpler storage (one row per segment)
- Direct correlation with JBI segments
- Easier to process for downstream tasks
- Confidence score per segment

---

## 4. Timestamp Reference Frames

### 4.1 Notebook Pipeline - Clip-Relative

```
Clip: result_000008.mp4 (starts at 00:00:08 in original video)
├── [0.00s -> 6.46s]   = 00:00:08 -> 00:00:14.46 in original
├── [6.46s -> 9.64s]   = 00:00:14.46 -> 00:00:17.64 in original
└── ...

Clip: result_000319.mp4 (starts at 00:03:19 in original video)
├── [0.00s -> 8.56s]   = 00:03:19 -> 00:03:27.56 in original
└── ...
```

**Calculation:**
```python
original_timestamp = clip_start_time + segment_timestamp
```

### 4.2 Production Pipeline - Segment-Relative

```
Original Video
├── Segment 0 (detected by JBI, 0s-187s)
│   ├── asr_start: 0
│   ├── asr_end: 187
│   └── asr_text: "..."
│
└── Segment 1 (detected by JBI, next 187s-587s)
    ├── asr_start: 0      # Reset to 0 for new segment
    ├── asr_end: 400
    └── asr_text: "..."
```

**Important Note:** Currently, `asr_start` and `asr_end` are relative to the cropped segment, NOT the original video. This is different from the notebook pipeline which preserves absolute timestamps.

---

## 5. Confidence Scoring

### 5.1 Notebook Pipeline
- No confidence scores in output
- Relies on Whisper's internal confidence (not exposed)

### 5.2 Production Pipeline
```python
# From stage2_asr.py
review_flag = result.average_confidence < 0.5
```

- Stores `asr_confidence` per segment (average)
- Flag for review if confidence < 0.5
- Enables quality filtering

---

## 6. Key Differences Summary

| Aspect | Notebook Pipeline | Production Pipeline |
|--------|------------------|---------------------|
| **Segmentation Basis** | Natural speech pauses | JBI presence detection |
| **Granularity** | High (3-10s utterances) | Low (entire JBI segments) |
| **Timestamp Type** | Clip-relative | Segment-relative |
| **Text Format** | Preserved utterances | Concatenated |
| **Storage** | Files (txt) | Database (PostgreSQL) |
| **Confidence** | Not stored | Stored per segment |
| **Segment Count** | 35 for 187s | 2 for entire video |
| **Use Case** | Research/Annotation | Production/Annotation |

---

## 7. Recommendations

### For Annotation Workflow:
The notebook format is better because:
- Smaller segments are easier to annotate
- Utterance boundaries align with natural speech
- Easier to spot and correct errors

### For Production Pipeline:
Current implementation is optimized for:
- Storage efficiency
- Direct JBI correlation
- Downstream processing

### Suggested Improvements:
1. **Add sub-segmentation** in production to match notebook granularity
2. **Store absolute timestamps** (relative to original video)
3. **Add confidence per utterance** (not just per segment)
4. **Preserve utterance boundaries** in database (as JSON array)

Example improved schema:
```sql
ALTER TABLE pipeline_segments ADD COLUMN asr_utterances JSONB;
-- [{"start": 0, "end": 6.46, "text": "...", "confidence": 0.8}, ...]
```

---

## 8. Technical Implementation Details

### 8.1 Whisper Segmentation Algorithm

Whisper uses a combination of:
1. **Audio features**: Mel spectrogram analysis
2. **Silence detection**: Energy-based voice activity detection
3. **Language model**: Predicts text boundaries
4. **Maximum duration**: Hard limit (typically 30s)

### 8.2 JBI Detection Algorithm

YOLO-based detection:
1. **Frame sampling**: 1 FPS analysis
2. **Confidence threshold**: 0.5
3. **Gap merging**: <1s gaps merged
4. **Minimum duration**: 5 seconds

---

## Conclusion

The two pipelines serve different purposes:
- **Notebook**: Research-focused, high granularity
- **Production**: Efficiency-focused, JBI-correlated

For the annotation platform, consider implementing a hybrid approach that stores both high-level segment data (current) and detailed utterance data (proposed JSONB column) to get the best of both worlds.
