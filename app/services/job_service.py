"""Job service for business logic."""

from typing import BinaryIO, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.db.models.auth import User
from app.db.models.pipeline import PipelineJob
from app.repositories.job_repository import JobRepository
from app.services.minio_service import get_minio_service
from app.services.queue_service import queue_service


class JobService:
    """Service for job lifecycle management."""
    
    # Supported video formats (extension -> MIME type)
    SUPPORTED_FORMATS = {
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska",
        ".mov": "video/quicktime",
    }
    
    MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
    
    def __init__(self, db: AsyncSession, job_repo: JobRepository):
        self.db = db
        self.job_repo = job_repo
        self.minio_service = get_minio_service()
    
    def _validate_file(self, filename: str, file_size: int) -> None:
        """Validate file format and size."""
        # Check file size
        if file_size > self.MAX_FILE_SIZE:
            raise ValidationError(
                f"File too large, maximum size is 10GB",
                details={
                    "file_size": file_size,
                    "max_size": self.MAX_FILE_SIZE
                }
            )
        
        # Check file extension
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        ext = f".{ext}"
        
        if ext not in self.SUPPORTED_FORMATS:
            raise ValidationError(
                f"Unsupported file format: {ext}",
                details={
                    "filename": filename,
                    "supported_formats": list(self.SUPPORTED_FORMATS.keys())
                }
            )
    
    async def create_job_from_upload(
        self,
        filename: str,
        file_data: Union[bytes, BinaryIO],
        file_size: int,
        user: User
    ) -> PipelineJob:
        """
        Create a new job from uploaded file.
        
        Args:
            filename: Original filename
            file_data: File content
            file_size: File size in bytes
            user: Uploading user
            
        Returns:
            Created PipelineJob
        """
        # Validate file
        self._validate_file(filename, file_size)
        
        # Create job record
        job = await self.job_repo.create(
            original_filename=filename,
            file_size=file_size,
            created_by=user.id
        )
        
        # Upload to MinIO
        await self.minio_service.upload_job_video(
            job_id=str(job.id),
            file_data=file_data,
            original_filename=filename
        )
        
        # Queue for detection
        await queue_service.enqueue(
            queue_name="detection",
            payload={
                "job_id": str(job.id),
                "stage": "detection"
            }
        )
        
        # Update status to QUEUED
        await self.job_repo.update_status(job.id, "QUEUED")
        job.status = "QUEUED"
        
        await self.db.commit()
        return job
    
    async def create_job_from_url(
        self,
        video_url: str,
        user: User
    ) -> PipelineJob:
        """
        Create a new job from URL.
        
        Downloads video from URL and proceeds with normal flow.
        
        Args:
            video_url: URL to download video from
            user: Uploading user
            
        Returns:
            Created PipelineJob
            
        Raises:
            NotImplementedError: URL upload not yet implemented
        """
        raise NotImplementedError("URL upload not yet implemented")


# Factory function
def get_job_service(
    db: AsyncSession,
    job_repo: JobRepository
) -> JobService:
    return JobService(db, job_repo)
