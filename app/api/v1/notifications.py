"""Notification API endpoints."""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.db.models.auth import User
from app.services.notification_service import NotificationService
from app.schemas.notification import (
    NotificationListResponse,
    NotificationItemResponse,
    MarkAsReadResponse,
)

router = APIRouter()


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    summary="List notifications",
    description="Returns paginated list of notifications for the current user."
)
async def list_notifications(
    unread_only: bool = Query(False, description="Only return unread notifications"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get notifications for the current user."""
    service = NotificationService(db)
    result = await service.list_notifications(
        user_id=current_user.id,
        unread_only=unread_only,
        limit=limit,
        offset=offset
    )
    return result


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MarkAsReadResponse,
    summary="Mark notification as read",
    description="Mark a specific notification as read."
)
async def mark_notification_as_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark a notification as read."""
    service = NotificationService(db)
    success = await service.mark_as_read(
        notification_id=notification_id,
        user_id=current_user.id
    )
    
    if not success:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notifikasi tidak ditemukan atau akses ditolak"
        )
    
    await db.commit()
    return {"success": True, "notification_id": str(notification_id)}


@router.post(
    "/notifications/read-all",
    response_model=MarkAsReadResponse,
    summary="Mark all notifications as read",
    description="Mark all notifications for the current user as read."
)
async def mark_all_notifications_as_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark all notifications as read for the current user."""
    service = NotificationService(db)
    count = await service.mark_all_as_read(user_id=current_user.id)
    await db.commit()
    return {"success": True, "marked_count": count}
