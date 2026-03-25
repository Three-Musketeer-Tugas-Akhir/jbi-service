---
story_id: "3.8"
story_key: "3-8-asr-confidence-scores"
epic: 3
title: "ASR Confidence Scores"
status: done
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 3.8: ASR Confidence Scores

## Story Header

**Epic:** 3 - Annotation Workflow  
**Story ID:** 3.8  
**Status:** done  
**Priority:** Medium  
**Estimated Effort:** Small (1 day)  
**Dependencies:** 
- Story 2.6: ASR Worker - faster-whisper Integration ✅
- Story 3.6: ASR Review Queue ✅
- Story 3.7: ASR Approval and Flagging ✅

**Reference Documents:**
- [Epics Document](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/epics.md) - Story 3.8 definition, FR49
- [PRD](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/prd.md) - Confidence score visibility, prioritization
- [Architecture](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/architecture.md) - pipeline_segments schema

---

## Story Requirements

### User Story

As a system,  
I want to store and display ASR confidence scores,  
So that reviewers can prioritize low-confidence segments.

### Business Context

This story implements ASR confidence score tracking as specified in FR49. Confidence scores from faster-whisper help prioritize review work by highlighting segments that likely contain transcription errors. This improves efficiency by directing reviewer attention where it's most needed.

**From PRD:** Dewi "sees confidence scores shown for each segment (92%, 87%, 95%)... identifies low-confidence segment at 00:45:30 has 45% confidence" (Journey 3, Steps 2-3).

**From Architecture:** Confidence scores are stored in `pipeline_segments.asr_confidence` and used for queue prioritization.

### Acceptance Criteria

**Given** ASR transcription completes  
**When** results are processed  
**Then** confidence scores are extracted from faster-whisper  
**And** stored in `pipeline_segments.asr_confidence` (0.0 - 1.0)

**Given** a segment has low confidence (< 0.5)  
**When** displayed in ASR Review queue  
**Then** it is sorted higher (priority review)  
**And** flagged as requiring attention

**Given** a segment has high confidence (> 0.9)  
**When** displayed  
**Then** it may be auto-approved (configurable)  
**Or** shown with positive indicator for quick review

**Given** I am an annotator  
**When** I view a segment in annotation queue  
**Then** I see the ASR confidence score  
**And** I understand the transcript may need more attention if low

**Given** I am an admin  
**When** I view system metrics  
**Then** I see average ASR confidence across all jobs  
**And** I can identify jobs with unusually low confidence

---

## Developer Context

### Architecture Alignment

This story implements the **Confidence-Based Prioritization** pattern:

```
Confidence Score Flow:

faster-whisper
     │
     │ Segment-level confidence
     ▼
pipeline_segments.asr_confidence
     │
     ├─────────────────┬─────────────────┐
     ▼                 ▼                 ▼
ASR Review Queue   Annotation Queue   Admin Metrics
(low first)        (display score)    (avg/min/max)
```

**Key Pattern:** Confidence is extracted at ASR time and used downstream for prioritization and display.

### Technical Requirements

1. **Extraction:** Parse confidence from faster-whisper segment output
2. **Storage:** Float field `asr_confidence` in pipeline_segments
3. **Range:** 0.0 (low confidence) to 1.0 (high confidence)
4. **Sorting:** ASR Review queue orders by confidence ascending
5. **Thresholds:** Configurable for auto-approval (default: 0.9)

---

## Implementation Plan

### Step 1: Update ASR Worker (30 min)

**File:** `app/workers/asr_worker.py` (update)

Extract and store confidence scores from faster-whisper:

```python
async def _process_asr_results(
    self,
    job_id: str,
    segment: PipelineSegment,
    asr_result: dict
) -> None:
    """
    Process ASR results and store with confidence score.
    
    Extracts confidence from faster-whisper output and stores
    in pipeline_segments.asr_confidence field.
    """
    # Extract transcript and timestamps
    transcript = asr_result.get("text", "").strip()
    start_time = asr_result.get("start", 0.0)
    end_time = asr_result.get("end", 0.0)
    
    # Extract confidence score (faster-whisper provides avg_logprob)
    # Convert log probability to confidence (0.0 - 1.0)
    avg_logprob = asr_result.get("avg_logprob", None)
    confidence = self._calculate_confidence(avg_logprob)
    
    # Store in segment
    segment.asr_text = transcript
    segment.asr_start = start_time
    segment.asr_end = end_time
    segment.asr_confidence = confidence
    
    # Flag low confidence for ASR Review
    if confidence is not None and confidence < 0.5:
        segment.asr_review_flag = True
    
    await self.db.flush()
    
    self.logger.info(
        f"ASR processed segment {segment.id}: "
        f"confidence={confidence:.2%}, "
        f"text_length={len(transcript)}"
    )

def _calculate_confidence(self, avg_logprob: Optional[float]) -> Optional[float]:
    """
    Convert faster-whisper avg_logprob to confidence score (0.0 - 1.0).
    
    faster-whisper returns log probabilities which are negative.
    We normalize these to a 0-1 confidence scale.
    
    Args:
        avg_logprob: Average log probability from faster-whisper
        
    Returns:
        Confidence score between 0.0 and 1.0, or None if not available
    """
    if avg_logprob is None:
        return None
    
    # faster-whisper avg_logprob typically ranges from -1.0 (bad) to 0.0 (perfect)
    # We map this to 0.0 - 1.0 confidence
    # -1.0 or worse -> 0.0 confidence
    # 0.0 -> 1.0 confidence
    
    normalized = (avg_logprob + 1.0)  # Shift to 0.0 to 1.0 range
    confidence = max(0.0, min(1.0, normalized))  # Clamp to valid range
    
    return confidence
```

**Verify:**
- Confidence calculated correctly from avg_logprob
- Values clamped to 0.0 - 1.0 range

---

### Step 2: Configuration for Auto-Approval (15 min)

**File:** `app/core/config.py` (append)

```python
    # ASR Confidence Configuration
    asr_confidence_threshold_high: float = Field(
        default=0.9,
        description="Confidence threshold for high-quality ASR (auto-approve eligible)"
    )
    asr_confidence_threshold_low: float = Field(
        default=0.5,
        description="Confidence threshold for low-quality ASR (flag for review)"
    )
    asr_auto_approve_enabled: bool = Field(
        default=False,
        description="Enable auto-approval of high-confidence ASR segments"
    )
```

---

### Step 3: Update Schemas (15 min)

**File:** `app/schemas/segment.py` (update or create)

```python
"""Segment schemas with confidence score."""
from typing import Optional
from pydantic import BaseModel, Field


class SegmentWithConfidence(BaseModel):
    """Segment with ASR confidence information."""
    segment_id: UUID
    asr_text: Optional[str]
    asr_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    # Confidence indicators
    confidence_level: str  # "high", "medium", "low"
    requires_attention: bool
    
    @classmethod
    def from_db_segment(cls, segment):
        """Create from database segment."""
        confidence = segment.asr_confidence
        
        if confidence is None:
            level = "unknown"
            requires_attention = False
        elif confidence >= 0.9:
            level = "high"
            requires_attention = False
        elif confidence >= 0.5:
            level = "medium"
            requires_attention = False
        else:
            level = "low"
            requires_attention = True
        
        return cls(
            segment_id=segment.id,
            asr_text=segment.asr_text,
            asr_confidence=confidence,
            confidence_level=level,
            requires_attention=requires_attention
        )
```

---

### Step 4: Service Layer Enhancement (30 min)

**File:** `app/services/asr_review_service.py` (append)

```python
    async def get_confidence_stats(self) -> dict:
        """
        Get ASR confidence statistics for admin dashboard.
        
        Returns average, min, max confidence across all segments.
        """
        from sqlalchemy import func
        from app.db.models.pipeline import PipelineSegment
        
        result = await self.db.execute(
            select(
                func.avg(PipelineSegment.asr_confidence).label("avg"),
                func.min(PipelineSegment.asr_confidence).label("min"),
                func.max(PipelineSegment.asr_confidence).label("max"),
                func.count(PipelineSegment.id).label("count")
            ).where(
                PipelineSegment.asr_confidence.isnot(None)
            )
        )
        
        row = result.one()
        
        return {
            "average_confidence": round(row.avg, 4) if row.avg else None,
            "min_confidence": round(row.min, 4) if row.min else None,
            "max_confidence": round(row.max, 4) if row.max else None,
            "total_segments": row.count,
            "confidence_distribution": await self._get_confidence_distribution()
        }
    
    async def _get_confidence_distribution(self) -> dict:
        """Get distribution of confidence scores."""
        from sqlalchemy import func, case
        from app.db.models.pipeline import PipelineSegment
        
        result = await self.db.execute(
            select(
                func.sum(case((PipelineSegment.asr_confidence < 0.5, 1), else_=0)).label("low"),
                func.sum(case((PipelineSegment.asr_confidence.between(0.5, 0.8), 1), else_=0)).label("medium"),
                func.sum(case((PipelineSegment.asr_confidence > 0.8, 1), else_=0)).label("high")
            ).where(
                PipelineSegment.asr_confidence.isnot(None)
            )
        )
        
        row = result.one()
        return {
            "low": row.low or 0,
            "medium": row.medium or 0,
            "high": row.high or 0
        }
```

---

### Step 5: Admin Metrics Endpoint (20 min)

**File:** `app/api/v1/admin.py` (append endpoint)

```python
from app.services.asr_review_service import ASRReviewService


@router.get(
    "/metrics/asr-confidence",
    summary="ASR Confidence Metrics",
    description="Get ASR confidence statistics across all jobs."
)
async def get_asr_confidence_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """
    Get ASR confidence metrics for admin dashboard.
    
    Returns:
    - Average confidence across all segments
    - Min/max confidence values
    - Distribution (low/medium/high counts)
    - Total segments processed
    """
    service = ASRReviewService(db)
    stats = await service.get_confidence_stats()
    return stats
```

---

### Step 6: Update Queue Service (15 min)

**File:** `app/services/annotation_queue_service.py` (update)

Include confidence score in queue items:

```python
    async def _build_queue_item(self, entry) -> dict:
        """Build a queue item response with metadata."""
        segment = await self.segment_repo.get_by_id(entry.segment_id)
        job = None
        if segment:
            job = await self.job_repo.get_by_id(segment.job_id)
        
        # ... existing code ...
        
        # Get current transcript
        transcript_text = segment.asr_text if segment else None
        
        # Determine confidence level
        confidence = segment.asr_confidence if segment else None
        confidence_level = "unknown"
        if confidence is not None:
            if confidence >= 0.9:
                confidence_level = "high"
            elif confidence >= 0.5:
                confidence_level = "medium"
            else:
                confidence_level = "low"
        
        return {
            "id": entry.id,
            "segment_id": entry.segment_id,
            "job_id": segment.job_id if segment else None,
            "original_filename": job.original_filename if job else "Unknown",
            "video_preview_url": video_preview_url,
            "status": entry.status,
            "priority": entry.priority,
            "assigned_at": entry.assigned_at,
            "transcript_text": transcript_text,
            "asr_confidence": confidence,
            "confidence_level": confidence_level,
            "requires_attention": confidence_level == "low" if confidence else False
        }
```

---

## Verification Steps

### Manual Testing

1. **Process a video through ASR:**
```bash
# Upload and process video
# Check confidence scores stored
```

2. **Verify confidence in ASR Review queue:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/asr-review/queue
# Verify low confidence segments appear first
```

3. **Verify confidence in Annotation queue:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/queue
# Verify confidence_level field present
```

4. **Get admin metrics:**
```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8000/api/v1/admin/metrics/asr-confidence
```

Expected response:
```json
{
  "average_confidence": 0.8234,
  "min_confidence": 0.2345,
  "max_confidence": 0.9876,
  "total_segments": 150,
  "confidence_distribution": {
    "low": 15,
    "medium": 45,
    "high": 90
  }
}
```

---

## Definition of Done

- [ ] ASR worker extracts confidence from faster-whisper
- [ ] Confidence stored in pipeline_segments.asr_confidence
- [ ] ASR Review queue sorts by confidence (low first)
- [ ] Annotation queue includes confidence in response
- [ ] Confidence level indicators (high/medium/low)
- [ ] Admin metrics endpoint for confidence statistics
- [ ] Configuration for auto-approval threshold
- [ ] Manual testing completed

---

## Notes

### Confidence Calculation

faster-whisper returns `avg_logprob` (average log probability) which is typically:
- 0.0: Perfect confidence (rare)
- -0.1 to -0.3: High confidence
- -0.5 to -0.7: Medium confidence
- -1.0 or lower: Low confidence

We normalize: `confidence = max(0.0, min(1.0, avg_logprob + 1.0))`

### Confidence Levels

| Level | Range | Attention | Color |
|-------|-------|-----------|-------|
| High | >= 0.9 | No | Green |
| Medium | 0.5 - 0.9 | No | Yellow |
| Low | < 0.5 | Yes | Red |

### Future Enhancements

- **Auto-approval:** Segments with confidence > 0.95 could skip ASR Review
- **Per-job thresholds:** Different quality requirements for different content types
- **Confidence visualization:** Charts showing confidence trends over time
- **Model comparison:** Track confidence improvements with ASR model updates
