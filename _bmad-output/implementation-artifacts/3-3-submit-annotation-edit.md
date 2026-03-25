---
story_id: "3.3"
story_key: "3-3-submit-annotation-edit"
epic: 3
title: "Submit Annotation Edit"
status: ready-for-dev
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 3.3: Submit Annotation Edit

## Story Header

**Epic:** 3 - Annotation Workflow  
**Story ID:** 3.3  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 3.1: Database Schema - Annotation Domain ✅
- Story 3.2: Annotation Queue API ✅

---

## Story Requirements

### User Story

As an annotator,  
I want to edit transcript text and timestamps,  
So that I can correct synchronization errors.

### Business Context

This story enables annotators to make corrections to ASR-generated transcripts and timestamps. The system preserves the complete audit trail by storing both old and new values, allowing curators to review what changes were made.

### Acceptance Criteria

**Given** I am viewing a segment  
**When** I POST `/api/v1/annotations/{segment_id}/edits` with:
  - new_text: "corrected transcript"
  - new_start: 12.5 (seconds)
  - new_end: 18.3 (seconds)  
**Then** an annotation_edits record is created  
**And** old values are preserved for change tracking  
**And** I receive 201 response with edit_id

**Given** I edit the transcript text  
**When** changes are saved  
**Then** the system records:
  - old_text (from ASR or previous edit)
  - new_text (my correction)
  - editor_id (my user id)
  - edited_at timestamp

**Given** I adjust timestamps using draggable handles  
**When** I save the annotation  
**Then** new_start and new_end are saved  
**And** old_start and old_end are preserved  
**And** changes are validated (start < end, within video bounds)

**Given** I submit an edit with invalid timestamps  
**When** validation fails  
**Then** I receive 400 response with error:
  - "Start time must be less than end time"
  - or "Timestamps must be within video duration"

**Given** I have made multiple edits to the same segment  
**When** I view the segment  
**Then** I see the most recent edit applied  
**And** edit history is available for reference

---

## Developer Context

### Architecture Alignment

This story implements the **Edit Tracking** pattern:

```
API Layer (router)       → POST /api/v1/annotations/{id}/edits
Service Layer            → AnnotationEditService.create_edit()
Repository Layer         → AnnotationEditRepository
Validation Layer         → Timestamp bounds checking
```

**Key Pattern:** Immutable edit history with soft delete support.

### Technical Requirements

1. **Validation:** Timestamps must satisfy: `0 <= start < end <= video_duration`
2. **Audit Trail:** Preserve old values from ASR or previous edit
3. **Idempotent:** Multiple edits create new records, don't update existing
4. **RBAC:** Only assigned annotator can create edits for a segment

---

## Implementation Plan

### Step 1: Repository Layer (30 min)

**File:** `app/repositories/annotation_edit_repository.py` (new)

```python
"""Annotation edit repository."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationEdit


class AnnotationEditRepository:
    """Repository for annotation edit operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, edit: AnnotationEdit) -> AnnotationEdit:
        """Create a new annotation edit."""
        self.db.add(edit)
        await self.db.flush()
        await self.db.refresh(edit)
        return edit
    
    async def get_by_id(self, edit_id: UUID) -> Optional[AnnotationEdit]:
        """Get edit by ID."""
        query = select(AnnotationEdit).where(AnnotationEdit.id == edit_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_segment(
        self,
        segment_id: UUID,
        include_deleted: bool = False
    ) -> List[AnnotationEdit]:
        """Get all edits for a segment, ordered by most recent first."""
        query = select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id
        )
        
        if not include_deleted:
            query = query.where(AnnotationEdit.is_deleted == False)
        
        query = query.order_by(desc(AnnotationEdit.edited_at))
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_latest_by_segment(
        self,
        segment_id: UUID,
        include_deleted: bool = False
    ) -> Optional[AnnotationEdit]:
        """Get the most recent edit for a segment."""
        query = select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id
        )
        
        if not include_deleted:
            query = query.where(AnnotationEdit.is_deleted == False)
        
        query = query.order_by(desc(AnnotationEdit.edited_at)).limit(1)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def soft_delete(self, edit_id: UUID) -> bool:
        """Soft delete an edit (preserves history)."""
        edit = await self.get_by_id(edit_id)
        if not edit:
            return False
        
        edit.is_deleted = True
        await self.db.flush()
        return True
```

**Verify:**
- Repository methods compile correctly
- Queries use proper indexes (idx_annotation_edits_segment)

---

### Step 2: Pydantic Schemas (30 min)

**File:** `app/schemas/annotation.py` (append to existing)

```python
# ============================================================================
# Annotation Edit Schemas
# ============================================================================

class AnnotationEditCreate(BaseModel):
    """Schema for creating a new annotation edit."""
    new_text: str = Field(..., min_length=1, description="Corrected transcript text")
    new_start: float = Field(..., ge=0, description="New start time in seconds")
    new_end: float = Field(..., gt=0, description="New end time in seconds")
    
    @model_validator(mode='after')
    def validate_timestamps(self):
        """Validate that start < end."""
        if self.new_start >= self.new_end:
            raise ValueError("Start time must be less than end time")
        return self


class AnnotationEditResponse(BaseModel):
    """Response schema for annotation edit."""
    id: UUID
    segment_id: UUID
    editor_id: Optional[UUID]
    
    # Old values
    old_text: Optional[str]
    old_start: Optional[float]
    old_end: Optional[float]
    
    # New values
    new_text: str
    new_start: float
    new_end: float
    
    # Metadata
    status: str
    is_deleted: bool
    edited_at: datetime
    submitted_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class AnnotationEditListResponse(BaseModel):
    """Response schema for list of edits."""
    segment_id: UUID
    edits: List[AnnotationEditResponse]
    total: int
```

**Verify:**
- Schemas validate correctly
- Timestamp validation works as expected

---

### Step 3: Service Layer (1 hour)

**File:** `app/services/annotation_edit_service.py` (new)

```python
"""Annotation edit service."""
from typing import Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.segment_repository import SegmentRepository
from app.core.exceptions import NotFoundError, PermissionError, ValidationError
from app.db.models.annotation import AnnotationEdit, AnnotationQueue


class AnnotationEditService:
    """Service for annotation edit operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.edit_repo = AnnotationEditRepository(db)
        self.queue_repo = AnnotationQueueRepository(db)
        self.segment_repo = SegmentRepository(db)
    
    async def create_edit(
        self,
        segment_id: UUID,
        editor_id: UUID,
        new_text: str,
        new_start: float,
        new_end: float
    ) -> AnnotationEdit:
        """
        Create a new annotation edit for a segment.
        
        Args:
            segment_id: The segment being edited
            editor_id: The user making the edit
            new_text: Corrected transcript text
            new_start: New start timestamp
            new_end: New end timestamp
            
        Returns:
            The created AnnotationEdit
            
        Raises:
            NotFoundError: If segment not found or not assigned
            PermissionError: If editor is not assigned to segment
            ValidationError: If timestamps are invalid
        """
        # Verify segment is assigned to this editor
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(
                f"Segment {segment_id} not found in annotation queue"
            )
        
        if queue_entry.annotator_id != editor_id:
            raise PermissionError(
                "You are not assigned to edit this segment"
            )
        
        # Get segment for validation
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Validate timestamps against video bounds
        # Use JBI timestamps as bounds if available, otherwise use ASR
        min_time = 0.0
        max_time = segment.jbi_end or segment.asr_end or new_end
        
        if new_start < min_time:
            raise ValidationError(
                f"Start time ({new_start}) must be at least {min_time}"
            )
        
        if new_end > max_time:
            raise ValidationError(
                f"End time ({new_end}) must not exceed video duration ({max_time})"
            )
        
        if new_start >= new_end:
            raise ValidationError("Start time must be less than end time")
        
        # Determine old values (from ASR or previous edit)
        old_text, old_start, old_end = await self._get_current_values(segment_id)
        
        # Create the edit
        edit = AnnotationEdit(
            segment_id=segment_id,
            editor_id=editor_id,
            old_text=old_text,
            old_start=old_start,
            old_end=old_end,
            new_text=new_text,
            new_start=new_start,
            new_end=new_end,
            status=AnnotationEdit.STATUS_PENDING,
            is_deleted=False,
            edited_at=datetime.utcnow()
        )
        
        created_edit = await self.edit_repo.create(edit)
        return created_edit
    
    async def get_edit_history(
        self,
        segment_id: UUID,
        user_id: UUID
    ) -> List[AnnotationEdit]:
        """
        Get edit history for a segment.
        
        Args:
            segment_id: The segment to get history for
            user_id: The requesting user (for permission check)
            
        Returns:
            List of edits ordered by most recent first
        """
        # Verify access (must be assigned annotator or admin)
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # TODO: Check if user is admin for full access
        if queue_entry.annotator_id != user_id:
            raise PermissionError(
                "You can only view edit history for your assigned segments"
            )
        
        return await self.edit_repo.get_by_segment(segment_id)
    
    async def _get_current_values(
        self,
        segment_id: UUID
    ) -> tuple[Optional[str], Optional[float], Optional[float]]:
        """
        Get current values for a segment (from latest edit or ASR).
        
        Returns:
            Tuple of (text, start, end) - values that will become 'old' values
        """
        # Check for most recent non-deleted edit
        latest_edit = await self.edit_repo.get_latest_by_segment(segment_id)
        if latest_edit:
            return (
                latest_edit.new_text,
                latest_edit.new_start,
                latest_edit.new_end
            )
        
        # No edits yet, use ASR values from segment
        segment = await self.segment_repo.get_by_id(segment_id)
        if segment:
            return (
                segment.asr_text,
                segment.asr_start,
                segment.asr_end
            )
        
        return (None, None, None)
```

**Verify:**
- Service methods handle all edge cases
- Validation logic is correct
- Permission checks work correctly

---

### Step 4: API Router (30 min)

**File:** `app/api/v1/annotations.py` (append to existing)

```python
from app.schemas.annotation import (
    AnnotationEditCreate,
    AnnotationEditResponse,
    AnnotationEditListResponse
)
from app.services.annotation_edit_service import AnnotationEditService


@router.post(
    "/{segment_id}/edits",
    response_model=AnnotationEditResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create annotation edit",
    description="Create a new edit for a segment with transcript and timestamp corrections."
)
async def create_annotation_edit(
    segment_id: UUID,
    edit_data: AnnotationEditCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Create a new annotation edit for a segment.
    
    The edit records:
    - Old values (from ASR or previous edit)
    - New values (annotator corrections)
    - Editor and timestamp
    
    Validation:
    - Start must be < end
    - Both must be within video bounds
    """
    service = AnnotationEditService(db)
    edit = await service.create_edit(
        segment_id=segment_id,
        editor_id=current_user.id,
        new_text=edit_data.new_text,
        new_start=edit_data.new_start,
        new_end=edit_data.new_end
    )
    return edit


@router.get(
    "/{segment_id}/edits",
    response_model=AnnotationEditListResponse,
    summary="Get edit history",
    description="Get the edit history for a segment."
)
async def get_annotation_edits(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get the edit history for a segment.
    
    Returns all edits ordered by most recent first.
    Only accessible to the assigned annotator.
    """
    service = AnnotationEditService(db)
    edits = await service.get_edit_history(
        segment_id=segment_id,
        user_id=current_user.id
    )
    
    return {
        "segment_id": segment_id,
        "edits": edits,
        "total": len(edits)
    }
```

**Verify:**
- Router endpoints are correctly typed
- Response models match schema definitions
- Status codes are correct (201 for create)

---

### Step 5: Update Queue Service (15 min)

**File:** `app/services/annotation_queue_service.py`

Update the `_get_edit_history` method to use the new repository:

```python
from app.repositories.annotation_edit_repository import AnnotationEditRepository

# In __init__:
self.edit_repo = AnnotationEditRepository(db)

# Update _get_edit_history:
async def _get_edit_history(self, segment_id: UUID) -> List[dict]:
    """Get edit history for a segment."""
    edits = await self.edit_repo.get_by_segment(segment_id)
    return [
        {
            "edit_id": edit.id,
            "old_text": edit.old_text,
            "new_text": edit.new_text,
            "old_start": edit.old_start,
            "new_start": edit.new_start,
            "old_end": edit.old_end,
            "new_end": edit.new_end,
            "edited_at": edit.edited_at,
            "status": edit.status
        }
        for edit in edits
    ]
```

---

## Verification Steps

### Manual Testing

1. **Create an edit:**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_text": "corrected transcript",
    "new_start": 12.5,
    "new_end": 18.3
  }' \
  http://localhost:8000/api/v1/annotations/{segment_id}/edits
```

2. **Get edit history:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/{segment_id}/edits
```

3. **Test validation (invalid timestamps):**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_text": "test",
    "new_start": 20.0,
    "new_end": 10.0
  }' \
  http://localhost:8000/api/v1/annotations/{segment_id}/edits
# Should return 400 with validation error
```

---

## Definition of Done

- [ ] Repository layer for edit CRUD operations
- [ ] Pydantic schemas with validation
- [ ] Service layer with business logic
- [ ] API endpoints (POST and GET)
- [ ] Timestamp validation
- [ ] RBAC enforcement
- [ ] Manual testing completed

---

## Notes

### Edit Status Workflow

```
PENDING → SUBMITTED (when submitted for review - Story 3.5)
SUBMITTED → APPROVED/REJECTED (by curator - Story 4.x)
```

### Timestamp Validation Rules

1. `start >= 0` (can't be negative)
2. `start < end` (start must be before end)
3. `end <= video_duration` (can't exceed video length)

### Permission Model

- Annotators can only edit their assigned segments
- Annotators can view edit history for their segments
- Curators/Admins can view all edit history (future enhancement)
