"""Annotation queue service."""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.job_repository import JobRepository
from app.services.minio_service import get_minio_service
from app.core.exceptions import NotFoundError, PermissionError
from app.core.config import settings
from app.db.models.annotation import AnnotationQueue


class AnnotationQueueService:
    """Service for annotation queue operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.queue_repo = AnnotationQueueRepository(db)
        self.edit_repo = AnnotationEditRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.job_repo = JobRepository(db)
        self.minio_service = get_minio_service()
    
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
        
        # Get segment details with transcripts
        segment = await self.segment_repo.get_by_id_with_transcripts(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Get job details for metadata
        job = await self.job_repo.get_by_id(segment.job_id)
        
        # Generate assets endpoint URL (authenticated, supports streaming)
        video_url = ""
        if segment.cropped_video_path:
            video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}"
        
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
        
        # Get first transcript for ASR data (if available)
        first_transcript = segment.transcripts[0] if segment.transcripts else None
        
        return {
            "segment_id": segment.id,
            "job_id": segment.job_id,
            "original_filename": job.original_filename if job else "Unknown",
            "video_url": video_url,
            "video_duration": None,  # TODO: Calculate from video metadata
            # ASR Data from first transcript
            "asr_text": first_transcript.text if first_transcript else None,
            "asr_start": first_transcript.start if first_transcript else None,
            "asr_end": first_transcript.end if first_transcript else None,
            "asr_confidence": first_transcript.confidence if first_transcript else None,
            # JBI Timestamps - use first transcript times or None
            "jbi_start": first_transcript.start if first_transcript else None,
            "jbi_end": first_transcript.end if first_transcript else None,
            # Current State
            "current_text": current_text,
            "current_start": current_start,
            "current_end": current_end,
            "edit_history": edit_history,
            "queue_status": queue_entry.status,
            "priority": queue_entry.priority
        }
    
    async def _build_queue_item(self, entry) -> dict:
        """Build a queue item response with metadata and active edit information."""
        segment = await self.segment_repo.get_by_id_with_transcripts(entry.segment_id)
        job = None
        if segment:
            job = await self.job_repo.get_by_id(segment.job_id)
        
        # Get preview URL via assets endpoint (authenticated)
        video_preview_url = ""
        if segment and segment.cropped_video_path:
            video_preview_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}"
        
        # Get first transcript text if available
        transcript_text = None
        if segment and segment.transcripts:
            first_transcript = segment.transcripts[0]
            transcript_text = first_transcript.text if first_transcript else None
        
        # Get latest ACTIVE edit (DRAFT, PENDING, SUBMITTED) - Option B
        latest_edit = await self.edit_repo.get_latest_active_by_segment(
            segment_id=entry.segment_id,
            editor_id=entry.annotator_id
        )
        
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
            "asr_confidence": segment.transcripts[0].confidence if (segment and segment.transcripts and segment.transcripts[0]) else None,
            # Active edit information (Option B)
            "edit_id": latest_edit.id if latest_edit else None,
            "edit_status": latest_edit.status if latest_edit else None,
            "has_active_work": latest_edit is not None,
            "last_edited_at": latest_edit.edited_at if latest_edit else None
        }
    
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
    
    async def _get_current_values(
        self,
        segment,
        edit_history: List[dict]
    ) -> Tuple[str, float, float]:
        """Determine current transcript values from edits or ASR."""
        # Get the latest non-deleted edit for this segment
        latest_edit = await self.edit_repo.get_latest_by_segment(segment.id)
        
        if latest_edit:
            return (
                latest_edit.new_text,
                latest_edit.new_start,
                latest_edit.new_end
            )
        
        # Otherwise use first transcript values if available
        if segment.transcripts and len(segment.transcripts) > 0:
            first = segment.transcripts[0]
            return (
                first.text or "",
                first.start or 0.0,
                first.end or 0.0
            )
        return ("", 0.0, 0.0)
