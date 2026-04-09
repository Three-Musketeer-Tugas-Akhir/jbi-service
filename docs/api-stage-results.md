# Pipeline Stage Results API

## Overview

The Stage Results API provides access to processed data from the three-stage video processing pipeline:

- **Stage 1 (Detection)**: YOLO-based JBI detection and segmentation
- **Stage 2 (ASR)**: Automatic Speech Recognition with Whisper
- **Stage 3 (Cropping)**: Video cropping with temporal adjustments

## Base Endpoint

```
GET /api/v1/pipeline/jobs/{job_id}/stage{N}/results
```

Where `{N}` is the stage number (1, 2, or 3).

---

## Stage 1: Detection Results

### Endpoint

```http
GET /api/v1/pipeline/jobs/{job_id}/stage1/results
```

### Description

Retrieves detection results including bounding box data and segment information from the YOLO model.

### Response Schema

```typescript
interface Stage1ResultsResponse {
  id: string;                    // Job UUID
  status: string;                // Job status
  original_filename: string;     // Original video filename
  total_segments: number;        // Total detected segments
  results: SegmentResult[];
}

interface SegmentResult {
  segment_id: string;            // Segment UUID
  segment_index: number;         // 0-based segment index
  bbox_data: BboxData;
  video_url: string;             // Original video URL
  created_at: string;            // ISO 8601 timestamp
}

interface BboxData {
  frame_count: number;           // Total frames analyzed
  detections: Detection[];
}

interface Detection {
  frame: number;                 // Frame number
  bbox: number[];                // [x, y, width, height]
  confidence: number;            // 0.0 - 1.0
  class: string;                 // Detection class
}
```

### Example Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ASR_COMPLETED",
  "original_filename": "news_broadcast.mp4",
  "total_segments": 5,
  "results": [
    {
      "segment_id": "660e8400-e29b-41d4-a716-446655440001",
      "segment_index": 0,
      "bbox_data": {
        "frame_count": 300,
        "detections": [
          {
            "frame": 15,
            "bbox": [100.5, 200.0, 150.0, 300.0],
            "confidence": 0.92,
            "class": "jbi_present"
          }
        ]
      },
      "video_url": "/api/v1/assets/jobs/550e8400/segments/segment_0000.mp4",
      "created_at": "2026-04-08T10:30:00.000Z"
    }
  ]
}
```

### Bounding Box Visualization

To visualize bounding boxes on the frontend:

```javascript
function drawBbox(canvas, detection, scaleX, scaleY) {
  const ctx = canvas.getContext('2d');
  const [x, y, width, height] = detection.bbox;
  
  ctx.strokeStyle = detection.confidence > 0.8 ? '#00ff00' : '#ffff00';
  ctx.lineWidth = 2;
  ctx.strokeRect(
    x * scaleX,
    y * scaleY,
    width * scaleX,
    height * scaleY
  );
  
  // Draw confidence label
  ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
  ctx.fillRect(x * scaleX, y * scaleY - 20, 60, 20);
  ctx.fillStyle = '#ffffff';
  ctx.fillText(`${(detection.confidence * 100).toFixed(0)}%`, x * scaleX + 5, y * scaleY - 5);
}
```

### Error Responses

| Status | Description |
|--------|-------------|
| 404 | Job not found |
| 400 | Stage 1 not completed yet |
| 403 | Not authorized to access this job |

---

## Stage 2: ASR Results

### Endpoint

```http
GET /api/v1/pipeline/jobs/{job_id}/stage2/results
```

### Description

Retrieves ASR (Automatic Speech Recognition) results with utterances and confidence scores. This returns **ORIGINAL ASR timestamps** (before any cropping adjustments).

### Response Schema

```typescript
interface Stage2ResultsResponse {
  id: string;                    // Job UUID
  status: string;                // Job status
  total_utterances: number;      // Total transcript utterances
  average_confidence: number;    // Average confidence score
  results: Stage2SegmentResponse[];
}

interface Stage2SegmentResponse {
  segment_id: string;            // Segment UUID
  segment_index: number;         // Segment index
  utterances: Stage2UtteranceResponse[];
}

interface Stage2UtteranceResponse {
  id: string;                    // Utterance UUID
  utterance_index: number;       // Index within segment
  text: string;                  // Transcribed text
  start: number;                 // Start time in seconds (ORIGINAL)
  end: number;                   // End time in seconds (ORIGINAL)
  confidence: number;            // Confidence 0.0 - 1.0
  status: string;                // pending | cropped | failed
}
```

### Example Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ASR_COMPLETED",
  "total_utterances": 12,
  "average_confidence": 0.87,
  "results": [
    {
      "segment_id": "660e8400-e29b-41d4-a716-446655440001",
      "segment_index": 0,
      "utterances": [
        {
          "id": "770e8400-e29b-41d4-a716-446655440001",
          "utterance_index": 0,
          "text": "Saya makan nasi di restoran",
          "start": 5.0,
          "end": 10.0,
          "confidence": 0.92,
          "status": "pending"
        },
        {
          "id": "770e8400-e29b-41d4-a716-446655440002",
          "utterance_index": 1,
          "text": "bersama keluarga saya",
          "start": 10.5,
          "end": 13.0,
          "confidence": 0.85,
          "status": "pending"
        }
      ]
    }
  ]
}
```

### Confidence Score Interpretation

| Score | Quality | Action |
|-------|---------|--------|
| ≥ 0.9 | High | Direct to annotation queue |
| 0.7 - 0.9 | Medium | Review recommended |
| < 0.7 | Low | ASR review required |

### Filtering Low Confidence

```javascript
// Filter utterances needing review
const needsReview = utterances.filter(u => u.confidence < 0.7);

// Group by confidence level
const grouped = utterances.reduce((acc, u) => {
  if (u.confidence >= 0.9) acc.high.push(u);
  else if (u.confidence >= 0.7) acc.medium.push(u);
  else acc.low.push(u);
  return acc;
}, { high: [], medium: [], low: [] });
```

---

## Stage 3: Cropping Results

### Endpoint

```http
GET /api/v1/pipeline/jobs/{job_id}/stage3/results
```

### Description

Retrieves final cropping results with **ADJUSTED timestamps**. These timestamps reflect the actual cropped video boundaries, which may differ from original ASR timestamps.

### Response Schema

```typescript
interface Stage3ResultsResponse {
  id: string;                    // Job UUID
  status: string;                // READY_FOR_ANNOTATION | etc.
  summary: Stage3Summary;
  results: Stage3SegmentResponse[];
}

interface Stage3Summary {
  total_utterances: number;
  cropped: number;               // Successfully cropped
  failed: number;                // Failed to crop
  pending: number;               // Still processing
}

interface Stage3SegmentResponse {
  segment_id: string;
  segment_index: number;
  video_url: string;             // Cropped video URL
  utterances: Stage3UtteranceResponse[];
}

interface Stage3UtteranceResponse {
  id: string;
  utterance_index: number;
  text: string;
  start: number;                 // CROPPED start time (may differ from Stage 2)
  end: number;                   // CROPPED end time (may differ from Stage 2)
  confidence: number;
  url: string;                   // Individual utterance video URL
  status: string;                // cropped | pending | failed
}
```

### Example Response

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "READY_FOR_ANNOTATION",
  "summary": {
    "total_utterances": 12,
    "cropped": 10,
    "failed": 1,
    "pending": 1
  },
  "results": [
    {
      "segment_id": "660e8400-e29b-41d4-a716-446655440001",
      "segment_index": 0,
      "video_url": "/api/v1/assets/jobs/550e8400/cropped/segment_0000.mp4",
      "utterances": [
        {
          "id": "770e8400-e29b-41d4-a716-446655440001",
          "utterance_index": 0,
          "text": "Saya makan nasi di restoran",
          "start": 4.8,              // Adjusted from 5.0
          "end": 10.2,             // Adjusted from 10.0
          "confidence": 0.92,
          "url": "/api/v1/assets/jobs/550e8400/utterances/u_0000_0000.mp4",
          "status": "cropped"
        }
      ]
    }
  ]
}
```

### Timestamp Differences

Stage 3 timestamps may differ from Stage 2 due to:
- Padding added for context
- Alignment adjustments
- Boundary corrections

```javascript
// Compare Stage 2 vs Stage 3 timestamps
function getTimestampDiff(stage2, stage3) {
  return {
    startDiff: stage3.start - stage2.start,
    endDiff: stage3.end - stage2.end,
    durationDiff: (stage3.end - stage3.start) - (stage2.end - stage2.start)
  };
}
```

---

## Frontend Integration Guide

### Job Status Polling

```javascript
class JobResultsPoller {
  constructor(jobId, token) {
    this.jobId = jobId;
    this.token = token;
    this.interval = null;
  }

  async checkStatus() {
    const response = await fetch(
      `/api/v1/pipeline/jobs/${this.jobId}`,
      { headers: { 'Authorization': `Bearer ${this.token}` } }
    );
    const job = await response.json();
    
    if (job.status === 'ASR_COMPLETED') {
      await this.loadStage2Results();
    } else if (job.status === 'READY_FOR_ANNOTATION') {
      await this.loadStage3Results();
      this.stop();
    }
  }

  async loadStage2Results() {
    const response = await fetch(
      `/api/v1/pipeline/jobs/${this.jobId}/stage2/results`,
      { headers: { 'Authorization': `Bearer ${this.token}` } }
    );
    const data = await response.json();
    this.onStage2Data(data);
  }

  async loadStage3Results() {
    const response = await fetch(
      `/api/v1/pipeline/jobs/${this.jobId}/stage3/results`,
      { headers: { 'Authorization': `Bearer ${this.token}` } }
    );
    const data = await response.json();
    this.onStage3Data(data);
  }

  start() {
    this.interval = setInterval(() => this.checkStatus(), 5000);
  }

  stop() {
    clearInterval(this.interval);
  }
}
```

### React Hook Example

```typescript
import { useState, useEffect } from 'react';

function useStageResults(jobId: string, token: string) {
  const [stage1, setStage1] = useState(null);
  const [stage2, setStage2] = useState(null);
  const [stage3, setStage3] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchResults = async () => {
      try {
        // Try to fetch all stages
        const [r1, r2, r3] = await Promise.allSettled([
          fetch(`/api/v1/pipeline/jobs/${jobId}/stage1/results`, {
            headers: { Authorization: `Bearer ${token}` }
          }).then(r => r.ok ? r.json() : null),
          fetch(`/api/v1/pipeline/jobs/${jobId}/stage2/results`, {
            headers: { Authorization: `Bearer ${token}` }
          }).then(r => r.ok ? r.json() : null),
          fetch(`/api/v1/pipeline/jobs/${jobId}/stage3/results`, {
            headers: { Authorization: `Bearer ${token}` }
          }).then(r => r.ok ? r.json() : null),
        ]);

        if (r1.status === 'fulfilled') setStage1(r1.value);
        if (r2.status === 'fulfilled') setStage2(r2.value);
        if (r3.status === 'fulfilled') setStage3(r3.value);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchResults();
  }, [jobId, token]);

  return { stage1, stage2, stage3, loading, error };
}
```

### Video Player Integration

```typescript
interface VideoSegment {
  id: string;
  url: string;
  start: number;
  end: number;
  text: string;
}

function VideoPlayer({ segments }: { segments: VideoSegment[] }) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);

  const currentSegment = segments[currentIndex];

  return (
    <div>
      <video
        ref={videoRef}
        src={currentSegment.url}
        controls
        onEnded={() => {
          if (currentIndex < segments.length - 1) {
            setCurrentIndex(i => i + 1);
          }
        }}
      />
      <div className="transcript">
        {currentSegment.text}
      </div>
      <div className="segment-info">
        Segment {currentIndex + 1} of {segments.length}
        ({currentSegment.start}s - {currentSegment.end}s)
      </div>
    </div>
  );
}
```

---

## Data Flow Diagram

```
Video Upload
    ↓
[Stage 1: Detection] → bbox_data, segments
    ↓
[Stage 2: ASR] → utterances with ORIGINAL timestamps
    ↓
[Stage 3: Cropping] → utterances with CROPPED timestamps
    ↓
[Annotation Queue]
```

## Common Use Cases

### 1. Display Processing Progress

```javascript
// Show which stages are complete
function getProgress(stage1, stage2, stage3) {
  return [
    { name: 'Detection', complete: !!stage1, progress: 100 },
    { name: 'ASR', complete: !!stage2, progress: stage2 ? 100 : 0 },
    { name: 'Cropping', complete: !!stage3, progress: stage3 ? 100 : 0 },
  ];
}
```

### 2. Quality Dashboard

```javascript
// Calculate quality metrics from Stage 2
function calculateQualityMetrics(stage2Data) {
  const utterances = stage2Data.results.flatMap(r => r.utterances);
  
  return {
    total: utterances.length,
    highConfidence: utterances.filter(u => u.confidence >= 0.9).length,
    mediumConfidence: utterances.filter(u => u.confidence >= 0.7 && u.confidence < 0.9).length,
    lowConfidence: utterances.filter(u => u.confidence < 0.7).length,
    averageConfidence: utterances.reduce((sum, u) => sum + u.confidence, 0) / utterances.length
  };
}
```

### 3. Export Results

```javascript
// Export to CSV format
function exportToCSV(stage3Data) {
  const utterances = stage3Data.results.flatMap(r => r.utterances);
  
  const csv = [
    ['ID', 'Text', 'Start', 'End', 'Duration', 'Confidence'].join(','),
    ...utterances.map(u => [
      u.id,
      `"${u.text.replace(/"/g, '""')}"`,
      u.start.toFixed(2),
      u.end.toFixed(2),
      (u.end - u.start).toFixed(2),
      u.confidence.toFixed(2)
    ].join(','))
  ].join('\n');
  
  return csv;
}
```

---

## Troubleshooting

### Issue: Video URLs Expired

**Symptom**: 403 Forbidden when playing video
**Solution**: Video URLs expire after 1 hour. Re-fetch the stage results to get fresh URLs.

### Issue: Stage Results Not Available

**Symptom**: 400 "Stage not completed"
**Solution**: Check job status first. Results are only available after the stage completes.

### Issue: Large Response Size

**Symptom**: Slow loading for jobs with many segments
**Solution**: Implement pagination on the frontend or lazy-load segment data.
