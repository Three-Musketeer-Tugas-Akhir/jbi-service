"""
User Repository.

Provides database access methods for user-related operations.
Follows repository pattern for clean separation of concerns.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import User


class UserRepository:
    """Repository for user database operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
    
    async def get_by_email(self, email: str) -> Optional[User]:
        """
        Get user by email (case-insensitive).
        
        Args:
            email: User email address
            
        Returns:
            User instance or None if not found
        """
        # Case-insensitive email lookup
        stmt = select(User).where(
            func.lower(User.email) == email.lower()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def get_by_id(self, user_id) -> Optional[User]:
        """
        Get user by ID.
        
        Args:
            user_id: User UUID
            
        Returns:
            User instance or None if not found
        """
        stmt = select(User).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def update_password(self, user_id, password_hash: str) -> bool:
        """
        Update user password hash.
        
        Args:
            user_id: User UUID
            password_hash: New bcrypt password hash
            
        Returns:
            True if user was found and updated, False otherwise
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return False
        
        user.password_hash = password_hash
        await self.session.flush()
        return True
    
    async def update_email(self, user_id, email: str) -> bool:
        """
        Update user email address.
        
        Args:
            user_id: User UUID
            email: New email address
            
        Returns:
            True if user was found and updated, False otherwise
            
        Note:
            Does not check for email uniqueness - caller should verify first.
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return False
        
        user.email = email.lower()
        await self.session.flush()
        return True
    
    async def email_exists(self, email: str, exclude_user_id=None) -> bool:
        """
        Check if an email address is already in use.
        
        Args:
            email: Email address to check
            exclude_user_id: Optional user ID to exclude from check (for updates)
            
        Returns:
            True if email exists, False otherwise
        """
        stmt = select(User).where(
            func.lower(User.email) == email.lower()
        )
        
        if exclude_user_id:
            stmt = stmt.where(User.id != exclude_user_id)
        
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
    
    async def list_users(
        self,
        limit: int = 20,
        offset: int = 0,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None
    ) -> Tuple[List[User], int]:
        """
        List users with optional filtering and pagination.
        
        Args:
            limit: Maximum number of users to return
            offset: Number of users to skip
            role: Filter by role (optional)
            is_active: Filter by active status (optional)
            search: Search in email (optional, case-insensitive)
            
        Returns:
            Tuple of (list of users, total count)
        """
        # Build base query
        base_stmt = select(User)
        
        # Apply filters
        filters = []
        if role:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active == is_active)
        if search:
            filters.append(
                func.lower(User.email).like(f"%{search.lower()}%")
            )
        
        if filters:
            base_stmt = base_stmt.where(and_(*filters))
        
        # Get total count
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar()
        
        # Get paginated results
        stmt = base_stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        users = result.scalars().all()
        
        return list(users), total
    
    async def create_user(
        self,
        email: str,
        password_hash: str,
        role: str = "annotator",
        is_active: bool = True,
        email_verified: bool = False
    ) -> User:
        """
        Create a new user.
        
        Args:
            email: User email address
            password_hash: Bcrypt password hash
            role: User role (default: annotator)
            is_active: Whether user is active (default: True)
            email_verified: Whether email is verified (default: False)
            
        Returns:
            Created User instance
        """
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            role=role,
            is_active=is_active
        )
        
        # Set email_verified_at if email_verified is True
        if email_verified:
            from datetime import datetime, timezone
            user.email_verified_at = datetime.now(timezone.utc)
        
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user
    
    async def update_user(
        self,
        user_id: UUID,
        email: Optional[str] = None,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        email_verified: Optional[bool] = None
    ) -> bool:
        """
        Update user fields.
        
        Args:
            user_id: User UUID
            email: New email (optional)
            role: New role (optional)
            is_active: New active status (optional)
            email_verified: Set email as verified (optional)
            
        Returns:
            True if user was found and updated, False otherwise
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return False
        
        if email is not None:
            user.email = email.lower()
        
        if role is not None:
            user.role = role
        
        if is_active is not None:
            user.is_active = is_active
        
        if email_verified is not None:
            if email_verified and user.email_verified_at is None:
                from datetime import datetime, timezone
                user.email_verified_at = datetime.now(timezone.utc)
            elif not email_verified:
                user.email_verified_at = None
        
        await self.session.flush()
        return True
    
    async def deactivate_user(self, user_id: UUID) -> bool:
        """
        Deactivate a user (soft delete).
        
        Args:
            user_id: User UUID
            
        Returns:
            True if user was found and deactivated, False otherwise
        """
        return await self.update_user(user_id, is_active=False)
