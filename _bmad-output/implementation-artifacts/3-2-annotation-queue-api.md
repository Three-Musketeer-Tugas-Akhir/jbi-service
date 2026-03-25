---
story_id: "3.2"
story_key: "3-2-annotation-queue-api"
epic: 3
title: "Annotation Queue API"
status: done
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 3.2: Annotation Queue API

## Story Header

**Epic:** 3 - Annotation Workflow  
**Story ID:** 3.2  
**Status:** done  
**Priority:** High  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 3.1: Database Schema - Annotation Domain ✅

---

## Story Requirements

### User Story

As an annotator,  
I want to see my assigned annotation queue,  
So that I know which videos need my attention.

### Business Context

This story provides the API foundation for the annotator's primary interface. The annotation queue shows annotators what work is assigned to them and allows them to start working on segments. It integrates with the storage layer to provide pre-signed URLs for video access.

### Acceptance Criteria

**Given** I am authenticated as an annotator  
**And** segments are assigned to me in annotation_queue  
**When** I GET `/api/v1/annotations/queue`  
**Then** I receive a list of segments assigned to me:
  - segment_id, video_preview_url, status, priority, assigned_at
  - job metadata (original video name, duration)
  - current transcript text

**Given** I have segments in my queue  
**When** I GET `/api/v1/annotations/queue` with filter `status=assigned`  
**Then** I see only segments not yet started

**Given** I click on a segment to annotate  
**When** I GET `/api/v1/segments/{segment_id}`  
**Then** I receive complete segment details:
  - video_url (pre-signed, 1hr expiry)
  - asr_text, asr_start, asr_end
  - jbi_start, jbi_end (final timestamps)
  - previous edits history (if any)
  - ASR confidence score

**Given** no segments are assigned to me  
**When** I view my queue  
**Then** I see empty state message: "No annotations assigned. Check back later!"

**Given** I am a curator  
**When** I attempt to access annotator queue  
**Then** I receive 403 response (different endpoint for curators)

---

## Developer Context

### Architecture Alignment

This story implements the **Service Layer** pattern:

```
API Layer (router)       → GET /api/v1/annotations/queue
Service Layer            → QueueService.get_annotator_queue()
Repository Layer         → AnnotationQueueRepository
Storage Layer            → MinIO pre-signed URLs
```

**Key Pattern:** Domain-prefixed schemas (`annotation_*`) with proper RBAC enforcement.

### Technical Requirements

1. **RBAC:** Only users with "annotator" role can access their queue
2. **Pre-signed URLs:** MinIO URLs valid for 1 hour (NFR10)
3. **Pagination:** Default 20 items, max 100
4. **Filtering:** By status (assigned, in_progress, completed)
5. **Sorting:** By priority (desc), then assigned_at (asc)

---

## Implementation Plan

### Step 1: Repository Layer (30 min)

**File:** `app/repositories/annotation_queue_repository.py` (new)

```python
"""Annotation queue repository."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationQueue


class AnnotationQueueRepository:
    """Repository for annotation queue operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_annotator(
        self,
        annotator_id: UUID,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[AnnotationQueue]:
        """Get queue entries for an annotator."""
        query = select(AnnotationQueue).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        query = query.order_by(
            AnnotationQueue.priority.desc(),
            AnnotationQueue.assigned_at.asc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_by_segment(self, segment_id: UUID) -> Optional[AnnotationQueue]:
        """Get queue entry by segment ID."""
        query = select(AnnotationQueue).where(
            AnnotationQueue.segment_id == segment_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, queue_id: UUID) -> Optional[AnnotationQueue]:
        """Get queue entry by ID."""
        query = select(AnnotationQueue).where(AnnotationQueue.id == queue_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        queue_id: UUID,
        status: str
    ) -> bool:
        """Update queue entry status."""
        entry = await self.get_by_id(queue_id)
        if not entry:
            return False
        
        entry.status = status
        await self.db.flush()
        return True
    
    async def count_by_annotator(
        self,
        annotator_id: UUID,
        status: Optional[str] = None
    ) -> int:
        """Count queue entries for an annotator."""
        from sqlalchemy import func
        
        query = select(func.count(AnnotationQueue.id)).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        result = await self.db.execute(query)
        return result.scalar()
```

**Verify:**
- Repository methods compile correctly
- Queries use proper indexes (idx_annotation_queue_annotator)

---

### Step 2: Pydantic Schemas (30 min)

**File:** `app/schemas/annotation.py` (new)

```python
"""Annotation domain Pydantic schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ============================================================================
# Queue Item Schemas
# ============================================================================

class QueueItemBase(BaseModel):
    """Base queue item schema."""
    segment_id: UUID
    status: str
    priority: int
    assigned_at: datetime
    due_date: Optional[datetime] = None


class QueueItemResponse(QueueItemBase):
    """Queue item response with metadata."""
    id: UUID
    job_id: UUID
    original_filename: str
    video_preview_url: str
    transcript_text: Optional[str] = None
    asr_confidence: Optional[float] = None
    
    class Config:
        from_attributes = True


class QueueListResponse(BaseModel):
    """Paginated queue list response."""
    items: List[QueueItemResponse]
    total: int
    page: int
    page_size: int
    pages: int


# ============================================================================
# Segment Detail Schemas
# ============================================================================

class SegmentEditHistory(BaseModel):
    """Edit history entry for segment."""
    edit_id: UUID
    old_text: Optional[str]
    new_text: str
    old_start: Optional[float]
    new_start: float
    old_end: Optional[float]
    new_end: float
    edited_at: datetime
    status: str


class SegmentDetailResponse(BaseModel):
    """Complete segment details for annotation interface."""
    segment_id: UUID
    job_id: UUID
    original_filename: str
    
    # Video
    video_url: str
    video_duration: Optional[float] = None
    
    # ASR Data
    asr_text: Optional[str]
    asr_start: Optional[float]
    asr_end: Optional[float]
    asr_confidence: Optional[float]
    
    # JBI Timestamps (final)
    jbi_start: Optional[float]
    jbi_end: Optional[float]
    
    # Current State
    current_text: str
    current_start: float
    current_end: float
    
    # Edit History
    edit_history: List[SegmentEditHistory]
    
    # Queue Info
    queue_status: str
    priority: int
    
    class Config:
        from_attributes = True


# ============================================================================
# Filter/Query Schemas
# ============================================================================

class QueueFilterParams(BaseModel):
    """Query parameters for queue filtering."""
    status: Optional[str] = Field(None, pattern="^(ASSIGNED|IN_PROGRESS|COMPLETED)$")
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
```

**Verify:**
- Schemas validate correctly
- Field constraints match database constraints

---

### Step 3: Service Layer (1 hour)

**File:** `app/services/annotation_queue_service.py` (new)

```python
"""Annotation queue service."""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.job_repository import JobRepository
from app.core.storage import minio_service
from app.core.exceptions import NotFoundError, PermissionError


class AnnotationQueueService:
    """Service for annotation queue operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.queue_repo = AnnotationQueueRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.job_repo = JobRepository(db)
    
    async def get_annotator_queue(
        self,
        annotator_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """Get paginated queue for an annotator."""
        offset = (page - 1) * page_size
        
        # Get queue entries
        entries = await self.queue_repo.get_by_annotator(
            annotator_id=annotator_id,
            status=status,
            limit=page_size,
            offset=offset
        )
        
        # Get total count
        total = await self.queue_repo.count_by_annotator(
            annotator_id=annotator_id,
            status=status
        )
        
        # Build response items
        items = []
        for entry in entries:
            item = await self._build_queue_item(entry)
            items.append(item)
        
        pages = (total + page_size - 1) // page_size
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages
        }
    
    async def get_segment_for_annotation(
        self,
        segment_id: UUID,
        annotator_id: UUID
    ) -> dict:
        """Get complete segment details for annotation."""
        # Verify segment is assigned to this annotator
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found in annotation queue")
        
        if queue_entry.annotator_id != annotator_id:
            raise PermissionError("This segment is not assigned to you")
        
        # Get segment details
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Get job details for metadata
        job = await self.job_repo.get_by_id(segment.job_id)
        
        # Generate pre-signed URL
        video_url = None
        if segment.cropped_video_path:
            video_url = await minio_service.generate_presigned_url(
                object_name=segment.cropped_video_path,
                expiry=3600  # 1 hour
            )
        
        # Get edit history
        edit_history = await self._get_edit_history(segment_id)
        
        # Determine current values (latest edit or ASR original)
        current_text, current_start, current_end = await self._get_current_values(
            segment, edit_history
        )
        
        # Update status to IN_PROGRESS if ASSIGNED
        if queue_entry.status == AnnotationQueue.STATUS_ASSIGNED:
            await self.queue_repo.update_status(
                queue_entry.id,
                AnnotationQueue.STATUS_IN_PROGRESS
            )
        
        return {
            "segment_id": segment.id,
            "job_id": segment.job_id,
            "original_filename": job.original_filename if job else "Unknown",
            "video_url": video_url,
            "video_duration": None,  # TODO: Calculate from video metadata
            "asr_text": segment.asr_text,
            "asr_start": segment.asr_start,
            "asr_end": segment.asr_end,
            "asr_confidence": segment.asr_confidence,
            "jbi_start": segment.jbi_start,
            "jbi_end": segment.jbi_end,
            "current_text": current_text,
            "current_start": current_start,
            "current_end": current_end,
            "edit_history": edit_history,
            "queue_status": queue_entry.status,
            "priority": queue_entry.priority
        }
    
    async def _build_queue_item(self, entry) -> dict:
        """Build a queue item response with metadata."""
        segment = await self.segment_repo.get_by_id(entry.segment_id)
        job = None
        if segment:
            job = await self.job_repo.get_by_id(segment.job_id)
        
        # Get preview URL (thumbnail or first frame)
        video_preview_url = ""
        if segment and segment.cropped_video_path:
            video_preview_url = await minio_service.generate_presigned_url(
                object_name=segment.cropped_video_path,
                expiry=3600
            )
        
        # Get current transcript
        transcript_text = segment.asr_text if segment else None
        
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
            "asr_confidence": segment.asr_confidence if segment else None
        }
    
    async def _get_edit_history(self, segment_id: UUID) -> List[dict]:
        """Get edit history for a segment."""
        # TODO: Implement when annotation_edit repository is available
        # For now, return empty list
        return []
    
    async def _get_current_values(
        self,
        segment,
        edit_history: List[dict]
    ) -> Tuple[str, float, float]:
        """Determine current transcript values from edits or ASR."""
        # If there are approved edits, use the latest
        approved_edits = [
            e for e in edit_history
            if e.get("status") == "APPROVED"
        ]
        
        if approved_edits:
            latest = max(approved_edits, key=lambda e: e["edited_at"])
            return (
                latest["new_text"],
                latest["new_start"],
                latest["new_end"]
            )
        
        # Otherwise use ASR values
        return (
            segment.asr_text or "",
            segment.asr_start or 0.0,
            segment.asr_end or 0.0
        )
```

**Verify:**
- Service methods handle all edge cases
- Pre-signed URL generation works with MinIO
- Status transitions are correct

---

### Step 4: API Router (30 min)

**File:** `app/api/v1/endpoints/annotations.py` (new)

```python
"""Annotation API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.db.models.auth import User
from app.services.annotation_queue_service import AnnotationQueueService
from app.schemas.annotation import QueueListResponse, SegmentDetailResponse, QueueFilterParams


router = APIRouter()


@router.get(
    "/queue",
    response_model=QueueListResponse,
    summary="Get annotator's queue",
    description="Returns a paginated list of segments assigned to the current annotator."
)
async def get_annotation_queue(
    status: Optional[str] = Query(
        None,
        description="Filter by status: ASSIGNED, IN_PROGRESS, COMPLETED"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get the annotation queue for the current annotator.
    
    Returns segments assigned to the annotator with metadata
    and pre-signed URLs for video access.
    """
    service = AnnotationQueueService(db)
    result = await service.get_annotator_queue(
        annotator_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size
    )
    return result


@router.get(
    "/segments/{segment_id}",
    response_model=SegmentDetailResponse,
    summary="Get segment for annotation",
    description="Returns complete segment details including video URL and transcript."
)
async def get_segment_for_annotation(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get complete details for a segment to annotate.
    
    Includes:
    - Pre-signed video URL (1 hour expiry)
    - ASR transcript and timestamps
    - Edit history
    - Current values (ASR or latest approved edit)
    """
    service = AnnotationQueueService(db)
    result = await service.get_segment_for_annotation(
        segment_id=segment_id,
        annotator_id=current_user.id
    )
    return result
```

**Verify:**
- Router endpoints are correctly typed
- RBAC decorator restricts to annotators only
- Response models match schema definitions

---

### Step 5: Wire Up Router (10 min)

**File:** `app/api/v1/router.py`

Add the annotations router:

```python
from app.api.v1.endpoints import annotations

# ... existing routers ...

api_router.include_router(
    annotations.router,
    prefix="/annotations",
    tags=["annotations"]
)
```

---

### Step 6: Update Segment Repository (Optional)

**File:** `app/repositories/segment_repository.py`

Ensure `get_by_id` method exists (may already exist from Epic 2):

```python
async def get_by_id(self, segment_id: UUID) -> Optional[PipelineSegment]:
    """Get segment by ID."""
    query = select(PipelineSegment).where(PipelineSegment.id == segment_id)
    result = await self.db.execute(query)
    return result.scalar_one_or_none()
```

---

## Verification Steps

### Manual Testing

1. **Create test data:**
```sql
-- Create a segment and assign to annotator
INSERT INTO annotation_queue (segment_id, annotator_id, status, priority)
VALUES ('segment-uuid', 'annotator-uuid', 'ASSIGNED', 1);
```

2. **Test queue endpoint:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/queue
```

3. **Test segment detail endpoint:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/segments/{segment_id}
```

4. **Verify RBAC:**
```bash
# Should return 403
curl -H "Authorization: Bearer $CURATOR_TOKEN" \
  http://localhost:8000/api/v1/annotations/queue
```

---

## Definition of Done

- [ ] Repository layer with query methods
- [ ] Pydantic schemas for request/response
- [ ] Service layer with business logic
- [ ] API endpoints with RBAC
- [ ] Pre-signed URL generation for videos
- [ ] Pagination and filtering support
- [ ] Manual testing completed

---

## Notes

### Status Transitions

```
ASSIGNED → IN_PROGRESS (when annotator opens segment)
IN_PROGRESS → COMPLETED (when submitted for review - Story 3.5)
```

### Performance Considerations

- Pre-signed URLs are generated on each request (fresh 1-hour expiry)
- Consider caching segment metadata if queue is large
- Database indexes support the queue queries efficiently

### Future Enhancements

- Batch assignment endpoint (for admins)
- Queue statistics endpoint
- Priority override (for urgent segments)
