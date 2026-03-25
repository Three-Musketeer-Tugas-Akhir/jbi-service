"""Annotation queue repository."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationQueue


class AnnotationQueueRepository:
    """Repository for annotation queue operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_by_annotator(
        self,
        annotator_id: UUID,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[AnnotationQueue]:
        """Get queue entries for an annotator."""
        query = select(AnnotationQueue).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        query = query.order_by(
            AnnotationQueue.priority.desc(),
            AnnotationQueue.assigned_at.asc()
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_by_segment(self, segment_id: UUID) -> Optional[AnnotationQueue]:
        """Get queue entry by segment ID."""
        query = select(AnnotationQueue).where(
            AnnotationQueue.segment_id == segment_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, queue_id: UUID) -> Optional[AnnotationQueue]:
        """Get queue entry by ID."""
        query = select(AnnotationQueue).where(AnnotationQueue.id == queue_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        queue_id: UUID,
        status: str
    ) -> bool:
        """Update queue entry status."""
        entry = await self.get_by_id(queue_id)
        if not entry:
            return False
        
        entry.status = status
        await self.db.flush()
        return True
    
    async def count_by_annotator(
        self,
        annotator_id: UUID,
        status: Optional[str] = None
    ) -> int:
        """Count queue entries for an annotator."""
        query = select(func.count(AnnotationQueue.id)).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        result = await self.db.execute(query)
        return result.scalar()
