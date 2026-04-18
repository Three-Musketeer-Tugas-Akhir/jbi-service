"""Notification Pydantic schemas."""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class NotificationItemResponse(BaseModel):
    """Single notification item."""
    id: UUID
    type: str
    title: str
    message: str
    job_id: Optional[UUID] = None
    is_read: bool
    read_at: Optional[datetime] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated notification list response."""
    items: List[NotificationItemResponse]
    total: int
    unread_count: int
    limit: int
    offset: int


class MarkAsReadResponse(BaseModel):
    """Response for marking notification(s) as read."""
    success: bool
    notification_id: Optional[str] = None
    marked_count: Optional[int] = None
