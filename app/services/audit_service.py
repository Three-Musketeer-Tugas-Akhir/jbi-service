"""
Audit Service.

Provides audit logging functionality for compliance.
"""

import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditAction
from app.repositories.audit_log_repository import AuditLogRepository

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.repository = AuditLogRepository(session)
    
    async def log_user_created(
        self,
        actor_id: UUID,
        new_user_id: UUID,
        email: str,
        role: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a user creation.
        
        Args:
            actor_id: Admin who created the user
            new_user_id: ID of created user
            email: Email of created user
            role: Role assigned
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_CREATED,
            resource_type="user",
            actor_id=actor_id,
            resource_id=new_user_id,
            details={
                "email": email,
                "role": role
            },
            ip_address=ip_address
        )
        logger.info(
            "User created: %s created user %s (%s) with role %s",
            actor_id, new_user_id, email, role
        )
    
    async def log_user_role_changed(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        old_role: str,
        new_role: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a user role change.
        
        Args:
            actor_id: Admin who made the change
            target_user_id: User whose role was changed
            old_role: Previous role
            new_role: New role
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_ROLE_CHANGED,
            resource_type="user",
            actor_id=actor_id,
            resource_id=target_user_id,
            details={
                "old_role": old_role,
                "new_role": new_role
            },
            ip_address=ip_address
        )
        logger.info(
            "User role changed: %s changed %s from %s to %s",
            actor_id, target_user_id, old_role, new_role
        )
    
    async def log_user_deactivated(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        email: str,
        tokens_revoked: int = 0,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a user deactivation.
        
        Args:
            actor_id: Admin who deactivated the user
            target_user_id: Deactivated user ID
            email: Email of deactivated user
            tokens_revoked: Number of refresh tokens revoked
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_DEACTIVATED,
            resource_type="user",
            actor_id=actor_id,
            resource_id=target_user_id,
            details={"email": email, "tokens_revoked": tokens_revoked},
            ip_address=ip_address
        )
        logger.info(
            "User deactivated: %s deactivated %s (%s), %d tokens revoked",
            actor_id, target_user_id, email, tokens_revoked
        )
    
    async def log_user_reactivated(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a user reactivation.
        
        Args:
            actor_id: Admin who reactivated the user
            target_user_id: Reactivated user ID
            email: Email of reactivated user
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_REACTIVATED,
            resource_type="user",
            actor_id=actor_id,
            resource_id=target_user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info(
            "User reactivated: %s reactivated %s (%s)",
            actor_id, target_user_id, email
        )
    
    async def log_user_updated(
        self,
        actor_id: UUID,
        target_user_id: UUID,
        email: str,
        changes: dict,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a user profile update.
        
        Args:
            actor_id: User who made the change (or admin)
            target_user_id: User who was updated
            email: Email of user
            changes: Dict of changed fields with old/new values
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_UPDATED,
            resource_type="user",
            actor_id=actor_id,
            resource_id=target_user_id,
            details={
                "email": email,
                "changes": changes
            },
            ip_address=ip_address
        )
        logger.info(
            "User updated: %s updated %s (%s) - changes: %s",
            actor_id, target_user_id, email, changes
        )
    
    async def log_password_changed(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a password change.
        
        Args:
            user_id: User who changed password
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.PASSWORD_CHANGED,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("Password changed for user %s (%s)", user_id, email)
    
    async def log_password_reset_requested(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a password reset request.
        
        Args:
            user_id: User who requested reset
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.PASSWORD_RESET_REQUESTED,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("Password reset requested for user %s (%s)", user_id, email)
    
    async def log_password_reset_completed(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a password reset completion.
        
        Args:
            user_id: User who reset password
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.PASSWORD_RESET_COMPLETED,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("Password reset completed for user %s (%s)", user_id, email)
    
    async def log_email_verified(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log email verification.
        
        Args:
            user_id: User who verified email
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.EMAIL_VERIFIED,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("Email verified for user %s (%s)", user_id, email)
    
    async def log_login(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a successful login.
        
        Args:
            user_id: User who logged in
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_LOGIN,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("User login: %s (%s)", user_id, email)
    
    async def log_login_failed(
        self,
        email: str,
        reason: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a failed login attempt.
        
        Args:
            email: Email attempted
            reason: Reason for failure
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_LOGIN_FAILED,
            resource_type="user",
            actor_id=None,
            resource_id=None,
            details={
                "email": email,
                "reason": reason
            },
            ip_address=ip_address
        )
        logger.info("Failed login attempt for %s: %s", email, reason)
    
    async def log_logout(
        self,
        user_id: UUID,
        email: str,
        ip_address: Optional[str] = None
    ) -> None:
        """
        Log a logout.
        
        Args:
            user_id: User who logged out
            email: User email
            ip_address: Request IP address
        """
        await self.repository.create(
            action=AuditAction.USER_LOGOUT,
            resource_type="user",
            actor_id=user_id,
            resource_id=user_id,
            details={"email": email},
            ip_address=ip_address
        )
        logger.info("User logout: %s (%s)", user_id, email)
