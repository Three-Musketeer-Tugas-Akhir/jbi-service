"""Annotation submission service."""
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.annotation_review_repository import AnnotationReviewRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.core.exceptions import NotFoundError, PermissionError, ValidationError, ConflictError
from app.db.models.annotation import AnnotationEdit, AnnotationQueue, AnnotationReview
from app.db.models.audit import AuditAction


class AnnotationSubmissionService:
    """Service for annotation submission and review tracking."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.edit_repo = AnnotationEditRepository(db)
        self.queue_repo = AnnotationQueueRepository(db)
        self.review_repo = AnnotationReviewRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.audit_repo = AuditLogRepository(db)
    
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
                utterance_corrections=[
                    {
                        "utterance_index": t.utterance_index,
                        "text": t.text,
                        "start": t.start,
                        "end": t.end
                    }
                    for t in sorted(segment.transcripts, key=lambda x: x.utterance_index)
                ] if segment.transcripts else [],
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
        
        # Log annotation submission
        await self.audit_repo.create(
            action=AuditAction.ANNOTATION_SUBMITTED,
            resource_type="annotation",
            actor_id=user_id,
            resource_id=latest_edit.id,
            details={
                "segment_id": str(segment_id),
                "review_id": str(review.id),
                "is_asr_original": not confirm_no_changes and (not latest_edit or latest_edit.status == AnnotationEdit.STATUS_DRAFT)
            }
        )
        await self.db.commit()
        
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
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        if queue_entry.annotator_id != user_id:
            raise PermissionError("You can only view your own submissions")
        
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
        # Get all queue entries for this annotator with COMPLETED status
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
