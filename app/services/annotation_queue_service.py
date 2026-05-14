"""Annotation queue service."""
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models.voice_annotation import VoiceAnnotation

from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.job_repository import JobRepository
from app.services.minio_service import get_minio_service
from app.services.streaming_token_service import streaming_token_service
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
        dataset_id: Optional[UUID] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """Get paginated queue for an annotator, optionally filtered by dataset."""
        offset = (page - 1) * page_size
        
        # Get queue entries
        entries = await self.queue_repo.get_by_annotator(
            annotator_id=annotator_id,
            status=status,
            dataset_id=dataset_id,
            limit=page_size,
            offset=offset
        )
        
        # Get total count
        total = await self.queue_repo.count_by_annotator(
            annotator_id=annotator_id,
            status=status,
            dataset_id=dataset_id,
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
        
        # Generate assets endpoint URL with streaming token
        video_url = ""
        if segment.cropped_video_path:
            token = streaming_token_service.generate_token(
                annotator_id, segment.cropped_video_path
            )
            video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"
        
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
        
        # Build transcripts list from all utterances, using Voice Annotation ground truth if available
        transcripts = []
        if segment.transcripts:
            sorted_transcripts = sorted(segment.transcripts, key=lambda t: t.utterance_index)
            
            # Fetch voice annotations for these transcripts
            transcript_ids = [t.id for t in sorted_transcripts]
            va_query = select(VoiceAnnotation).where(VoiceAnnotation.transcript_id.in_(transcript_ids))
            va_result = await self.db.execute(va_query)
            voice_annotations = {va.transcript_id: va for va in va_result.scalars().all()}
            
            transcripts = []
            for t in sorted_transcripts:
                cv2_url = None
                if t.video_path:
                    token = streaming_token_service.generate_token(annotator_id, t.video_path)
                    cv2_url = f"{settings.api_v1_prefix}/assets/{t.video_path}?token={token}"
                
                transcripts.append({
                    "utterance_index": t.utterance_index,
                    "text": voice_annotations[t.id].ground_truth_text if t.id in voice_annotations else t.text,
                    "start": t.start,
                    "end": t.end,
                    "confidence": t.confidence,
                    "video_path": cv2_url,
                    "merged_video_path": t.merged_video_path,
                    "video_n_duration": t.video_n_duration,
                })
        
        # Get current utterance corrections from latest edit (if any)
        latest_edit = await self.edit_repo.get_latest_by_segment(segment.id)
        current_utterances = None
        if latest_edit and latest_edit.utterance_corrections:
            current_utterances = []
            for u in latest_edit.utterance_corrections:
                cv_path = u.get("cropped_video_path")
                cv_url = None
                if cv_path:
                    # Generate streaming URL for the utterance video
                    token = streaming_token_service.generate_token(annotator_id, cv_path)
                    cv_url = f"{settings.api_v1_prefix}/assets/{cv_path}?token={token}"
                
                current_utterances.append({
                    "utterance_index": u["utterance_index"],
                    "text": u["text"],
                    "start": u["start"],
                    "end": u["end"],
                    "cropped_video_path": cv_url,
                    "status": u.get("status")
                })
        
        return {
            "segment_id": segment.id,
            "job_id": segment.job_id,
            "original_filename": job.original_filename if job else "Unknown",
            "video_url": video_url,
            "video_duration": None,  # TODO: Calculate from video metadata
            # ASR Data — now full list of utterances
            "transcripts": transcripts,
            "avg_confidence": segment.asr_confidence,
            "current_utterances": current_utterances,
            # Backward-compatible aggregated fields
            "asr_text": segment.asr_text,
            "asr_start": segment.asr_start,
            "asr_end": segment.asr_end,
            "asr_confidence": segment.asr_confidence,
            "jbi_start": segment.asr_start,
            "jbi_end": segment.asr_end,
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
        
        # Get preview URL via assets endpoint with streaming token
        video_preview_url = ""
        if segment and segment.cropped_video_path:
            token = streaming_token_service.generate_token(
                entry.annotator_id, segment.cropped_video_path
            )
            video_preview_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"
        
        # Get transcript info using computed properties
        utterance_count = len(segment.transcripts) if segment and segment.transcripts else 0
        transcript_text = segment.asr_text if segment else None
        
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
            "utterance_count": utterance_count,
            "asr_confidence": segment.asr_confidence if segment else None,
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
        
        # Otherwise use aggregated ASR values from segment properties
        if segment.transcripts and len(segment.transcripts) > 0:
            return (
                segment.asr_text or "",
                segment.asr_start or 0.0,
                segment.asr_end or 0.0
            )
        return ("", 0.0, 0.0)
