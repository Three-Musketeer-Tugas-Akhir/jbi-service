---
story_id: "1.7"
story_key: "1-7-admin-modify-user-roles"
epic: 1
status: ready-for-dev
created: "2026-03-19"
last_updated: "2026-03-19"
---

# Story 1.7: Admin - Modify User Roles

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.7  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts ✅ (uses same admin router)

---

## Story Requirements

### User Story

As an admin,  
I want to modify user roles,  
So that I can update permissions as team responsibilities change.

### Business Context

This story enables administrators to change user roles when team members move between responsibilities (e.g., an annotator becoming a curator). The role change takes effect on the next token refresh, allowing current sessions to complete gracefully. This story also introduces basic audit logging infrastructure for compliance.

### Acceptance Criteria

**Given** I am authenticated as an admin  
**And** a user exists with id "uuid-123" and role "annotator"  
**When** I PUT to `/api/v1/admin/users/uuid-123/role` with:
  - role: "curator"  
**Then** the user's role is updated to "curator"  
**And** I receive a 200 response with updated user details  
**And** an audit log entry is created for the role change

**Given** I attempt to modify my own role  
**When** I PUT to my own user role endpoint  
**Then** I receive a 400 response with error "Cannot modify your own role"

**Given** I attempt to change a user's role to an invalid value  
**When** I PUT to the role endpoint with role "superadmin"  
**Then** I receive a 400 response with error "Invalid role specified"

**Given** the user is currently logged in  
**When** their role is changed  
**Then** their current session remains valid until token expiry  
**And** on next token refresh, the new role takes effect

### Technical Notes

- Role change affects future tokens, not current sessions
- Self-modification prevention for safety
- Audit log entry for compliance tracking
- Valid roles: admin, annotator, curator

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: Admin router endpoint
   - **Service Layer**: Role update logic, audit logging
   - **Repository Layer**: User update operations
   - **Pipeline Layer**: (Not applicable)

2. **RBAC Protection**
   - Use `require_admin` dependency
   - Self-modification prevention at service layer

3. **Token Behavior**
   - Existing tokens remain valid until expiry
   - New role takes effect on next token refresh
   - No forced logout on role change

4. **Audit Logging Pattern**
   - Lightweight audit log table
   - Async logging (don't block response)
   - Foundation for Epic 5 (full audit system)

### Technical Requirements

**Required Technologies:**
- FastAPI (API framework)
- SQLAlchemy 2.0 async (database)
- Pydantic v2 (validation)

**Audit Log Schema (Foundation):**

```python
class AuditLog(Base):
    """Audit log entry for compliance tracking."""
    
    id: UUID  # Primary key
    timestamp: datetime  # When action occurred
    actor_id: UUID  # User who performed action (admin)
    action: str  # "user.role_changed"
    resource_type: str  # "user"
    resource_id: UUID  # Target user ID
    details: dict  # { "old_role": "annotator", "new_role": "curator" }
    ip_address: Optional[str]  # Request IP
```

**API Specifications:**

```yaml
endpoint: PUT /api/v1/admin/users/{user_id}/role
tags: ["admin"]
security:
  - BearerAuth: []
parameters:
  - name: user_id
    in: path
    required: true
    schema:
      type: string
      format: uuid
request_body:
  content:
    application/json:
      schema:
        type: object
        required: [role]
        properties:
          role:
            type: string
            enum: ["admin", "annotator", "curator"]
            example: "curator"

responses:
  200:
    description: Role updated successfully
    content:
      application/json:
        schema:
          type: object
          properties:
            id:
              type: string
              format: uuid
            email:
              type: string
            role:
              type: string
            previous_role:
              type: string
            updated_at:
              type: string
              format: date-time
  400:
    description: Bad request (self-modification, invalid role, same role)
  403:
    description: Admin access required
  404:
    description: User not found
```

### File Structure Requirements

```
jbi-service/
├── alembic/versions/
│   └── 004_add_audit_log_table.py      # NEW - Audit log migration
├── app/
│   ├── db/models/
│   │   ├── __init__.py                 # UPDATE - Export AuditLog
│   │   └── audit.py                    # NEW - AuditLog model
│   ├── models/
│   │   └── schemas.py                  # UPDATE - Add role update schemas
│   ├── repositories/
│   │   ├── __init__.py                 # UPDATE - Export AuditLogRepository
│   │   ├── audit_log_repository.py     # NEW - Audit log persistence
│   │   └── user_repository.py          # UPDATE - Add update_role method
│   ├── services/
│   │   ├── audit_service.py            # NEW - Audit logging service
│   │   └── user_service.py             # UPDATE - Add update_role method
│   └── routers/
│       └── admin.py                    # UPDATE - Add PUT /role endpoint
├── tests/
│   ├── unit/
│   │   ├── test_repositories/
│   │   │   └── test_audit_log_repository.py
│   │   └── test_services/
│   │       └── test_audit_service.py
│   └── integration/
│       └── test_admin_modify_role.py
└── docs/
    └── audit-logging-guide.md          # NEW
```

---

## Implementation Guide

### Phase 1: Database Migration

#### Step 1.1: Create Alembic Migration 004_add_audit_log_table.py

```python
"""Add audit log table

Revision ID: 004
Revises: 003_add_refresh_token_table
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '004_add_audit_log_table'
down_revision: Union[str, None] = '003_add_refresh_token_table'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create audit log table."""
    
    op.create_table(
        'audit_logs',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False
        ),
        sa.Column(
            'timestamp',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.Column(
            'actor_id',
            postgresql.UUID(as_uuid=True),
            nullable=True  # Nullable for system actions
        ),
        sa.Column(
            'action',
            sa.String(50),
            nullable=False
        ),
        sa.Column(
            'resource_type',
            sa.String(50),
            nullable=False
        ),
        sa.Column(
            'resource_id',
            postgresql.UUID(as_uuid=True),
            nullable=True
        ),
        sa.Column(
            'details',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False
        ),
        sa.Column(
            'ip_address',
            sa.String(45),  # IPv6 compatible
            nullable=True
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for common queries
    op.create_index(
        'idx_audit_logs_timestamp',
        'audit_logs',
        ['timestamp']
    )
    op.create_index(
        'idx_audit_logs_actor_id',
        'audit_logs',
        ['actor_id']
    )
    op.create_index(
        'idx_audit_logs_action',
        'audit_logs',
        ['action']
    )
    op.create_index(
        'idx_audit_logs_resource',
        'audit_logs',
        ['resource_type', 'resource_id']
    )


def downgrade() -> None:
    """Drop audit log table."""
    op.drop_index('idx_audit_logs_resource', table_name='audit_logs')
    op.drop_index('idx_audit_logs_action', table_name='audit_logs')
    op.drop_index('idx_audit_logs_actor_id', table_name='audit_logs')
    op.drop_index('idx_audit_logs_timestamp', table_name='audit_logs')
    op.drop_table('audit_logs')
```

### Phase 2: Model Layer

#### Step 2.1: Create app/db/models/audit.py

```python
"""
Audit domain models.

Models for compliance audit logging.
"""

from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    """
    Audit log entry for compliance tracking.
    
    Records significant system actions for audit purposes.
    Immutable - entries are never updated or deleted.
    """
    
    __tablename__ = "audit_logs"
    
    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        comment="Unique audit log entry identifier"
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
        comment="When the action occurred"
    )
    actor_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
        comment="User who performed the action (NULL for system)"
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Action type (e.g., 'user.role_changed', 'user.created')"
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of resource affected (e.g., 'user', 'annotation')"
    )
    resource_id: Mapped[Optional[UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        comment="ID of affected resource"
    )
    details: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
        comment="Additional action details as JSON"
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
        comment="IP address of request (IPv6 compatible)"
    )
    
    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action}, "
            f"resource={self.resource_type}:{self.resource_id})>"
        )


# Common action types for consistency
class AuditAction:
    """Constants for audit action types."""
    
    # User management
    USER_CREATED = "user.created"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    
    # Authentication
    USER_LOGIN = "user.login"
    USER_LOGOUT = "user.logout"
    USER_LOGIN_FAILED = "user.login_failed"
    
    # Token management
    TOKEN_REFRESHED = "token.refreshed"
    TOKEN_REVOKED = "token.revoked"
```

#### Step 2.2: Update app/db/models/__init__.py

```python
"""Database models."""

from app.db.models.auth import User, Role, RefreshToken
from app.db.models.audit import AuditLog, AuditAction

__all__ = [
    "User",
    "Role", 
    "RefreshToken",
    "AuditLog",
    "AuditAction",
]
```

### Phase 3: Repository Layer

#### Step 3.1: Create app/repositories/audit_log_repository.py

```python
"""
Audit Log Repository.

Provides database access for audit logging.
"""

from typing import Optional, Any
from uuid import UUID

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
```

#### Step 3.2: Update app/repositories/user_repository.py

Add update methods:

```python
async def get_by_id(self, user_id: UUID) -> Optional[User]:
    """
    Get user by ID.
    
    Args:
        user_id: User UUID
        
    Returns:
        User instance or None
    """
    stmt = select(User).where(User.id == user_id)
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none()


async def update_role(self, user_id: UUID, new_role: str) -> Optional[User]:
    """
    Update user role.
    
    Args:
        user_id: User UUID
        new_role: New role value
        
    Returns:
        Updated User instance or None if not found
    """
    user = await self.get_by_id(user_id)
    if user is None:
        return None
    
    user.role = new_role
    await self.session.flush()
    await self.session.refresh(user)
    
    return user
```

### Phase 4: Service Layer

#### Step 4.1: Create app/services/audit_service.py

```python
"""
Audit Service.

Provides audit logging functionality for compliance.
"""

import logging
from typing import Optional, Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.audit_log_repository import AuditLogRepository
from app.db.models.audit import AuditAction

logger = logging.getLogger(__name__)


class AuditService:
    """Service for audit logging operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.repository = AuditLogRepository(session)
    
    async def log_user_role_change(
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
```

#### Step 4.2: Update app/services/user_service.py

Add update_role method:

```python
from uuid import UUID
from typing import Tuple, Optional

from app.services.audit_service import AuditService


class UserService:
    """Service for user operations."""
    
    # ... existing methods ...
    
    async def update_role(
        self,
        admin_id: UUID,
        target_user_id: UUID,
        new_role: str,
        ip_address: Optional[str] = None
    ) -> Tuple[Optional[User], str]:
        """
        Update a user's role.
        
        Args:
            admin_id: ID of admin making the change
            target_user_id: ID of user to update
            new_role: New role value
            ip_address: Request IP address for audit
            
        Returns:
            Tuple of (updated_user, previous_role)
            
        Raises:
            ValueError: If validation fails
        """
        # Validate roles
        allowed_roles = {"admin", "annotator", "curator"}
        if new_role not in allowed_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(allowed_roles)}")
        
        # Get target user
        user = await self.repository.get_by_id(target_user_id)
        if user is None:
            raise ValueError("User not found")
        
        # Check for self-modification
        if str(admin_id) == str(target_user_id):
            raise ValueError("Cannot modify your own role")
        
        # Check if role is actually changing
        old_role = user.role
        if old_role == new_role:
            raise ValueError(f"User already has role '{new_role}'")
        
        # Update role
        user = await self.repository.update_role(target_user_id, new_role)
        
        # Log audit event
        audit_service = AuditService(self.session)
        await audit_service.log_user_role_change(
            actor_id=admin_id,
            target_user_id=target_user_id,
            old_role=old_role,
            new_role=new_role,
            ip_address=ip_address
        )
        
        await self.session.commit()
        
        return user, old_role
```

### Phase 5: API Layer

#### Step 5.1: Update app/models/schemas.py

Add role update schemas:

```python
class UserRoleUpdateRequest(BaseModel):
    """Request body for PUT /api/v1/admin/users/{id}/role."""
    role: str = Field(..., pattern="^(admin|annotator|curator)$")


class UserRoleUpdateResponse(BaseModel):
    """Response for successful role update."""
    id: UUID
    email: str
    role: str
    previous_role: str
    updated_at: datetime
```

#### Step 5.2: Update app/routers/admin.py

Add role update endpoint:

```python
from uuid import UUID
from fastapi import Request

from app.models.schemas import (
    UserCreateRequest,
    UserCreateResponse,
    UserRoleUpdateRequest,
    UserRoleUpdateResponse,
    AuthErrorResponse,
)


@router.put(
    "/users/{user_id}/role",
    response_model=UserRoleUpdateResponse,
    responses={
        400: {"description": "Bad request (self-modification, invalid role, same role)"},
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def update_user_role(
    user_id: UUID,
    role_data: UserRoleUpdateRequest,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Update a user's role (Admin only).
    
    - **user_id**: UUID of user to update
    - **role**: New role (admin, annotator, curator)
    
    Role change takes effect on next token refresh.
    Current sessions remain valid until token expiry.
    """
    user_service = UserService(db_session)
    
    # Extract IP address for audit
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    
    try:
        user, previous_role = await user_service.update_role(
            admin_id=current_user.id,
            target_user_id=user_id,
            new_role=role_data.role,
            ip_address=client_ip
        )
        
        return UserRoleUpdateResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            previous_role=previous_role,
            updated_at=user.updated_at
        )
        
    except ValueError as e:
        error_msg = str(e).lower()
        
        if "not found" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        if "cannot modify your own" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify your own role"
            )
        
        if "already has role" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e)
            )
        
        # Invalid role or other validation error
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
```

### Phase 6: Testing

#### Step 6.1: Create tests/unit/test_services/test_audit_service.py

```python
"""Tests for AuditService."""

import pytest
from uuid import uuid4

from app.services.audit_service import AuditService
from app.repositories.audit_log_repository import AuditLogRepository


@pytest.mark.asyncio
class TestAuditService:
    """Tests for AuditService."""
    
    async def test_log_user_role_change(self, db_session):
        """Test logging role change."""
        service = AuditService(db_session)
        
        admin_id = uuid4()
        user_id = uuid4()
        
        await service.log_user_role_change(
            actor_id=admin_id,
            target_user_id=user_id,
            old_role="annotator",
            new_role="curator",
            ip_address="192.168.1.1"
        )
        
        await db_session.commit()
        
        # Verify log entry created
        repo = AuditLogRepository(db_session)
        # Query would need to be added to repository
```

#### Step 6.2: Create tests/integration/test_admin_modify_role.py

```python
"""Integration tests for role modification."""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service

client = TestClient(app)


def create_token(user_id: UUID, role: str):
    """Helper to create token."""
    return jwt_auth_service.create_access_token(user_id, role)


class TestUpdateUserRole:
    """Tests for PUT /api/v1/admin/users/{id}/role."""
    
    def test_update_role_success(self, db_session, test_user):
        """Test successful role update by admin."""
        admin_id = uuid4()
        admin_token = create_token(admin_id, "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{test_user.id}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["role"] == "curator"
        assert data["previous_role"] == test_user.role
        assert data["id"] == str(test_user.id)
    
    def test_self_modification_forbidden(self, db_session):
        """Test admin cannot modify own role."""
        admin_id = uuid4()
        admin_token = create_token(admin_id, "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{admin_id}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "annotator"}
        )
        
        assert response.status_code == 400
        assert "Cannot modify your own" in response.json()["detail"]
    
    def test_non_admin_forbidden(self, db_session, test_user):
        """Test non-admin cannot modify roles."""
        annotator_id = uuid4()
        annotator_token = create_token(annotator_id, "annotator")
        
        response = client.put(
            f"/api/v1/admin/users/{test_user.id}/role",
            headers={"Authorization": f"Bearer {annotator_token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 403
    
    def test_invalid_role(self, db_session, test_user):
        """Test 400 for invalid role."""
        admin_token = create_token(uuid4(), "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{test_user.id}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "superadmin"}
        )
        
        assert response.status_code == 422
    
    def test_same_role(self, db_session, test_user):
        """Test 400 for setting same role."""
        admin_token = create_token(uuid4(), "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{test_user.id}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": test_user.role}  # Same role
        )
        
        assert response.status_code == 400
        assert "already has role" in response.json()["detail"]
    
    def test_user_not_found(self, db_session):
        """Test 404 for non-existent user."""
        admin_token = create_token(uuid4(), "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{uuid4()}/role",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 404
```

### Phase 7: Documentation

#### Step 7.1: Create docs/audit-logging-guide.md

```markdown
# Audit Logging Guide

This guide covers the audit logging system for compliance tracking.

## Overview

The audit log captures significant system actions for:
- Compliance requirements (FR55-FR59)
- Security monitoring
- Activity tracking

## Logged Actions

### User Management

| Action | Description | Details |
|--------|-------------|---------|
| `user.created` | User account created | email, role |
| `user.role_changed` | User role modified | old_role, new_role |
| `user.deactivated` | User account deactivated | reason |
| `user.reactivated` | User account reactivated | - |

### Authentication

| Action | Description |
|--------|-------------|
| `user.login` | Successful login |
| `user.login_failed` | Failed login attempt |
| `user.logout` | User logout |
| `token.refreshed` | Token refreshed |
| `token.revoked` | Token revoked |

## Audit Log Schema

```json
{
  "id": "uuid",
  "timestamp": "2026-03-19T10:30:00Z",
  "actor_id": "admin-uuid",
  "action": "user.role_changed",
  "resource_type": "user",
  "resource_id": "user-uuid",
  "details": {
    "old_role": "annotator",
    "new_role": "curator"
  },
  "ip_address": "192.168.1.1"
}
```

## Using AuditService

```python
from app.services.audit_service import AuditService

audit_service = AuditService(db_session)

# Log role change
await audit_service.log_user_role_change(
    actor_id=admin.id,
    target_user_id=user.id,
    old_role="annotator",
    new_role="curator",
    ip_address="192.168.1.1"
)
```

## Immutability

Audit log entries are immutable:
- Never updated after creation
- Never deleted (retained for compliance)
- Only expired entries cleaned up after retention period

## Retention

Default retention: 7 years for compliance.

## Querying (Future)

Future Epic 5 will add:
- Filter by date range
- Filter by user
- Filter by action type
- Export for compliance
```

---

## Implementation Checklist

### Phase 1: Database Migration
- [ ] Create Alembic migration 004_add_audit_log_table.py
- [ ] Run migration

### Phase 2: Model Layer
- [ ] Create app/db/models/audit.py with AuditLog and AuditAction
- [ ] Update app/db/models/__init__.py

### Phase 3: Repository Layer
- [ ] Create app/repositories/audit_log_repository.py
- [ ] Update UserRepository with get_by_id and update_role

### Phase 4: Service Layer
- [ ] Create app/services/audit_service.py
- [ ] Update UserService with update_role method

### Phase 5: API Layer
- [ ] Add schemas for role update
- [ ] Add PUT /admin/users/{id}/role endpoint

### Phase 6: Testing
- [ ] Unit tests for AuditService
- [ ] Integration tests for role update endpoint

### Phase 7: Documentation
- [ ] Create audit-logging-guide.md

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts ✅

**Stories that depend on this:**
- Story 1.8: Admin Deactivate User Accounts (uses same patterns)
- Story 1.9: Admin List and View Users
- Epic 5: Audit & Compliance (builds on audit infrastructure)

---

## Next Story

After completing this story, proceed to:  
**Story 1.8: Admin - Deactivate User Accounts**

This story will add DELETE /api/v1/admin/users/{user_id} endpoint with soft delete.

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. **Self-Modification**: Always check admin != target user
2. **Token Behavior**: Role change doesn't invalidate current tokens
3. **Audit Logging**: All role changes must be logged
4. **Transaction**: Role update and audit log in same transaction

**Common Mistakes to Avoid:**
- ❌ Forgetting to prevent self-modification
- ❌ Not logging audit entry
- ❌ Invalidating current tokens on role change
- ❌ Missing 400 for same-role update

**Security Checklist:**
- [ ] Self-modification prevented
- [ ] Admin-only access enforced
- [ ] Audit log entry created
- [ ] Input validation on role
- [ ] IP address captured for audit

**Questions?**  
Refer to:
- Story 1.6 for admin endpoint patterns
- Architecture: "Audit Trail" section
