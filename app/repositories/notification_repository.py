"""Notification repository."""
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.notification import Notification


class NotificationRepository:
    """Repository for notification operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        user_id: UUID,
        type: str,
        title: str,
        message: str,
        job_id: Optional[UUID] = None
    ) -> Notification:
        """Create a new notification."""
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            job_id=job_id,
            is_read=False
        )
        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)
        return notification
    
    async def get_by_id(self, notification_id: UUID) -> Optional[Notification]:
        """Get notification by ID."""
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()
    
    async def list_for_user(
        self,
        user_id: UUID,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> List[Notification]:
        """List notifications for a user."""
        query = select(Notification).where(
            Notification.user_id == user_id
        )
        
        if unread_only:
            query = query.where(Notification.is_read == False)
        
        query = query.order_by(
            Notification.created_at.desc()
        ).offset(offset).limit(limit)
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def count_for_user(
        self,
        user_id: UUID,
        unread_only: bool = False
    ) -> int:
        """Count notifications for a user."""
        query = select(func.count(Notification.id)).where(
            Notification.user_id == user_id
        )
        
        if unread_only:
            query = query.where(Notification.is_read == False)
        
        result = await self.db.execute(query)
        return result.scalar()
    
    async def mark_as_read(self, notification_id: UUID) -> bool:
        """Mark a notification as read."""
        from datetime import datetime
        
        result = await self.db.execute(
            update(Notification)
            .where(Notification.id == notification_id)
            .values(is_read=True, read_at=datetime.utcnow())
        )
        return result.rowcount > 0
    
    async def mark_all_as_read(self, user_id: UUID) -> int:
        """Mark all notifications for a user as read."""
        from datetime import datetime
        
        result = await self.db.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read == False
            )
            .values(is_read=True, read_at=datetime.utcnow())
        )
        return result.rowcount
