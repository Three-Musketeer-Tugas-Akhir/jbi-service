"""Annotation edit service."""
from typing import List, Optional, Tuple
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
    ) -> Tuple[Optional[str], Optional[float], Optional[float]]:
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
