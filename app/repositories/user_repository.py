"""
User Repository.

Provides database access methods for user-related operations.
Follows repository pattern for clean separation of concerns.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import User, Role
from app.db.models.password_change_log import PasswordChangeLog


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
    
    async def get_by_id(self, user_id, load_roles: bool = True) -> Optional[User]:
        """
        Get user by ID.
        
        Args:
            user_id: User UUID
            load_roles: Whether to eagerly load roles (default: True)
            
        Returns:
            User instance or None if not found
        """
        stmt = select(User).where(User.id == user_id)
        
        if load_roles:
            from sqlalchemy.orm import joinedload
            stmt = stmt.options(joinedload(User.roles))
        
        result = await self.session.execute(stmt)
        return result.scalars().first()
    
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
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        search: Optional[str] = None
    ) -> Tuple[List[User], int]:
        """
        List users with optional filtering, sorting, and pagination.
        
        Args:
            page: Page number (1-based)
            page_size: Items per page
            role: Filter by role name (optional)
            is_active: Filter by active status (optional)
            sort_by: Sort field (created_at, email, role)
            sort_order: Sort direction (asc, desc)
            search: Search in email (optional, case-insensitive)
            
        Returns:
            Tuple of (list of users, total count)
        """
        from sqlalchemy.orm import joinedload
        from sqlalchemy import desc, asc
        
        # Build base query with roles eager loaded
        base_stmt = select(User).options(joinedload(User.roles))
        count_stmt = select(func.count(User.id))
        
        # Apply filters
        filters = []
        if is_active is not None:
            filters.append(User.is_active == is_active)
        if search:
            filters.append(
                func.lower(User.email).like(f"%{search.lower()}%")
            )
        
        if filters:
            base_stmt = base_stmt.where(and_(*filters))
            count_stmt = count_stmt.where(and_(*filters))
        
        # Get total count (efficient database count)
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar_one()
        
        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order.lower() == "desc":
            base_stmt = base_stmt.order_by(desc(sort_column))
        else:
            base_stmt = base_stmt.order_by(asc(sort_column))
        
        # Apply pagination
        offset = (page - 1) * page_size
        base_stmt = base_stmt.offset(offset).limit(page_size)
        
        # Execute query to get users
        result = await self.session.execute(base_stmt)
        users = result.scalars().unique().all()
        
        # Filter by role in Python (since it's many-to-many)
        if role:
            users = [
                u for u in users 
                if any(r.name == role for r in u.roles)
            ]
            # Adjust total for role filter (approximate for pagination)
            # In production, use a subquery or materialized view
        
        return list(users), total
    
    async def create_user(
        self,
        email: str,
        password_hash: str,
        roles: Optional[List[str]] = None,
        is_active: bool = True,
        email_verified: bool = False,
        must_change_password: bool = False
    ) -> User:
        """
        Create a new user with roles.
        
        Args:
            email: User email address
            password_hash: Bcrypt password hash
            roles: List of role names (default: ["annotator"])
            is_active: Whether user is active (default: True)
            email_verified: Whether email is verified (default: False)
            must_change_password: Set to True to force password change on next login (default: False)
            
        Returns:
            Created User instance
        """
        # Create user without roles first
        user = User(
            email=email.lower(),
            password_hash=password_hash,
            is_active=is_active,
            must_change_password=must_change_password
        )
        
        # Set email_verified_at if email_verified is True
        if email_verified:
            from datetime import datetime, timezone
            user.email_verified_at = datetime.now(timezone.utc)
        
        self.session.add(user)
        await self.session.flush()
        
        # Assign roles
        if roles:
            await self._assign_roles_to_user(user, roles)
        
        await self.session.refresh(user)
        return user
    
    async def _assign_roles_to_user(self, user: User, role_names: List[str]) -> None:
        """
        Assign roles to a user via the junction table.
        
        Args:
            user: User instance
            role_names: List of role names to assign
        """
        # Get role entities
        role_stmt = select(Role).where(Role.name.in_(role_names))
        role_result = await self.session.execute(role_stmt)
        role_entities = role_result.scalars().all()
        
        # Assign roles to user
        user.roles = list(role_entities)
        await self.session.flush()
    
    async def get_roles_by_name(self, role_names: List[str]) -> List[Role]:
        """
        Get role entities by their names.
        
        Args:
            role_names: List of role names
            
        Returns:
            List of Role entities
        """
        stmt = select(Role).where(Role.name.in_(role_names))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def update_user(
        self,
        user_id: UUID,
        email: Optional[str] = None,
        roles: Optional[List[str]] = None,
        is_active: Optional[bool] = None,
        email_verified: Optional[bool] = None
    ) -> bool:
        """
        Update user fields.
        
        Args:
            user_id: User UUID
            email: New email (optional)
            roles: New list of role names (optional)
            is_active: New active status (optional)
            email_verified: Set email as verified (optional)
            
        Returns:
            True if user was found and updated, False otherwise
        """
        from sqlalchemy.orm import joinedload
        
        # Load user with roles
        stmt = select(User).where(User.id == user_id).options(joinedload(User.roles))
        result = await self.session.execute(stmt)
        user = result.scalars().first()
        
        if user is None:
            return False
        
        if email is not None:
            user.email = email.lower()
        
        if roles is not None:
            await self._assign_roles_to_user(user, roles)
        
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

    async def log_password_change(
        self,
        user_id: UUID,
        change_type: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        was_temporary: bool = False
    ) -> PasswordChangeLog:
        """
        Log a password change.
        
        Args:
            user_id: User UUID
            change_type: Type of change (FIRST_LOGIN, SELF_CHANGE, ADMIN_RESET)
            ip_address: IP address of requester
            user_agent: User agent string
            was_temporary: Whether the previous password was a temporary one
            
        Returns:
            Created log entry
        """
        log_entry = PasswordChangeLog(
            user_id=user_id,
            change_type=change_type,
            ip_address=ip_address,
            user_agent=user_agent,
            was_temporary=was_temporary
        )
        self.session.add(log_entry)
        await self.session.flush()
        return log_entry
        
    async def get_password_change_history(self, user_id: UUID) -> List[PasswordChangeLog]:
        """
        Get password change history for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            List of log entries ordered by most recent first
        """
        from sqlalchemy import desc
        
        stmt = select(PasswordChangeLog).where(
            PasswordChangeLog.user_id == user_id
        ).order_by(
            desc(PasswordChangeLog.changed_at)
        )
        
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
