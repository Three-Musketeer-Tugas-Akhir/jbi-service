"""Annotation edit service."""
from typing import List, Optional, Tuple, Any, Dict
from uuid import UUID
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.segment_repository import SegmentRepository
from app.core.exceptions import NotFoundError, PermissionError, ValidationError
from app.core.config import settings
from app.services.streaming_token_service import streaming_token_service
from app.db.models.annotation import AnnotationEdit, AnnotationQueue


def _sanitize_cv_path(cv_path: Optional[str]) -> Optional[str]:
    """Strip URL prefix from cropped_video_path to ensure only MinIO object keys are stored."""
    if not cv_path:
        return None
    # Legacy corrupted data may contain full URLs like /api/v1/assets/jobs/...?token=...
    if cv_path.startswith("/api/v1/assets/"):
        cv_path = cv_path.replace("/api/v1/assets/", "", 1).split("?")[0]
    # Also handle cases with duplicated prefixes (recursive corruption)
    while cv_path.startswith("api/v1/assets/"):
        cv_path = cv_path.replace("api/v1/assets/", "", 1).split("?")[0]
    return cv_path


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
        utterances: List[Any],
        new_text: Optional[str] = None,
        new_start: Optional[float] = None,
        new_end: Optional[float] = None
    ) -> AnnotationEdit:
        """
        Create a new annotation edit for a segment with utterance-level corrections.
        
        Args:
            segment_id: The segment being edited
            editor_id: The user making the edit
            utterances: List of corrected utterances (dicts or UtteranceCorrection objects)
            new_text: Optional aggregated corrected transcript text (auto-computed if not provided)
            new_start: Optional aggregated start timestamp (auto-computed if not provided)
            new_end: Optional aggregated end timestamp (auto-computed if not provided)
            
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
        
        # Convert utterances to dicts and auto-compute aggregated values if needed
        utterance_dicts = []
        for u in utterances:
            if hasattr(u, 'model_dump'):
                d = u.model_dump()
            elif hasattr(u, 'dict'):
                d = u.dict()
            else:
                d = dict(u)
            # Sanitize cropped_video_path to prevent URL corruption from legacy data
            if d.get('cropped_video_path'):
                d['cropped_video_path'] = _sanitize_cv_path(d['cropped_video_path'])
            utterance_dicts.append(d)
        
        # Auto-compute aggregated values from utterances if not provided
        if not new_text and utterance_dicts:
            sorted_u = sorted(utterance_dicts, key=lambda x: x['utterance_index'])
            new_text = " ".join(u['text'] for u in sorted_u)
            new_start = min(u['start'] for u in utterance_dicts)
            new_end = max(u['end'] for u in utterance_dicts)
        
        # Validate timestamps
        min_time = 0.0
        max_time = segment.jbi_end if segment.jbi_end is not None else (segment.asr_end if segment.asr_end is not None else new_end)
        
        if new_start is not None and new_start < min_time:
            new_start = min_time
        
        if new_end is not None and max_time is not None and new_end > max_time:
            new_end = max_time
        
        if new_start is not None and new_end is not None and new_start >= new_end:
            raise ValidationError("Start time must be less than end time")
        
        # Clamp individual utterance start times to >= 0, but do NOT clamp end
        # times to segment boundaries — cross-segment trim-out requires end
        # timestamps that can exceed the current segment.
        for u_dict in utterance_dicts:
            if u_dict.get('start') is not None and u_dict['start'] < min_time:
                u_dict['start'] = min_time
        
        # Determine old values (from ASR or previous edit)
        old_text, old_start, old_end = await self._get_current_values(segment_id)
        
        # Create the edit
        edit = AnnotationEdit(
            segment_id=segment_id,
            editor_id=editor_id,
            old_text=old_text,
            old_start=old_start,
            old_end=old_end,
            new_text=new_text or "",
            new_start=new_start or 0.0,
            new_end=new_end or 0.0,
            utterance_corrections=utterance_dicts,
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
    
    async def create_draft(
        self,
        segment_id: UUID,
        editor_id: UUID,
        utterances: List[Any],
        new_text: Optional[str] = None,
        new_start: Optional[float] = None,
        new_end: Optional[float] = None
    ) -> AnnotationEdit:
        """
        Save an annotation edit as draft with utterance-level corrections.
        
        Draft edits:
        - Can be overwritten by subsequent drafts
        - Not visible to curators
        - Allow annotator to save progress without submitting
        """
        # Validation same as regular edit
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found in annotation queue")
        
        if queue_entry.annotator_id != editor_id:
            raise PermissionError("You are not assigned to edit this segment")
        
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Convert utterances to dicts and auto-compute aggregated values if needed
        utterance_dicts = []
        for u in utterances:
            if hasattr(u, 'model_dump'):
                utterance_dicts.append(u.model_dump())
            elif hasattr(u, 'dict'):
                utterance_dicts.append(u.dict())
            else:
                utterance_dicts.append(dict(u))
        
        # Auto-compute aggregated values from utterances if not provided
        if not new_text and utterance_dicts:
            sorted_u = sorted(utterance_dicts, key=lambda x: x['utterance_index'])
            new_text = " ".join(u['text'] for u in sorted_u)
            new_start = min(u['start'] for u in utterance_dicts)
            new_end = max(u['end'] for u in utterance_dicts)
        
        # Validate timestamps
        min_time = 0.0
        max_time = segment.jbi_end if segment.jbi_end is not None else (segment.asr_end if segment.asr_end is not None else new_end)
        
        if new_start is not None and new_start < min_time:
            new_start = min_time
        
        if new_end is not None and max_time is not None and new_end > max_time:
            new_end = max_time
        
        # Clamp individual utterance start times to >= 0, but do NOT clamp end
        # times to segment boundaries — cross-segment trim-out requires end
        # timestamps that can exceed the current segment.
        for u_dict in utterance_dicts:
            if u_dict.get('start') is not None and u_dict['start'] < min_time:
                u_dict['start'] = min_time
        
        # Get current values (excluding previous drafts)
        old_text, old_start, old_end = await self._get_current_values_for_draft(segment_id, editor_id)
        
        # Sort utterances by utterance_index before storing for consistent ordering
        utterance_dicts.sort(key=lambda x: x.get('utterance_index', 0))
        
        # Create draft edit
        draft = AnnotationEdit(
            segment_id=segment_id,
            editor_id=editor_id,
            old_text=old_text,
            old_start=old_start,
            old_end=old_end,
            new_text=new_text or "",
            new_start=new_start or 0.0,
            new_end=new_end or 0.0,
            utterance_corrections=utterance_dicts,
            status=AnnotationEdit.STATUS_DRAFT,
            is_deleted=False,
            edited_at=datetime.utcnow()
        )
        
        return await self.edit_repo.create(draft)
    
    async def get_preview(
        self,
        segment_id: UUID,
        user_id: UUID,
        start_time: float,
        end_time: float
    ) -> dict:
        """
        Get preview data for annotation with specific timestamps.
        
        Returns video URL and metadata for the annotator to verify
        synchronization before saving/submitting.
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        if queue_entry.annotator_id != user_id:
            raise PermissionError("You can only preview your assigned segments")
        
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment or not segment.cropped_video_path:
            raise NotFoundError("Video not available for preview")
        
        # Generate assets endpoint URL with streaming token
        token = streaming_token_service.generate_token(
            user_id, segment.cropped_video_path
        )
        video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"
        
        return {
            "segment_id": segment_id,
            "video_url": video_url,
            "start_time": start_time,
            "end_time": end_time,
            "duration": end_time - start_time
        }
    
    async def reset_to_original(
        self,
        segment_id: UUID,
        editor_id: UUID
    ) -> dict:
        """
        Reset all edits for a segment back to ASR-original state.
        
        This operation:
        1. Soft-deletes all existing edits by this user
        2. Creates a "reset" edit record for audit trail
        3. Returns the ASR-original values
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        if queue_entry.annotator_id != editor_id:
            raise PermissionError("You can only reset your own edits")
        
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Soft delete all user's edits for this segment
        deleted_count = await self.edit_repo.soft_delete_all_for_segment(
            segment_id=segment_id,
            editor_id=editor_id
        )
        
        # Create reset record for audit trail
        # This records that a reset happened and what values were reverted to
        reset_edit = AnnotationEdit(
            segment_id=segment_id,
            editor_id=editor_id,
            old_text=None,  # Reset has no "old" value
            old_start=None,
            old_end=None,
            new_text=segment.asr_text or "",
            new_start=segment.asr_start or 0.0,
            new_end=segment.asr_end or 0.0,
            utterance_corrections=None,  # Reset clears all utterance corrections
            status=AnnotationEdit.STATUS_PENDING,  # Reset is pending, not draft
            is_deleted=False,
            edited_at=datetime.utcnow()
        )
        reset_record = await self.edit_repo.create(reset_edit)
        
        return {
            "segment_id": segment_id,
            "reset_edit_id": reset_record.id,
            "edits_removed": deleted_count,
            "message": f"Reset completed. {deleted_count} edit(s) removed.",
            "reverted_to": {
                "text": segment.asr_text or "",
                "start": segment.asr_start or 0.0,
                "end": segment.asr_end or 0.0
            }
        }
    
    async def _get_current_values_for_draft(
        self,
        segment_id: UUID,
        editor_id: UUID
    ) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        """
        Get current values for draft creation.
        
        For drafts, we look at the latest non-draft, non-deleted edit
        by this editor, or fall back to ASR values.
        """
        latest_edit = await self.edit_repo.get_latest_non_draft(segment_id, editor_id)
        if latest_edit:
            return (
                latest_edit.new_text,
                latest_edit.new_start,
                latest_edit.new_end
            )
        
        segment = await self.segment_repo.get_by_id(segment_id)
        if segment:
            return (
                segment.asr_text,
                segment.asr_start,
                segment.asr_end
            )
        
        return (None, None, None)
    
    async def get_current_values_with_draft(
        self,
        segment_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Get current values for a segment, including any draft edits.
        
        This is used when loading a segment for editing - it returns
        the most recent values (whether draft, pending, or ASR).
        """
        # Verify access
        queue_entry = await self.queue_repo.get_by_segment(segment_id)
        if not queue_entry:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        if queue_entry.annotator_id != user_id:
            raise PermissionError("You are not assigned to view this segment")
        
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Get latest edit (including drafts)
        latest_edit = await self.edit_repo.get_latest_by_segment(segment_id)
        
        if latest_edit:
            return {
                "source": "edit",
                "edit_id": latest_edit.id,
                "status": latest_edit.status,
                "text": latest_edit.new_text,
                "start": latest_edit.new_start,
                "end": latest_edit.new_end,
                "utterances": [
                    {
                        **u,
                        "cropped_video_path": _sanitize_cv_path(u.get("cropped_video_path"))
                    }
                    for u in latest_edit.utterance_corrections
                ] if latest_edit.utterance_corrections else [],
                "edited_at": latest_edit.edited_at
            }
        
        # No edits, use ASR
        return {
            "source": "asr",
            "text": segment.asr_text or "",
            "start": segment.asr_start or 0.0,
            "end": segment.asr_end or 0.0,
            "utterances": [
                {
                    "utterance_index": t.utterance_index,
                    "text": t.text,
                    "start": t.start,
                    "end": t.end
                }
                for t in sorted(segment.transcripts, key=lambda x: x.utterance_index)
            ] if segment.transcripts else []
        }
