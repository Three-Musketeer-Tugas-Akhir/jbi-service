"""
Authentication domain models.

This module defines the SQLAlchemy models for user authentication,
role-based access control, and user-role relationships.
"""

from datetime import datetime, timezone
from typing import List, Optional, TYPE_CHECKING
import uuid as uuid_module
from uuid import UUID

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

if TYPE_CHECKING:
    from app.db.models.annotation import AnnotationEdit, AnnotationReview, AnnotationComment, ASRReview, AnnotationQueue
    from app.db.models.password_change_log import PasswordChangeLog


class User(Base):
    """
    User model for authentication and authorization.
    
    Stores user credentials, role assignments (many-to-many), and account status.
    Passwords are stored as bcrypt hashes.
    """
    
    __tablename__ = "auth_users"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
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
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When email was verified (NULL if not verified)"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="Whether user must change password on next login (first-login flow)"
    )
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When password was last changed by the user"
    )
    
    # Relationships
    roles: Mapped[List["Role"]] = relationship(
        "Role",
        secondary="auth_user_roles",
        back_populates="users",
        lazy="selectin"
    )
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    password_reset_tokens: Mapped[List["PasswordResetToken"]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    email_verification_tokens: Mapped[List["EmailVerificationToken"]] = relationship(
        "EmailVerificationToken",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    password_change_logs: Mapped[List["PasswordChangeLog"]] = relationship(
        "PasswordChangeLog",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    
    # Annotation domain relationships
    annotation_edits: Mapped[List["AnnotationEdit"]] = relationship(
        "AnnotationEdit",
        back_populates="editor",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    annotation_reviews: Mapped[List["AnnotationReview"]] = relationship(
        "AnnotationReview",
        back_populates="curator",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    annotation_comments: Mapped[List["AnnotationComment"]] = relationship(
        "AnnotationComment",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    asr_reviews: Mapped[List["ASRReview"]] = relationship(
        "ASRReview",
        back_populates="reviewer",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    annotation_queue: Mapped[List["AnnotationQueue"]] = relationship(
        "AnnotationQueue",
        back_populates="annotator",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    
    @property
    def is_email_verified(self) -> bool:
        """Check if email has been verified."""
        return self.email_verified_at is not None
    
    def mark_email_verified(self) -> None:
        """Mark email as verified."""
        self.email_verified_at = datetime.now(timezone.utc)
    
    @property
    def primary_role(self) -> Optional[str]:
        """Get the primary (first) role name for backwards compatibility."""
        if self.roles:
            return self.roles[0].name
        return None
    
    @property
    def role_names(self) -> List[str]:
        """Get list of role names assigned to user."""
        return [role.name for role in self.roles]
    
    @property
    def permissions(self) -> List[str]:
        """Get all permissions from all roles."""
        perms = set()
        for role in self.roles:
            perms.update(role.permissions)
        return list(perms)
    
    def has_role(self, role_name: str) -> bool:
        """Check if user has a specific role."""
        return any(role.name == role_name for role in self.roles)
    
    def has_any_role(self, role_names: List[str]) -> bool:
        """Check if user has any of the specified roles."""
        return any(self.has_role(name) for name in role_names)
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions
    
    def has_any_permission(self, permissions: List[str]) -> bool:
        """Check if user has any of the specified permissions."""
        return any(self.has_permission(p) for p in permissions)
    
    def __repr__(self) -> str:
        roles = ", ".join(self.role_names) if self.roles else "none"
        return f"<User(id={self.id}, email={self.email}, roles=[{roles}])>"


class Role(Base):
    """
    Role model for role-based access control.
    
    Defines available roles and their associated permissions.
    """
    
    __tablename__ = "auth_roles"
    
    # Default permissions for each role
    DEFAULT_PERMISSIONS = {
        "admin": ["*"],  # All permissions
        "curator": [
            "annotation:read:all",
            "annotation:write:reviews",
            "export:read",
            "slang:read",
        ],
        "annotator": [
            "annotation:read:own",
            "annotation:write:own",
            "queue:read:own",
        ],
    }
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
        comment="Unique role identifier (UUID)"
    )
    name: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False,
        comment="Role name: admin, annotator, or curator"
    )
    permissions: Mapped[List[str]] = mapped_column(
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
    
    @classmethod
    def get_default_permissions(cls, role_name: str) -> List[str]:
        """Get default permissions for a role."""
        return cls.DEFAULT_PERMISSIONS.get(role_name, [])
    
    # Relationships
    users: Mapped[List["User"]] = relationship(
        "User",
        secondary="auth_user_roles",
        back_populates="roles",
        lazy="selectin"
    )
    
    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name={self.name})>"


class RefreshToken(Base):
    """
    Refresh Token model for token tracking and revocation.
    
    Stores refresh token metadata for rotation and revocation support.
    """
    
    __tablename__ = "auth_refresh_tokens"
    
    jti: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
        comment="Token unique identifier (JWT ID)"
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to user who owns this token"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token expiration timestamp"
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When token was revoked (NULL if active)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Token creation timestamp"
    )
    rotated_to_jti: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_refresh_tokens.jti", ondelete="SET NULL"),
        nullable=True,
        comment="Reference to token this was rotated to"
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="refresh_tokens")
    rotated_to: Mapped[Optional["RefreshToken"]] = relationship(
        "RefreshToken",
        remote_side=[jti],
        back_populates="rotated_from"
    )
    rotated_from: Mapped[Optional["RefreshToken"]] = relationship(
        "RefreshToken",
        remote_side=[rotated_to_jti],
        back_populates="rotated_to"
    )
    
    @property
    def is_revoked(self) -> bool:
        """Check if token has been revoked."""
        return self.revoked_at is not None
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_active(self) -> bool:
        """Check if token is active (not revoked, not expired)."""
        return not self.is_revoked and not self.is_expired
    
    def revoke(self) -> None:
        """Mark token as revoked."""
        self.revoked_at = datetime.now(timezone.utc)
    
    def __repr__(self) -> str:
        return f"<RefreshToken(jti={self.jti}, user_id={self.user_id}, active={self.is_active})>"


class PasswordResetToken(Base):
    """
    Password Reset Token model for secure password reset flow.
    
    Stores hashed reset tokens with expiration for password reset functionality.
    """
    
    __tablename__ = "auth_password_reset_tokens"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
        comment="Token unique identifier"
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to user who requested reset"
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Bcrypt hash of the reset token"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token expiration timestamp"
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When token was used (NULL if unused)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Token creation timestamp"
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="password_reset_tokens")
    
    @property
    def is_used(self) -> bool:
        """Check if token has been used."""
        return self.used_at is not None
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not used, not expired)."""
        return not self.is_used and not self.is_expired
    
    def mark_used(self) -> None:
        """Mark token as used."""
        self.used_at = datetime.now(timezone.utc)
    
    def __repr__(self) -> str:
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id}, valid={self.is_valid})>"


class EmailVerificationToken(Base):
    """
    Email Verification Token model for email verification flow.
    
    Stores hashed verification tokens with expiration for email verification.
    """
    
    __tablename__ = "auth_email_verification_tokens"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid_module.uuid4,
        comment="Token unique identifier"
    )
    user_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to user who needs verification"
    )
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        comment="Bcrypt hash of the verification token"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Token expiration timestamp"
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When token was used (NULL if unused)"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="Token creation timestamp"
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="email_verification_tokens")
    
    @property
    def is_used(self) -> bool:
        """Check if token has been used."""
        return self.used_at is not None
    
    @property
    def is_expired(self) -> bool:
        """Check if token has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if token is valid (not used, not expired)."""
        return not self.is_used and not self.is_expired
    
    def mark_used(self) -> None:
        """Mark token as used."""
        self.used_at = datetime.now(timezone.utc)
    
    def __repr__(self) -> str:
        return f"<EmailVerificationToken(id={self.id}, user_id={self.user_id}, valid={self.is_valid})>"


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
