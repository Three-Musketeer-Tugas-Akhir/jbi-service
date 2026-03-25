---
story_id: "3.5"
story_key: "3-5-submit-for-review"
epic: 3
title: "Submit for Review"
status: ready-for-dev
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 3.5: Submit for Review

## Story Header

**Epic:** 3 - Annotation Workflow  
**Story ID:** 3.5  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 3.1: Database Schema - Annotation Domain ✅
- Story 3.2: Annotation Queue API ✅
- Story 3.3: Submit Annotation Edit ✅
- Story 3.4: Preview and Save Annotations ✅

**Reference Documents:**
- [Epics Document](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/epics.md) - Story 3.5 definition, FR23, FR29-FR30
- [PRD](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/prd.md) - User journeys for Rina (Annotator) and Pak Budi (Curator)
- [Architecture](/home/arxeno/Documents/TA/jbi-service/_bmad-output/planning-artifacts/architecture.md) - Workflow states, annotation_reviews table

---

## Story Requirements

### User Story

As an annotator,  
I want to submit my completed annotations for curator review,  
So that they can be approved for the dataset.

### Business Context

This story completes the annotation workflow for Epic 3. When an annotator finishes correcting a segment, they submit it for curator review. The submission transitions the segment from the annotator's queue to the curator's review queue, enabling the quality assurance workflow described in the PRD where Pak Budi reviews and approves Rina's work.

**From PRD:** Rina "clicks 'Submit for Curation.' Video status changes to 'Pending Review' and disappears from her queue" (Journey 1, Step 6).

**From Architecture:** The annotation workflow state transitions from `ANNOTATING` → `PENDING_REVIEW` → (`APPROVED` | `REJECTED`).

### Acceptance Criteria

**Given** I have completed editing a segment  
**When** I POST `/api/v1/annotations/{segment_id}/submit`  
**Then** annotation_edits status changes to "SUBMITTED"  
**And** annotation_queue status changes to "COMPLETED"  
**And** segment is added to curator review queue (annotation_reviews table)  
**And** I receive confirmation: "Annotation submitted for review"

**Given** I have multiple segments for the same job  
**When** I submit all segments  
**Then** each is individually submitted for review  
**And** I can track each segment's review status

**Given** I try to submit without any edits  
**When** I click submit  
**Then** I receive warning: "No changes made. Submit ASR-original?"  
**And** I can confirm or cancel

**Given** I have submitted an annotation  
**When** the curator rejects it (Epic 4)  
**Then** segment returns to my queue with status "NEEDS_REVISION"  
**And** I see curator feedback  
**And** I can make further edits and resubmit

**Given** I have submitted an annotation  
**When** the curator approves it (Epic 4)  
**Then** segment status changes to "APPROVED"  
**And** it becomes available for dataset export  
**And** I see approval notification

---

## Developer Context

### Architecture Alignment

This story implements the **State Transition** pattern per Architecture §4.2:

```
Annotation Workflow State Machine:

┌─────────────────┐     submit      ┌─────────────────┐
│   ANNOTATING    │ ──────────────► │  PENDING_REVIEW │
│  (in_progress)  │                 │   (submitted)   │
└─────────────────┘                 └─────────────────┘
         ▲                                    │
         │         reject + feedback          │
         └────────────────────────────────────┤
                                              │ approve
                                              ▼
                                       ┌─────────────────┐
                                       │    APPROVED     │
                                       │  (exportable)   │
                                       └─────────────────┘
```

**Key Pattern:** Submission creates an `annotation_reviews` record linking the edit to a curator review workflow.

### Technical Requirements

1. **Status Updates:**
   - `annotation_edits.status` → "SUBMITTED"
   - `annotation_queue.status` → "COMPLETED"
   
2. **Review Queue Entry:** Create `annotation_reviews` record with:
   - `edit_id`: Reference to submitted edit
   - `status`: "PENDING" (awaiting curator)
   - `curator_id`: NULL (unassigned, or auto-assigned via round-robin)

3. **Validation:** Check for at least one non-draft edit before submission

4. **Submission Timestamp:** Track when annotation was submitted

---

## Implementation Plan

### Step 1: Update Model Constants (5 min)

**File:** `app/db/models/annotation.py`

Update status constants for complete workflow:

```python
class AnnotationEdit(Base):
    # ... existing fields ...
    
    # Status constants (CONSTANT_CASE per Architecture §5.1)
    STATUS_DRAFT = "DRAFT"
    STATUS_PENDING = "PENDING"       # Ready for submission
    STATUS_SUBMITTED = "SUBMITTED"   # Submitted for review
    STATUS_APPROVED = "APPROVED"     # Approved by curator
    STATUS_REJECTED = "REJECTED"     # Rejected by curator


class AnnotationReview(Base):
    """Curator reviews of annotation edits."""
    
    # ... existing fields ...
    
    # Status constants
    STATUS_PENDING = "PENDING"       # Awaiting curator review
    STATUS_APPROVED = "APPROVED"     # Curator approved
    STATUS_REJECTED = "REJECTED"     # Curator rejected
```

**Verify:**
- Constants follow CONSTANT_CASE convention
- Status values match Architecture §4.2 state definitions

---

### Step 2: Repository Layer (30 min)

**File:** `app/repositories/annotation_review_repository.py` (new)

```python
"""Annotation review repository."""
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationReview


class AnnotationReviewRepository:
    """Repository for annotation review operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, review: AnnotationReview) -> AnnotationReview:
        """Create a new review record."""
        self.db.add(review)
        await self.db.flush()
        await self.db.refresh(review)
        return review
    
    async def get_by_id(self, review_id: UUID) -> Optional[AnnotationReview]:
        """Get review by ID."""
        query = select(AnnotationReview).where(AnnotationReview.id == review_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_edit_id(self, edit_id: UUID) -> Optional[AnnotationReview]:
        """Get review by edit ID."""
        query = select(AnnotationReview).where(
            AnnotationReview.edit_id == edit_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_pending_reviews(
        self,
        curator_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[AnnotationReview]:
        """Get pending reviews, optionally filtered by curator assignment."""
        query = select(AnnotationReview).where(
            AnnotationReview.status == AnnotationReview.STATUS_PENDING
        )
        
        if curator_id:
            query = query.where(AnnotationReview.curator_id == curator_id)
        
        query = query.order_by(desc(AnnotationReview.reviewed_at))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_status(
        self,
        review_id: UUID,
        status: str,
        curator_id: Optional[UUID] = None,
        feedback: Optional[str] = None
    ) -> bool:
        """Update review status (approve/reject)."""
        review = await self.get_by_id(review_id)
        if not review:
            return False
        
        review.status = status
        if curator_id:
            review.curator_id = curator_id
        if feedback is not None:
            review.feedback = feedback
        
        await self.db.flush()
        return True
```

**Verify:**
- Repository methods compile correctly
- Queries use proper indexes

---

### Step 3: Repository Enhancements (15 min)

**File:** `app/repositories/annotation_edit_repository.py` (append methods)

```python
    async def update_status(
        self,
        edit_id: UUID,
        status: str
    ) -> bool:
        """Update edit status."""
        edit = await self.get_by_id(edit_id)
        if not edit:
            return False
        
        edit.status = status
        await self.db.flush()
        return True
    
    async def has_submitted_edit(self, segment_id: UUID) -> bool:
        """Check if segment has a submitted edit."""
        from sqlalchemy import exists
        
        query = select(
            exists().where(
                AnnotationEdit.segment_id == segment_id,
                AnnotationEdit.status == AnnotationEdit.STATUS_SUBMITTED,
                AnnotationEdit.is_deleted == False
            )
        )
        result = await self.db.execute(query)
        return result.scalar()
    
    async def get_submitted_edit(
        self,
        segment_id: UUID
    ) -> Optional[AnnotationEdit]:
        """Get the submitted edit for a segment."""
        query = select(AnnotationEdit).where(
            AnnotationEdit.segment_id == segment_id,
            AnnotationEdit.status == AnnotationEdit.STATUS_SUBMITTED,
            AnnotationEdit.is_deleted == False
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
```

---

### Step 4: Pydantic Schemas (20 min)

**File:** `app/schemas/annotation.py` (append to existing)

```python
# ============================================================================
# Submission Schemas
# ============================================================================

class SubmitForReviewRequest(BaseModel):
    """Request to submit annotation for curator review."""
    confirm_no_changes: bool = Field(
        False,
        description="Confirm submission even if no edits were made"
    )


class SubmitForReviewResponse(BaseModel):
    """Response after submitting for review."""
    segment_id: UUID
    edit_id: UUID
    review_id: UUID
    status: str
    message: str
    submitted_at: datetime


class SubmissionStatusResponse(BaseModel):
    """Status of a segment's submission."""
    segment_id: UUID
    has_edits: bool
    edit_count: int
    last_edit_status: Optional[str]
    can_submit: bool
    warning: Optional[str] = None


# ============================================================================
# Review Status Schemas (for annotator to track their submissions)
# ============================================================================

class ReviewStatusResponse(BaseModel):
    """Review status for an annotator's submission."""
    segment_id: UUID
    review_id: UUID
    status: str  # PENDING, APPROVED, REJECTED
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    curator_id: Optional[UUID]
    feedback: Optional[str]
    
    class Config:
        from_attributes = True


class ReviewStatusListResponse(BaseModel):
    """List of review statuses for annotator's submissions."""
    items: List[ReviewStatusResponse]
    total: int
```

---

### Step 5: Service Layer (1 hour)

**File:** `app/services/annotation_submission_service.py` (new)

```python
"""Annotation submission service."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.annotation_review_repository import AnnotationReviewRepository
from app.repositories.segment_repository import SegmentRepository
from app.core.exceptions import NotFoundError, PermissionError, ValidationError, ConflictError
from app.db.models.annotation import AnnotationEdit, AnnotationQueue, AnnotationReview


class AnnotationSubmissionService:
    """Service for annotation submission and review tracking."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.edit_repo = AnnotationEditRepository(db)
        self.queue_repo = AnnotationQueueRepository(db)
        self.review_repo = AnnotationReviewRepository(db)
        self.segment_repo = SegmentRepository(db)
    
    async def check_submission_status(
        self,
        segment_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Check if a segment can be submitted for review.
        
        Returns status information including:
        - Whether edits exist
        - Edit count
        - Any warnings (e.g., no changes made)
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        if queue_entry.annotator_id != user_id:
            raise PermissionError("You can only submit your own annotations")
        
        # Check if already submitted
        if await self.edit_repo.has_submitted_edit(segment_id):
            raise ConflictError("This segment has already been submitted for review")
        
        # Get edit information
        edits = await self.edit_repo.get_by_segment(segment_id)
        non_draft_edits = [e for e in edits if e.status != AnnotationEdit.STATUS_DRAFT]
        
        has_edits = len(non_draft_edits) > 0
        warning = None
        
        if not has_edits:
            warning = "No changes made. Submit ASR-original?"
        
        last_edit = edits[0] if edits else None
        
        return {
            "segment_id": segment_id,
            "has_edits": has_edits,
            "edit_count": len(non_draft_edits),
            "last_edit_status": last_edit.status if last_edit else None,
            "can_submit": True,
            "warning": warning
        }
    
    async def submit_for_review(
        self,
        segment_id: UUID,
        user_id: UUID,
        confirm_no_changes: bool = False
    ) -> dict:
        """
        Submit an annotation for curator review.
        
        This operation:
        1. Validates the segment belongs to the annotator
        2. Updates the latest edit status to SUBMITTED
        3. Updates queue status to COMPLETED
        4. Creates an annotation_reviews record
        5. Returns submission confirmation
        
        Args:
            segment_id: The segment to submit
            user_id: The annotator submitting
            confirm_no_changes: Whether to proceed if no edits exist
            
        Returns:
            Submission confirmation with review_id
            
        Raises:
            NotFoundError: If segment not found
            PermissionError: If not the assigned annotator
            ValidationError: If no edits and confirm_no_changes=False
            ConflictError: If already submitted
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found in annotation queue")
        
        if queue_entry.annotator_id != user_id:
            raise PermissionError("You can only submit your own annotations")
        
        # Check if already submitted
        existing_review = await self.review_repo.get_by_edit_id(
            (await self.edit_repo.get_submitted_edit(segment_id)).id 
            if await self.edit_repo.has_submitted_edit(segment_id) 
            else UUID(int=0)  # Dummy UUID to skip query
        )
        if await self.edit_repo.has_submitted_edit(segment_id):
            raise ConflictError("This segment has already been submitted for review")
        
        # Get the latest non-deleted, non-draft edit
        latest_edit = await self.edit_repo.get_latest_by_segment(segment_id)
        
        if not latest_edit or latest_edit.status == AnnotationEdit.STATUS_DRAFT:
            # No edits or only drafts - need confirmation
            if not confirm_no_changes:
                raise ValidationError(
                    "No changes made. Set confirm_no_changes=true to submit ASR-original."
                )
            
            # Create a "submission" edit that represents ASR-original
            segment = await self.segment_repo.get_by_id(segment_id)
            if not segment:
                raise NotFoundError(f"Segment {segment_id} not found")
            
            latest_edit = AnnotationEdit(
                segment_id=segment_id,
                editor_id=user_id,
                old_text=None,
                old_start=None,
                old_end=None,
                new_text=segment.asr_text or "",
                new_start=segment.asr_start or 0.0,
                new_end=segment.asr_end or 0.0,
                status=AnnotationEdit.STATUS_SUBMITTED,
                is_deleted=False,
                edited_at=datetime.utcnow(),
                submitted_at=datetime.utcnow()
            )
            latest_edit = await self.edit_repo.create(latest_edit)
        else:
            # Update existing edit to submitted
            latest_edit.status = AnnotationEdit.STATUS_SUBMITTED
            latest_edit.submitted_at = datetime.utcnow()
            await self.db.flush()
        
        # Update queue status to COMPLETED
        await self.queue_repo.update_status(
            queue_entry.id,
            AnnotationQueue.STATUS_COMPLETED
        )
        
        # Create review record
        review = AnnotationReview(
            edit_id=latest_edit.id,
            curator_id=None,  # Unassigned - will be assigned by curator system
            status=AnnotationReview.STATUS_PENDING,
            feedback=None,
            reviewed_at=datetime.utcnow()
        )
        review = await self.review_repo.create(review)
        
        return {
            "segment_id": segment_id,
            "edit_id": latest_edit.id,
            "review_id": review.id,
            "status": "SUBMITTED",
            "message": "Annotation submitted for review",
            "submitted_at": latest_edit.submitted_at
        }
    
    async def get_submission_status(
        self,
        segment_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Get the review status for a submitted annotation.
        
        Allows annotators to track whether their submission is:
        - PENDING (awaiting curator)
        - APPROVED (accepted)
        - REJECTED (needs revision)
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry or queue_entry.annotator_id != user_id:
            raise PermissionError("Access denied")
        
        # Get the submitted edit
        submitted_edit = await self.edit_repo.get_submitted_edit(segment_id)
        if not submitted_edit:
            return {
                "segment_id": segment_id,
                "status": "NOT_SUBMITTED",
                "message": "This segment has not been submitted for review"
            }
        
        # Get review record
        review = await self.review_repo.get_by_edit_id(submitted_edit.id)
        
        if not review:
            return {
                "segment_id": segment_id,
                "status": "SUBMITTED",
                "message": "Submitted, awaiting review assignment"
            }
        
        return {
            "segment_id": segment_id,
            "review_id": review.id,
            "status": review.status,
            "submitted_at": submitted_edit.submitted_at,
            "reviewed_at": review.reviewed_at if review.status != AnnotationReview.STATUS_PENDING else None,
            "curator_id": review.curator_id,
            "feedback": review.feedback
        }
    
    async def list_my_submissions(
        self,
        user_id: UUID,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """
        List all submissions by an annotator with their review status.
        """
        # Get all queue entries for this annotator
        from sqlalchemy import select
        from app.db.models.annotation import AnnotationQueue
        
        # This is a simplified version - in production, use proper joins
        queue_entries = await self.queue_repo.get_by_annotator(
            annotator_id=user_id,
            status=AnnotationQueue.STATUS_COMPLETED,
            limit=page_size,
            offset=(page - 1) * page_size
        )
        
        items = []
        for entry in queue_entries:
            status_info = await self.get_submission_status(entry.segment_id, user_id)
            if status is None or status_info.get("status") == status:
                items.append(status_info)
        
        return {
            "items": items,
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "pages": (len(items) + page_size - 1) // page_size
        }
```

---

### Step 6: API Router (30 min)

**File:** `app/api/v1/annotations.py` (append endpoints)

```python
from app.schemas.annotation import (
    # ... existing imports ...
    SubmitForReviewRequest,
    SubmitForReviewResponse,
    SubmissionStatusResponse,
    ReviewStatusResponse,
    ReviewStatusListResponse
)
from app.services.annotation_submission_service import AnnotationSubmissionService


@router.get(
    "/{segment_id}/submission-status",
    response_model=SubmissionStatusResponse,
    summary="Check submission status",
    description="Check if a segment can be submitted and get any warnings."
)
async def check_submission_status(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Check the submission status for a segment.
    
    Returns:
    - Whether edits exist
    - Edit count
    - Any warnings (e.g., no changes made)
    - Whether submission is allowed
    """
    service = AnnotationSubmissionService(db)
    status = await service.check_submission_status(
        segment_id=segment_id,
        user_id=current_user.id
    )
    return status


@router.post(
    "/{segment_id}/submit",
    response_model=SubmitForReviewResponse,
    summary="Submit for review",
    description="Submit annotation for curator review."
)
async def submit_for_review(
    segment_id: UUID,
    submit_data: SubmitForReviewRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Submit an annotation for curator review.
    
    This transitions the annotation from "in progress" to "pending review".
    The segment will be added to the curator's review queue.
    
    If no edits were made, set confirm_no_changes=true to submit ASR-original.
    """
    service = AnnotationSubmissionService(db)
    result = await service.submit_for_review(
        segment_id=segment_id,
        user_id=current_user.id,
        confirm_no_changes=submit_data.confirm_no_changes
    )
    return result


@router.get(
    "/{segment_id}/review-status",
    response_model=ReviewStatusResponse,
    summary="Get review status",
    description="Get the review status for a submitted annotation."
)
async def get_review_status(
    segment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    Get the review status for a submitted annotation.
    
    Status values:
    - NOT_SUBMITTED: Not yet submitted
    - SUBMITTED: Awaiting curator review
    - PENDING: In curator queue
    - APPROVED: Accepted by curator
    - REJECTED: Rejected with feedback
    """
    service = AnnotationSubmissionService(db)
    status = await service.get_submission_status(
        segment_id=segment_id,
        user_id=current_user.id
    )
    return status


@router.get(
    "/my-submissions",
    response_model=ReviewStatusListResponse,
    summary="List my submissions",
    description="List all annotations submitted by the current user with their review status."
)
async def list_my_submissions(
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("annotator"))
):
    """
    List all annotations submitted by the current user.
    
    Returns paginated list with review status for each submission.
    """
    service = AnnotationSubmissionService(db)
    result = await service.list_my_submissions(
        user_id=current_user.id,
        status=status,
        page=page,
        page_size=page_size
    )
    return result
```

---

## Verification Steps

### Manual Testing

1. **Check submission status:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/{segment_id}/submission-status
```

2. **Submit for review (with edits):**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' \
  http://localhost:8000/api/v1/annotations/{segment_id}/submit
```

3. **Submit ASR-original (no edits):**
```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"confirm_no_changes": true}' \
  http://localhost:8000/api/v1/annotations/{segment_id}/submit
```

4. **Check review status:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/annotations/{segment_id}/review-status
```

5. **List my submissions:**
```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/annotations/my-submissions?status=PENDING"
```

---

## Definition of Done

- [ ] SUBMITTED status constant added to model
- [ ] AnnotationReview repository for curator queue management
- [ ] Pydantic schemas for submission and status tracking
- [ ] Submission service with validation and state transitions
- [ ] API endpoints (GET status, POST submit, GET review status, GET list)
- [ ] Support for "no changes" submission with confirmation
- [ ] Review record creation for curator workflow (Epic 4)
- [ ] Manual testing completed

---

## Notes

### Submission Workflow

```
1. Annotator completes edits
2. Check submission status → warnings if no edits
3. POST /submit → edit.status = SUBMITTED
                  queue.status = COMPLETED
                  review record created
4. Segment appears in curator queue (Epic 4)
5. Curator approves/rejects
6. Annotator sees result via review-status endpoint
```

### No-Changes Submission

When an annotator submits without making edits:
- If `confirm_no_changes=false`: Returns 400 with validation error
- If `confirm_no_changes=true`: Creates edit record with ASR values marked as SUBMITTED
- This ensures every submission has an audit trail

### State Persistence

Once submitted:
- Edit status is locked (cannot be changed by annotator)
- Queue entry stays COMPLETED
- Review record tracks curator decision
- Rejection returns segment to annotator (Epic 4 implementation)

### Future Enhancements (Epic 4)

- Auto-assignment of curators via round-robin
- Email notifications on approval/rejection
- Batch submission of multiple segments
