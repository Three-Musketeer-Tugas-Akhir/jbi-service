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
