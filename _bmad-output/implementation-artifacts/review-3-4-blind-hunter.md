# Blind Hunter Review - Story 3.4

## Role
You are the Blind Hunter — a code reviewer who sees ONLY the diff, with zero project context. Your job is to spot bugs, security issues, logic errors, and code smells that are visible from the code alone.

## Input: Diff to Review

```diff
diff --git a/app/api/v1/annotations.py b/app/api/v1/annotations.py
index 527b60c..c6b2af8 100644
--- a/app/api/v1/annotations.py
+++ b/app/api/v1/annotations.py
@@ -15,7 +15,12 @@ from app.schemas.annotation import (
     QueueFilterParams,
     AnnotationEditCreate,
     AnnotationEditResponse,
-    AnnotationEditListResponse
+    AnnotationEditListResponse,
+    AnnotationPreviewRequest,
+    AnnotationPreviewResponse,
+    SaveDraftRequest,
+    SaveDraftResponse,
+    ResetResponse
 )
 
 
@@ -146,3 +151,126 @@ async def get_annotation_edits(
         "edits": edits,
         "total": len(edits)
     }
+
+
+@router.post(
+    "/{segment_id}/preview",
+    response_model=AnnotationPreviewResponse,
+    summary="Preview annotation",
+    description="Get video preview with specified timestamps for verification."
+)
+async def preview_annotation(
+    segment_id: UUID,
+    preview_data: AnnotationPreviewRequest,
+    db: AsyncSession = Depends(get_db),
+    current_user: User = Depends(require_role("annotator"))
+):
+    """
+    Get a preview of the annotation with specified timestamps.
+    
+    Returns a pre-signed video URL that can be used to verify
+    synchronization before saving or submitting.
+    """
+    service = AnnotationEditService(db)
+    preview = await service.get_preview(
+        segment_id=segment_id,
+        user_id=current_user.id,
+        start_time=preview_data.start_time,
+        end_time=preview_data.end_time
+    )
+    
+    # Add transcript if provided
+    if preview_data.transcript_text:
+        preview["transcript_text"] = preview_data.transcript_text
+    
+    return preview
+
+
+@router.post(
+    "/{segment_id}/draft",
+    response_model=SaveDraftResponse,
+    summary="Save annotation draft",
+    description="Save annotation edits as draft without submitting for review."
+)
+async def save_annotation_draft(
+    segment_id: UUID,
+    draft_data: SaveDraftRequest,
+    db: AsyncSession = Depends(get_db),
+    current_user: User = Depends(require_role("annotator"))
+):
+    """
+    Save annotation edits as a draft.
+    
+    Draft edits:
+    - Are not visible to curators
+    - Can be overwritten by subsequent drafts
+    - Allow saving work-in-progress
+    """
+    service = AnnotationEditService(db)
+    draft = await service.create_draft(
+        segment_id=segment_id,
+        editor_id=current_user.id,
+        new_text=draft_data.new_text,
+        new_start=draft_data.new_start,
+        new_end=draft_data.new_end
+    )
+    
+    return {
+        "edit_id": draft.id,
+        "segment_id": segment_id,
+        "status": draft.status,
+        "saved_at": draft.edited_at,
+        "message": "Draft saved successfully"
+    }
+
+
+@router.post(
+    "/{segment_id}/reset",
+    response_model=ResetResponse,
+    summary="Reset to original",
+    description="Reset all edits and revert to ASR-original values."
+)
+async def reset_annotation(
+    segment_id: UUID,
+    db: AsyncSession = Depends(get_db),
+    current_user: User = Depends(require_role("annotator"))
+):
+    """
+    Reset all edits for a segment back to ASR-original state.
+    
+    This operation:
+    - Soft-deletes all your edits for this segment
+    - Creates a reset record for audit trail
+    - Reverts values to the original ASR output
+    """
+    service = AnnotationEditService(db)
+    result = await service.reset_to_original(
+        segment_id=segment_id,
+        editor_id=current_user.id
+    )
+    return result
+
+
+@router.get(
+    "/{segment_id}/current",
+    summary="Get current values",
+    description="Get current annotation values including any draft edits."
+)
+async def get_current_annotation_values(
+    segment_id: UUID,
+    db: AsyncSession = Depends(get_db),
+    current_user: User = Depends(require_role("annotator"))
+):
+    """
+    Get the current annotation values for a segment.
+    
+    Returns the most recent values from either:
+    - Latest edit (draft, pending, or submitted)
+    - ASR original (if no edits)
+    """
+    service = AnnotationEditService(db)
+    values = await service.get_current_values_with_draft(
+        segment_id=segment_id,
+        user_id=current_user.id
+    )
+    return values

diff --git a/app/db/models/annotation.py b/app/db/models/annotation.py
index 00acbe6..62d1738 100644
--- a/app/db/models/annotation.py
+++ b/app/db/models/annotation.py
@@ -10,7 +10,7 @@ from uuid import UUID
 from sqlalchemy import ForeignKey, String, Float, Text, Boolean, DateTime, Integer
 from sqlalchemy.orm import Mapped, mapped_column, relationship
 
-from app.db.models.base import Base
+from app.db.base import Base
 
 if TYPE_CHECKING:
     from app.db.models.pipeline import PipelineSegment
@@ -55,6 +55,7 @@ class AnnotationEdit(Base):
     comments: Mapped[List["AnnotationComment"]] = relationship("AnnotationComment", back_populates="edit", cascade="all, delete-orphan")
     
     # Status constants
+    STATUS_DRAFT = "DRAFT"
     STATUS_PENDING = "PENDING"
     STATUS_SUBMITTED = "SUBMITTED"
     STATUS_APPROVED = "APPROVED"

diff --git a/app/repositories/annotation_edit_repository.py b/app/repositories/annotation_edit_repository.py
index 4393a4d..6e1489e 100644
--- a/app/repositories/annotation_edit_repository.py
+++ b/app/repositories/annotation_edit_repository.py
@@ -70,3 +70,41 @@ class AnnotationEditRepository:
         edit.is_deleted = True
         await self.db.flush()
         return True
+    
+    async def get_latest_non_draft(
+        self,
+        segment_id: UUID,
+        include_deleted: bool = False
+    ) -> Optional[AnnotationEdit]:
+        """Get latest non-draft edit for a segment."""
+        query = select(AnnotationEdit).where(
+            AnnotationEdit.segment_id == segment_id,
+            AnnotationEdit.status != AnnotationEdit.STATUS_DRAFT
+        )
+        
+        if not include_deleted:
+            query = query.where(AnnotationEdit.is_deleted == False)
+        
+        query = query.order_by(desc(AnnotationEdit.edited_at)).limit(1)
+        result = await self.db.execute(query)
+        return result.scalar_one_or_none()
+    
+    async def soft_delete_all_for_segment(
+        self,
+        segment_id: UUID,
+        editor_id: UUID
+    ) -> int:
+        """Soft delete all edits by an editor for a segment. Returns count deleted."""
+        from sqlalchemy import update
+        
+        result = await self.db.execute(
+            update(AnnotationEdit)
+            .where(
+                AnnotationEdit.segment_id == segment_id,
+                AnnotationEdit.editor_id == editor_id,
+                AnnotationEdit.is_deleted == False
+            )
+            .values(is_deleted=True)
+        )
+        await self.db.flush()
+        return result.rowcount

diff --git a/app/schemas/annotation.py b/app/schemas/annotation.py
index 8394ef0..cafa729 100644
--- a/app/schemas/annotation.py
+++ b/app/schemas/annotation.py
@@ -154,3 +154,66 @@ class AnnotationEditListResponse(BaseModel):
     segment_id: UUID
     edits: List[AnnotationEditResponse]
     total: int
+
+
+# ============================================================================
+# Preview and Draft Schemas
+# ============================================================================
+
+class AnnotationPreviewRequest(BaseModel):
+    """Request to preview annotation with specific timestamps."""
+    start_time: float = Field(..., ge=0, description="Start time in seconds")
+    end_time: float = Field(..., gt=0, description="End time in seconds")
+    transcript_text: Optional[str] = Field(None, description="Transcript to preview")
+    
+    @model_validator(mode='after')
+    def validate_timestamps(self):
+        """Validate that start < end."""
+        if self.start_time >= self.end_time:
+            raise ValueError("Start time must be less than end time")
+        return self
+
+
+class AnnotationPreviewResponse(BaseModel):
+    """Preview response with video URL and metadata."""
+    segment_id: UUID
+    video_url: str
+    start_time: float
+    end_time: float
+    transcript_text: Optional[str]
+    duration: float
+    
+    class Config:
+        from_attributes = True
+
+
+class SaveDraftRequest(BaseModel):
+    """Request to save annotation as draft."""
+    new_text: str = Field(..., min_length=1, description="Corrected transcript text")
+    new_start: float = Field(..., ge=0, description="New start time in seconds")
+    new_end: float = Field(..., gt=0, description="New end time in seconds")
+    
+    @model_validator(mode='after')
+    def validate_timestamps(self):
+        """Validate that start < end."""
+        if self.new_start >= self.new_end:
+            raise ValueError("Start time must be less than end time")
+        return self
+
+
+class SaveDraftResponse(BaseModel):
+    """Response after saving draft."""
+    edit_id: UUID
+    segment_id: UUID
+    status: str
+    saved_at: datetime
+    message: str = "Draft saved successfully"
+
+
+class ResetResponse(BaseModel):
+    """Response after resetting annotations."""
+    segment_id: UUID
+    reset_edit_id: UUID
+    edits_removed: int
+    message: str
+    reverted_to: dict  # ASR original values

diff --git a/app/services/annotation_edit_service.py b/app/services/annotation_edit_service.py
index 5faf43c..6610721 100644
--- a/app/services/annotation_edit_service.py
+++ b/app/services/annotation_edit_service.py
@@ -160,3 +160,232 @@ class AnnotationEditService:
             )
         
         return (None, None, None)
+    
+    async def create_draft(
+        self,
+        segment_id: UUID,
+        editor_id: UUID,
+        new_text: str,
+        new_start: float,
+        new_end: float
+    ) -> AnnotationEdit:
+        """
+        Save an annotation edit as draft.
+        
+        Draft edits:
+        - Can be overwritten by subsequent drafts
+        - Not visible to curators
+        - Allow annotator to save progress without submitting
+        """
+        # Validation same as regular edit
+        queue_entry = await self.queue_repo.get_by_segment(segment_id)
+        if not queue_entry:
+            raise NotFoundError(f"Segment {segment_id} not found in annotation queue")
+        
+        if queue_entry.annotator_id != editor_id:
+            raise PermissionError("You are not assigned to edit this segment")
+        
+        segment = await self.segment_repo.get_by_id(segment_id)
+        if not segment:
+            raise NotFoundError(f"Segment {segment_id} not found")
+        
+        # Validate timestamps
+        min_time = 0.0
+        max_time = segment.jbi_end or segment.asr_end or new_end
+        
+        if new_start < min_time:
+            raise ValidationError(f"Start time ({new_start}) must be at least {min_time}")
+        
+        if new_end > max_time:
+            raise ValidationError(f"End time ({new_end}) must not exceed video duration ({max_time})")
+        
+        # Get current values (excluding previous drafts)
+        old_text, old_start, old_end = await self._get_current_values_for_draft(segment_id)
+        
+        # Create draft edit
+        draft = AnnotationEdit(
+            segment_id=segment_id,
+            editor_id=editor_id,
+            old_text=old_text,
+            old_start=old_start,
+            old_end=old_end,
+            new_text=new_text,
+            new_start=new_start,
+            new_end=new_end,
+            status=AnnotationEdit.STATUS_DRAFT,
+            is_deleted=False,
+            edited_at=datetime.utcnow()
+        )
+        
+        return await self.edit_repo.create(draft)
+    
+    async def get_preview(
+        self,
+        segment_id: UUID,
+        user_id: UUID,
+        start_time: float,
+        end_time: float
+    ) -> dict:
+        """
+        Get preview data for annotation with specific timestamps.
+        
+        Returns video URL and metadata for the annotator to verify
+        synchronization before saving/submitting.
+        """
+        # Verify access
+        queue_entry = await self.queue_repo.get_by_segment(segment_id)
+        if not queue_entry:
+            raise NotFoundError(f"Segment {segment_id} not found")
+        
+        if queue_entry.annotator_id != user_id:
+            raise PermissionError("You can only preview your assigned segments")
+        
+        segment = await self.segment_repo.get_by_id(segment_id)
+        if not segment or not segment.cropped_video_path:
+            raise NotFoundError("Video not available for preview")
+        
+        # Generate pre-signed URL
+        from app.services.minio_service import get_minio_service
+        minio_service = get_minio_service()
+        video_url = await minio_service.generate_presigned_url(
+            object_name=segment.cropped_video_path,
+            expiry=3600  # 1 hour
+        )
+        
+        return {
+            "segment_id": segment_id,
+            "video_url": video_url,
+            "start_time": start_time,
+            "end_time": end_time,
+            "duration": end_time - start_time
+        }
+    
+    async def reset_to_original(
+        self,
+        segment_id: UUID,
+        editor_id: UUID
+    ) -> dict:
+        """
+        Reset all edits for a segment back to ASR-original state.
+        
+        This operation:
+        1. Soft-deletes all existing edits by this user
+        2. Creates a "reset" edit record for audit trail
+        3. Returns the ASR-original values
+        """
+        # Verify access
+        queue_entry = await self.queue_repo.get_by_segment(segment_id)
+        if not queue_entry:
+            raise NotFoundError(f"Segment {segment_id} not found")
+        
+        if queue_entry.annotator_id != editor_id:
+            raise PermissionError("You can only reset your own edits")
+        
+        segment = await self.segment_repo.get_by_id(segment_id)
+        if not segment:
+            raise NotFoundError(f"Segment {segment_id} not found")
+        
+        # Soft delete all user's edits for this segment
+        deleted_count = await self.edit_repo.soft_delete_all_for_segment(
+            segment_id=segment_id,
+            editor_id=editor_id
+        )
+        
+        # Create reset record for audit trail
+        # This records that a reset happened and what values were reverted to
+        reset_edit = AnnotationEdit(
+            segment_id=segment_id,
+            editor_id=editor_id,
+            old_text=None,  # Reset has no "old" value
+            old_start=None,
+            old_end=None,
+            new_text=segment.asr_text or "",
+            new_start=segment.asr_start or 0.0,
+            new_end=segment.asr_end or 0.0,
+            status=AnnotationEdit.STATUS_PENDING,  # Reset is pending, not draft
+            is_deleted=False,
+            edited_at=datetime.utcnow()
+        )
+        reset_record = await self.edit_repo.create(reset_edit)
+        
+        return {
+            "segment_id": segment_id,
+            "reset_edit_id": reset_record.id,
+            "edits_removed": deleted_count,
+            "message": f"Reset completed. {deleted_count} edit(s) removed.",
+            "reverted_to": {
+                "text": segment.asr_text or "",
+                "start": segment.asr_start or 0.0,
+                "end": segment.asr_end or 0.0
+            }
+        }
+    
+    async def _get_current_values_for_draft(
+        self,
+        segment_id: UUID
+    ) -> Tuple[Optional[str], Optional[float], Optional[float]]:
+        """
+        Get current values for draft creation.
+        
+        For drafts, we look at the latest non-draft, non-deleted edit
+        or fall back to ASR values.
+        """
+        latest_edit = await self.edit_repo.get_latest_non_draft(segment_id)
+        if latest_edit:
+            return (
+                latest_edit.new_text,
+                latest_edit.new_start,
+                latest_edit.new_end
+            )
+        
+        segment = await self.segment_repo.get_by_id(segment_id)
+        if segment:
+            return (
+                segment.asr_text,
+                segment.asr_start,
+                segment.asr_end
+            )
+        
+        return (None, None, None)
+    
+    async def get_current_values_with_draft(
+        self,
+        segment_id: UUID,
+        user_id: UUID
+    ) -> dict:
+        """
+        Get current values for a segment, including any draft edits.
+        
+        This is used when loading a segment for editing - it returns
+        the most recent values (whether draft, pending, or ASR).
+        """
+        # Verify access
+        queue_entry = await self.queue_repo.get_by_segment(segment_id)
+        if not queue_entry or queue_entry.annotator_id != user_id:
+            raise PermissionError("Access denied")
+        
+        segment = await self.segment_repo.get_by_id(segment_id)
+        if not segment:
+            raise NotFoundError(f"Segment {segment_id} not found")
+        
+        # Get latest edit (including drafts)
+        latest_edit = await self.edit_repo.get_latest_by_segment(segment_id)
+        
+        if latest_edit:
+            return {
+                "source": "edit",
+                "edit_id": latest_edit.id,
+                "status": latest_edit.status,
+                "text": latest_edit.new_text,
+                "start": latest_edit.new_start,
+                "end": latest_edit.new_end,
+                "edited_at": latest_edit.edited_at
+            }
+        
+        # No edits, use ASR
+        return {
+            "source": "asr",
+            "text": segment.asr_text or "",
+            "start": segment.asr_start or 0.0,
+            "end": segment.asr_end or 0.0
+        }
```

## Your Task

Review this diff WITHOUT any project context. Spot:
1. Bugs and logic errors
2. Security vulnerabilities
3. Performance issues
4. Code smells and anti-patterns
5. Type safety issues
6. Error handling gaps

## Output Format

```markdown
## Blind Hunter Findings

### Critical
- **[File:Line]** One-line title
  - Evidence: specific code reference
  - Risk: what could go wrong

### High
- **[File:Line]** One-line title
  - Evidence
  - Risk

### Medium
- **[File:Line]** One-line title
  - Evidence
  - Risk

### Low
- **[File:Line]** One-line title
  - Evidence
  - Risk
```

If no findings in a severity, omit that section.
