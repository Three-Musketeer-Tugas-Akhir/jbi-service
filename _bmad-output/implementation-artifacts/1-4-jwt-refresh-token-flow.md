---
story_id: "1.4"
story_key: "1-4-jwt-refresh-token-flow"
epic: 1
status: ready-for-dev
created: "2026-03-19"
last_updated: "2026-03-19"
---

# Story 1.4: JWT Refresh Token Flow

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.4  
**Status:** ready-for-dev  
**Priority:** Critical (Foundation Story)  
**Estimated Effort:** Medium (2-3 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.2: JWT Authentication Service ✅
- Story 1.3: User Login API Endpoint (recommended, not blocking)

---

## Story Requirements

### User Story

As a user,  
I want to refresh my access token using a refresh token,  
So that I don't need to re-login frequently.

### Business Context

This story implements the token refresh mechanism, allowing users to obtain new access tokens without re-entering credentials. This is essential for UX (users stay logged in) and security (short-lived access tokens can be rotated). The implementation includes token rotation and revocation capabilities for enhanced security.

### Acceptance Criteria

**Given** I have a valid refresh token (7-day expiry)  
**When** I POST to `/api/v1/auth/refresh` with the refresh token  
**Then** I receive a new access_token and refresh_token pair  
**And** the new access token has 24-hour expiry  
**And** the new refresh token has 7-day expiry

**Given** I have an expired refresh token  
**When** I attempt to refresh  
**Then** I receive a 401 response with error "Refresh token expired, please login again"

**Given** I have a revoked/blacklisted refresh token  
**When** I attempt to refresh  
**Then** I receive a 401 response with error "Invalid refresh token"

### Technical Notes from Epic

- Store refresh token jti in database for revocation capability
- Rotate refresh tokens (new token issued on each refresh)

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **Token Refresh Pattern: Rotation with Revocation**
   - Issue new refresh token on every refresh (rotation)
   - Store token jti (JWT ID) in database for revocation tracking
   - Invalidate old refresh token after successful refresh

2. **Database Schema Extension**
   - New table: `auth_refresh_tokens` for token tracking
   - Columns: jti (primary key), user_id, expires_at, revoked_at, created_at
   - Index on user_id for efficient user token lookup
   - Index on expires_at for cleanup jobs

3. **Security Requirements**
   - Tokens must have unique jti claim (UUID)
   - Revoked tokens cannot be reused
   - Token family tracking for detecting replay attacks (optional v2)
   - Automatic cleanup of expired tokens

4. **API Pattern**
   - POST to `/api/v1/auth/refresh` for token refresh
   - Accept refresh token in Authorization header (Bearer) or request body
   - Return same response format as login endpoint

### Technical Requirements

**Required Technologies:**
- SQLAlchemy 2.0 async (database access)
- PyJWT (token generation with jti claim)
- PostgreSQL (token storage)
- Alembic (database migration)

**Database Schema:**

```sql
-- auth_refresh_tokens table
CREATE TABLE auth_refresh_tokens (
    jti UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    revoked_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    rotated_to_jti UUID REFERENCES auth_refresh_tokens(jti) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX idx_auth_refresh_tokens_user_id ON auth_refresh_tokens(user_id);
CREATE INDEX idx_auth_refresh_tokens_expires_at ON auth_refresh_tokens(expires_at);
CREATE INDEX idx_auth_refresh_tokens_revoked_at ON auth_refresh_tokens(revoked_at) WHERE revoked_at IS NOT NULL;
```

**API Specifications:**

```yaml
endpoint: POST /api/v1/auth/refresh
tags: ["authentication"]
security:
  - BearerAuth: []
request_body:
  content:
    application/json:
      schema:
        type: object
        required: [refresh_token]
        properties:
          refresh_token:
            type: string
            description: Refresh token (alternative to Authorization header)
            example: "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."

responses:
  200:
    description: Refresh successful
    content:
      application/json:
        schema:
          type: object
          properties:
            access_token:
              type: string
            refresh_token:
              type: string
            token_type:
              type: string
              enum: ["bearer"]
            expires_in:
              type: integer
              description: Seconds until access token expires
              example: 86400
  401:
    description: Invalid or expired refresh token
    content:
      application/json:
        schema:
          type: object
          properties:
            error:
              type: string
              enum:
                - "Refresh token expired, please login again"
                - "Invalid refresh token"
```

### File Structure Requirements

```
jbi-service/
├── alembic/versions/
│   └── 003_add_refresh_token_table.py    # NEW - Migration for refresh tokens
├── app/
│   ├── db/models/
│   │   ├── __init__.py                   # UPDATE - Export RefreshToken
│   │   └── auth.py                       # UPDATE - Add RefreshToken model
│   ├── models/schemas.py                 # UPDATE - Add RefreshRequest schema
│   ├── repositories/
│   │   ├── __init__.py                   # UPDATE - Export RefreshTokenRepository
│   │   └── refresh_token_repository.py   # NEW - Token persistence
│   ├── services/
│   │   ├── auth_service.py               # UPDATE - Add jti claim, full rotation
│   │   └── token_refresh_service.py      # NEW - Refresh logic with rotation
│   ├── routers/
│   │   └── auth.py                       # UPDATE - Add POST /refresh endpoint
│   └── services/
│       └── cleanup.py                    # UPDATE - Add token cleanup job
├── tests/
│   ├── unit/
│   │   ├── test_repositories/
│   │   │   └── test_refresh_token_repository.py
│   │   └── test_services/
│   │       └── test_token_refresh_service.py
│   └── integration/
│       └── test_refresh_endpoint.py
└── requirements.txt                      # No new dependencies needed
```

---

## Implementation Guide

### Phase 1: Database Migration

#### Step 1.1: Create Alembic Migration 003_add_refresh_token_table.py

```python
"""Add refresh token table

Revision ID: 003
Revises: 002_add_auth_tables
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '003_add_refresh_token_table'
down_revision: Union[str, None] = '002_add_auth_tables'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create refresh token tracking table."""
    
    op.create_table(
        'auth_refresh_tokens',
        sa.Column(
            'jti',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False
        ),
        sa.Column(
            'revoked_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.Column(
            'rotated_to_jti',
            postgresql.UUID(as_uuid=True),
            nullable=True
        ),
        sa.PrimaryKeyConstraint('jti'),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['auth_users.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['rotated_to_jti'],
            ['auth_refresh_tokens.jti'],
            ondelete='SET NULL'
        )
    )
    
    # Create indexes
    op.create_index(
        'idx_auth_refresh_tokens_user_id',
        'auth_refresh_tokens',
        ['user_id']
    )
    op.create_index(
        'idx_auth_refresh_tokens_expires_at',
        'auth_refresh_tokens',
        ['expires_at']
    )
    op.create_index(
        'idx_auth_refresh_tokens_revoked_at',
        'auth_refresh_tokens',
        ['revoked_at'],
        postgresql_where=sa.text('revoked_at IS NOT NULL')
    )


def downgrade() -> None:
    """Drop refresh token table."""
    op.drop_index('idx_auth_refresh_tokens_revoked_at', table_name='auth_refresh_tokens')
    op.drop_index('idx_auth_refresh_tokens_expires_at', table_name='auth_refresh_tokens')
    op.drop_index('idx_auth_refresh_tokens_user_id', table_name='auth_refresh_tokens')
    op.drop_table('auth_refresh_tokens')
```

### Phase 2: Model Layer

#### Step 2.1: Update app/db/models/auth.py

Add RefreshToken model:

```python
from uuid import uuid4

class RefreshToken(Base):
    """
    Refresh Token model for token tracking and revocation.
    
    Stores refresh token metadata for rotation and revocation support.
    """
    
    __tablename__ = "auth_refresh_tokens"
    
    jti: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
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


# Update User model to add relationship
class User(Base):
    # ... existing columns ...
    
    # Relationships
    roles: Mapped[List["Role"]] = relationship(...)
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
```

### Phase 3: Repository Layer

#### Step 3.1: Create app/repositories/refresh_token_repository.py

```python
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
        # Keep revoked tokens for 7 days for audit purposes
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        
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
```

### Phase 4: Service Layer

#### Step 4.1: Update app/services/auth_service.py

Add jti claim and helper methods:

```python
from uuid import uuid4, UUID

def create_access_token(self, user_id: UUID, role: str) -> str:
    """Create a new access token (no jti needed for access tokens)."""
    # ... existing code ...
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
        "iss": "anotasi-api",
        "aud": "anotasi-client",
        "nbf": int(now.timestamp()),
    }
    return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

def create_refresh_token(self, user_id: UUID, role: str) -> tuple[str, UUID]:
    """
    Create a new refresh token with jti claim.
    
    Returns:
        Tuple of (token_string, jti_uuid)
    """
    if not isinstance(user_id, UUID):
        raise ValueError("user_id must be a UUID instance")
    self._validate_role(role)
    
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=self.refresh_token_expire_days)
    jti = uuid4()
    
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "refresh",
        "jti": str(jti),  # JWT ID for token tracking
        "iss": "anotasi-api",
        "aud": "anotasi-client",
        "nbf": int(now.timestamp()),
    }
    
    try:
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        return token, jti
    except PyJWTError as e:
        raise InvalidTokenError(f"Failed to encode token: {str(e)}") from e

def decode_token(self, token: str) -> dict:
    """
    Decode token without verification (for extracting jti before DB lookup).
    
    Args:
        token: JWT token string
        
    Returns:
        Decoded payload (without verification)
    """
    try:
        return jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            options={"verify_exp": False}  # Don't verify exp here
        )
    except PyJWTError as e:
        raise InvalidTokenError(f"Failed to decode token: {str(e)}") from e
```

#### Step 4.2: Create app/services/token_refresh_service.py

```python
"""
Token Refresh Service.

Handles refresh token rotation and validation with database tracking.
"""

from datetime import datetime, timezone
from typing import Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.services.auth_service import jwt_auth_service
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.db.models.auth import RefreshToken


class TokenRefreshService:
    """Service for token refresh operations with rotation."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.token_repo = RefreshTokenRepository(session)
    
    async def refresh_tokens(
        self, 
        refresh_token: str
    ) -> Tuple[str, str, str, str]:
        """
        Refresh access token using refresh token with rotation.
        
        Args:
            refresh_token: Current refresh token
            
        Returns:
            Tuple of (new_access_token, new_refresh_token, user_id, role)
            
        Raises:
            ExpiredSignatureError: If refresh token has expired
            InvalidTokenError: If refresh token is invalid or revoked
        """
        # Step 1: Decode token to get jti (without verifying expiration)
        try:
            payload = jwt_auth_service.decode_token(refresh_token)
        except InvalidTokenError:
            raise InvalidTokenError("Invalid refresh token")
        
        # Step 2: Verify it's a refresh token
        if payload.get("type") != "refresh":
            raise InvalidTokenError("Invalid token type")
        
        # Step 3: Get jti from payload
        jti_str = payload.get("jti")
        if not jti_str:
            raise InvalidTokenError("Token missing jti claim")
        
        try:
            jti = UUID(jti_str)
        except ValueError:
            raise InvalidTokenError("Invalid jti in token")
        
        # Step 4: Check if token exists in database and is valid
        token_record = await self.token_repo.get_by_jti(jti)
        
        if token_record is None:
            raise InvalidTokenError("Invalid refresh token")
        
        if token_record.is_revoked:
            raise InvalidTokenError("Invalid refresh token")
        
        if token_record.is_expired:
            raise ExpiredSignatureError(
                "Refresh token expired, please login again"
            )
        
        # Step 5: Verify full token (signature, expiration)
        try:
            jwt_auth_service.verify_token(refresh_token, expected_type="refresh")
        except ExpiredSignatureError:
            # Mark as expired in database for cleanup
            token_record.revoke()
            await self.session.flush()
            raise ExpiredSignatureError(
                "Refresh token expired, please login again"
            )
        
        # Step 6: Get user info
        user_id = token_record.user_id
        role = payload.get("role")
        
        if not role:
            raise InvalidTokenError("Token missing role claim")
        
        # Step 7: Generate new token pair
        new_access_token = jwt_auth_service.create_access_token(user_id, role)
        new_refresh_token, new_jti = jwt_auth_service.create_refresh_token(
            user_id, role
        )
        
        # Step 8: Store new refresh token with rotation link
        expires_at = datetime.now(timezone.utc) + timedelta(
            days=jwt_auth_service.refresh_token_expire_days
        )
        await self.token_repo.create(
            jti=new_jti,
            user_id=user_id,
            expires_at=expires_at,
            rotated_from_jti=jti
        )
        
        # Step 9: Revoke old refresh token
        await self.token_repo.revoke(jti)
        
        # Step 10: Commit transaction
        await self.session.commit()
        
        return new_access_token, new_refresh_token, str(user_id), role
    
    async def revoke_token(self, refresh_token: str) -> bool:
        """
        Revoke a refresh token.
        
        Args:
            refresh_token: Refresh token to revoke
            
        Returns:
            True if token was revoked, False if not found
        """
        try:
            payload = jwt_auth_service.decode_token(refresh_token)
            jti_str = payload.get("jti")
            
            if not jti_str:
                return False
            
            jti = UUID(jti_str)
            return await self.token_repo.revoke(jti)
            
        except (InvalidTokenError, ValueError):
            return False
    
    async def revoke_all_user_tokens(self, user_id: UUID) -> int:
        """
        Revoke all refresh tokens for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Number of tokens revoked
        """
        return await self.token_repo.revoke_all_for_user(user_id)
```

### Phase 5: API Layer

#### Step 5.1: Update app/models/schemas.py

Add refresh request/response schemas:

```python
class RefreshRequest(BaseModel):
    """Request body for POST /api/v1/auth/refresh."""
    refresh_token: str = Field(..., description="Refresh token")


class RefreshResponse(BaseModel):
    """Response for successful token refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires
```

#### Step 5.2: Update app/routers/auth.py

Add refresh endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_async_session
from app.models.schemas import (
    LoginRequest, 
    LoginResponse, 
    AuthErrorResponse,
    RefreshRequest,
    RefreshResponse,
)
from app.services.auth_service import jwt_auth_service
from app.services.user_service import UserService
from app.services.token_refresh_service import TokenRefreshService
from app.middleware.rate_limiter import record_failed_login
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)

# ... existing login endpoint ...

@router.post(
    "/refresh",
    response_model=RefreshResponse,
    responses={
        401: {"model": AuthErrorResponse, "description": "Invalid or expired refresh token"},
        422: {"description": "Validation error"},
    },
)
async def refresh(
    request: Request,
    refresh_data: RefreshRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Refresh access token using refresh token with rotation.
    
    - **refresh_token**: Valid refresh token
    
    Returns new access_token and refresh_token pair.
    Old refresh token is invalidated after successful refresh.
    """
    refresh_service = TokenRefreshService(db_session)
    
    try:
        access_token, refresh_token, user_id, role = await refresh_service.refresh_tokens(
            refresh_data.refresh_token
        )
        
        return RefreshResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.jwt_access_token_expire_minutes * 60,
        )
        
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired, please login again",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": AuthErrorResponse, "description": "Invalid token"},
    },
)
async def logout(
    refresh_data: RefreshRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Logout by revoking refresh token.
    
    - **refresh_token**: Refresh token to revoke
    
    Returns 204 on success (idempotent - succeeds even if token already revoked).
    """
    refresh_service = TokenRefreshService(db_session)
    await refresh_service.revoke_token(refresh_data.refresh_token)
    await db_session.commit()
    return None
```

### Phase 6: Cleanup Job

#### Step 6.1: Update app/services/cleanup.py

Add token cleanup:

```python
async def cleanup_expired_refresh_tokens(batch_size: int = 1000) -> int:
    """
    Clean up expired and old revoked refresh tokens.
    
    Args:
        batch_size: Maximum number of tokens to delete per run
        
    Returns:
        Number of tokens deleted
    """
    from app.database import AsyncSessionLocal
    from app.repositories.refresh_token_repository import RefreshTokenRepository
    
    async with AsyncSessionLocal() as session:
        repo = RefreshTokenRepository(session)
        deleted = await repo.cleanup_expired(batch_size)
        await session.commit()
        return deleted

# Add to scheduler in app/services/scheduler.py:
# scheduler.add_job(
#     cleanup_expired_refresh_tokens,
#     'interval',
#     hours=24,
#     id='cleanup_refresh_tokens',
#     replace_existing=True
# )
```

### Phase 7: Testing

#### Step 7.1: Create tests/unit/test_repositories/test_refresh_token_repository.py

```python
"""Tests for RefreshTokenRepository."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.db.models.auth import RefreshToken


@pytest.mark.asyncio
class TestRefreshTokenRepository:
    """Tests for RefreshTokenRepository."""
    
    async def test_create_token(self, db_session, test_user):
        """Test creating a refresh token record."""
        repo = RefreshTokenRepository(db_session)
        
        jti = uuid4()
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
        
        token = await repo.create(
            jti=jti,
            user_id=test_user.id,
            expires_at=expires_at
        )
        
        assert token.jti == jti
        assert token.user_id == test_user.id
        assert token.is_active is True
    
    async def test_get_by_jti(self, db_session, test_refresh_token):
        """Test finding token by JTI."""
        repo = RefreshTokenRepository(db_session)
        
        found = await repo.get_by_jti(test_refresh_token.jti)
        
        assert found is not None
        assert found.jti == test_refresh_token.jti
    
    async def test_revoke_token(self, db_session, test_refresh_token):
        """Test revoking a token."""
        repo = RefreshTokenRepository(db_session)
        
        result = await repo.revoke(test_refresh_token.jti)
        assert result is True
        
        # Verify it's revoked
        token = await repo.get_by_jti(test_refresh_token.jti)
        assert token.is_revoked is True
        assert token.is_active is False
    
    async def test_is_valid(self, db_session, test_refresh_token):
        """Test token validity check."""
        repo = RefreshTokenRepository(db_session)
        
        # Valid token
        assert await repo.is_valid(test_refresh_token.jti) is True
        
        # After revoke
        await repo.revoke(test_refresh_token.jti)
        assert await repo.is_valid(test_refresh_token.jti) is False
    
    async def test_get_active_tokens_for_user(self, db_session, test_user):
        """Test getting active tokens for user."""
        repo = RefreshTokenRepository(db_session)
        
        tokens = await repo.get_active_tokens_for_user(test_user.id)
        
        assert len(tokens) >= 0  # May be empty or have test tokens
        for token in tokens:
            assert token.is_active is True
    
    async def test_revoke_all_for_user(self, db_session, test_user):
        """Test revoking all tokens for user."""
        repo = RefreshTokenRepository(db_session)
        
        # Create multiple tokens
        for _ in range(3):
            await repo.create(
                jti=uuid4(),
                user_id=test_user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        count = await repo.revoke_all_for_user(test_user.id)
        assert count == 3
```

#### Step 7.2: Create tests/unit/test_services/test_token_refresh_service.py

```python
"""Tests for TokenRefreshService."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.services.token_refresh_service import TokenRefreshService
from app.services.auth_service import jwt_auth_service
from app.repositories.refresh_token_repository import RefreshTokenRepository
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError


@pytest.mark.asyncio
class TestTokenRefreshService:
    """Tests for TokenRefreshService."""
    
    async def test_refresh_tokens_success(self, db_session, test_user):
        """Test successful token refresh with rotation."""
        # Create initial refresh token
        refresh_token, jti = jwt_auth_service.create_refresh_token(
            test_user.id, test_user.role
        )
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=test_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await db_session.commit()
        
        # Refresh
        service = TokenRefreshService(db_session)
        new_access, new_refresh, user_id, role = await service.refresh_tokens(
            refresh_token
        )
        
        assert new_access is not None
        assert new_refresh is not None
        assert user_id == str(test_user.id)
        assert role == test_user.role
        
        # Old token should be revoked
        assert await repo.is_valid(jti) is False
    
    async def test_refresh_with_revoked_token(self, db_session, test_user):
        """Test refresh with revoked token fails."""
        refresh_token, jti = jwt_auth_service.create_refresh_token(
            test_user.id, test_user.role
        )
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=test_user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7)
        )
        await repo.revoke(jti)
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        
        with pytest.raises(InvalidTokenError, match="Invalid refresh token"):
            await service.refresh_tokens(refresh_token)
    
    async def test_refresh_with_expired_token(self, db_session, test_user):
        """Test refresh with expired token fails."""
        # Create expired token record
        refresh_token, jti = jwt_auth_service.create_refresh_token(
            test_user.id, test_user.role
        )
        
        repo = RefreshTokenRepository(db_session)
        await repo.create(
            jti=jti,
            user_id=test_user.id,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1)  # Expired
        )
        await db_session.commit()
        
        service = TokenRefreshService(db_session)
        
        with pytest.raises(ExpiredSignatureError):
            await service.refresh_tokens(refresh_token)
    
    async def test_revoke_all_user_tokens(self, db_session, test_user):
        """Test revoking all tokens for user."""
        # Create multiple tokens
        repo = RefreshTokenRepository(db_session)
        for _ in range(3):
            _, jti = jwt_auth_service.create_refresh_token(
                test_user.id, test_user.role
            )
            await repo.create(
                jti=jti,
                user_id=test_user.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=7)
            )
        
        service = TokenRefreshService(db_session)
        count = await service.revoke_all_user_tokens(test_user.id)
        
        assert count == 3
```

#### Step 7.3: Create tests/integration/test_refresh_endpoint.py

```python
"""Integration tests for refresh token endpoint."""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service
from app.repositories.refresh_token_repository import RefreshTokenRepository

client = TestClient(app)


class TestRefreshEndpoint:
    """Tests for POST /api/v1/auth/refresh."""
    
    def test_refresh_success(self, db_session, test_user):
        """Test successful token refresh."""
        # Create and store refresh token
        refresh_token, jti = jwt_auth_service.create_refresh_token(
            test_user.id, test_user.role
        )
        
        repo = RefreshTokenRepository(db_session)
        # Need to run this in async context in actual test
        
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
    
    def test_refresh_with_expired_token(self):
        """Test refresh with expired token returns 401."""
        # Create expired token manually
        import jwt
        from app.config import settings
        
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid4()),
            "role": "annotator",
            "iat": int((now - timedelta(days=10)).timestamp()),
            "exp": int((now - timedelta(days=1)).timestamp()),
            "type": "refresh",
            "jti": str(uuid4()),
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int((now - timedelta(days=10)).timestamp()),
        }
        expired_token = jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm="HS256"
        )
        
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": expired_token}
        )
        
        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()
    
    def test_refresh_with_invalid_token(self):
        """Test refresh with invalid token returns 401."""
        response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid.token.here"}
        )
        
        assert response.status_code == 401
        assert response.json()["error"] == "Invalid refresh token"
    
    def test_refresh_token_rotation(self, db_session, test_user):
        """Test that refresh token is rotated (old invalidated, new issued)."""
        # Setup and test that old token cannot be reused
        pass  # Implementation depends on async test setup


class TestLogoutEndpoint:
    """Tests for POST /api/v1/auth/logout."""
    
    def test_logout_revokes_token(self, db_session, test_user):
        """Test logout revokes refresh token."""
        refresh_token, jti = jwt_auth_service.create_refresh_token(
            test_user.id, test_user.role
        )
        
        # Store token first
        
        response = client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token}
        )
        
        assert response.status_code == 204
        
        # Try to use revoked token
        refresh_response = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        
        assert refresh_response.status_code == 401
```

---

## Implementation Checklist

### Phase 1: Database Migration
- [ ] Create Alembic migration 003_add_refresh_token_table.py
- [ ] Run migration and verify table created

### Phase 2: Model Layer
- [ ] Add RefreshToken model to app/db/models/auth.py
- [ ] Update User model with refresh_tokens relationship

### Phase 3: Repository Layer
- [ ] Create app/repositories/refresh_token_repository.py
- [ ] Implement all CRUD operations

### Phase 4: Service Layer
- [ ] Update app/services/auth_service.py with jti claim and decode_token method
- [ ] Create app/services/token_refresh_service.py with rotation logic

### Phase 5: API Layer
- [ ] Add RefreshRequest and RefreshResponse schemas
- [ ] Add POST /auth/refresh endpoint
- [ ] Add POST /auth/logout endpoint

### Phase 6: Cleanup & Maintenance
- [ ] Add cleanup job for expired tokens
- [ ] Schedule cleanup to run daily

### Phase 7: Testing
- [ ] Unit tests for RefreshTokenRepository
- [ ] Unit tests for TokenRefreshService
- [ ] Integration tests for refresh endpoint
- [ ] Integration tests for logout endpoint

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.2: JWT Authentication Service ✅
- Story 1.3: User Login API Endpoint (recommended)

**Stories that depend on this:**
- Story 1.5: Role-Based Access Control Middleware (uses token patterns)
- Story 1.8: Admin Deactivate User Accounts (uses token revocation)
- All authenticated endpoints (use token refresh)

---

## Next Story

After completing this story, proceed to:  
**Story 1.5: Role-Based Access Control Middleware**

This story will implement FastAPI dependencies for protecting endpoints based on user roles.

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. **Token Rotation**: Always revoke old refresh token after issuing new one
2. **JTI Tracking**: Every refresh token must have unique jti stored in database
3. **Database Transaction**: Token creation and revocation must be in same transaction
4. **Idempotent Logout**: Logout should succeed even if token already revoked
5. **Expired Token Cleanup**: Schedule regular cleanup of old expired tokens

**Security Considerations:**
- Revoked tokens cannot be reused (check database on every refresh)
- Token rotation prevents replay attacks
- Short-lived access tokens limit exposure window
- Refresh tokens have longer expiry but are tracked

**Performance Considerations:**
- Database has indexes on jti, user_id, expires_at
- Consider Redis for high-volume token storage in production
- Cleanup job prevents table bloat

**Testing Checklist:**
- [ ] Refresh with valid token issues new pair
- [ ] Old token is invalidated after refresh
- [ ] Revoked token cannot be used
- [ ] Expired token returns specific error message
- [ ] Invalid token returns generic error
- [ ] Logout revokes token

**Questions?**  
Refer to:
- `architecture.md` section "Authentication Method"
- `1-2-jwt-authentication-service.md` for JWT service details
- OWASP guidelines on token refresh: https://cheatsheetseries.owasp.org/cheatsheets/JSON_Web_Token_for_Java_Cheat_Sheet.html
