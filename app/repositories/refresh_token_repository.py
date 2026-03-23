"""
Refresh Token Repository.

Provides database access methods for refresh token operations.
"""

from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import RefreshToken


class RefreshTokenRepository:
    """Repository for refresh token database operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
    
    async def get_by_jti(self, jti: UUID) -> Optional[RefreshToken]:
        """
        Get refresh token by JTI.
        
        Args:
            jti: Token unique identifier
            
        Returns:
            RefreshToken instance or None
        """
        stmt = select(RefreshToken).where(RefreshToken.jti == jti)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def create(
        self, 
        jti: UUID, 
        user_id: UUID, 
        expires_at: datetime,
        rotated_from_jti: Optional[UUID] = None
    ) -> RefreshToken:
        """
        Create a new refresh token record.
        
        Args:
            jti: Token unique identifier
            user_id: User UUID
            expires_at: Expiration timestamp
            rotated_from_jti: Previous token JTI if this is a rotation
            
        Returns:
            Created RefreshToken instance
        """
        token = RefreshToken(
            jti=jti,
            user_id=user_id,
            expires_at=expires_at,
            rotated_to_jti=None,
        )
        
        self.session.add(token)
        await self.session.flush()
        
        # If this is a rotation, update the parent token
        if rotated_from_jti:
            await self.session.execute(
                update(RefreshToken)
                .where(RefreshToken.jti == rotated_from_jti)
                .values(rotated_to_jti=jti)
            )
        
        await self.session.refresh(token)
        return token
    
    async def revoke(self, jti: UUID) -> bool:
        """
        Revoke a refresh token.
        
        Args:
            jti: Token unique identifier
            
        Returns:
            True if token was found and revoked, False otherwise
        """
        token = await self.get_by_jti(jti)
        if token is None:
            return False
        
        token.revoke()
        await self.session.flush()
        return True
    
    async def is_valid(self, jti: UUID) -> bool:
        """
        Check if a refresh token is valid (exists, not revoked, not expired).
        
        Args:
            jti: Token unique identifier
            
        Returns:
            True if token is valid, False otherwise
        """
        token = await self.get_by_jti(jti)
        if token is None:
            return False
        return token.is_active
    
    async def get_active_tokens_for_user(self, user_id: UUID) -> List[RefreshToken]:
        """
        Get all active refresh tokens for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            List of active RefreshToken instances
        """
        now = datetime.now(timezone.utc)
        stmt = select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
    
    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """
        Revoke all active refresh tokens for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Number of tokens revoked
        """
        now = datetime.now(timezone.utc)
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.revoked_at.is_(None)
            )
            .values(revoked_at=now)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
    
    async def cleanup_expired(self, batch_size: int = 1000) -> int:
        """
        Delete expired and revoked tokens older than retention period.
        
        Args:
            batch_size: Maximum number of tokens to delete
            
        Returns:
            Number of tokens deleted
        """
        # Delete expired tokens
        stmt = (
            RefreshToken.__table__.delete()
            .where(
                RefreshToken.expires_at < datetime.now(timezone.utc)
            )
            .limit(batch_size)
        )
        result = await self.session.execute(stmt)
        return result.rowcount
