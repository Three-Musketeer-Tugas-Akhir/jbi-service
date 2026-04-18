"""Notification service.

Business logic for creating and managing user notifications.
"""
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.notification_repository import NotificationRepository
from app.repositories.job_repository import JobRepository
from app.db.models.notification import Notification


class NotificationService:
    """Service for notification operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NotificationRepository(db)
    
    async def create_notification(
        self,
        user_id: UUID,
        type: str,
        title: str,
        message: str,
        job_id: Optional[UUID] = None
    ) -> Notification:
        """Create a notification for a user."""
        return await self.repo.create(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            job_id=job_id
        )
    
    async def notify_job_complete(
        self,
        user_id: UUID,
        job_id: UUID,
        job_name: str,
        status: str
    ) -> Notification:
        """Notify user that a job has completed processing."""
        if status == "READY_FOR_ANNOTATION":
            title = "Video Processing Complete"
            message = f"'{job_name}' has finished processing and is ready for annotation."
        elif status == "FAILED":
            title = "Video Processing Failed"
            message = f"'{job_name}' failed during processing. Please check the job details."
        else:
            title = "Video Status Update"
            message = f"'{job_name}' status updated to {status}."
        
        return await self.create_notification(
            user_id=user_id,
            type="job_complete",
            title=title,
            message=message,
            job_id=job_id
        )
    
    async def notify_annotation_ready(
        self,
        user_id: UUID,
        job_id: UUID,
        job_name: str
    ) -> Notification:
        """Notify user that annotations are ready to be normalized."""
        return await self.create_notification(
            user_id=user_id,
            type="annotation_ready",
            title="Annotations Ready for Normalization",
            message=f"All annotations for '{job_name}' have been reviewed and are ready to be normalized.",
            job_id=job_id
        )
    
    async def notify_stage_complete(
        self,
        user_id: UUID,
        job_id: UUID,
        job_name: str,
        stage: str
    ) -> Notification:
        """Notify user that a pipeline stage has completed."""
        stage_names = {
            "DETECTING": "Detection",
            "TRANSCRIBING": "ASR Transcription",
            "CROPPING": "Video Cropping",
        }
        stage_name = stage_names.get(stage, stage)
        
        return await self.create_notification(
            user_id=user_id,
            type="stage_complete",
            title=f"{stage_name} Complete",
            message=f"'{job_name}' has completed the {stage_name.lower()} stage.",
            job_id=job_id
        )
    
    async def list_notifications(
        self,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> dict:
        """List notifications for a user."""
        notifications = await self.repo.list_for_user(
            user_id=user_id,
            unread_only=unread_only,
            limit=limit,
            offset=offset
        )
        total = await self.repo.count_for_user(user_id=user_id, unread_only=unread_only)
        unread_count = await self.repo.count_for_user(user_id=user_id, unread_only=True)
        
        return {
            "items": notifications,
            "total": total,
            "unread_count": unread_count,
            "limit": limit,
            "offset": offset
        }
    
    async def mark_as_read(self, notification_id: UUID, user_id: UUID) -> bool:
        """Mark a notification as read, verifying ownership."""
        notification = await self.repo.get_by_id(notification_id)
        if not notification:
            return False
        if notification.user_id != user_id:
            return False
        return await self.repo.mark_as_read(notification_id)
    
    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications for a user as read."""
        return await self.repo.mark_all_as_read(user_id)
