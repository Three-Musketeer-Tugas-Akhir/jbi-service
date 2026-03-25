"""
Password Reset Token Repository.

Provides database access methods for password reset token operations.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, List
from uuid import UUID

import bcrypt
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import PasswordResetToken


class PasswordResetRepository:
    """Repository for password reset token database operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
    
    async def create(
        self, 
        user_id: UUID, 
        token_hash: str,
        expires_at: datetime
    ) -> PasswordResetToken:
        """
        Create a new password reset token record.
        
        Args:
            user_id: User UUID
            token_hash: Bcrypt hash of the plain token
            expires_at: Expiration timestamp
            
        Returns:
            Created PasswordResetToken instance
        """
        token = PasswordResetToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            used_at=None
        )
        
        self.session.add(token)
        await self.session.flush()
        await self.session.refresh(token)
        return token
    
    async def get_by_id(self, token_id: UUID) -> Optional[PasswordResetToken]:
        """
        Get password reset token by ID.
        
        Args:
            token_id: Token unique identifier
            
        Returns:
            PasswordResetToken instance or None
        """
        stmt = select(PasswordResetToken).where(PasswordResetToken.id == token_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_valid_token_for_user(
        self, 
        user_id: UUID
    ) -> Optional[PasswordResetToken]:
        """
        Get the most recent valid (unused, not expired) token for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Most recent valid PasswordResetToken or None
        """
        now = datetime.now(timezone.utc)
        stmt = (
            select(PasswordResetToken)
            .where(
                and_(
                    PasswordResetToken.user_id == user_id,
                    PasswordResetToken.used_at.is_(None),
                    PasswordResetToken.expires_at > now
                )
            )
            .order_by(PasswordResetToken.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def mark_used(self, token_id: UUID) -> bool:
        """
        Mark a token as used.
        
        Args:
            token_id: Token unique identifier
            
        Returns:
            True if token was found and marked used, False otherwise
        """
        token = await self.get_by_id(token_id)
        if token is None:
            return False
        
        token.mark_used()
        await self.session.flush()
        return True
    
    async def invalidate_all_for_user(self, user_id: UUID) -> int:
        """
        Mark all valid tokens for a user as used (for security).
        
        Args:
            user_id: User UUID
            
        Returns:
            Number of tokens invalidated
        """
        now = datetime.now(timezone.utc)
        
        # Get all valid tokens for user
        stmt = select(PasswordResetToken).where(
            and_(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now
            )
        )
        result = await self.session.execute(stmt)
        tokens = result.scalars().all()
        
        # Mark each as used
        count = 0
        for token in tokens:
            token.mark_used()
            count += 1
        
        if count > 0:
            await self.session.flush()
        
        return count
    
    async def cleanup_expired(self, batch_size: int = 1000) -> int:
        """
        Delete expired or used tokens older than retention period.
        
        Args:
            batch_size: Maximum number of tokens to delete
            
        Returns:
            Number of tokens deleted
        """
        # Delete tokens that are either expired or used
        stmt = (
            PasswordResetToken.__table__.delete()
            .where(
                and_(
                    PasswordResetToken.expires_at < datetime.now(timezone.utc)
                )
            )
            .limit(batch_size)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
    
    async def count_recent_requests(
        self, 
        user_id: UUID, 
        window_minutes: int = 60
    ) -> int:
        """
        Count recent password reset requests for rate limiting.
        
        Args:
            user_id: User UUID
            window_minutes: Time window in minutes
            
        Returns:
            Number of requests in the time window
        """
        cutoff = datetime.now(timezone.utc) - datetime.timedelta(minutes=window_minutes)
        
        stmt = select(PasswordResetToken).where(
            and_(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.created_at > cutoff
            )
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())
