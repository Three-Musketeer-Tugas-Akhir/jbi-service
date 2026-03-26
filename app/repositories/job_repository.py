"""Job repository for database operations."""

from typing import Optional
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob
from app.db.session import get_db


class JobRepository:
    """Repository for pipeline job operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        job_id: str,
        video_path: str,
        video_title: str = "",
        status: str = "UPLOADED"
    ) -> PipelineJob:
        """Create a new pipeline job."""
        from uuid import UUID
        
        job = PipelineJob(
            id=UUID(job_id),
            video_path=video_path,
            original_filename=video_title,
            status=status,
            current_stage="upload",
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
        
        Returns:
            True if job was found and updated, False otherwise
        """
        job = await self.get_by_id(job_id)
        if job:
            job.status = status
            if error_message:
                job.error_message = error_message
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


# Dependency function
def get_job_repository(db: AsyncSession = Depends(get_db)) -> JobRepository:
    return JobRepository(db)
