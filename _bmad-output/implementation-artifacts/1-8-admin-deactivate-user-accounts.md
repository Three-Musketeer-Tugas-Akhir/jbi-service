---
story_id: "1.8"
story_key: "1-8-admin-deactivate-user-accounts"
epic: 1
status: ready-for-dev
created: "2026-03-19"
last_updated: "2026-03-19"
---

# Story 1.8: Admin - Deactivate User Accounts

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.8  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.3: User Login API Endpoint (uses login logic) ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts (same admin router) ✅
- Story 1.7: Admin Modify User Roles (uses audit logging) ✅

---

## Story Requirements

### User Story

As an admin,  
I want to deactivate user accounts,  
So that former employees can no longer access the system.

### Business Context

This story implements the user deactivation feature for removing system access from former team members. It uses soft delete (is_active flag) to preserve audit history and data integrity. Deactivated users cannot login, but their historical actions remain in the system for compliance.

### Acceptance Criteria

**Given** I am authenticated as an admin  
**And** a user exists with id "uuid-123" and is_active: true  
**When** I DELETE to `/api/v1/admin/users/uuid-123`  
**Then** the user's is_active flag is set to false (soft delete)  
**And** I receive a 200 response confirming deactivation  
**And** an audit log entry is created

**Given** I attempt to deactivate my own account  
**When** I DELETE to my own user endpoint  
**Then** I receive a 400 response with error "Cannot deactivate your own account"

**Given** a deactivated user attempts to login  
**When** they POST to `/api/v1/auth/login`  
**Then** they receive a 401 response with error "Account is deactivated"

**Given** I am an admin  
**When** I list users  
**Then** I can see both active and inactive users  
**And** there is a filter to show only active/inactive

### Technical Notes from Epic

- Use soft delete (is_active flag) not hard delete
- Preserve audit history for deactivated users
- Consider revoking all refresh tokens on deactivation

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: Admin router DELETE endpoint
   - **Service Layer**: Deactivation logic, token revocation
   - **Repository Layer**: User update operations
   - **Pipeline Layer**: (Not applicable)

2. **Soft Delete Pattern**
   - Set `is_active = false` instead of DELETE
   - Preserve all user data and relationships
   - Maintain audit history integrity
   - Filter active users in queries where appropriate

3. **Security Requirements**
   - Deactivated users cannot login
   - Existing tokens should be invalidated (optional for MVP)
   - Self-deactivation prevention
   - Admin-only access

4. **Token Revocation Strategy**
   - Option A: Revoke all refresh tokens on deactivation
   - Option B: Check is_active on token refresh (MVP)
   - Option C: Block at middleware level (comprehensive)

### Technical Requirements

**Soft Delete Implementation:**
```python
# Instead of:
await session.delete(user)

# Use:
user.is_active = False
await session.flush()
```

**Login Check Update:**
```python
# In authenticate() method:
if not user.is_active:
    return False, None  # Account deactivated
```

**API Specifications:**

```yaml
endpoint: DELETE /api/v1/admin/users/{user_id}
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

responses:
  200:
    description: User deactivated successfully
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
            is_active:
              type: boolean
              example: false
            deactivated_at:
              type: string
              format: date-time
            message:
              type: string
              example: "User deactivated successfully"
  400:
    description: Cannot deactivate own account
  403:
    description: Admin access required
  404:
    description: User not found
```

### File Structure Requirements

```
jbi-service/
├── app/
│   ├── models/
│   │   └── schemas.py              # UPDATE - Add deactivation schemas
│   ├── repositories/
│   │   ├── refresh_token_repository.py  # UPDATE - Add revoke_all_for_user
│   │   └── user_repository.py      # UPDATE - Add deactivate method
│   ├── services/
│   │   ├── audit_service.py        # UPDATE - Add deactivation logging
│   │   ├── auth_service.py         # No changes (already handles tokens)
│   │   └── user_service.py         # UPDATE - Add deactivate method
│   └── routers/
│       └── admin.py                # UPDATE - Add DELETE endpoint
├── tests/
│   ├── unit/
│   │   └── test_services/
│   │       └── test_user_service.py  # UPDATE
│   └── integration/
│       └── test_admin_deactivate.py   # NEW
└── docs/
    └── user-lifecycle-guide.md     # NEW
```

---

## Implementation Guide

### Phase 1: Repository Layer

#### Step 1.1: Update app/repositories/user_repository.py

Add deactivation method:

```python
async def deactivate(self, user_id: UUID) -> Optional[User]:
    """
    Deactivate a user account (soft delete).
    
    Args:
        user_id: User UUID to deactivate
        
    Returns:
        Deactivated User instance or None if not found
    """
    user = await self.get_by_id(user_id)
    if user is None:
        return None
    
    if not user.is_active:
        # Already deactivated
        return user
    
    user.is_active = False
    await self.session.flush()
    await self.session.refresh(user)
    
    return user


async def is_active(self, user_id: UUID) -> bool:
    """
    Check if user account is active.
    
    Args:
        user_id: User UUID
        
    Returns:
        True if user exists and is active
    """
    stmt = select(User.is_active).where(User.id == user_id)
    result = await self.session.execute(stmt)
    is_active = result.scalar_one_or_none()
    return is_active if is_active is not None else False
```

#### Step 1.2: Update app/repositories/refresh_token_repository.py

Add revoke all method (if not already from Story 1.4):

```python
async def revoke_all_for_user(self, user_id: UUID) -> int:
    """
    Revoke all active refresh tokens for a user.
    
    Args:
        user_id: User UUID
        
    Returns:
        Number of tokens revoked
    """
    from datetime import datetime, timezone
    
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
```

### Phase 2: Service Layer

#### Step 2.1: Update app/services/audit_service.py

Add deactivation logging:

```python
async def log_user_deactivated(
    self,
    actor_id: UUID,
    target_user_id: UUID,
    email: str,
    ip_address: Optional[str] = None
) -> None:
    """
    Log a user deactivation.
    
    Args:
        actor_id: Admin who deactivated the user
        target_user_id: Deactivated user ID
        email: Email of deactivated user
        ip_address: Request IP address
    """
    from app.db.models.audit import AuditAction
    
    await self.repository.create(
        action=AuditAction.USER_DEACTIVATED,
        resource_type="user",
        actor_id=actor_id,
        resource_id=target_user_id,
        details={"email": email},
        ip_address=ip_address
    )
    logger.info(
        "User deactivated: %s deactivated %s (%s)",
        actor_id, target_user_id, email
    )
```

#### Step 2.2: Update app/services/user_service.py

Add deactivate method:

```python
from app.repositories.refresh_token_repository import RefreshTokenRepository


class UserService:
    """Service for user operations."""
    
    # ... existing methods ...
    
    async def deactivate_user(
        self,
        admin_id: UUID,
        target_user_id: UUID,
        revoke_tokens: bool = True,
        ip_address: Optional[str] = None
    ) -> Optional[User]:
        """
        Deactivate a user account.
        
        Args:
            admin_id: ID of admin performing deactivation
            target_user_id: ID of user to deactivate
            revoke_tokens: Whether to revoke all refresh tokens
            ip_address: Request IP address for audit
            
        Returns:
            Deactivated User or None if not found
            
        Raises:
            ValueError: If trying to deactivate self
        """
        # Prevent self-deactivation
        if str(admin_id) == str(target_user_id):
            raise ValueError("Cannot deactivate your own account")
        
        # Get target user
        user = await self.repository.get_by_id(target_user_id)
        if user is None:
            return None
        
        # Check if already deactivated
        if not user.is_active:
            return user  # Already deactivated, idempotent
        
        # Deactivate user
        user = await self.repository.deactivate(target_user_id)
        
        # Revoke all refresh tokens (optional)
        if revoke_tokens:
            token_repo = RefreshTokenRepository(self.session)
            revoked_count = await token_repo.revoke_all_for_user(target_user_id)
            logger.info(
                "Revoked %d refresh tokens for deactivated user %s",
                revoked_count, target_user_id
            )
        
        # Log audit event
        audit_service = AuditService(self.session)
        await audit_service.log_user_deactivated(
            actor_id=admin_id,
            target_user_id=target_user_id,
            email=user.email,
            ip_address=ip_address
        )
        
        await self.session.commit()
        
        return user
```

#### Step 2.3: Update app/services/user_service.py (authenticate)

Add deactivated check:

```python
async def authenticate(
    self, 
    email: str, 
    password: str
) -> Tuple[bool, Optional[User], Optional[str]]:
    """
    Authenticate user with email and password.
    
    Returns:
        Tuple of (success, user, error_message)
    """
    # Find user by email
    user = await self.repository.get_by_email(email)
    
    # Dummy check for timing attack prevention
    if user is None:
        bcrypt.checkpw(
            password.encode('utf-8'),
            b'$2b$12$' + b'0' * 53
        )
        return False, None, "Invalid credentials"
    
    # Check if user is active
    if not user.is_active:
        return False, None, "Account is deactivated"
    
    # Verify password
    password_bytes = password.encode('utf-8')
    stored_hash = user.password_hash.encode('utf-8')
    
    if bcrypt.checkpw(password_bytes, stored_hash):
        return True, user, None
    
    return False, None, "Invalid credentials"
```

**Note**: Update the login endpoint to handle the new error message format.

### Phase 3: API Layer

#### Step 3.1: Update app/models/schemas.py

Add deactivation schemas:

```python
class UserDeactivateResponse(BaseModel):
    """Response for successful user deactivation."""
    id: UUID
    email: str
    is_active: bool
    deactivated_at: Optional[datetime] = None
    message: str = "User deactivated successfully"


class UserReactivateResponse(BaseModel):
    """Response for successful user reactivation."""
    id: UUID
    email: str
    is_active: bool
    reactivated_at: datetime
    message: str = "User reactivated successfully"
```

#### Step 3.2: Update app/routers/auth.py

Update login to handle deactivated accounts:

```python
@router.post("/login", ...)
async def login(
    request: Request,
    login_data: LoginRequest,
    db_session: AsyncSession = Depends(get_async_session),
):
    """Authenticate user and return JWT tokens."""
    user_service = UserService(db_session)
    success, user, error_msg = await user_service.authenticate(
        login_data.email, 
        login_data.password
    )
    
    if not success or user is None:
        record_failed_login(request)
        
        # Check for specific error message
        if error_msg == "Account is deactivated":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is deactivated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Generate tokens...
```

#### Step 3.3: Update app/routers/admin.py

Add deactivation endpoint:

```python
from fastapi import Request
from app.models.schemas import (
    UserDeactivateResponse,
    UserReactivateResponse,
)


@router.delete(
    "/users/{user_id}",
    response_model=UserDeactivateResponse,
    responses={
        400: {"description": "Cannot deactivate own account"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def deactivate_user(
    user_id: UUID,
    request: Request,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Deactivate a user account (Admin only).
    
    - **user_id**: UUID of user to deactivate
    
    Performs soft delete (sets is_active=false).
    Preserves all user data and audit history.
    Revokes all refresh tokens for the user.
    """
    user_service = UserService(db_session)
    
    # Extract IP for audit
    client_ip = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    
    try:
        user = await user_service.deactivate_user(
            admin_id=current_user.id,
            target_user_id=user_id,
            revoke_tokens=True,
            ip_address=client_ip
        )
        
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserDeactivateResponse(
            id=user.id,
            email=user.email,
            is_active=user.is_active,
            deactivated_at=user.updated_at,  # updated_at reflects deactivation
            message="User deactivated successfully"
        )
        
    except ValueError as e:
        if "Cannot deactivate your own" in str(e):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot deactivate your own account"
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/users/{user_id}/reactivate",
    response_model=UserReactivateResponse,
    responses={
        400: {"description": "User already active"},
        403: {"description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def reactivate_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Reactivate a deactivated user account (Admin only).
    
    - **user_id**: UUID of user to reactivate
    
    Restores account access by setting is_active=true.
    User must reset password before logging in.
    """
    # Implementation similar to deactivate
    # Sets is_active = True
    # Logs audit event
    pass
```

### Phase 4: Testing

#### Step 4.1: Create tests/integration/test_admin_deactivate.py

```python
"""Integration tests for user deactivation."""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service
from app.db.models.auth import User

client = TestClient(app)


def create_token(user_id, role):
    """Helper to create JWT token."""
    return jwt_auth_service.create_access_token(user_id, role)


class TestDeactivateUser:
    """Tests for DELETE /api/v1/admin/users/{id}."""
    
    def test_deactivate_user_success(self, db_session, test_user):
        """Test successful user deactivation."""
        admin_id = uuid4()
        admin_token = create_token(admin_id, "admin")
        
        response = client.delete(
            f"/api/v1/admin/users/{test_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False
        assert data["email"] == test_user.email
        assert "deactivated successfully" in data["message"]
    
    def test_deactivate_self_forbidden(self, db_session):
        """Test admin cannot deactivate own account."""
        admin_id = uuid4()
        admin_token = create_token(admin_id, "admin")
        
        response = client.delete(
            f"/api/v1/admin/users/{admin_id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 400
        assert "Cannot deactivate your own" in response.json()["detail"]
    
    def test_deactivate_non_admin_forbidden(self, db_session, test_user):
        """Test non-admin cannot deactivate users."""
        annotator_id = uuid4()
        annotator_token = create_token(annotator_id, "annotator")
        
        response = client.delete(
            f"/api/v1/admin/users/{test_user.id}",
            headers={"Authorization": f"Bearer {annotator_token}"}
        )
        
        assert response.status_code == 403
    
    def test_deactivate_already_inactive(self, db_session, inactive_user):
        """Test deactivating already inactive user is idempotent."""
        admin_token = create_token(uuid4(), "admin")
        
        response = client.delete(
            f"/api/v1/admin/users/{inactive_user.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        assert response.json()["is_active"] is False
    
    def test_deactivate_nonexistent_user(self, db_session):
        """Test 404 for non-existent user."""
        admin_token = create_token(uuid4(), "admin")
        
        response = client.delete(
            f"/api/v1/admin/users/{uuid4()}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 404


class TestDeactivatedUserLogin:
    """Tests that deactivated users cannot login."""
    
    def test_deactivated_user_cannot_login(self, db_session, inactive_user):
        """Test deactivated user gets 401 on login."""
        # Assuming we know the password
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": inactive_user.email,
                "password": "correct_password"
            }
        )
        
        assert response.status_code == 401
        assert "deactivated" in response.json()["detail"].lower()
    
    def test_active_user_can_login(self, db_session, test_user, plain_password):
        """Test active user can still login."""
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": test_user.email,
                "password": plain_password
            }
        )
        
        assert response.status_code == 200
```

### Phase 5: Documentation

#### Step 5.1: Create docs/user-lifecycle-guide.md

```markdown
# User Lifecycle Guide

This guide covers user account lifecycle management.

## Account States

### Active
- User can login and access system
- All permissions based on role apply
- Default state for new accounts

### Inactive (Deactivated)
- User cannot login
- All refresh tokens revoked
- Historical data preserved
- Can be reactivated by admin

## Deactivation

### When to Deactivate
- Employee leaves organization
- Account compromise suspected
- Temporary suspension needed

### Effects of Deactivation
1. Immediate: User cannot login
2. Token revocation: All refresh tokens invalidated
3. Data preservation: All history retained
4. Audit trail: Deactivation logged

### API

```bash
# Deactivate user
DELETE /api/v1/admin/users/{user_id}
Authorization: Bearer <admin-token>

# Response
{
  "id": "uuid",
  "email": "user@example.com",
  "is_active": false,
  "deactivated_at": "2026-03-19T10:30:00Z",
  "message": "User deactivated successfully"
}
```

## Reactivation

### When to Reactivate
- Employee returns
- Temporary suspension lifted
- Account recovered after investigation

### Effects of Reactivation
1. User can login again
2. Must reset password (recommended)
3. Historical permissions restored
4. Audit trail: Reactivation logged

### API

```bash
# Reactivate user
POST /api/v1/admin/users/{user_id}/reactivate
Authorization: Bearer <admin-token>
```

## Best Practices

1. **Never delete users**: Always use soft delete
2. **Audit everything**: Log all lifecycle events
3. **Review periodically**: Audit inactive accounts
4. **Secure reactivation**: Require password reset

## Soft Delete vs Hard Delete

| Aspect | Soft Delete (is_active) | Hard Delete (DELETE) |
|--------|------------------------|---------------------|
| Data retention | Preserved | Lost |
| Audit trail | Maintained | Broken |
| Referential integrity | Preserved | Risk of FK violations |
| Recovery | Possible | Impossible |
| Compliance | Better | Risky |

We always use soft delete for user accounts.
```

---

## Implementation Checklist

### Phase 1: Repository Layer
- [ ] Add `deactivate()` method to UserRepository
- [ ] Add `is_active()` method to UserRepository
- [ ] Ensure `revoke_all_for_user()` exists in RefreshTokenRepository

### Phase 2: Service Layer
- [ ] Add `log_user_deactivated()` to AuditService
- [ ] Add `deactivate_user()` to UserService
- [ ] Update `authenticate()` to check is_active

### Phase 3: API Layer
- [ ] Add deactivation schemas to app/models/schemas.py
- [ ] Update login endpoint for deactivated account error
- [ ] Add DELETE /admin/users/{id} endpoint
- [ ] Add POST /admin/users/{id}/reactivate endpoint (optional)

### Phase 4: Testing
- [ ] Integration tests for deactivation
- [ ] Tests for deactivated user login
- [ ] Test self-deactivation prevention

### Phase 5: Documentation
- [ ] Create user-lifecycle-guide.md

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.3: User Login API Endpoint ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts ✅
- Story 1.7: Admin Modify User Roles (audit logging) ✅

**Stories that depend on this:**
- Story 1.9: Admin List and View Users (needs is_active filter)

---

## Next Story

After completing this story, proceed to:  
**Story 1.9: Admin - List and View Users**

This story will add GET /api/v1/admin/users with pagination and is_active filter.

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. **Soft Delete Only**: Never hard delete users
2. **Token Revocation**: Revoke refresh tokens on deactivation
3. **Self-Protection**: Prevent self-deactivation
4. **Login Check**: Update authenticate() to check is_active
5. **Idempotent**: Deactivating already inactive user should succeed

**Common Mistakes to Avoid:**
- ❌ Using session.delete() instead of is_active = False
- ❌ Forgetting to revoke refresh tokens
- ❌ Not updating login to check is_active
- ❌ Missing audit log entry
- ❌ Allowing self-deactivation

**Security Checklist:**
- [ ] Soft delete implemented correctly
- [ ] Refresh tokens revoked on deactivation
- [ ] Deactivated users cannot login
- [ ] Self-deactivation prevented
- [ ] Audit log entry created
- [ ] Admin-only access enforced

**Questions?**  
Refer to:
- Story 1.6 and 1.7 for admin endpoint patterns
- Architecture: "Audit Trail" for compliance requirements
