"""
Annotation Synchronization Service.

Business logic for video-audio temporal alignment.
"""
from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation_sync import AnnotationSync
from app.db.models.annotation import AnnotationEdit
from app.db.models.pipeline import PipelineSegment, PipelineTranscript
from app.repositories.annotation_sync_repository import AnnotationSyncRepository
from app.repositories.annotation_edit_repository import AnnotationEditRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.transcript_repository import TranscriptRepository
from app.services.minio_service import get_minio_service
from app.core.exceptions import NotFoundError, PermissionError, ValidationError


class AnnotationSyncService:
    """Service for annotation synchronization operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.sync_repo = AnnotationSyncRepository(db)
        self.edit_repo = AnnotationEditRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.transcript_repo = TranscriptRepository(db)
        self.minio_service = get_minio_service()
    
    async def get_sync_data(
        self,
        edit_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Get sync data for an annotation edit.
        
        Args:
            edit_id: Annotation edit ID
            user_id: Requesting user ID
            
        Returns:
            Dict with sync data and computed fields
        """
        # Get edit with permission check
        edit = await self.edit_repo.get_by_id(edit_id)
        if not edit:
            raise NotFoundError(f"Annotation edit {edit_id} not found")
        
        # Check permission (editor or admin)
        if edit.editor_id != user_id:
            # TODO: Check if user is admin
            raise PermissionError("You can only access your own annotations")
        
        # Get or create sync data
        sync = await self.sync_repo.get_by_edit_id(edit_id)
        
        if not sync:
            # Create default sync data from edit timestamps
            sync = await self.sync_repo.create_or_update(
                edit_id=edit_id,
                audio_start=edit.new_start,
                audio_end=edit.new_end,
                video_start_offset=None,
                video_end_offset=None
            )
        
        return self._format_sync_response(sync)
    
    async def update_sync_boundaries(
        self,
        edit_id: UUID,
        user_id: UUID,
        video_start_offset: Optional[float] = None,
        video_end_offset: Optional[float] = None,
        glosa: Optional[str] = None,
        precision_ms: Optional[float] = None
    ) -> dict:
        """
        Update video boundaries for sync.
        
        Args:
            edit_id: Annotation edit ID
            user_id: User making the change
            video_start_offset: New video start time
            video_end_offset: New video end time
            glosa: Sign language gloss
            precision_ms: Precision setting
            
        Returns:
            Updated sync data
        """
        # Get edit with permission check
        edit = await self.edit_repo.get_by_id(edit_id)
        if not edit:
            raise NotFoundError(f"Annotation edit {edit_id} not found")
        
        if edit.editor_id != user_id:
            raise PermissionError("You can only modify your own annotations")
        
        # Get or create sync
        sync = await self.sync_repo.get_by_edit_id(edit_id)
        if not sync:
            sync = await self.sync_repo.create_or_update(
                edit_id=edit_id,
                audio_start=edit.new_start,
                audio_end=edit.new_end
            )
        
        # Store previous values for history
        prev_start = sync.video_start_offset
        prev_end = sync.video_end_offset
        
        # Validate boundaries
        effective_start = video_start_offset if video_start_offset is not None else sync.audio_start
        effective_end = video_end_offset if video_end_offset is not None else sync.audio_end
        
        if effective_end <= effective_start:
            raise ValidationError("Video end must be after video start")
        
        # Update sync
        updated = await self.sync_repo.update(
            sync.id,
            video_start_offset=video_start_offset,
            video_end_offset=video_end_offset,
            glosa=glosa,
            precision_ms=precision_ms
        )
        
        # Add history entry
        await self.sync_repo.add_history_entry(
            sync_id=sync.id,
            user_id=user_id,
            previous_start=prev_start,
            previous_end=prev_end,
            new_start=video_start_offset,
            new_end=video_end_offset,
            change_reason="Manual boundary adjustment"
        )
        
        await self.db.commit()
        
        return self._format_sync_response(updated)
    
    async def fine_tune_sync(
        self,
        edit_id: UUID,
        user_id: UUID,
        adjustment_ms: float,
        target: str
    ) -> dict:
        """
        Fine-tune sync with millisecond precision.
        
        Args:
            edit_id: Annotation edit ID
            user_id: User making the change
            adjustment_ms: Adjustment in milliseconds (+/-)
            target: Which boundary to adjust ('start', 'end', or 'both')
            
        Returns:
            Result with before/after values
        """
        edit = await self.edit_repo.get_by_id(edit_id)
        if not edit:
            raise NotFoundError(f"Annotation edit {edit_id} not found")
        
        if edit.editor_id != user_id:
            raise PermissionError("You can only modify your own annotations")
        
        sync = await self.sync_repo.get_by_edit_id(edit_id)
        if not sync:
            raise NotFoundError("Sync data not found. Initialize sync first.")
        
        adjustment_sec = adjustment_ms / 1000.0
        
        prev_start = sync.video_start_offset
        prev_end = sync.video_end_offset
        
        new_start = prev_start
        new_end = prev_end
        
        if target == "start":
            new_start = (prev_start or sync.audio_start) + adjustment_sec
        elif target == "end":
            new_end = (prev_end or sync.audio_end) + adjustment_sec
        elif target == "both":
            new_start = (prev_start or sync.audio_start) + adjustment_sec
            new_end = (prev_end or sync.audio_end) + adjustment_sec
        
        # Validate
        effective_start = new_start if new_start is not None else sync.audio_start
        effective_end = new_end if new_end is not None else sync.audio_end
        
        if effective_end <= effective_start:
            raise ValidationError("Adjustment would make video end before start")
        
        # Update
        updated = await self.sync_repo.update(
            sync.id,
            video_start_offset=new_start,
            video_end_offset=new_end
        )
        
        await self.sync_repo.add_history_entry(
            sync_id=sync.id,
            user_id=user_id,
            previous_start=prev_start,
            previous_end=prev_end,
            new_start=new_start,
            new_end=new_end,
            change_reason=f"Fine-tune: {adjustment_ms}ms on {target}"
        )
        
        await self.db.commit()
        
        return {
            "edit_id": edit_id,
            "adjustment_ms": adjustment_ms,
            "previous_start": prev_start,
            "previous_end": prev_end,
            "new_start": new_start,
            "new_end": new_end,
            "video_duration": effective_end - effective_start,
            "message": f"Adjusted {target} by {adjustment_ms}ms"
        }
    
    async def validate_sync(
        self,
        edit_id: UUID,
        user_id: UUID,
        text_match: bool = False,
        video_complete: bool = False,
        sync_locked: bool = False
    ) -> dict:
        """
        Validate and update sync status.
        
        Args:
            edit_id: Annotation edit ID
            user_id: User ID
            text_match: Whether text matches audio
            video_complete: Whether video captures full JBI
            sync_locked: Whether to lock the sync
            
        Returns:
            Validation result with warnings/suggestions
        """
        edit = await self.edit_repo.get_by_id(edit_id)
        if not edit:
            raise NotFoundError(f"Annotation edit {edit_id} not found")
        
        if edit.editor_id != user_id:
            raise PermissionError("You can only validate your own annotations")
        
        sync = await self.sync_repo.get_by_edit_id(edit_id)
        if not sync:
            raise NotFoundError("Sync data not found")
        
        warnings = []
        suggestions = []
        
        # Calculate extension
        extension = sync.get_extension_seconds()
        
        # Determine sync status
        if sync_locked:
            sync_status = AnnotationSync.STATUS_LOCKED
        elif text_match and video_complete:
            sync_status = AnnotationSync.STATUS_SYNCED
        elif text_match or video_complete:
            sync_status = AnnotationSync.STATUS_PARTIAL
        else:
            sync_status = AnnotationSync.STATUS_UNSYNCED
        
        # Generate warnings
        if extension > 5.0:
            warnings.append(f"Large video extension ({extension:.1f}s). Verify this is intentional.")
        
        if not video_complete and extension == 0:
            suggestions.append("Consider extending video end time to capture complete JBI movement")
        
        if not text_match:
            suggestions.append("Review text alignment with audio waveform")
        
        # Update sync
        await self.sync_repo.update(
            sync.id,
            sync_status=sync_status,
            text_match=text_match,
            video_complete=video_complete,
            sync_locked=sync_locked
        )
        
        await self.db.commit()
        
        return {
            "edit_id": edit_id,
            "is_valid": sync_status in (AnnotationSync.STATUS_SYNCED, AnnotationSync.STATUS_LOCKED),
            "sync_status": sync_status,
            "indicators": {
                "text_match": text_match,
                "video_complete": video_complete,
                "sync_locked": sync_locked
            },
            "warnings": warnings,
            "suggestions": suggestions
        }
    
    async def get_sync_context(
        self,
        segment_id: UUID,
        user_id: UUID,
        context_range: int = 2
    ) -> dict:
        """
        Get sync data with surrounding context.
        
        Args:
            segment_id: Current segment ID
            user_id: User ID
            context_range: Number of neighboring segments to include
            
        Returns:
            Dict with current segment and context
        """
        # Get segment
        segment = await self.segment_repo.get_by_id(segment_id)
        if not segment:
            raise NotFoundError(f"Segment {segment_id} not found")
        
        # Get all transcripts for this segment's job
        transcripts = await self.transcript_repo.get_by_segment_id(segment_id)
        if not transcripts:
            raise NotFoundError("No transcripts found for segment")
        
        # Build context
        context = {
            "segment_id": segment_id,
            "transcripts": [],
            "previous_segments": [],
            "next_segments": []
        }
        
        # TODO: Implement proper context fetching from neighboring segments
        # This requires getting adjacent segments from the same job
        
        return context
    
    async def get_stitched_preview(
        self,
        edit_id: UUID,
        user_id: UUID,
        buffer_seconds: float = 2.0
    ) -> dict:
        """
        Get preview URL for stitched video.
        
        Args:
            edit_id: Annotation edit ID
            user_id: User ID
            buffer_seconds: Buffer time for stitching
            
        Returns:
            Preview data with video URL
        """
        edit = await self.edit_repo.get_by_id(edit_id)
        if not edit:
            raise NotFoundError(f"Annotation edit {edit_id} not found")
        
        if edit.editor_id != user_id:
            raise PermissionError("You can only preview your own annotations")
        
        sync = await self.sync_repo.get_by_edit_id(edit_id)
        if not sync:
            # Return default preview from edit
            video_url = await self._get_video_url_for_edit(edit)
            return {
                "edit_id": edit_id,
                "segment_id": edit.segment_id,
                "original_start": edit.new_start,
                "original_end": edit.new_end,
                "stitched_start": edit.new_start,
                "stitched_end": edit.new_end,
                "total_duration": edit.new_end - edit.new_start,
                "video_url": video_url,
                "requires_stitching": False,
                "stitched_segments": [],
                "sync_status": AnnotationSync.STATUS_UNSYNCED,
                "extension_seconds": 0.0
            }
        
        # Calculate stitched range
        video_start = sync.get_effective_video_start()
        video_end = sync.get_effective_video_end()
        
        # Get video URL
        video_url = await self._get_video_url_for_edit(edit)
        
        # Check if stitching is needed
        requires_stitching = (
            video_start < sync.audio_start - 0.5 or
            video_end > sync.audio_end + 0.5
        )
        
        return {
            "edit_id": edit_id,
            "segment_id": edit.segment_id,
            "original_start": sync.audio_start,
            "original_end": sync.audio_end,
            "stitched_start": video_start,
            "stitched_end": video_end,
            "total_duration": video_end - video_start,
            "video_url": video_url,
            "requires_stitching": requires_stitching,
            "stitched_segments": [],  # TODO: Populate if multi-chunk
            "sync_status": sync.sync_status,
            "extension_seconds": sync.get_extension_seconds()
        }
    
    async def _get_video_url_for_edit(self, edit: AnnotationEdit) -> str:
        """Get pre-signed video URL for an edit."""
        segment = await self.segment_repo.get_by_id(edit.segment_id)
        if segment and segment.cropped_video_path:
            return await self.minio_service.generate_presigned_url(
                object_name=segment.cropped_video_path,
                expiry=3600
            )
        return ""
    
    def _format_sync_response(self, sync: AnnotationSync) -> dict:
        """Format sync data for response."""
        return {
            "id": sync.id,
            "annotation_edit_id": sync.annotation_edit_id,
            "audio_start": sync.audio_start,
            "audio_end": sync.audio_end,
            "audio_duration": sync.get_audio_duration(),
            "video_start_offset": sync.video_start_offset,
            "video_end_offset": sync.video_end_offset,
            "video_duration": sync.get_video_duration(),
            "extension_seconds": sync.get_extension_seconds(),
            "sync_status": sync.sync_status,
            "glosa": sync.glosa,
            "precision_ms": sync.precision_ms,
            "indicators": {
                "text_match": sync.text_match,
                "video_complete": sync.video_complete,
                "sync_locked": sync.sync_locked
            },
            "created_at": sync.created_at,
            "updated_at": sync.updated_at
        }
