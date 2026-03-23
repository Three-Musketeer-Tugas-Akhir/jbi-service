"""Job service for business logic."""

import os
from pathlib import Path
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
    MIN_FILE_SIZE = 1  # 1 byte (reject empty files)
    
    def __init__(self, db: AsyncSession, job_repo: JobRepository):
        self.db = db
        self.job_repo = job_repo
        self.minio_service = get_minio_service()
    
    def _validate_file(self, filename: str, file_size: int) -> None:
        """Validate file format and size."""
        # Check filename is provided
        if not filename:
            raise ValidationError(
                "Filename is required",
                details={"filename": filename}
            )
        
        # Check file size is positive
        if file_size < self.MIN_FILE_SIZE:
            raise ValidationError(
                "File is empty",
                details={"file_size": file_size, "min_size": self.MIN_FILE_SIZE}
            )
        
        # Check file size doesn't exceed limit
        if file_size > self.MAX_FILE_SIZE:
            raise ValidationError(
                f"File too large, maximum size is 10GB",
                details={
                    "file_size": file_size,
                    "max_size": self.MAX_FILE_SIZE
                }
            )
        
        # Check file extension
        ext = Path(filename.lower()).suffix
        
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
        
        Flow:
        1. Validate file
        2. Create DB record with status UPLOADED
        3. Upload to MinIO
        4. Update video_path in DB
        5. Enqueue for processing (same transaction)
        6. Commit transaction
        
        Args:
            filename: Original filename
            file_data: File content
            file_size: File size in bytes
            user: Uploading user
            
        Returns:
            Created PipelineJob with status UPLOADED
            
        Raises:
            ValidationError: If file validation fails
            StorageError: If MinIO upload fails
        """
        # Validate file before any DB operations
        self._validate_file(filename, file_size)
        
        # Create job record (status = UPLOADED)
        job = await self.job_repo.create(
            original_filename=filename,
            file_size=file_size,
            created_by=user.id
        )
        
        try:
            # Upload to MinIO
            video_path = await self.minio_service.upload_job_video(
                job_id=str(job.id),
                file_data=file_data,
                original_filename=filename
            )
            
            # Update video_path in DB
            await self.job_repo.update_video_path(job.id, video_path)
            job.video_path = video_path
            
            # Enqueue for detection (using same DB session for atomicity)
            await queue_service.enqueue(
                db=self.db,
                queue_name="detection",
                payload={
                    "job_id": str(job.id),
                    "stage": "detection"
                }
            )
            
            # Commit all changes atomically
            await self.db.commit()
            
            # Refresh to get updated timestamps
            await self.db.refresh(job)
            
            return job
            
        except Exception:
            # Rollback on any error
            await self.db.rollback()
            raise
    
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
            NotImplementedError: URL upload not yet implemented (deferred to Story 2.6)
        """
        raise NotImplementedError(
            "URL upload not yet implemented. This feature is planned for Story 2.6."
        )


# Factory function
def get_job_service(
    db: AsyncSession,
    job_repo: JobRepository
) -> JobService:
    return JobService(db, job_repo)
