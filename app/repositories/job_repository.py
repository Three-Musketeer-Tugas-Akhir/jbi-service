"""Job repository for database operations."""

from typing import Optional, Tuple, List
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob
from app.db.session import get_db


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
        error_message: Optional[str] = None
    ) -> bool:
        """
        Update job status.
        
        Args:
            job_id: Job UUID
            status: New status
            error_message: Optional error message for FAILED status
            
        Returns:
            True if job was found and updated, False otherwise
        """
        from datetime import datetime
        
        job = await self.get_by_id(job_id)
        if job:
            job.status = status
            if error_message:
                job.error_message = error_message
            # Set completion timestamp for terminal states
            if status in ["READY_FOR_ANNOTATION", "FAILED"]:
                job.completed_at = datetime.utcnow()
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
