"""
Authentication domain models.

This module defines the SQLAlchemy models for user authentication,
role-based access control, and user-role relationships.
"""

from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    String,
    Table,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    """
    User model for authentication and authorization.
    
    Stores user credentials, role assignment, and account status.
    Passwords are stored as bcrypt hashes.
    """
    
    __tablename__ = "auth_users"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique user identifier (UUID)"
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="User email address (unique)"
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Bcrypt password hash (~60 characters)"
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="User role: admin, annotator, or curator"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Account activation status"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Account creation timestamp"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Last update timestamp"
    )
    
    # Relationships
    roles: Mapped[List["Role"]] = relationship(
        "Role",
        secondary="auth_user_roles",
        back_populates="users",
        lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


class Role(Base):
    """
    Role model for role-based access control.
    
    Defines available roles and their associated permissions.
    """
    
    __tablename__ = "auth_roles"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique role identifier (UUID)"
    )
    name: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        comment="Role name: admin, annotator, or curator"
    )
    permissions: Mapped[dict] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
        comment="List of permissions for this role"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Role creation timestamp"
    )
    
    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        secondary="auth_user_roles",
        back_populates="roles",
        lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name={self.name})>"


# Junction table for many-to-many relationship between users and roles
user_roles = Table(
    "auth_user_roles",
    Base.metadata,
    Column(
        "user_id",
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        primary_key=True,
        comment="Reference to user"
    ),
    Column(
        "role_id",
        UUID(as_uuid=True),
        ForeignKey("auth_roles.id", ondelete="CASCADE"),
        primary_key=True,
        comment="Reference to role"
    ),
    Column(
        "created_at",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Assignment timestamp"
    ),
    comment="Junction table linking users to their roles"
)
