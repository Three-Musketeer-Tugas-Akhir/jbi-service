"""
Transcript Repository.

Database operations for pipeline transcript utterances.
"""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineTranscript


class TranscriptRepository:
    """Repository for transcript operations."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_by_id(self, transcript_id: UUID) -> Optional[PipelineTranscript]:
        """Get transcript by ID."""
        stmt = select(PipelineTranscript).where(PipelineTranscript.id == transcript_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_segment_id(self, segment_id: UUID) -> List[PipelineTranscript]:
        """Get all transcripts for a segment."""
        stmt = (
            select(PipelineTranscript)
            .where(PipelineTranscript.segment_id == segment_id)
            .order_by(PipelineTranscript.utterance_index)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def get_by_segment_and_index(
        self,
        segment_id: UUID,
        utterance_index: int
    ) -> Optional[PipelineTranscript]:
        """Get transcript by segment and utterance index."""
        stmt = (
            select(PipelineTranscript)
            .where(
                PipelineTranscript.segment_id == segment_id,
                PipelineTranscript.utterance_index == utterance_index
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
