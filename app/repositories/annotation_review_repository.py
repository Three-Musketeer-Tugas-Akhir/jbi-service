"""Annotation review repository."""
from typing import List, Optional
from uuid import UUID
from datetime import datetime

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import AnnotationReview


class AnnotationReviewRepository:
    """Repository for annotation review operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, review: AnnotationReview) -> AnnotationReview:
        """Create a new review record."""
        self.db.add(review)
        await self.db.flush()
        await self.db.refresh(review)
        return review
    
    async def get_by_id(self, review_id: UUID) -> Optional[AnnotationReview]:
        """Get review by ID."""
        query = select(AnnotationReview).where(AnnotationReview.id == review_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_edit_id(self, edit_id: UUID) -> Optional[AnnotationReview]:
        """Get review by edit ID."""
        query = select(AnnotationReview).where(
            AnnotationReview.edit_id == edit_id
        )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_pending_reviews(
        self,
        curator_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[AnnotationReview]:
        """Get pending reviews, optionally filtered by curator assignment."""
        query = select(AnnotationReview).where(
            AnnotationReview.status == AnnotationReview.STATUS_PENDING
        )
        
        if curator_id:
            query = query.where(AnnotationReview.curator_id == curator_id)
        
        query = query.order_by(desc(AnnotationReview.reviewed_at))
        query = query.limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def update_status(
        self,
        review_id: UUID,
        status: str,
        curator_id: Optional[UUID] = None,
        feedback: Optional[str] = None
    ) -> bool:
        """Update review status (approve/reject)."""
        review = await self.get_by_id(review_id)
        if not review:
            return False
        
        review.status = status
        if curator_id:
            review.curator_id = curator_id
        if feedback is not None:
            review.feedback = feedback
        
        await self.db.flush()
        return True
