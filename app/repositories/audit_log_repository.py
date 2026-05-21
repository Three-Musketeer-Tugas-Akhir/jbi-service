"""
Audit Log Repository.

Provides database access for audit logging.
"""

from datetime import datetime
from typing import Optional, List, Any, Dict, Tuple
from uuid import UUID

from sqlalchemy import select, desc, func, and_, String
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog
from app.db.models.auth import User


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
        count_stmt = select(func.count(AuditLog.id))
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar()
        
        # Get paginated results with actor info
        stmt = (
            select(AuditLog)
            .options(selectinload(AuditLog.actor))
            .order_by(desc(AuditLog.timestamp))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
    
    # ========================================================================
    # Admin Query Methods with Filtering
    # ========================================================================
    
    async def search_with_filters(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        actor_id: Optional[UUID] = None,
        action: Optional[str] = None,
        actions: Optional[List[str]] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[UUID] = None,
        ip_address: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[List[AuditLog], int]:
        """
        Search audit logs with multiple filters.
        
        Args:
            start_date: Filter from date
            end_date: Filter to date
            actor_id: Filter by actor
            action: Filter by action type
            resource_type: Filter by resource type
            resource_id: Filter by resource ID
            ip_address: Filter by IP address
            limit: Maximum entries to return
            offset: Number of entries to skip
            
        Returns:
            Tuple of (list of AuditLog entries, total count)
        """
        # Build conditions
        conditions = []
        
        if start_date:
            conditions.append(AuditLog.timestamp >= start_date)
        if end_date:
            conditions.append(AuditLog.timestamp <= end_date)
        if actor_id:
            conditions.append(AuditLog.actor_id == actor_id)
        if action:
            conditions.append(AuditLog.action == action)
        if actions:
            conditions.append(AuditLog.action.in_(actions))
        if resource_type:
            conditions.append(AuditLog.resource_type == resource_type)
        if resource_id:
            conditions.append(AuditLog.resource_id == resource_id)
        if ip_address:
            conditions.append(AuditLog.ip_address.ilike(f"%{ip_address}%"))
        
        # Base query
        base_query = select(AuditLog)
        if conditions:
            base_query = base_query.where(and_(*conditions))
        
        # Get total count
        count_stmt = select(func.count(AuditLog.id)).select_from(base_query.subquery())
        count_result = await self.session.execute(count_stmt)
        total = count_result.scalar()
        
        # Get paginated results with actor info
        stmt = (
            base_query
            .options(selectinload(AuditLog.actor))
            .order_by(desc(AuditLog.timestamp))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
    
    async def get_unique_actions(self) -> List[str]:
        """
        Get list of unique action types in audit logs.
        
        Returns:
            List of unique action strings
        """
        stmt = select(AuditLog.action).distinct().order_by(AuditLog.action)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
    
    async def get_unique_resource_types(self) -> List[str]:
        """
        Get list of unique resource types in audit logs.
        
        Returns:
            List of unique resource type strings
        """
        stmt = select(AuditLog.resource_type).distinct().order_by(AuditLog.resource_type)
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
    
    async def get_stats_by_action(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 10
    ) -> List[Tuple[str, int]]:
        """
        Get action counts grouped by action type.
        
        Args:
            start_date: Filter from date
            end_date: Filter to date
            limit: Maximum results to return
            
        Returns:
            List of (action, count) tuples
        """
        conditions = []
        if start_date:
            conditions.append(AuditLog.timestamp >= start_date)
        if end_date:
            conditions.append(AuditLog.timestamp <= end_date)
        
        stmt = (
            select(AuditLog.action, func.count(AuditLog.id).label("count"))
            .group_by(AuditLog.action)
            .order_by(desc("count"))
            .limit(limit)
        )
        
        if conditions:
            stmt = stmt.where(and_(*conditions))
        
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
    
    async def get_daily_activity(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Tuple[str, int]]:
        """
        Get activity counts grouped by date.
        
        Args:
            start_date: Start date
            end_date: End date
            
        Returns:
            List of (date_string, count) tuples
        """
        # Use database-specific date formatting
        stmt = (
            select(
                func.to_char(AuditLog.timestamp, 'YYYY-MM-DD').label("date"),
                func.count(AuditLog.id).label("count")
            )
            .where(
                and_(
                    AuditLog.timestamp >= start_date,
                    AuditLog.timestamp <= end_date
                )
            )
            .group_by("date")
            .order_by("date")
        )
        
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
    
    async def get_unique_user_count(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> int:
        """
        Get count of unique users who performed actions.
        
        Args:
            start_date: Filter from date
            end_date: Filter to date
            
        Returns:
            Number of unique users
        """
        conditions = [AuditLog.actor_id.isnot(None)]
        if start_date:
            conditions.append(AuditLog.timestamp >= start_date)
        if end_date:
            conditions.append(AuditLog.timestamp <= end_date)
        
        stmt = (
            select(func.count(func.distinct(AuditLog.actor_id)))
            .where(and_(*conditions))
        )
        
        result = await self.session.execute(stmt)
        return result.scalar()
    
    async def get_user_activity_summary(
        self,
        user_id: UUID,
        period_days: int = 30
    ) -> Dict[str, Any]:
        """
        Get activity summary for a specific user.
        
        Args:
            user_id: User ID
            period_days: Number of days to look back
            
        Returns:
            Dictionary with activity summary
        """
        from sqlalchemy import text
        
        # Get user info
        user_stmt = select(User.email).where(User.id == user_id)
        user_result = await self.session.execute(user_stmt)
        user_email = user_result.scalar()
        
        # Calculate date range
        from datetime import timedelta
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=period_days)
        
        # Total actions
        total_stmt = (
            select(func.count(AuditLog.id))
            .where(
                and_(
                    AuditLog.actor_id == user_id,
                    AuditLog.timestamp >= start_date
                )
            )
        )
        total_result = await self.session.execute(total_stmt)
        total_actions = total_result.scalar()
        
        # Last active
        last_stmt = (
            select(AuditLog.timestamp)
            .where(AuditLog.actor_id == user_id)
            .order_by(desc(AuditLog.timestamp))
            .limit(1)
        )
        last_result = await self.session.execute(last_stmt)
        last_active = last_result.scalar()
        
        # Actions by type
        actions_stmt = (
            select(AuditLog.action, func.count(AuditLog.id).label("count"))
            .where(
                and_(
                    AuditLog.actor_id == user_id,
                    AuditLog.timestamp >= start_date
                )
            )
            .group_by(AuditLog.action)
            .order_by(desc("count"))
        )
        actions_result = await self.session.execute(actions_stmt)
        actions_by_type = [(row[0], row[1]) for row in actions_result.all()]
        
        return {
            "user_id": user_id,
            "email": user_email,
            "total_actions": total_actions,
            "last_active": last_active,
            "actions_by_type": actions_by_type,
            "period_days": period_days
        }
