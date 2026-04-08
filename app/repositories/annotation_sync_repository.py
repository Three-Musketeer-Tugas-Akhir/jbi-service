"""
Annotation Sync Repository.

Database operations for annotation synchronization data.
"""
from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation_sync import AnnotationSync, AnnotationSyncHistory


class AnnotationSyncRepository:
    """Repository for annotation sync operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_edit_id(self, edit_id: UUID) -> Optional[AnnotationSync]:
        """Get sync data by annotation edit ID."""
        stmt = select(AnnotationSync).where(
            AnnotationSync.annotation_edit_id == edit_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, sync_id: UUID) -> Optional[AnnotationSync]:
        """Get sync data by ID."""
        stmt = select(AnnotationSync).where(AnnotationSync.id == sync_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(self, sync: AnnotationSync) -> AnnotationSync:
        """Create new sync data."""
        self.session.add(sync)
        await self.session.flush()
        await self.session.refresh(sync)
        return sync
    
    async def update(
        self,
        sync_id: UUID,
        video_start_offset: Optional[float] = None,
        video_end_offset: Optional[float] = None,
        glosa: Optional[str] = None,
        precision_ms: Optional[float] = None,
        sync_status: Optional[str] = None,
        text_match: Optional[bool] = None,
        video_complete: Optional[bool] = None,
        sync_locked: Optional[bool] = None
    ) -> Optional[AnnotationSync]:
        """Update sync data."""
        sync = await self.get_by_id(sync_id)
        if not sync:
            return None
        
        if video_start_offset is not None:
            sync.video_start_offset = video_start_offset
        if video_end_offset is not None:
            sync.video_end_offset = video_end_offset
        if glosa is not None:
            sync.glosa = glosa
        if precision_ms is not None:
            sync.precision_ms = precision_ms
        if sync_status is not None:
            sync.sync_status = sync_status
        if text_match is not None:
            sync.text_match = text_match
        if video_complete is not None:
            sync.video_complete = video_complete
        if sync_locked is not None:
            sync.sync_locked = sync_locked
        
        await self.session.flush()
        await self.session.refresh(sync)
        return sync
    
    async def create_or_update(
        self,
        edit_id: UUID,
        audio_start: float,
        audio_end: float,
        video_start_offset: Optional[float] = None,
        video_end_offset: Optional[float] = None,
        glosa: Optional[str] = None,
        precision_ms: float = 33.0
    ) -> AnnotationSync:
        """Create or update sync data for an edit."""
        existing = await self.get_by_edit_id(edit_id)
        
        if existing:
            return await self.update(
                existing.id,
                video_start_offset=video_start_offset,
                video_end_offset=video_end_offset,
                glosa=glosa,
                precision_ms=precision_ms
            )
        
        new_sync = AnnotationSync(
            annotation_edit_id=edit_id,
            audio_start=audio_start,
            audio_end=audio_end,
            video_start_offset=video_start_offset,
            video_end_offset=video_end_offset,
            glosa=glosa,
            precision_ms=precision_ms
        )
        return await self.create(new_sync)
    
    async def get_history(self, sync_id: UUID, limit: int = 50) -> List[AnnotationSyncHistory]:
        """Get sync adjustment history."""
        stmt = (
            select(AnnotationSyncHistory)
            .where(AnnotationSyncHistory.sync_id == sync_id)
            .order_by(desc(AnnotationSyncHistory.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def add_history_entry(
        self,
        sync_id: UUID,
        user_id: Optional[UUID],
        previous_start: Optional[float],
        previous_end: Optional[float],
        new_start: Optional[float],
        new_end: Optional[float],
        change_reason: Optional[str] = None
    ) -> AnnotationSyncHistory:
        """Add a history entry for audit trail."""
        entry = AnnotationSyncHistory(
            sync_id=sync_id,
            user_id=user_id,
            previous_video_start=previous_start,
            previous_video_end=previous_end,
            new_video_start=new_start,
            new_video_end=new_end,
            change_reason=change_reason
        )
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry
