"""ASR Review repository."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.annotation import ASRReview


class ASRReviewRepository:
    """Repository for ASR review operations."""
    
    LOW_CONFIDENCE_THRESHOLD = 0.5
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(self, review: ASRReview) -> ASRReview:
        """Create a new ASR review record."""
        self.db.add(review)
        await self.db.flush()
        await self.db.refresh(review)
        return review
    
    async def get_by_id(self, review_id: UUID) -> Optional[ASRReview]:
        """Get ASR review by ID."""
        query = select(ASRReview).where(ASRReview.id == review_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_by_segment(self, segment_id: UUID) -> Optional[ASRReview]:
        """Get ASR review by segment ID."""
        query = select(ASRReview).where(ASRReview.segment_id == segment_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
    
    async def get_pending_reviews(
        self,
        reviewer_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[ASRReview]:
        """
        Get pending ASR reviews.
        
        Args:
            reviewer_id: Filter by assigned reviewer (optional)
            limit: Maximum results
            offset: Pagination offset
        """
        query = select(ASRReview).where(
            ASRReview.status == ASRReview.STATUS_PENDING
        )
        
        if reviewer_id:
            query = query.where(ASRReview.reviewer_id == reviewer_id)
        
        # Order by: low confidence first (needs attention), then by segment
        query = query.order_by(
            ASRReview.confidence_score.asc(),
            desc(ASRReview.reviewed_at)
        ).limit(limit).offset(offset)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def get_low_confidence_reviews(
        self,
        threshold: float = None,
        limit: int = 20
    ) -> List[ASRReview]:
        """Get reviews with confidence below threshold."""
        if threshold is None:
            threshold = self.LOW_CONFIDENCE_THRESHOLD
        
        query = select(ASRReview).where(
            and_(
                ASRReview.status == ASRReview.STATUS_PENDING,
                ASRReview.confidence_score < threshold
            )
        ).order_by(ASRReview.confidence_score.asc()).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def count_pending(self) -> int:
        """Count total pending ASR reviews."""
        from sqlalchemy import func
        
        query = select(func.count(ASRReview.id)).where(
            ASRReview.status == ASRReview.STATUS_PENDING
        )
        result = await self.db.execute(query)
        return result.scalar()
    
    async def assign_reviewer(
        self,
        review_id: UUID,
        reviewer_id: UUID
    ) -> bool:
        """Assign a reviewer to an ASR review."""
        review = await self.get_by_id(review_id)
        if not review:
            return False
        
        review.reviewer_id = reviewer_id
        await self.db.flush()
        return True
    
    async def update_status(
        self,
        review_id: UUID,
        status: str,
        corrected_text: Optional[str] = None,
        flag_reason: Optional[str] = None
    ) -> bool:
        """Update ASR review status."""
        from datetime import datetime
        
        review = await self.get_by_id(review_id)
        if not review:
            return False
        
        review.status = status
        review.reviewed_at = datetime.utcnow()
        
        if corrected_text is not None:
            review.corrected_text = corrected_text
        
        if flag_reason is not None:
            review.flag_reason = flag_reason
        
        await self.db.flush()
        return True
