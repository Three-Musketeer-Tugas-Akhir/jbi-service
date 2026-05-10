"""Job service for business logic."""

import os
from pathlib import Path
from typing import BinaryIO, Union, Optional, List
from uuid import UUID

from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError, NotFoundError, PermissionError
from app.core.cache import job_status_cache
from app.db.models.auth import User
from app.db.models.audit import AuditAction
from app.db.models.pipeline import PipelineJob, PipelineSegment
from app.repositories.job_repository import JobRepository
from app.repositories.audit_log_repository import AuditLogRepository
from app.services.minio_service import get_minio_service
from app.messaging.kafka_client import pipeline_producer


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
    
    def __init__(self, db: AsyncSession, job_repo: JobRepository, audit_repo: AuditLogRepository = None):
        self.db = db
        self.job_repo = job_repo
        self.minio_service = get_minio_service()
        self.audit_repo = audit_repo or AuditLogRepository(db)
    
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
        user: User,
        dataset_id: Optional[UUID] = None,
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
            dataset_id: Optional associated dataset ID
            
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
            created_by=user.id,
            dataset_id=dataset_id,
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
            
            # Publish to Kafka for pipeline detection
            await pipeline_producer.publish_detection_job(
                job_id=str(job.id),
                video_key=video_path,
                category=job.category or "SIBI",
            )
            
            # Commit all changes atomically
            await self.db.commit()
            
            # Refresh to get updated timestamps
            await self.db.refresh(job)
            
            # Log job creation
            await self.audit_repo.create(
                action=AuditAction.JOB_CREATED,
                resource_type="job",
                actor_id=user.id,
                resource_id=job.id,
                details={
                    "original_filename": filename,
                    "file_size": file_size,
                    "video_path": video_path
                }
            )
            await self.db.commit()
            
            return job
            
        except Exception:
            # Rollback on any error
            await self.db.rollback()
            raise
    
    async def create_job_from_url(
        self,
        video_url: str,
        user: User,
        dataset_id: Optional[UUID] = None,
    ) -> PipelineJob:
        """
        Create a new job from URL.
        
        Downloads video from URL and proceeds with normal flow.
        
        Args:
            video_url: URL to download video from
            user: Uploading user
            dataset_id: Optional associated dataset ID
            
        Returns:
            Created PipelineJob
            
        Raises:
            NotImplementedError: URL upload not yet implemented (deferred to Story 2.6)
        """
        raise NotImplementedError(
            "URL upload not yet implemented. This feature is planned for Story 2.6."
        )
    
    async def get_job(
        self,
        job_id: str,
        current_user_id: str,
        is_admin: bool = False
    ) -> dict:
        """
        Get single job with progress calculation.
        
        Checks cache first, then queries database with segment counts.
        Results are cached for 2 seconds per NFR3.
        
        Args:
            job_id: Job UUID string
            current_user_id: Requesting user's ID
            is_admin: Whether user has admin role
            
        Returns:
            Job details dict with progress percentage
            
        Raises:
            NotFoundError: Job not found
            PermissionError: User not authorized to view this job
        """
        # Check cache first
        cache_key = f"job:{job_id}:user:{current_user_id}"
        cached = job_status_cache.get(cache_key)
        if cached:
            return cached
        
        # Parse UUID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Build query with segment counts
        query = (
            select(
                PipelineJob,
                func.count(PipelineSegment.id).label('total_segments'),
                func.sum(
                    case((PipelineSegment.status == 'PROCESSED', 1), else_=0)
                ).label('completed_segments')
            )
            .outerjoin(PipelineSegment, PipelineJob.id == PipelineSegment.job_id)
            .where(PipelineJob.id == job_uuid)
            .group_by(PipelineJob.id)
        )
        
        result = await self.db.execute(query)
        row = result.first()
        
        if not row:
            raise NotFoundError(f"Job {job_id} not found")
        
        job, total_segments, completed_segments = row
        
        # Authorization check
        if not is_admin and str(job.created_by) != current_user_id:
            raise PermissionError("Not authorized to view this job")
        
        # Calculate progress
        progress = 0
        if total_segments and total_segments > 0:
            progress = int((completed_segments or 0) / total_segments * 100)
        
        response = {
            "id": str(job.id),
            "original_filename": job.original_filename,
            "status": job.status,
            "category": job.category,
            "curation_status": job.curation_status,
            "current_stage": job.current_stage,
            "dataset_id": str(job.dataset_id) if job.dataset_id else None,
            "progress": progress,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "error_message": job.error_message,
            "total_segments": total_segments or 0,
            "completed_segments": completed_segments or 0,
            "created_by": str(job.created_by) if job.created_by else None
        }
        
        # Cache response for 2 seconds (NFR3)
        job_status_cache.set(cache_key, response, ttl=2.0)
        
        return response
    
    async def list_jobs(
        self,
        current_user_id: str,
        is_admin: bool = False,
        status: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> dict:
        """
        List jobs with pagination and filtering.
        
        Regular users see only their own jobs. Admins see all jobs.
        
        Args:
            current_user_id: Requesting user's ID
            is_admin: Whether user has admin role
            status: Optional status filter
            from_date: Optional start date (ISO 8601)
            to_date: Optional end date (ISO 8601)
            page: Page number (1-indexed)
            page_size: Items per page (max 100)
            
        Returns:
            Paginated response dict with items and metadata
        """
        # Build conditions
        conditions = []
        if not is_admin:
            conditions.append(PipelineJob.created_by == UUID(current_user_id))
        if status:
            conditions.append(PipelineJob.status == status)
        if from_date:
            conditions.append(PipelineJob.created_at >= from_date)
        if to_date:
            conditions.append(PipelineJob.created_at <= to_date)
        
        # Count total
        count_query = select(func.count(PipelineJob.id))
        if conditions:
            count_query = count_query.where(and_(*conditions))
        
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0
        
        # Fetch paginated results
        offset = (page - 1) * page_size
        
        query = (
            select(
                PipelineJob,
                func.count(PipelineSegment.id).label('total_segments'),
                func.sum(
                    case((PipelineSegment.status == 'PROCESSED', 1), else_=0)
                ).label('completed_segments')
            )
            .outerjoin(PipelineSegment, PipelineJob.id == PipelineSegment.job_id)
        )
        
        if conditions:
            query = query.where(and_(*conditions))
        
        query = (
            query
            .group_by(PipelineJob.id)
            .order_by(PipelineJob.created_at.desc())
            .limit(page_size)
            .offset(offset)
        )
        
        result = await self.db.execute(query)
        rows = result.all()
        
        items = []
        for job, total_segments, completed_segments in rows:
            progress = 0
            if total_segments and total_segments > 0:
                progress = int((completed_segments or 0) / total_segments * 100)
            
            items.append({
                "id": str(job.id),
                "original_filename": job.original_filename,
                "status": job.status,
                "curation_status": job.curation_status,
                "current_stage": job.current_stage,
                "dataset_id": str(job.dataset_id) if job.dataset_id else None,
                "progress": progress,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "error_message": job.error_message,
                "total_segments": total_segments or 0,
                "completed_segments": completed_segments or 0,
                "category": job.category
            })
        
        total_pages = (total + page_size - 1) // page_size if total > 0 else 1
        
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages
        }
    
    async def cancel_job(
        self,
        job_id: str,
        current_user_id: str,
        is_admin: bool = False
    ) -> dict:
        """
        Cancel a video processing job.
        
        Args:
            job_id: Job UUID string
            current_user_id: Requesting user's ID
            is_admin: Whether user has admin role
            
        Returns:
            Cancellation result dict
            
        Raises:
            NotFoundError: Job not found
            PermissionError: User not authorized to cancel this job
            ConflictError: Job already in terminal state
        """
        from app.core.exceptions import ConflictError
        from app.services.queue_service import queue_service
        
        # Parse UUID
        try:
            job_uuid = UUID(job_id)
        except ValueError:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Get job
        job = await self.job_repo.get_by_id(job_uuid)
        if not job:
            raise NotFoundError(f"Job {job_id} not found")
        
        # Authorization check
        if not is_admin and str(job.created_by) != current_user_id:
            raise PermissionError("Not authorized to cancel this job")
        
        # Check if already terminal
        terminal_states = {"READY_FOR_ANNOTATION", "FAILED", "CANCELLED"}
        if job.status in terminal_states:
            raise ConflictError(f"Cannot cancel job in '{job.status}' status")
        
        # Cancel queue jobs first
        queue_cancelled = await queue_service.cancel_job_queues(
            job_id,
            self.db
        )
        
        # Cancel the job
        cancelled_by = UUID(current_user_id) if current_user_id else None
        success = await self.job_repo.cancel_job(job_uuid, cancelled_by=cancelled_by)
        
        if not success:
            raise ConflictError(f"Cannot cancel job in '{job.status}' status")
        
        # Log job cancellation
        await self.audit_repo.create(
            action=AuditAction.JOB_CANCELLED,
            resource_type="job",
            actor_id=cancelled_by,
            resource_id=job_uuid,
            details={
                "previous_status": job.status,
                "queue_jobs_cancelled": queue_cancelled
            }
        )
        await self.db.commit()
        
        # Invalidate cache
        self.invalidate_job_cache(job_id, current_user_id)
        
        return {
            "id": job_id,
            "status": "CANCELLED",
            "queue_jobs_cancelled": queue_cancelled,
            "message": "Job cancelled successfully"
        }
    
    def invalidate_job_cache(self, job_id: str, user_id: str) -> None:
        """
        Invalidate cache for a job.
        
        Called by workers when job status changes.
        
        Args:
            job_id: Job UUID string
            user_id: User ID who cached the job
        """
        cache_key = f"job:{job_id}:user:{user_id}"
        job_status_cache.delete(cache_key)


# Factory function
def get_job_service(
    db: AsyncSession,
    job_repo: JobRepository
) -> JobService:
    return JobService(db, job_repo)
