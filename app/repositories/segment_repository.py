"""Segment repository for detection results."""

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineSegment


class SegmentRepository:
    """Repository for pipeline segment operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_many(self, segments: List[PipelineSegment]) -> None:
        """Bulk insert segments."""
        for segment in segments:
            self.db.add(segment)
        await self.db.flush()
    
    async def get_by_job_id(self, job_id: UUID) -> List[PipelineSegment]:
        """Get all segments for a job."""
        result = await self.db.execute(
            select(PipelineSegment)
            .where(PipelineSegment.job_id == job_id)
            .order_by(PipelineSegment.segment_index)
        )
        return result.scalars().all()
    
    async def get_by_id(self, segment_id: UUID) -> Optional[PipelineSegment]:
        """Get segment by ID."""
        result = await self.db.execute(
            select(PipelineSegment).where(PipelineSegment.id == segment_id)
        )
        return result.scalar_one_or_none()


def get_segment_repository(db: AsyncSession) -> SegmentRepository:
    return SegmentRepository(db)
