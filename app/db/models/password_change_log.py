"""
Password Change Log model.

Tracks all password changes for audit trail and security analysis.
Used to detect potential impersonation attempts.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING
import uuid as uuid_module
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.auth import User


class PasswordChangeLog(Base):
    """
    Password Change Log model for tracking all password changes.
    
    Records when a user changes their password, including the change type,
    IP address, and whether it was a temporary (admin-generated) password.
    This enables security auditing to detect impersonation attempts.
    """
    
    __tablename__ = "auth_password_change_log"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
        comment="Unique log entry identifier"
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to user who changed password"
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="When the password was changed"
    )
    change_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="Type of change: FIRST_LOGIN, SELF_CHANGE, ADMIN_RESET"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="IP address of the requester"
    )
    user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="User agent string of the requester"
    )
    was_temporary: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether the previous password was a temporary/admin-generated one"
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="password_change_logs")
    
    def __repr__(self) -> str:
        return f"<PasswordChangeLog(id={self.id}, user_id={self.user_id}, type={self.change_type})>"
