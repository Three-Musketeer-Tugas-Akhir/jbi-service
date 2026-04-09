# Annotation Synchronization API

## Overview

The Annotation Sync API provides video-audio temporal alignment capabilities for sign language annotation. This solves the **Temporal Asynchrony** problem where sign language (JBI) takes longer to complete than the corresponding spoken audio.

### The Problem

```
Audio (ASR): "Saya makan nasi di restoran" → 5.0s - 10.0s (5 seconds)
JBI Video:   Same sentence in sign language → 5.0s - 12.5s (7.5 seconds)
                                                                  ↑
                                                              2.5s lag!
```

If we cut video at 10.0s (end of audio), the sign for "restoran" is incomplete!

### The Solution

Extend video boundaries beyond original ASR timestamps:

```json
{
  "audio_start": 5.0,
  "audio_end": 10.0,
  "video_start_offset": 4.8,   // Can start earlier
  "video_end_offset": 12.5     // Can end later (capture complete JBI)
}
```

### Key Features

- **Multi-Chunk Video Stitching**: Extend video across segment boundaries
- **Millisecond Precision**: Fine-tune with 33ms precision (1 frame @ 30fps)
- **Sync Status Tracking**: TEXT_MATCH, VIDEO_COMPLETE, SYNC_LOCKED indicators
- **Context View**: See neighboring segments for look-ahead stitching
- **Glosa Support**: Sign language gloss notation

## Base Endpoint

```
/api/v1/annotations/sync
```

---

## Endpoints

### 1. Get Sync Data

```http
GET /api/v1/annotations/sync/{edit_id}
```

#### Description

Retrieve synchronization data for an annotation edit. If sync doesn't exist, returns default values based on annotation timestamps.

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `edit_id` | UUID | Yes | Annotation edit ID |

#### Response Schema

```typescript
interface AnnotationSyncResponse {
  id: string;                          // Sync UUID
  annotation_edit_id: string;          // Edit UUID
  
  // Original ASR timestamps
  audio_start: number;                 // Start time in seconds
  audio_end: number;                   // End time in seconds
  audio_duration: number;              // Calculated duration
  
  // Adjusted video boundaries
  video_start_offset: number | null;   // May be earlier than audio_start
  video_end_offset: number | null;     // May be later than audio_end
  video_duration: number;              // Duration after adjustment
  extension_seconds: number;           // Total extension beyond audio
  
  // Sync metadata
  sync_status: 'UNSYNCED' | 'PARTIAL' | 'SYNCED' | 'LOCKED';
  glosa: string | null;                // Sign language gloss
  precision_ms: number;                // Precision setting (default 33ms)
  
  // Quality indicators
  indicators: {
    text_match: boolean;               // Text aligns with audio
    video_complete: boolean;           // JBI fully captured
    sync_locked: boolean;              // Alignment finalized
  };
  
  created_at: string;                  // ISO 8601
  updated_at: string;                  // ISO 8601
}
```

#### Example Response

```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440000",
  "annotation_edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "audio_start": 5.0,
  "audio_end": 10.0,
  "audio_duration": 5.0,
  "video_start_offset": 4.8,
  "video_end_offset": 12.5,
  "video_duration": 7.7,
  "extension_seconds": 2.7,
  "sync_status": "SYNCED",
  "glosa": "SAYA MAKAN NASI RESTORAN",
  "precision_ms": 33.0,
  "indicators": {
    "text_match": true,
    "video_complete": true,
    "sync_locked": true
  },
  "created_at": "2026-04-08T10:00:00.000Z",
  "updated_at": "2026-04-08T14:30:00.000Z"
}
```

---

### 2. Update Sync Boundaries

```http
PUT /api/v1/annotations/sync/{edit_id}
```

#### Description

Update video boundaries for synchronization. Use this to extend or adjust video start/end times.

#### Request Body

```typescript
interface AnnotationSyncUpdateRequest {
  video_start_offset?: number;   // Video start time in seconds
  video_end_offset?: number;     // Video end time in seconds
  glosa?: string;                // Sign language gloss
  precision_ms?: number;         // Precision in milliseconds
}
```

#### Validation Rules

- `video_end_offset` must be > `video_start_offset`
- Maximum extension: 5 seconds beyond original boundaries
- Minimum duration: 0.5 seconds

#### Example Request

```http
PUT /api/v1/annotations/sync/bb0e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{
  "video_end_offset": 12.5,
  "glosa": "SAYA MAKAN NASI RESTORAN"
}
```

#### Example Response

```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440000",
  "annotation_edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "audio_start": 5.0,
  "audio_end": 10.0,
  "audio_duration": 5.0,
  "video_start_offset": 4.8,
  "video_end_offset": 12.5,
  "video_duration": 7.7,
  "extension_seconds": 2.7,
  "sync_status": "PARTIAL",
  "glosa": "SAYA MAKAN NASI RESTORAN",
  "precision_ms": 33.0,
  "indicators": {
    "text_match": false,
    "video_complete": false,
    "sync_locked": false
  },
  "created_at": "2026-04-08T10:00:00.000Z",
  "updated_at": "2026-04-08T14:35:00.000Z"
}
```

---

### 3. Fine-Tune Sync

```http
POST /api/v1/annotations/sync/{edit_id}/fine-tune
```

#### Description

Fine-tune synchronization with millisecond precision. Use for small adjustments after initial boundary setting.

#### Request Body

```typescript
interface AnnotationSyncFineTuneRequest {
  adjustment_ms: number;     // Adjustment in milliseconds (+/-)
  target: 'start' | 'end' | 'both';  // Which boundary to adjust
}
```

#### Adjustment Limits

- Range: ±5000ms (±5 seconds)
- Recommended step: ±100ms for buttons

#### Example Request

```http
POST /api/v1/annotations/sync/bb0e8400-e29b-41d4-a716-446655440000/fine-tune
Content-Type: application/json

{
  "adjustment_ms": 100,
  "target": "end"
}
```

#### Example Response

```json
{
  "edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "adjustment_ms": 100,
  "previous_start": 4.8,
  "previous_end": 12.5,
  "new_start": 4.8,
  "new_end": 12.6,
  "video_duration": 7.8,
  "message": "Adjusted end by 100ms"
}
```

#### UI Button Pattern

```typescript
// Fine-tune button component
<FineTuneButtons
  onAdjust={(ms) => fineTune(editId, ms, 'end')}
  precision={sync.precision_ms}
/>

// Renders: [-500ms] [-100ms] [+100ms] [+500ms]
```

---

### 4. Validate Sync

```http
POST /api/v1/annotations/sync/{edit_id}/validate
```

#### Description

Validate synchronization and update quality indicators. This sets the TEXT_MATCH, VIDEO_COMPLETE, and SYNC_LOCKED status flags.

#### Request Body

```typescript
interface AnnotationSyncValidateRequest {
  text_match: boolean;       // Text aligns with audio
  video_complete: boolean;   // JBI fully captured
  sync_locked: boolean;      // Alignment finalized
}
```

#### Sync Status Logic

| text_match | video_complete | sync_locked | sync_status |
|------------|----------------|-------------|-------------|
| false | false | false | UNSYNCED |
| true | false | false | PARTIAL |
| false | true | false | PARTIAL |
| true | true | false | SYNCED |
| any | any | true | LOCKED |

#### Example Request

```http
POST /api/v1/annotations/sync/bb0e8400-e29b-41d4-a716-446655440000/validate
Content-Type: application/json

{
  "text_match": true,
  "video_complete": true,
  "sync_locked": true
}
```

#### Example Response

```json
{
  "edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "is_valid": true,
  "sync_status": "LOCKED",
  "indicators": {
    "text_match": true,
    "video_complete": true,
    "sync_locked": true
  },
  "warnings": [],
  "suggestions": []
}
```

---

### 5. Get Stitched Preview

```http
GET /api/v1/annotations/sync/{edit_id}/preview
```

#### Description

Get preview URL for stitched video with sync adjustments applied. If boundaries extend beyond original segment, video is stitched from multiple chunks.

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `buffer_seconds` | float | No | Buffer time for stitching (default: 2.0) |

#### Response Schema

```typescript
interface StitchPreviewResponse {
  edit_id: string;
  segment_id: string;
  
  // Time ranges
  original_start: number;      // Original audio start
  original_end: number;        // Original audio end
  stitched_start: number;      // Adjusted video start
  stitched_end: number;        // Adjusted video end
  total_duration: number;
  
  // Video URL
  video_url: string;           // Pre-signed URL (1 hour expiry)
  
  // Stitching info
  requires_stitching: boolean; // True if multi-chunk
  stitched_segments: Array<{
    segment_id: string;
    start: number;
    end: number;
    url: string;
  }>;
  
  // Sync info
  sync_status: string;
  extension_seconds: number;
}
```

#### Example Response

```json
{
  "edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "segment_id": "cc0e8400-e29b-41d4-a716-446655440000",
  "original_start": 5.0,
  "original_end": 10.0,
  "stitched_start": 4.8,
  "stitched_end": 12.5,
  "total_duration": 7.7,
  "video_url": "https://minio.example.com/videos/stitched/...",
  "requires_stitching": true,
  "stitched_segments": [
    {
      "segment_id": "cc0e8400-e29b-41d4-a716-446655440000",
      "start": 4.8,
      "end": 10.0,
      "url": "/api/v1/assets/jobs/.../segment_0000.mp4"
    },
    {
      "segment_id": "cc0e8400-e29b-41d4-a716-446655440001",
      "start": 10.0,
      "end": 12.5,
      "url": "/api/v1/assets/jobs/.../segment_0001.mp4"
    }
  ],
  "sync_status": "SYNCED",
  "extension_seconds": 2.7
}
```

---

### 6. Get Timeline Range

```http
GET /api/v1/annotations/sync/{edit_id}/timeline
```

#### Description

Get timeline configuration for the sync editor. Returns range slider bounds and step size.

#### Response Schema

```typescript
interface TimelineRangeResponse {
  edit_id: string;
  
  // Audio range (fixed)
  audio_start: number;
  audio_end: number;
  
  // Video range (adjustable)
  video_start: number;
  video_end: number;
  
  // Playback state
  playhead_position: number;   // Current play position
  text_overlay: string;        // Current text
  
  // Slider configuration
  min_bound: number;           // Minimum allowed boundary
  max_bound: number;           // Maximum allowed boundary
  step: number;                // Step size in seconds
}
```

#### Example Response

```json
{
  "edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "audio_start": 5.0,
  "audio_end": 10.0,
  "video_start": 4.8,
  "video_end": 12.5,
  "playhead_position": 5.0,
  "text_overlay": "Saya makan nasi di restoran",
  "min_bound": 0.0,
  "max_bound": 15.0,
  "step": 0.033
}
```

---

### 7. Get Sync Context

```http
GET /api/v1/annotations/sync/segments/{segment_id}/context
```

#### Description

Get synchronization data with surrounding segment context. Useful for look-ahead stitching and context-aware editing.

#### Path Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `segment_id` | UUID | Yes | Segment ID |

#### Query Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `context_range` | integer | No | Neighboring segments (default: 2, max: 5) |

#### Response Schema

```typescript
interface AnnotationSyncContextResponse {
  // Current segment
  segment_id: string;
  transcript_id: string;
  edit_id: string;
  text: string;
  
  // Sync data
  sync: AnnotationSyncResponse;
  
  // Context
  previous_segments: SyncContextItem[];
  next_segments: SyncContextItem[];
  
  // Visual data
  video_url: string | null;
  waveform_data: number[] | null;  // Audio waveform samples
}

interface SyncContextItem {
  segment_id: string;
  transcript_id: string;
  text: string;
  audio_start: number;
  audio_end: number;
  video_available: boolean;
  has_sync_data: boolean;
}
```

---

### 8. Merge with Adjacent Segment

```http
POST /api/v1/annotations/sync/{edit_id}/merge
```

#### Description

Merge video boundaries with adjacent segment for significant extensions.

#### Request Body

```typescript
interface MergeSegmentRequest {
  direction: 'next' | 'prev';
  reason?: string;
}
```

#### Response

```json
{
  "edit_id": "bb0e8400-e29b-41d4-a716-446655440000",
  "merged": true,
  "new_boundaries": {
    "start": 4.8,
    "end": 15.2
  },
  "video_url": "https://minio.example.com/...",
  "message": "Merged with next segment (segment_0001)"
}
```

---

## Frontend Integration Guide

### Complete Sync Workbench Component

```tsx
import React, { useState, useEffect, useRef } from 'react';
import { 
  Play, Pause, SkipBack, SkipForward, 
  ChevronLeft, ChevronRight, Lock, Unlock,
  CheckCircle, AlertCircle
} from 'lucide-react';

interface SyncWorkbenchProps {
  editId: string;
  token: string;
}

export function SyncWorkbench({ editId, token }: SyncWorkbenchProps) {
  const [sync, setSync] = useState<AnnotationSyncResponse | null>(null);
  const [preview, setPreview] = useState<StitchPreviewResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Load sync data
  useEffect(() => {
    fetchSyncData();
  }, [editId]);

  const fetchSyncData = async () => {
    const response = await fetch(
      `/api/v1/annotations/sync/${editId}`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const data = await response.json();
    setSync(data);
  };

  const loadPreview = async () => {
    const response = await fetch(
      `/api/v1/annotations/sync/${editId}/preview`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const data = await response.json();
    setPreview(data);
  };

  // Fine-tune handlers
  const handleFineTune = async (ms: number, target: 'start' | 'end') => {
    setLoading(true);
    const response = await fetch(
      `/api/v1/annotations/sync/${editId}/fine-tune`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ adjustment_ms: ms, target })
      }
    );
    const data = await response.json();
    await fetchSyncData();
    await loadPreview();
    setLoading(false);
  };

  // Validate and lock
  const handleValidate = async () => {
    const response = await fetch(
      `/api/v1/annotations/sync/${editId}/validate`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          text_match: true,
          video_complete: true,
          sync_locked: true
        })
      }
    );
    await fetchSyncData();
  };

  if (!sync) return <div>Loading...</div>;

  return (
    <div className="sync-workbench">
      {/* Header */}
      <div className="sync-header">
        <h2>Sync Workbench</h2>
        <SyncStatusBadge status={sync.sync_status} indicators={sync.indicators} />
      </div>

      {/* Video Player */}
      <div className="video-container">
        <video
          ref={videoRef}
          src={preview?.video_url}
          controls
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        
        {/* Playhead indicator */}
        <div className="playhead-indicator">
          <span className="current-time">{formatTime(videoRef.current?.currentTime || 0)}</span>
          <span className="text-overlay">{sync.glosa}</span>
        </div>
      </div>

      {/* Timeline Range Slider */}
      <div className="timeline-section">
        <h3>Timeline Adjustment</h3>
        
        <div className="range-slider">
          {/* Audio range (fixed, gray) */}
          <div 
            className="audio-range"
            style={{
              left: `${(sync.audio_start / 20) * 100}%`,
              width: `${((sync.audio_end - sync.audio_start) / 20) * 100}%`
            }}
          >
            <span className="audio-label">Audio: {formatTime(sync.audio_start)} - {formatTime(sync.audio_end)}</span>
          </div>
          
          {/* Video range (adjustable, blue) */}
          <div 
            className="video-range"
            style={{
              left: `${((sync.video_start_offset || sync.audio_start) / 20) * 100}%`,
              width: `${(sync.video_duration / 20) * 100}%`
            }}
          >
            <span className="video-label">
              Video: {formatTime(sync.video_start_offset || sync.audio_start)} - {formatTime(sync.video_end_offset || sync.audio_end)}
            </span>
            
            {/* Drag handles */}
            <div className="handle start" onMouseDown={(e) => handleDragStart(e, 'start')} />
            <div className="handle end" onMouseDown={(e) => handleDragStart(e, 'end')} />
          </div>
        </div>

        {/* Extension indicator */}
        {sync.extension_seconds > 0 && (
          <div className="extension-badge">
            +{sync.extension_seconds.toFixed(1)}s extension beyond audio
          </div>
        )}
      </div>

      {/* Fine-tune controls */}
      <div className="fine-tune-section">
        <h4>Fine-Tune (±{sync.precision_ms}ms steps)</h4>
        
        <div className="tune-buttons">
          <div className="start-controls">
            <span>Start:</span>
            <button onClick={() => handleFineTune(-500, 'start')}>-500ms</button>
            <button onClick={() => handleFineTune(-100, 'start')}>-100ms</button>
            <button onClick={() => handleFineTune(100, 'start')}>+100ms</button>
            <button onClick={() => handleFineTune(500, 'start')}>+500ms</button>
          </div>
          
          <div className="end-controls">
            <span>End:</span>
            <button onClick={() => handleFineTune(-500, 'end')}>-500ms</button>
            <button onClick={() => handleFineTune(-100, 'end')}>-100ms</button>
            <button onClick={() => handleFineTune(100, 'end')}>+100ms</button>
            <button onClick={() => handleFineTune(500, 'end')}>+500ms</button>
          </div>
        </div>
      </div>

      {/* Glosa input */}
      <div className="glosa-section">
        <h4>Glosa (Sign Language Gloss)</h4>
        <input
          type="text"
          value={sync.glosa || ''}
          onChange={(e) => handleGlosaChange(e.target.value)}
          placeholder="e.g., SAYA MAKAN NASI RESTORAN"
        />
      </div>

      {/* Sync indicators */}
      <div className="indicators-section">
        <h4>Sync Quality</h4>
        
        <div className="indicator-list">
          <label className="indicator">
            <input 
              type="checkbox" 
              checked={sync.indicators.text_match}
              onChange={(e) => handleIndicatorChange('text_match', e.target.checked)}
            />
            <CheckCircle className={sync.indicators.text_match ? 'checked' : ''} />
            <span>TEXT_MATCH - Text aligns with audio</span>
          </label>
          
          <label className="indicator">
            <input 
              type="checkbox" 
              checked={sync.indicators.video_complete}
              onChange={(e) => handleIndicatorChange('video_complete', e.target.checked)}
            />
            <CheckCircle className={sync.indicators.video_complete ? 'checked' : ''} />
            <span>VIDEO_COMPLETE - JBI fully captured</span>
          </label>
          
          <label className="indicator">
            <input 
              type="checkbox" 
              checked={sync.indicators.sync_locked}
              onChange={(e) => handleIndicatorChange('sync_locked', e.target.checked)}
            />
            <Lock className={sync.indicators.sync_locked ? 'locked' : ''} />
            <span>SYNC_LOCKED - Alignment finalized</span>
          </label>
        </div>
      </div>

      {/* Actions */}
      <div className="actions">
        <button onClick={loadPreview} disabled={loading}>
          {loading ? 'Loading...' : 'Preview'}
        </button>
        
        <button 
          onClick={handleValidate}
          disabled={!sync.indicators.text_match || !sync.indicators.video_complete}
          className="primary"
        >
          Lock Sync
        </button>
      </div>
    </div>
  );
}

// Helper components
function SyncStatusBadge({ status, indicators }: { status: string, indicators: any }) {
  const getColor = () => {
    if (status === 'LOCKED') return 'green';
    if (status === 'SYNCED') return 'blue';
    if (status === 'PARTIAL') return 'orange';
    return 'gray';
  };

  return (
    <span className={`status-badge ${getColor()}`}>
      {status}
    </span>
  );
}

function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.floor((seconds % 1) * 1000);
  return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
}
```

### CSS Styling

```css
.sync-workbench {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.sync-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.video-container {
  position: relative;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
}

.video-container video {
  width: 100%;
  max-height: 500px;
}

.playhead-indicator {
  position: absolute;
  bottom: 60px;
  left: 0;
  right: 0;
  text-align: center;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 10px;
}

.timeline-section {
  margin: 20px 0;
  padding: 20px;
  background: #f5f5f5;
  border-radius: 8px;
}

.range-slider {
  position: relative;
  height: 60px;
  background: #ddd;
  border-radius: 4px;
  overflow: hidden;
}

.audio-range {
  position: absolute;
  top: 10px;
  height: 40px;
  background: #999;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: white;
}

.video-range {
  position: absolute;
  top: 10px;
  height: 40px;
  background: #3b82f6;
  border-radius: 4px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: white;
}

.handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 10px;
  background: rgba(255, 255, 255, 0.5);
  cursor: ew-resize;
}

.handle.start { left: 0; }
.handle.end { right: 0; }

.extension-badge {
  margin-top: 10px;
  padding: 8px 12px;
  background: #fef3c7;
  color: #92400e;
  border-radius: 4px;
  font-size: 14px;
}

.fine-tune-section {
  margin: 20px 0;
}

.tune-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.tune-buttons > div {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tune-buttons button {
  padding: 8px 16px;
  border: 1px solid #ddd;
  background: white;
  border-radius: 4px;
  cursor: pointer;
}

.tune-buttons button:hover {
  background: #f5f5f5;
}

.indicator-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.indicator {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px;
  background: #f9fafb;
  border-radius: 4px;
  cursor: pointer;
}

.indicator input {
  display: none;
}

.indicator svg {
  width: 20px;
  height: 20px;
}

.indicator svg.checked {
  color: #10b981;
}

.indicator svg.locked {
  color: #3b82f6;
}
```

---

## Common Use Cases

### 1. Initial Sync Setup

```typescript
async function initializeSync(editId: string, token: string) {
  // Get current sync data (creates default if not exists)
  const syncResponse = await fetch(`/api/v1/annotations/sync/${editId}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const sync = await syncResponse.json();
  
  // If video is longer than audio, extend boundaries
  if (needsExtension(sync)) {
    await fetch(`/api/v1/annotations/sync/${editId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        video_end_offset: sync.audio_end + 2.5  // Extend by 2.5s
      })
    });
  }
  
  // Load preview
  const previewResponse = await fetch(
    `/api/v1/annotations/sync/${editId}/preview`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  
  return previewResponse.json();
}
```

### 2. Quick Fine-Tune Pattern

```typescript
function QuickTunePanel({ editId, token, sync }: { editId: string, token: string, sync: any }) {
  const adjust = async (ms: number) => {
    await fetch(`/api/v1/annotations/sync/${editId}/fine-tune`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        adjustment_ms: ms,
        target: 'end'
      })
    });
    // Refresh data
    window.location.reload();
  };

  return (
    <div className="quick-tune">
      <button onClick={() => adjust(-100)}>◀ 100ms</button>
      <button onClick={() => adjust(100)}>100ms ▶</button>
    </div>
  );
}
```

### 3. Context-Aware Stitching

```typescript
async function checkStitchingNeeded(editId: string, segmentId: string, token: string) {
  // Get context
  const contextResponse = await fetch(
    `/api/v1/annotations/sync/segments/${segmentId}/context?context_range=2`,
    { headers: { Authorization: `Bearer ${token}` } }
  );
  const context = await contextResponse.json();
  
  // Check if next segment is needed
  const sync = context.sync;
  const nextSegment = context.next_segments[0];
  
  if (sync.video_end_offset > sync.audio_end && nextSegment) {
    console.log('Stitching with next segment:', nextSegment.segment_id);
    return true;
  }
  
  return false;
}
```

---

## Troubleshooting

### Issue: Video Not Extending

**Symptom**: After setting `video_end_offset`, video still cuts at original end
**Solution**: Check if next segment video is available. May need to wait for Stage 3 (cropping) to complete.

### Issue: Sync Status Not Updating

**Symptom**: Status stays UNSYNCED after setting indicators
**Solution**: Call `/validate` endpoint after setting indicators, not just PUT to `/sync`.

### Issue: Fine-tune Not Working

**Symptom**: 422 error on fine-tune
**Solution**: Adjustment exceeds ±5000ms limit. Use PUT `/sync` for large adjustments.

---

## Best Practices

1. **Always Preview**: Call `/preview` after boundary changes before locking
2. **Increment Fine-tune**: Use ±100ms buttons for precision, ±500ms for coarse
3. **Set Glosa Early**: Write glosa before fine-tuning to verify sign coverage
4. **Check Context**: Use `/context` to see if stitching will be needed
5. **Lock When Done**: Set SYNC_LOCKED only after complete verification
