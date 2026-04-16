"""Chat repository for database operations."""

from typing import Optional, List, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.chat import ChatRoom, ChatParticipant, ChatMessage


class ChatRepository:
    """Repository for chat operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------
    async def create_room(
        self,
        created_by: UUID,
        name: Optional[str] = None
    ) -> ChatRoom:
        """Create a new chat room."""
        room = ChatRoom(created_by=created_by, name=name)
        self.db.add(room)
        await self.db.flush()
        await self.db.refresh(room)
        return room
    
    async def get_room_by_id(self, room_id: UUID) -> Optional[ChatRoom]:
        """Get room by ID with participants and messages."""
        result = await self.db.execute(
            select(ChatRoom).where(ChatRoom.id == room_id)
        )
        return result.scalar_one_or_none()
    
    async def list_rooms_for_user(
        self,
        user_id: UUID,
        is_admin: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[ChatRoom], int]:
        """List rooms accessible to a user."""
        if is_admin:
            count_query = select(func.count(ChatRoom.id))
            query = select(ChatRoom).order_by(desc(ChatRoom.created_at))
        else:
            count_query = (
                select(func.count(ChatRoom.id))
                .join(ChatParticipant, ChatParticipant.room_id == ChatRoom.id)
                .where(ChatParticipant.user_id == user_id)
            )
            query = (
                select(ChatRoom)
                .join(ChatParticipant, ChatParticipant.room_id == ChatRoom.id)
                .where(ChatParticipant.user_id == user_id)
                .order_by(desc(ChatRoom.created_at))
            )
        
        total_result = await self.db.execute(count_query)
        total = total_result.scalar() or 0
        
        result = await self.db.execute(query.offset(offset).limit(limit))
        rooms = result.scalars().all()
        return list(rooms), total
    
    async def is_user_in_room(self, room_id: UUID, user_id: UUID) -> bool:
        """Check if a user is a participant in a room."""
        result = await self.db.execute(
            select(ChatParticipant)
            .where(
                and_(
                    ChatParticipant.room_id == room_id,
                    ChatParticipant.user_id == user_id
                )
            )
        )
        return result.scalar_one_or_none() is not None
    
    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    async def add_participant(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> ChatParticipant:
        """Add a user to a room."""
        participant = ChatParticipant(room_id=room_id, user_id=user_id)
        self.db.add(participant)
        await self.db.flush()
        await self.db.refresh(participant)
        return participant
    
    async def get_participants(self, room_id: UUID) -> List[ChatParticipant]:
        """Get all participants in a room."""
        result = await self.db.execute(
            select(ChatParticipant)
            .where(ChatParticipant.room_id == room_id)
        )
        return list(result.scalars().all())
    
    async def update_last_read(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> bool:
        """Update last_read_at timestamp for a participant."""
        result = await self.db.execute(
            select(ChatParticipant)
            .where(
                and_(
                    ChatParticipant.room_id == room_id,
                    ChatParticipant.user_id == user_id
                )
            )
        )
        participant = result.scalar_one_or_none()
        if participant:
            from datetime import datetime, timezone
            participant.last_read_at = datetime.now(timezone.utc)
            await self.db.flush()
            return True
        return False
    
    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    async def create_message(
        self,
        room_id: UUID,
        sender_id: UUID,
        content: str
    ) -> ChatMessage:
        """Create a new chat message."""
        message = ChatMessage(
            room_id=room_id,
            sender_id=sender_id,
            content=content
        )
        self.db.add(message)
        await self.db.flush()
        await self.db.refresh(message)
        return message
    
    async def get_messages(
        self,
        room_id: UUID,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[ChatMessage], int]:
        """Get paginated messages for a room."""
        count_result = await self.db.execute(
            select(func.count(ChatMessage.id))
            .where(ChatMessage.room_id == room_id)
        )
        total = count_result.scalar() or 0
        
        result = await self.db.execute(
            select(ChatMessage)
            .where(ChatMessage.room_id == room_id)
            .order_by(desc(ChatMessage.created_at))
            .offset(offset)
            .limit(limit)
        )
        messages = result.scalars().all()
        # Return in chronological order
        return list(reversed(messages)), total
    
    async def mark_messages_as_read(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> int:
        """Mark all unread messages in a room as read (except user's own)."""
        result = await self.db.execute(
            select(ChatMessage)
            .where(
                and_(
                    ChatMessage.room_id == room_id,
                    ChatMessage.is_read == False,
                    ChatMessage.sender_id != user_id
                )
            )
        )
        messages = result.scalars().all()
        count = 0
        for msg in messages:
            msg.is_read = True
            count += 1
        if count > 0:
            await self.db.flush()
        return count
    
    async def get_unread_count(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> int:
        """Get unread message count for a user in a room."""
        result = await self.db.execute(
            select(func.count(ChatMessage.id))
            .where(
                and_(
                    ChatMessage.room_id == room_id,
                    ChatMessage.is_read == False,
                    ChatMessage.sender_id != user_id
                )
            )
        )
        return result.scalar() or 0
