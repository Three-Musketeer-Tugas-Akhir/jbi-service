"""Job repository for database operations."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import PipelineJob


class JobRepository:
    """Repository for pipeline job operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        original_filename: str,
        file_size: int,
        created_by: UUID,
        status: str = "UPLOADED"
    ) -> PipelineJob:
        """Create a new pipeline job."""
        job = PipelineJob(
            video_path="",  # Will be set to MinIO path after upload
            original_filename=original_filename,
            status=status,
            current_stage="upload",
            created_by=created_by
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
    ) -> None:
        """Update job status."""
        job = await self.get_by_id(job_id)
        if job:
            job.status = status
            if error_message:
                job.error_message = error_message
            await self.db.flush()


# Dependency function
def get_job_repository(db: AsyncSession) -> JobRepository:
    return JobRepository(db)
