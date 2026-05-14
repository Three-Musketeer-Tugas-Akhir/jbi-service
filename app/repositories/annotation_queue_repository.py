"""Annotation queue repository."""
from datetime import datetime
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
        dataset_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[AnnotationQueue]:
        """Get queue entries for an annotator, optionally filtered by dataset."""
        from app.db.models.pipeline import PipelineSegment, PipelineJob

        query = select(AnnotationQueue).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        if dataset_id:
            query = (
                query
                .join(PipelineSegment, AnnotationQueue.segment_id == PipelineSegment.id)
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(PipelineJob.dataset_id == dataset_id)
            )
        
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
    
    async def get_by_job_id(
        self,
        job_id: UUID
    ) -> List[AnnotationQueue]:
        """Get all queue entries for segments belonging to a job."""
        from app.db.models.pipeline import PipelineSegment
        
        query = (
            select(AnnotationQueue)
            .join(PipelineSegment, AnnotationQueue.segment_id == PipelineSegment.id)
            .where(PipelineSegment.job_id == job_id)
        )
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_annotator(
        self,
        queue_id: UUID,
        new_annotator_id: UUID
    ) -> bool:
        """Update the annotator assigned to a queue entry."""
        entry = await self.get_by_id(queue_id)
        if not entry:
            return False
        
        entry.annotator_id = new_annotator_id
        entry.assigned_at = datetime.utcnow()
        await self.db.flush()
        return True
    
    async def count_by_annotator(
        self,
        annotator_id: UUID,
        status: Optional[str] = None,
        dataset_id: Optional[UUID] = None,
    ) -> int:
        """Count queue entries for an annotator, optionally filtered by dataset."""
        from app.db.models.pipeline import PipelineSegment, PipelineJob

        query = select(func.count(AnnotationQueue.id)).where(
            AnnotationQueue.annotator_id == annotator_id
        )
        
        if status:
            query = query.where(AnnotationQueue.status == status)
        
        if dataset_id:
            query = (
                query
                .join(PipelineSegment, AnnotationQueue.segment_id == PipelineSegment.id)
                .join(PipelineJob, PipelineSegment.job_id == PipelineJob.id)
                .where(PipelineJob.dataset_id == dataset_id)
            )
        
        result = await self.db.execute(query)
        return result.scalar()
