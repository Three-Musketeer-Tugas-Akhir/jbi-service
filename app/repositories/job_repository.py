"""Job repository for database operations."""

import logging
from typing import Optional, Tuple, List
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob
from app.db.session import get_db
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)


class JobRepository:
    """Repository for pipeline job operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        original_filename: str,
        file_size: int,
        created_by: Optional[UUID] = None,
        status: str = "UPLOADED",
        category: Optional[str] = None,
        dataset_id: Optional[UUID] = None,
    ) -> PipelineJob:
        """Create a new pipeline job.
        
        Args:
            original_filename: Original filename of the uploaded video
            file_size: Size of the file in bytes
            created_by: UUID of the user who created the job
            status: Initial job status (default: UPLOADED)
            category: Sign language category (SIBI or BISINDO)
            dataset_id: Associated dataset ID
            
        Returns:
            Created PipelineJob instance
        """
        from uuid import uuid4
        
        job = PipelineJob(
            id=uuid4(),
            original_filename=original_filename,
            file_size=file_size,
            created_by=created_by,
            status=status,
            current_stage="upload",
            category=category,
            dataset_id=dataset_id,
        )
        self.db.add(job)
        await self.db.flush()
        await self.db.refresh(job)
        return job
    
    async def get_by_id(self, job_id: UUID) -> Optional[PipelineJob]:
        """Get job by ID."""
        result = await self.db.execute(
            select(PipelineJob).where(PipelineJob.id == job_id)
        )
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        job_id: UUID,
        status: str,
        error_message: Optional[str] = None,
        current_stage: Optional[str] = None,
    ) -> bool:
        """
        Update job status.
        
        Args:
            job_id: Job UUID
            status: New status
            error_message: Optional error message for FAILED status
            current_stage: Optional current processing stage
            
        Returns:
            True if job was found and updated, False otherwise
        """
        from datetime import datetime
        
        job = await self.get_by_id(job_id)
        if job:
            # Guard: a cancelled job must NOT be silently resurrected by a worker
            # that finishes an in-flight stage after cancellation (it would
            # overwrite CANCELLED and then block retry). Only an explicit retry —
            # which resets is_cancelled/status directly — can leave CANCELLED.
            if (job.is_cancelled or job.status == "CANCELLED") and status != "CANCELLED":
                logger.info(
                    "Ignoring status update to '%s' for cancelled job %s", status, job_id
                )
                return False
            job.status = status
            if current_stage is not None:
                job.current_stage = current_stage
            if error_message:
                job.error_message = error_message
            # Set completion timestamp for terminal states
            if status in ["READY_FOR_ANNOTATION", "FAILED"]:
                job.completed_at = datetime.utcnow()
            await self.db.flush()
            return True
        return False
    
    async def update_premerge_progress(
        self,
        job_id: UUID,
        status: str,
        total_pairs: int = 0,
        completed_pairs: int = 0,
        failed_pairs: int = 0,
        batches: Optional[list] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Update pre-merge progress tracking.
        
        Args:
            job_id: Job UUID
            status: Pre-merge status (PENDING, RUNNING, COMPLETED, FAILED)
            total_pairs: Total pairs to merge
            completed_pairs: Pairs successfully merged
            failed_pairs: Pairs that failed
            batches: Batch-level detail list
            error: Error message if failed
            
        Returns:
            True if job was found and updated
        """
        from datetime import datetime
        
        job = await self.get_by_id(job_id)
        if job:
            job.premerge_status = status
            job.premerge_total_pairs = total_pairs
            job.premerge_completed_pairs = completed_pairs
            job.premerge_failed_pairs = failed_pairs
            if batches is not None:
                job.premerge_batches = batches
                flag_modified(job, "premerge_batches")
            job.premerge_error = error  # Always set — None clears previous error
            if status == "RUNNING" and not job.premerge_started_at:
                job.premerge_started_at = datetime.utcnow()
            if status in ("COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"):
                job.premerge_completed_at = datetime.utcnow()
            await self.db.flush()
            return True
        return False
    
    async def update_curation_status(
        self,
        job_id: UUID,
        curation_status: str
    ) -> bool:
        """
        Update job curation status.
        
        Args:
            job_id: Job UUID
            curation_status: New curation status
            
        Returns:
            True if job was found and updated, False otherwise
        """
        job = await self.get_by_id(job_id)
        if job:
            job.curation_status = curation_status
            await self.db.flush()
            return True
        return False
    
    async def update_category(
        self,
        job_id: UUID,
        category: str
    ) -> bool:
        """
        Update job category (SIBI or BISINDO).
        
        Args:
            job_id: Job UUID
            category: Sign language category (SIBI or BISINDO)
            
        Returns:
            True if job was found and updated, False otherwise
        """
        job = await self.get_by_id(job_id)
        if job:
            job.category = category
            await self.db.flush()
            return True
        return False
    
    async def update_video_path(
        self,
        job_id: UUID,
        video_path: str
    ) -> bool:
        """
        Update job video_path after MinIO upload.
        
        Args:
            job_id: Job UUID
            video_path: Path to video in MinIO
            
        Returns:
            True if job was found and updated, False otherwise
        """
        job = await self.get_by_id(job_id)
        if job:
            job.video_path = video_path
            await self.db.flush()
            return True
        return False
    
    async def cancel_job(
        self,
        job_id: UUID,
        cancelled_by: Optional[UUID] = None
    ) -> bool:
        """
        Cancel a job and mark it as cancelled.
        
        Args:
            job_id: Job UUID
            cancelled_by: User who cancelled (for audit)
            
        Returns:
            True if job was found and cancelled, False otherwise
        """
        from datetime import datetime
        
        job = await self.get_by_id(job_id)
        if not job:
            return False
        
        # Don't allow cancelling already terminal jobs
        terminal_states = {"READY_FOR_ANNOTATION", "FAILED", "CANCELLED"}
        if job.status in terminal_states:
            return False
        
        job.is_cancelled = True
        job.status = "CANCELLED"
        job.cancelled_at = datetime.utcnow()
        job.cancelled_by = cancelled_by
        
        await self.db.flush()
        return True
    
    async def is_job_cancelled(self, job_id: UUID) -> bool:
        """
        Check if a job has been cancelled.
        
        Args:
            job_id: Job UUID
            
        Returns:
            True if job is cancelled, False otherwise
        """
        job = await self.get_by_id(job_id)
        if not job:
            return False
        return job.is_cancelled
    
    async def list_all(self) -> List[PipelineJob]:
        """List all jobs without filtering.
        
        Returns:
            List of all PipelineJob instances
        """
        result = await self.db.execute(select(PipelineJob))
        return list(result.scalars().all())
    
    async def list_filtered(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
        dataset_id: Optional[UUID] = None,
        limit: int = 20,
        offset: int = 0
    ) -> Tuple[List[PipelineJob], int]:
        """
        List jobs with optional status, category, and dataset filtering and pagination.
        
        Args:
            status: Filter by job status (optional)
            category: Filter by sign language category (optional)
            dataset_id: Filter by dataset ID (optional)
            limit: Max number of jobs to return
            offset: Number of jobs to skip
            
        Returns:
            Tuple of (list of jobs, total count)
        """
        # Build base query
        base_query = select(PipelineJob)
        count_query = select(func.count(PipelineJob.id))
        
        # Apply status filter if provided
        if status:
            base_query = base_query.where(PipelineJob.status == status)
            count_query = count_query.where(PipelineJob.status == status)
        
        # Apply category filter if provided
        if category:
            base_query = base_query.where(PipelineJob.category == category)
            count_query = count_query.where(PipelineJob.category == category)
        
        # Apply dataset filter if provided
        if dataset_id:
            base_query = base_query.where(PipelineJob.dataset_id == dataset_id)
            count_query = count_query.where(PipelineJob.dataset_id == dataset_id)
        
        # Get total count
        total_result = await self.db.execute(count_query)
        total = total_result.scalar()
        
        # Get paginated results, sorted by creation time (newest first)
        query = (
            base_query
            .order_by(PipelineJob.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(query)
        records = result.scalars().all()
        
        return list(records), total


# Dependency function
def get_job_repository(db: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(db)
