"""Chat service for business logic."""

import logging
from typing import Dict, Any, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.connection_manager import chat_manager
from app.core.exceptions import NotFoundError, PermissionError
from app.db.models.chat import ChatRoom, ChatMessage
from app.repositories.chat_repository import ChatRepository


logger = logging.getLogger(__name__)


class ChatService:
    """Service for chat lifecycle management."""
    
    def __init__(self, db: AsyncSession, repo: ChatRepository = None):
        self.db = db
        self.repo = repo or ChatRepository(db)
    
    async def create_room(
        self,
        user_id: UUID,
        name: str = None
    ) -> ChatRoom:
        """Create a new support chat room and add creator as participant."""
        room = await self.repo.create_room(created_by=user_id, name=name)
        await self.repo.add_participant(room.id, user_id)
        await self.db.commit()
        await self.db.refresh(room)
        return room
    
    async def list_rooms(
        self,
        user_id: UUID,
        is_admin: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """List rooms for a user with unread counts."""
        rooms, total = await self.repo.list_rooms_for_user(
            user_id=user_id,
            is_admin=is_admin,
            limit=limit,
            offset=offset
        )
        
        items = []
        for room in rooms:
            unread = await self.repo.get_unread_count(room.id, user_id)
            last_message = None
            if room.messages:
                last_msg = room.messages[-1]
                last_message = {
                    "id": str(last_msg.id),
                    "content": last_msg.content,
                    "sender_id": str(last_msg.sender_id) if last_msg.sender_id else None,
                    "created_at": last_msg.created_at.isoformat() if last_msg.created_at else None,
                }
            
            participant_emails = []
            for p in room.participants:
                if p.user and p.user.email:
                    participant_emails.append(p.user.email)
            
            items.append({
                "id": str(room.id),
                "name": room.name,
                "created_at": room.created_at.isoformat() if room.created_at else None,
                "unread_count": unread,
                "last_message": last_message,
                "participants": participant_emails,
            })
        
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    async def get_room_history(
        self,
        room_id: UUID,
        user_id: UUID,
        is_admin: bool = False,
        limit: int = 50,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get message history for a room."""
        room = await self.repo.get_room_by_id(room_id)
        if not room:
            raise NotFoundError(f"Room {room_id} not found")
        
        if not is_admin and not await self.repo.is_user_in_room(room_id, user_id):
            raise PermissionError("You are not a participant in this room")
        
        messages, total = await self.repo.get_messages(room_id, limit=limit, offset=offset)
        
        items = []
        for msg in messages:
            items.append({
                "id": str(msg.id),
                "sender_id": str(msg.sender_id) if msg.sender_id else None,
                "sender_email": msg.sender.email if msg.sender else None,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "is_read": msg.is_read,
            })
        
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    async def send_message(
        self,
        room_id: UUID,
        sender_id: UUID,
        content: str
    ) -> ChatMessage:
        """Persist a message and broadcast it via websocket."""
        room = await self.repo.get_room_by_id(room_id)
        if not room:
            raise NotFoundError(f"Room {room_id} not found")
        
        if not await self.repo.is_user_in_room(room_id, sender_id):
            raise PermissionError("You are not a participant in this room")
        
        message = await self.repo.create_message(
            room_id=room_id,
            sender_id=sender_id,
            content=content
        )
        await self.db.commit()
        await self.db.refresh(message)
        
        # Broadcast via websocket manager
        payload = {
            "type": "message",
            "id": str(message.id),
            "room_id": str(room_id),
            "sender_id": str(sender_id),
            "content": content,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        await chat_manager.broadcast_to_room(str(room_id), payload)
        
        return message
    
    async def mark_room_as_read(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> int:
        """Mark all messages in a room as read for a user."""
        room = await self.repo.get_room_by_id(room_id)
        if not room:
            raise NotFoundError(f"Room {room_id} not found")
        
        if not await self.repo.is_user_in_room(room_id, user_id):
            raise PermissionError("You are not a participant in this room")
        
        count = await self.repo.mark_messages_as_read(room_id, user_id)
        await self.repo.update_last_read(room_id, user_id)
        await self.db.commit()
        
        # Notify other users in the room that messages were read
        await chat_manager.broadcast_to_room(
            str(room_id),
            {
                "type": "read_receipt",
                "room_id": str(room_id),
                "reader_id": str(user_id),
            }
        )
        
        return count
    
    async def join_room(
        self,
        room_id: UUID,
        user_id: UUID
    ) -> bool:
        """Add a user to a room if not already a participant."""
        if await self.repo.is_user_in_room(room_id, user_id):
            return False
        
        await self.repo.add_participant(room_id, user_id)
        await self.db.commit()
        
        await chat_manager.broadcast_to_room(
            str(room_id),
            {
                "type": "join",
                "room_id": str(room_id),
                "user_id": str(user_id),
            }
        )
        return True


# Factory function
def get_chat_service(db: AsyncSession) -> ChatService:
    return ChatService(db)
