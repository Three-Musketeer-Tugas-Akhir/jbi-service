"""Chat REST API Router.

Endpoints for room management and message history.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_async_session
from app.api.deps import get_current_user, CurrentUser, require_admin
from app.services.chat_service import ChatService, get_chat_service


router = APIRouter(prefix="/chat", tags=["chat"])


# ============================================================================
# Schemas
# ============================================================================

class CreateRoomRequest(BaseModel):
    name: Optional[str] = Field(None, description="Optional room name")


class CreateRoomResponse(BaseModel):
    id: str = Field(..., description="Room ID")
    name: Optional[str] = Field(None, description="Room name")
    created_at: str = Field(..., description="Creation timestamp")


class MessageItem(BaseModel):
    id: str
    sender_id: Optional[str]
    sender_email: Optional[str]
    content: str
    created_at: str
    is_read: bool


class RoomHistoryResponse(BaseModel):
    items: list[MessageItem]
    total: int
    limit: int
    offset: int


class RoomListItem(BaseModel):
    id: str
    name: Optional[str]
    created_at: str
    unread_count: int
    last_message: Optional[dict]
    participants: list[str]


class RoomListResponse(BaseModel):
    items: list[RoomListItem]
    total: int
    limit: int
    offset: int


class MarkReadResponse(BaseModel):
    marked_count: int
    message: str


# ============================================================================
# Endpoints
# ============================================================================

@router.post(
    "/rooms",
    response_model=CreateRoomResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chat room",
)
async def create_room(
    request: CreateRoomRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new chat room.
    
    The authenticated user is automatically added as a participant.
    """
    chat_service = get_chat_service(db_session)
    room = await chat_service.create_room(
        user_id=current_user.id,
        name=request.name
    )
    return CreateRoomResponse(
        id=str(room.id),
        name=room.name,
        created_at=room.created_at.isoformat() if room.created_at else ""
    )


@router.get(
    "/rooms",
    response_model=RoomListResponse,
    summary="List chat rooms",
)
async def list_rooms(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    List chat rooms accessible to the current user.
    
    - **Admin**: sees all rooms
    - **Non-admin**: sees only rooms they participate in
    """
    chat_service = get_chat_service(db_session)
    result = await chat_service.list_rooms(
        user_id=current_user.id,
        is_admin=current_user.is_admin,
        limit=limit,
        offset=offset
    )
    return RoomListResponse(**result)


@router.get(
    "/rooms/{room_id}/messages",
    response_model=RoomHistoryResponse,
    summary="Get room message history",
)
async def get_room_messages(
    room_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get paginated message history for a specific room.
    """
    chat_service = get_chat_service(db_session)
    result = await chat_service.get_room_history(
        room_id=room_id,
        user_id=current_user.id,
        is_admin=current_user.is_admin,
        limit=limit,
        offset=offset
    )
    return RoomHistoryResponse(**result)


@router.patch(
    "/rooms/{room_id}/read",
    response_model=MarkReadResponse,
    summary="Mark room messages as read",
)
async def mark_room_read(
    room_id: UUID,
    current_user: CurrentUser = Depends(get_current_user),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Mark all messages in a room as read for the current user.
    """
    chat_service = get_chat_service(db_session)
    count = await chat_service.mark_room_as_read(
        room_id=room_id,
        user_id=current_user.id
    )
    return MarkReadResponse(
        marked_count=count,
        message=f"{count} messages marked as read"
    )


@router.post(
    "/rooms/{room_id}/join",
    status_code=status.HTTP_200_OK,
    summary="Join a chat room",
)
async def join_room(
    room_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Join a chat room (admin only).
    
    Allows admins to enter any room to provide support.
    """
    chat_service = get_chat_service(db_session)
    joined = await chat_service.join_room(
        room_id=room_id,
        user_id=current_user.id
    )
    return {
        "joined": joined,
        "message": "Joined room" if joined else "Already a participant"
    }
