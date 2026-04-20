"""ASR Review service."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.asr_review_repository import ASRReviewRepository
from app.repositories.segment_repository import SegmentRepository
from app.repositories.job_repository import JobRepository
from app.repositories.annotation_queue_repository import AnnotationQueueRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.services.minio_service import get_minio_service
from app.services.streaming_token_service import streaming_token_service
from app.core.exceptions import NotFoundError, PermissionError
from app.core.config import settings
from app.db.models.annotation import ASRReview, AnnotationQueue
from app.db.models.audit import AuditAction


class ASRReviewService:
    """Service for ASR review operations."""
    
    LOW_CONFIDENCE_THRESHOLD = 0.5
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.review_repo = ASRReviewRepository(db)
        self.segment_repo = SegmentRepository(db)
        self.job_repo = JobRepository(db)
        self.queue_repo = AnnotationQueueRepository(db)
        self.minio_service = get_minio_service()
        self.audit_repo = AuditLogRepository(db)
    
    async def get_review_queue(
        self,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        low_confidence_only: bool = False
    ) -> dict:
        """
        Get the ASR Review queue.
        
        Returns pending ASR reviews with video URLs and confidence scores.
        Low confidence segments (< 0.5) are flagged for extra attention.
        """
        offset = (page - 1) * page_size
        
        # Get reviews
        if low_confidence_only:
            reviews = await self.review_repo.get_low_confidence_reviews(
                threshold=self.LOW_CONFIDENCE_THRESHOLD,
                limit=page_size
            )
        else:
            reviews = await self.review_repo.get_pending_reviews(
                limit=page_size,
                offset=offset
            )
        
        # Get total counts
        total = await self.review_repo.count_pending()
        low_confidence_count = len(
            await self.review_repo.get_low_confidence_reviews(
                threshold=self.LOW_CONFIDENCE_THRESHOLD,
                limit=10000  # Large limit to get accurate count
            )
        )
        
        # Build response items
        items = []
        for review in reviews:
            item = await self._build_queue_item(review, user_id)
            items.append(item)
        
        pages = (total + page_size - 1) // page_size
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": pages,
            "low_confidence_count": low_confidence_count
        }
    
    async def get_review_detail(
        self,
        review_id: UUID,
        user_id: UUID
    ) -> dict:
        """
        Get complete details for an ASR review.
        
        Includes video URL, ASR transcript, and confidence score.
        Low confidence segments include attention warnings.
        """
        review = await self.review_repo.get_by_id(review_id)
        if not review:
            raise NotFoundError(f"ASR Review {review_id} not found")
        
        # Get segment and job details
        segment = await self.segment_repo.get_by_id(review.segment_id)
        if not segment:
            raise NotFoundError(f"Segment {review.segment_id} not found")
        
        job = await self.job_repo.get_by_id(segment.job_id)
        
        # Generate video URL via assets endpoint with streaming token
        video_url = ""
        if segment.cropped_video_path:
            token = streaming_token_service.generate_token(
                user_id, segment.cropped_video_path
            )
            video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"
        
        # Determine if low confidence
        is_low_confidence = (
            review.confidence_score is not None and
            review.confidence_score < self.LOW_CONFIDENCE_THRESHOLD
        )
        
        attention_message = None
        if is_low_confidence:
            attention_message = (
                f"Low confidence score ({review.confidence_score:.0%}). "
                "Please verify this transcript carefully."
            )
        
        return {
            "review_id": review.id,
            "segment_id": review.segment_id,
            "job_id": segment.job_id,
            "original_filename": job.original_filename if job else "Unknown",
            "video_url": video_url,
            "video_duration": None,  # TODO: Calculate from metadata
            "asr_text": review.original_text,
            "asr_start": segment.asr_start,
            "asr_end": segment.asr_end,
            "confidence_score": review.confidence_score,
            "status": review.status,
            "reviewer_id": review.reviewer_id,
            "reviewed_at": review.reviewed_at,
            "is_low_confidence": is_low_confidence,
            "attention_message": attention_message
        }
    
    async def get_review_by_segment(
        self,
        segment_id: UUID
    ) -> Optional[dict]:
        """Get ASR review for a specific segment."""
        review = await self.review_repo.get_by_segment(segment_id)
        if not review:
            return None
        
        # Return basic info
        return {
            "review_id": review.id,
            "segment_id": review.segment_id,
            "status": review.status,
            "confidence_score": review.confidence_score,
            "is_pending": review.status == ASRReview.STATUS_PENDING
        }
    
    async def _build_queue_item(self, review: ASRReview, user_id: UUID) -> dict:
        """Build a queue item response."""
        segment = await self.segment_repo.get_by_id(review.segment_id)
        job = None
        if segment:
            job = await self.job_repo.get_by_id(segment.job_id)
        
        # Generate video URL via assets endpoint with streaming token
        video_url = ""
        if segment and segment.cropped_video_path:
            token = streaming_token_service.generate_token(
                user_id, segment.cropped_video_path
            )
            video_url = f"{settings.api_v1_prefix}/assets/{segment.cropped_video_path}?token={token}"
        
        # Determine flags
        is_low_confidence = (
            review.confidence_score is not None and
            review.confidence_score < self.LOW_CONFIDENCE_THRESHOLD
        )
        
        return {
            "review_id": review.id,
            "segment_id": review.segment_id,
            "job_id": segment.job_id if segment else None,
            "original_filename": job.original_filename if job else "Unknown",
            "video_url": video_url,
            "asr_text": review.original_text,
            "asr_start": segment.asr_start if segment else None,
            "asr_end": segment.asr_end if segment else None,
            "confidence_score": review.confidence_score,
            "is_low_confidence": is_low_confidence,
            "requires_attention": is_low_confidence
        }

    
    async def approve_asr_review(
        self,
        review_id: UUID,
        reviewer_id: UUID,
        notes: Optional[str] = None
    ) -> dict:
        """
        Approve an ASR review.
        
        The ASR transcript is accepted as-is and the segment
        moves to the annotation queue.
        """
        from app.core.exceptions import ConflictError
        from datetime import datetime
        
        review = await self._get_and_validate_review(review_id, reviewer_id)
        
        # Update review status
        await self.review_repo.update_status(
            review_id=review_id,
            status=ASRReview.STATUS_APPROVED,
            reviewer_id=reviewer_id
        )
        
        # Move to annotation queue
        queue_entry = await self._move_to_annotation_queue(
            review=review,
            transcript_text=review.original_text,
            reviewer_id=reviewer_id
        )
        
        # Log ASR review approval
        await self.audit_repo.create(
            action=AuditAction.ASR_REVIEW_SUBMITTED,
            resource_type="asr_review",
            actor_id=reviewer_id,
            resource_id=review_id,
            details={
                "segment_id": str(review.segment_id),
                "confidence_score": review.confidence_score,
                "action": "approved",
                "notes": notes
            }
        )
        await self.db.commit()
        
        return {
            "review_id": review_id,
            "segment_id": review.segment_id,
            "action": "APPROVED",
            "status": ASRReview.STATUS_APPROVED,
            "reviewer_id": reviewer_id,
            "reviewed_at": datetime.utcnow(),
            "message": "ASR transcript approved and moved to annotation queue",
            "moved_to_annotation_queue": True,
            "queue_entry_id": queue_entry.id if queue_entry else None
        }
    
    async def correct_asr_review(
        self,
        review_id: UUID,
        reviewer_id: UUID,
        corrected_text: str,
        notes: Optional[str] = None
    ) -> dict:
        """
        Correct an ASR transcript.
        
        The corrected text is used for annotation, while the
        original ASR output is preserved for reference.
        """
        from app.core.exceptions import ConflictError
        from datetime import datetime
        
        review = await self._get_and_validate_review(review_id, reviewer_id)
        
        # Update review with correction
        await self.review_repo.update_status(
            review_id=review_id,
            status=ASRReview.STATUS_CORRECTED,
            reviewer_id=reviewer_id,
            corrected_text=corrected_text
        )
        
        # Move to annotation queue with corrected text
        queue_entry = await self._move_to_annotation_queue(
            review=review,
            transcript_text=corrected_text,
            reviewer_id=reviewer_id
        )
        
        # Update segment transcripts with corrected text
        from app.db.models.pipeline import PipelineTranscript
        segment = await self.segment_repo.get_by_id(review.segment_id)
        if segment:
            if segment.transcripts:
                # Preserve time bounds from existing transcripts
                old_transcripts = list(segment.transcripts)
                old_start = min(t.start for t in old_transcripts) if old_transcripts else 0.0
                old_end = max(t.end for t in old_transcripts) if old_transcripts else 0.0
                # Clear existing transcripts (cascade delete)
                segment.transcripts.clear()
            else:
                old_start, old_end = 0.0, 0.0
            
            # Create single corrected transcript
            new_transcript = PipelineTranscript(
                segment_id=segment.id,
                utterance_index=0,
                text=corrected_text,
                start=old_start,
                end=old_end,
                confidence=1.0
            )
            self.db.add(new_transcript)
            await self.db.flush()
        
        # Log ASR review correction
        await self.audit_repo.create(
            action=AuditAction.ASR_REVIEW_CORRECTED,
            resource_type="asr_review",
            actor_id=reviewer_id,
            resource_id=review_id,
            details={
                "segment_id": str(review.segment_id),
                "confidence_score": review.confidence_score,
                "corrected": True,
                "has_notes": bool(notes)
            }
        )
        await self.db.commit()
        
        return {
            "review_id": review_id,
            "segment_id": review.segment_id,
            "action": "CORRECTED",
            "status": ASRReview.STATUS_CORRECTED,
            "reviewer_id": reviewer_id,
            "reviewed_at": datetime.utcnow(),
            "message": "ASR transcript corrected and moved to annotation queue",
            "moved_to_annotation_queue": True,
            "queue_entry_id": queue_entry.id if queue_entry else None
        }
    
    async def flag_asr_review(
        self,
        review_id: UUID,
        reviewer_id: UUID,
        flag_reason: str,
        notes: str
    ) -> dict:
        """
        Flag an ASR segment for reprocessing.
        
        The segment is marked for manual transcription or
        specialized handling. Does NOT move to annotation queue.
        """
        from app.core.exceptions import ConflictError
        from datetime import datetime
        
        review = await self._get_and_validate_review(review_id, reviewer_id)
        
        # Update review as flagged
        await self.review_repo.update_status(
            review_id=review_id,
            status=ASRReview.STATUS_FLAGGED,
            reviewer_id=reviewer_id,
            flag_reason=flag_reason
        )
        
        # Update segment status to reflect flagging
        segment = await self.segment_repo.get_by_id(review.segment_id)
        if segment:
            # Assuming segment has asr_review_flag field
            # If not, this can be stored in metadata or omitted
            pass
        
        # TODO: Notify admin (Story 5.x)
        
        return {
            "review_id": review_id,
            "segment_id": review.segment_id,
            "action": "FLAGGED",
            "status": ASRReview.STATUS_FLAGGED,
            "reviewer_id": reviewer_id,
            "reviewed_at": datetime.utcnow(),
            "flag_reason": flag_reason,
            "notes": notes,
            "message": "Segment flagged for reprocessing",
            "moved_to_annotation_queue": False,
            "queue_entry_id": None
        }
    
    async def check_review_status(
        self,
        review_id: UUID,
        user_id: UUID
    ) -> dict:
        """Check if a review can be performed (not already reviewed)."""
        review = await self.review_repo.get_by_id(review_id)
        
        if not review:
            raise NotFoundError(f"ASR Review {review_id} not found")
        
        is_reviewed = review.status != ASRReview.STATUS_PENDING
        
        if is_reviewed:
            return {
                "review_id": review_id,
                "segment_id": review.segment_id,
                "is_reviewed": True,
                "status": review.status,
                "reviewer_id": review.reviewer_id,
                "can_review": False,
                "message": f"Already reviewed by {review.reviewer_id}"
            }
        
        return {
            "review_id": review_id,
            "segment_id": review.segment_id,
            "is_reviewed": False,
            "status": review.status,
            "reviewer_id": None,
            "can_review": True,
            "message": "Ready for review"
        }
    
    async def _get_and_validate_review(
        self,
        review_id: UUID,
        reviewer_id: UUID
    ) -> ASRReview:
        """Get review and validate it can be reviewed."""
        from app.core.exceptions import ConflictError
        
        review = await self.review_repo.get_by_id(review_id)
        
        if not review:
            raise NotFoundError(f"ASR Review {review_id} not found")
        
        if review.status != ASRReview.STATUS_PENDING:
            raise ConflictError(
                f"Review already completed with status: {review.status}"
            )
        
        return review
    
    async def _move_to_annotation_queue(
        self,
        review: ASRReview,
        transcript_text: str,
        reviewer_id: UUID
    ) -> AnnotationQueue:
        """
        Move an approved/corrected segment to the annotation queue.
        
        Creates annotation_queue entry for the segment with the
        validated transcript (either original ASR or corrected).
        """
        from datetime import datetime, timedelta
        
        # Check if already in annotation queue
        existing = await self.queue_repo.get_by_segment(review.segment_id)
        if existing:
            # Already queued, just update status
            await self.queue_repo.update_status(
                existing.id,
                AnnotationQueue.STATUS_ASSIGNED
            )
            return existing
        
        # Get segment for job info
        segment = await self.segment_repo.get_by_id(review.segment_id)
        if not segment:
            raise NotFoundError(f"Segment {review.segment_id} not found")
        
        # TODO: Assign to annotator (round-robin or workload-based)
        # For now, assign to the reviewer who approved (self-assignment)
        
        queue_entry = AnnotationQueue(
            segment_id=review.segment_id,
            annotator_id=reviewer_id,  # Self-assign for now
            status=AnnotationQueue.STATUS_ASSIGNED,
            priority=0,  # Default priority
            assigned_at=datetime.utcnow(),
            due_date=datetime.utcnow() + timedelta(days=7)  # 1 week default
        )
        
        self.db.add(queue_entry)
        await self.db.flush()
        await self.db.refresh(queue_entry)
        
        return queue_entry

    
    async def get_confidence_stats(self) -> dict:
        """
        Get ASR confidence statistics for admin dashboard.
        
        Returns average, min, max confidence across all transcripts.
        """
        from sqlalchemy import func
        from app.db.models.pipeline import PipelineTranscript
        
        result = await self.db.execute(
            select(
                func.avg(PipelineTranscript.confidence).label("avg"),
                func.min(PipelineTranscript.confidence).label("min"),
                func.max(PipelineTranscript.confidence).label("max"),
                func.count(PipelineTranscript.id).label("count")
            )
        )
        
        row = result.one()
        
        return {
            "average_confidence": round(row.avg, 4) if row.avg else None,
            "min_confidence": round(row.min, 4) if row.min else None,
            "max_confidence": round(row.max, 4) if row.max else None,
            "total_transcripts": row.count,
            "confidence_distribution": await self._get_confidence_distribution()
        }
    
    async def _get_confidence_distribution(self) -> dict:
        """Get distribution of confidence scores."""
        from sqlalchemy import func, case
        from app.db.models.pipeline import PipelineTranscript
        
        result = await self.db.execute(
            select(
                func.sum(case((PipelineTranscript.confidence < 0.5, 1), else_=0)).label("low"),
                func.sum(case((PipelineTranscript.confidence.between(0.5, 0.8), 1), else_=0)).label("medium"),
                func.sum(case((PipelineTranscript.confidence > 0.8, 1), else_=0)).label("high")
            )
        )
        
        row = result.one()
        return {
            "low": row.low or 0,
            "medium": row.medium or 0,
            "high": row.high or 0
        }
