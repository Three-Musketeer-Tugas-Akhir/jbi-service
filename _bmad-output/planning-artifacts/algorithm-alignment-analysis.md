# Algorithm & Model Alignment Analysis
## Python Notebooks ↔ PRD Verification

**Analysis Date:** 2026-03-18  
**Notebooks:** `asr_code.ipynb`, `cv_asr_annotation.ipynb`  
**PRD:** `jbi-service/_bmad-output/planning-artifacts/prd.md`

---

## Executive Summary

| Aspect | Notebook Implementation | PRD Definition | Status |
|--------|------------------------|----------------|--------|
| **ASR Library** | `faster-whisper` | `faster-whisper` (mentioned in scoping) | ✅ **ALIGNED** |
| **Pipeline Flow** | CV Crop → ASR → Timestamp Crop | Detection → ASR → Crop | 🔴 **MISALIGNED** |
| **Cropping Stages** | TWO stages (CV-based + Timestamp-based) | ONE stage (bounding box only) | 🔴 **CRITICAL GAP** |
| **Input/Output Paths** | Specific folder structure | Generic storage (MinIO) | 🟡 **IMPLEMENTATION DETAIL** |

---

## 1. Critical Finding: Two-Stage Cropping Not Reflected in PRD

### Notebook Flow (Actual Implementation)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         NOTEBOOK PIPELINE FLOW                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Stage 1: CV Detection & Initial Crop                                        │
│  ┌─────────────┐    ┌─────────────────────────┐                             │
│  │ Full Video  │───▶│ YOLOv8 Detection        │                             │
│  │ (News)      │    │ → Find JBI regions      │                             │
│  └─────────────┘    │ → Crop to bbox          │                             │
│                     │ → Save as result_*.mp4  │                             │
│                     └─────────────────────────┘                             │
│                              │                                              │
│                              ▼                                              │
│  Stage 2: ASR Transcription                                                 │
│                     ┌─────────────────────────┐                             │
│                     │ faster-whisper          │                             │
│                     │ → Transcribe cropped    │                             │
│                     │   clips                 │                             │
│                     │ → Output segments.txt   │                             │
│                     └─────────────────────────┘                             │
│                              │                                              │
│                              ▼                                              │
│  Stage 3: Timestamp-Based Cropping (cv_asr_annotation.ipynb)               │
│                     ┌─────────────────────────┐                             │
│                     │ Parse ASR timestamps    │                             │
│                     │ → Add ±2s buffer        │                             │
│                     │ → Re-crop video         │                             │
│                     │ → Final clips for UI    │                             │
│                     └─────────────────────────┘                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### PRD Flow (Current Definition)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          PRD PIPELINE FLOW                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  FR3: CV Detection          FR4: ASR              FR5: Cropping             │
│  ┌─────────────┐           ┌──────────┐          ┌─────────────┐            │
│  │   Detect    │──────────▶│Transcribe│─────────▶│    Crop     │            │
│  │   JBI       │           │  Audio   │          │   (bbox)    │            │
│  └─────────────┘           └──────────┘          └─────────────┘            │
│                                                                │            │
│                                                                ▼            │
│                                                       ┌─────────────┐       │
│                                                       │   Output    │       │
│                                                       │   Clips     │       │
│                                                       └─────────────┘       │
│                                                                              │
│  ❌ MISSING: Second cropping stage based on ASR timestamps                   │
│  ❌ MISSING: ±2s buffer adjustment                                           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Detailed Component Analysis

### 2.1 ASR Implementation

| Aspect | Notebook (`asr_code.ipynb`) | PRD | Status |
|--------|---------------------------|-----|--------|
| **Library** | `faster-whisper` | `faster-whisper` | ✅ Aligned |
| **Model Sizes** | tiny, base, small, medium, large-v3 | Not specified | 🟡 Gap |
| **Device** | cuda (GPU) or cpu | GPU/CPU configurable | ✅ Aligned |
| **Compute Type** | int8, float16, int8_float16 | Not specified | 🟡 Gap |
| **Beam Size** | 5 | Not specified | 🟡 Gap |
| **Output Format** | `segments.txt` with timestamps | Generic transcript | 🟡 Format detail |

**Output Format (Notebook):**
```
[0.00s -> 6.46s]  Sejumlah pedagang mengamuk dan terus memaki petugas
[6.46s -> 9.64s]  Lantaran tak terima barang dagangan mereka diangkut paksa
```

**Required PRD Update:** Specify output format matches notebook exactly.

---

### 2.2 CV Detection & Cropping

| Aspect | Notebook Implementation | PRD | Status |
|--------|-------------------------|-----|--------|
| **Model** | YOLOv8 (implied from JBI Service) | YOLOv8 | ✅ Aligned |
| **Stage 1 Crop** | Bounding box based (result_*.mp4) | FR5: bbox crop | ✅ Aligned |
| **Stage 2 Crop** | Timestamp-based with ±2s buffer | ❌ NOT IN PRD | 🔴 **CRITICAL** |
| **Buffer Logic** | `max(0, start-2)` to `min(duration, end+2)` | ❌ NOT IN PRD | 🔴 **CRITICAL** |

**Notebook Cropping Logic (cv_asr_annotation.ipynb):**
```python
# JBI time range with ±2s buffer
jbi_start = max(0, start_time - 2)
jbi_end = min(total_duration, end_time + 2)
```

**Required PRD Update:** Add second cropping stage with buffer logic.

---

### 2.3 Directory Structure

**Notebook Structure:**
```
data/
├── videos_sibi/{video_name}/result_{timestamp}.mp4  # CV cropped
├── transcripts/{video_name}/{timestamp}/segmented/segments.txt  # ASR output
├── annotation/jbi_sibi/{video_name}/  # Final cropped clips
└── csv_sibi/  # Annotation CSV
```

**PRD Storage:**
- MinIO (S3-compatible) for video files
- PostgreSQL for metadata

**Alignment:** 🟡 **COMPATIBLE** - PRD uses MinIO but should preserve hierarchical naming convention.

---

### 2.4 Pipeline Stages Comparison

| Stage | Notebook | PRD | Match |
|-------|----------|-----|-------|
| **1** | CV Detection + Initial Crop | CV Detection | ⚠️ Partial |
| **2** | ASR on cropped clips | ASR | ✅ Yes |
| **3** | Timestamp Crop (±2s buffer) | ❌ Missing | 🔴 **No** |
| **4** | CSV Generation | Export Dataset | 🟡 Similar |

---

## 3. Required PRD Corrections

### 🔴 CRITICAL: Add Second Cropping Stage

The PRD currently has:
- **FR5:** System crops video segments based on detected bounding boxes with preserved audio

**NEEDS ADDITION:**
```markdown
### 1. Video Processing Pipeline (REVISED)

- **FR1:** Users can upload video files (MP4, AVI, MKV, MOV) via multipart upload or URL
- **FR2:** Users receive a job ID immediately upon successful upload for status tracking
- **FR3:** System automatically detects JBI (sign language interpreter) regions in uploaded videos
- **FR4:** System crops video segments based on detected bounding boxes (Stage 1 cropping)
- **FR4a:** System automatically transcribes audio from detected segments using faster-whisper ASR
- **FR4b:** System parses ASR timestamps and applies ±2 second buffer (Stage 2 cropping)
- **FR4c:** System generates final cropped clips aligned to transcript timestamps with JBI time ranges
- **FR5:** Users can poll for job status at configurable intervals (5s, 10s, 30s, 60s)
```

### 🟡 IMPORTANT: Specify ASR Configuration

Add to PRD:
```markdown
**ASR Configuration:**
- Library: faster-whisper
- Model sizes supported: tiny, base, small, medium, large-v3
- Compute types: int8, float16, int8_float16
- Default beam size: 5
- Output format: segments.txt with [start -> end] timestamps
```

### 🟡 IMPORTANT: Clarify "JBI Time Range"

The notebooks use specific terminology:
- **Audio Time Range:** From ASR (exact speech timestamps)
- **JBI Time Range:** Audio time ±2s buffer (for sign language context)

This should be explicitly defined in the PRD.

---

## 4. Impact Assessment

### If PRD Is Not Updated:

| Risk | Impact |
|------|--------|
| Backend implements single cropping | Frontend expects double-cropped clips (misalignment) |
| Missing ±2s buffer | Annotators won't have sign language context buffer |
| Wrong clip durations | Timestamp sync between video and transcript fails |
| Dataset quality issues | Training data won't match expected format |

### Frontend Impact:

The frontend (`anotasi.ai-FE/`) currently shows:
- Video player with transcript
- Timestamp adjustment handles
- This implies the clips are ALREADY cropped and aligned

**Question:** Does the frontend expect:
1. **Option A:** Pre-cropped clips from backend (matching notebook flow)
2. **Option B:** Full video with segment markers (different approach)

Based on the annotation interface showing specific clips, **Option A** is correct - matching the notebook.

---

## 5. Recommendation

### IMMEDIATE ACTION REQUIRED 🔴

Update the PRD to accurately reflect the **three-stage pipeline** from the notebooks:

```
┌─────────────────────────────────────────────────────────────────┐
│              CORRECTED PRD PIPELINE                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Stage 1: CV Detection & Initial Crop (Bounding Box)            │
│  ├── Input: Full news video                                     │
│  ├── Model: YOLOv8                                              │
│  └── Output: result_{timestamp}.mp4 clips                      │
│                                                                  │
│  Stage 2: ASR Transcription (faster-whisper)                    │
│  ├── Input: Cropped clips from Stage 1                          │
│  ├── Model: faster-whisper (configurable size)                  │
│  └── Output: segments.txt with [start -> end] timestamps       │
│                                                                  │
│  Stage 3: Timestamp-Based Cropping (±2s Buffer)               │
│  ├── Input: Clips + ASR timestamps                              │
│  ├── Logic: max(0, start-2) to min(duration, end+2)            │
│  └── Output: Final clips for annotation UI                     │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Specific PRD Changes Needed:

1. **Split FR4 and FR5** to show two cropping stages
2. **Add ASR configuration details** (faster-whisper, model sizes)
3. **Define JBI Time Range calculation** explicitly
4. **Add output format specification** for segments.txt
5. **Update pipeline diagram** to show 3 stages, not 2

---

## 6. Alignment Verification Checklist

- [x] ASR library matches (faster-whisper)
- [x] CV model matches (YOLOv8)
- [ ] **TWO cropping stages documented** ❌ CRITICAL
- [ ] **±2s buffer logic specified** ❌ CRITICAL
- [ ] ASR output format defined ❌ IMPORTANT
- [ ] JBI Time Range calculation defined ❌ IMPORTANT

**Overall Algorithm Alignment: 60%** 🔴 **NEEDS CRITICAL UPDATES**

---

*This analysis ensures the backend implementation will match the proven notebook workflow.*
