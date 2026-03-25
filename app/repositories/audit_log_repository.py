"""
Audit Log Repository.

Provides database access for audit logging.
"""

from typing import Optional, List, Any
from uuid import UUID

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog


class AuditLogRepository:
    """Repository for audit log database operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
    
    async def create(
        self,
        action: str,
        resource_type: str,
        actor_id: Optional[UUID] = None,
        resource_id: Optional[UUID] = None,
        details: Optional[dict] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Create a new audit log entry.
        
        Args:
            action: Action type (use AuditAction constants)
            resource_type: Type of resource affected
            actor_id: User who performed the action
            resource_id: ID of affected resource
            details: Additional details as dict
            ip_address: Request IP address
            
        Returns:
            Created AuditLog instance
        """
        log_entry = AuditLog(
            action=action,
            resource_type=resource_type,
            actor_id=actor_id,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address
        )
        
        self.session.add(log_entry)
        await self.session.flush()
        
        return log_entry
    
    async def get_by_id(self, log_id: UUID) -> Optional[AuditLog]:
        """
        Get audit log entry by ID.
        
        Args:
            log_id: Audit log entry UUID
            
        Returns:
            AuditLog instance or None
        """
        stmt = select(AuditLog).where(AuditLog.id == log_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_by_resource(
        self,
        resource_type: str,
        resource_id: UUID,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        List audit log entries for a specific resource.
        
        Args:
            resource_type: Type of resource
            resource_id: Resource UUID
            limit: Maximum entries to return
            
        Returns:
            List of AuditLog entries
        """
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.resource_type == resource_type,
                AuditLog.resource_id == resource_id
            )
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def list_by_actor(
        self,
        actor_id: UUID,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        List audit log entries by actor (who performed actions).
        
        Args:
            actor_id: Actor user UUID
            limit: Maximum entries to return
            
        Returns:
            List of AuditLog entries
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor_id)
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def list_by_action(
        self,
        action: str,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        List audit log entries by action type.
        
        Args:
            action: Action type constant
            limit: Maximum entries to return
            
        Returns:
            List of AuditLog entries
        """
        stmt = (
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def list_recent(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[AuditLog], int]:
        """
        List recent audit log entries with pagination.
        
        Args:
            limit: Maximum entries to return
            offset: Number of entries to skip
            
        Returns:
            Tuple of (list of AuditLog entries, total count)
        """
        # Get total count
        count_stmt = select(AuditLog)
        count_result = await self.session.execute(count_stmt)
        total = len(count_result.scalars().all())
        
        # Get paginated results
        stmt = (
            select(AuditLog)
            .order_by(desc(AuditLog.timestamp))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
