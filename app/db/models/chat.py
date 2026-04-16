"""Chat domain models.

Models for real-time chat between users and admins.
"""

from datetime import datetime
from typing import Optional, List, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, String, Text, ForeignKey, func, Index
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.auth import User


class ChatRoom(Base):
    """Chat room for user-admin conversations."""
    
    __tablename__ = "chat_rooms"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Optional room name"
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    # Relationships
    participants: Mapped[List["ChatParticipant"]] = relationship(
        "ChatParticipant",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin"
    )
    messages: Mapped[List["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="room",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.created_at.asc()"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[created_by]
    )
    
    def __repr__(self) -> str:
        return f"<ChatRoom(id={self.id}, name={self.name})>"


class ChatParticipant(Base):
    """Participant in a chat room."""
    
    __tablename__ = "chat_participants"
    
    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_rooms.id", ondelete="CASCADE"),
        primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    last_read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    room: Mapped["ChatRoom"] = relationship("ChatRoom", back_populates="participants")
    user: Mapped["User"] = relationship("User", lazy="joined")
    
    def __repr__(self) -> str:
        return f"<ChatParticipant(room_id={self.room_id}, user_id={self.user_id})>"


class ChatMessage(Base):
    """Individual chat message."""
    
    __tablename__ = "chat_messages"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    room_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_rooms.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    sender_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Message text content"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True
    )
    is_read: Mapped[bool] = mapped_column(
        default=False,
        nullable=False
    )
    
    # Relationships
    room: Mapped["ChatRoom"] = relationship("ChatRoom", back_populates="messages")
    sender: Mapped[Optional["User"]] = relationship("User", lazy="joined")
    
    # Indexes
    __table_args__ = (
        Index('idx_chat_messages_room_created', 'room_id', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<ChatMessage(id={self.id}, room_id={self.room_id}, sender_id={self.sender_id})>"
