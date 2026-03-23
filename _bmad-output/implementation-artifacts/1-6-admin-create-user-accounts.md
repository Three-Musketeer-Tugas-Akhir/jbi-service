---
story_id: "1.6"
story_key: "1-6-admin-create-user-accounts"
epic: 1
status: ready-for-dev
created: "2026-03-19"
last_updated: "2026-03-19"
---

# Story 1.6: Admin - Create User Accounts

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.6  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (2-3 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.2: JWT Authentication Service ✅
- Story 1.3: User Login API Endpoint (recommended)
- Story 1.4: JWT Refresh Token Flow (recommended)
- Story 1.5: Role-Based Access Control Middleware ✅ (uses require_admin)

---

## Story Requirements

### User Story

As an admin,  
I want to create new user accounts with role assignment,  
So that new team members can access the system.

### Business Context

This story implements the user management capability for administrators. It's the first admin-only feature and uses the RBAC middleware from Story 1.5. Admins can create accounts for new annotators and curators, assigning appropriate roles during creation.

### Acceptance Criteria

**Given** I am authenticated as an admin  
**When** I POST to `/api/v1/admin/users` with:
  - email: "newuser@lbi.ac.id"
  - role: "annotator"
  - temporary_password: "TempPass123!"  
**Then** a new user is created in the database  
**And** the password is hashed with bcrypt  
**And** I receive a 201 response with user details (excluding password)  
**And** an invitation email is queued for sending

**Given** I attempt to create a user with an existing email  
**When** I POST to `/api/v1/admin/users`  
**Then** I receive a 409 response with error "User with this email already exists"

**Given** I attempt to create a user without admin role  
**When** I POST to `/api/v1/admin/users`  
**Then** I receive a 403 response with error "Admin access required"

**Given** I create a user with role "curator"  
**When** the user is created  
**Then** the user can immediately login with the temporary password  
**And** the user is assigned to the curator role

### Technical Notes from Epic

- Validate email format
- Validate role is one of allowed values
- Generate secure temporary password if not provided
- Email service integration (can be stubbed for MVP)

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: Admin router handles HTTP
   - **Service Layer**: User creation logic, password generation
   - **Repository Layer**: User persistence
   - **Pipeline Layer**: (Not applicable)

2. **RBAC Protection**
   - Use `require_admin` dependency from Story 1.5
   - All `/admin/*` endpoints protected

3. **Password Security**
   - bcrypt with 12+ rounds
   - Auto-generate secure passwords if not provided
   - Temporary passwords should be strong

4. **Email Service Pattern**
   - Abstract email interface
   - Stub implementation for MVP
   - Queue-based for production

### Technical Requirements

**Required Technologies:**
- FastAPI (API framework)
- SQLAlchemy 2.0 async (database)
- bcrypt (password hashing)
- Pydantic v2 (validation)

**Password Generation:**
```python
import secrets
import string

def generate_temporary_password(length=16):
    """Generate secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(secrets.choice(alphabet) for _ in range(length))
```

**API Specifications:**

```yaml
endpoint: POST /api/v1/admin/users
tags: ["admin"]
security:
  - BearerAuth: []
request_body:
  content:
    application/json:
      schema:
        type: object
        required: [email, role]
        properties:
          email:
            type: string
            format: email
            example: "newuser@lbi.ac.id"
          role:
            type: string
            enum: ["admin", "annotator", "curator"]
            example: "annotator"
          temporary_password:
            type: string
            minLength: 8
            description: Optional, auto-generated if not provided
            example: "TempPass123!"

responses:
  201:
    description: User created successfully
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
            is_active:
              type: boolean
            created_at:
              type: string
              format: date-time
            temporary_password:
              type: string
              description: Only returned when auto-generated
  403:
    description: Admin access required
  409:
    description: User with email already exists
  422:
    description: Validation error
```

### File Structure Requirements

```
jbi-service/
├── app/
│   ├── models/
│   │   └── schemas.py               # UPDATE - Add user creation schemas
│   ├── routers/
│   │   ├── __init__.py              # UPDATE - Export admin router
│   │   └── admin.py                 # NEW - Admin routes
│   ├── services/
│   │   ├── user_service.py          # UPDATE - Add create_user method
│   │   └── email_service.py         # NEW - Email service interface
│   ├── repositories/
│   │   └── user_repository.py       # UPDATE - Add create method
│   └── utils/
│       └── password.py              # NEW - Password generation utilities
├── tests/
│   ├── unit/
│   │   ├── test_services/
│   │   │   └── test_user_service.py # UPDATE
│   │   └── test_utils/
│   │       └── test_password.py     # NEW
│   └── integration/
│       └── test_admin_endpoints.py  # NEW
└── docs/
    └── admin-api-guide.md           # NEW
```

---

## Implementation Guide

### Phase 1: Utilities

#### Step 1.1: Create app/utils/__init__.py

```python
"""Utility functions."""

from app.utils.password import generate_temporary_password

__all__ = ["generate_temporary_password"]
```

#### Step 1.2: Create app/utils/password.py

```python
"""
Password utilities.

Functions for secure password generation and validation.
"""

import secrets
import string
import re


def generate_temporary_password(length: int = 16) -> str:
    """
    Generate a secure temporary password.
    
    Generates a random password with:
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    
    Args:
        length: Password length (default 16, minimum 12)
        
    Returns:
        Generated password string
        
    Raises:
        ValueError: If length is less than 12
    """
    if length < 12:
        raise ValueError("Password length must be at least 12 characters")
    
    # Character sets
    uppercase = string.ascii_uppercase
    lowercase = string.ascii_lowercase
    digits = string.digits
    special = "!@#$%^&*"
    
    # Ensure at least one of each required type
    password = [
        secrets.choice(uppercase),
        secrets.choice(lowercase),
        secrets.choice(digits),
        secrets.choice(special),
    ]
    
    # Fill remaining with all character types
    all_chars = uppercase + lowercase + digits + special
    for _ in range(length - 4):
        password.append(secrets.choice(all_chars))
    
    # Shuffle to randomize positions
    secrets.SystemRandom().shuffle(password)
    
    return ''.join(password)


def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate password strength.
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    return True, ""
```

### Phase 2: Email Service

#### Step 2.1: Create app/services/email_service.py

```python
"""
Email Service.

Abstract email service with stub and SMTP implementations.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService(ABC):
    """Abstract base class for email services."""
    
    @abstractmethod
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """
        Send user invitation email.
        
        Args:
            to_email: Recipient email address
            temporary_password: Temporary password for login
            role: Assigned role
            
        Returns:
            True if email queued/sent successfully
        """
        pass


class StubEmailService(EmailService):
    """
    Stub email service for development/MVP.
    
    Logs emails instead of sending them.
    """
    
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """Log invitation instead of sending."""
        logger.info(
            "[STUB EMAIL] Invitation to %s - Role: %s - Temp Password: %s",
            to_email,
            role,
            temporary_password
        )
        return True


class SmtpEmailService(EmailService):
    """
    SMTP email service for production.
    
    Sends actual emails via SMTP.
    """
    
    def __init__(self):
        """Initialize SMTP configuration."""
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email
    
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """Send actual invitation email via SMTP."""
        # Implementation for production
        # This is a placeholder - implement with aiosmtplib or similar
        logger.info("Sending email to %s via SMTP", to_email)
        # TODO: Implement actual SMTP sending
        return True


# Factory function to get email service
def get_email_service() -> EmailService:
    """
    Get email service instance based on configuration.
    
    Returns:
        EmailService instance
    """
    if settings.environment == "production":
        return SmtpEmailService()
    return StubEmailService()


# Singleton instance
email_service = get_email_service()
```

#### Step 2.2: Update app/config.py

Add email configuration:

```python
# --- Email Configuration ---
smtp_host: str = "localhost"
smtp_port: int = 587
smtp_user: str = ""
smtp_password: str = ""
from_email: str = "noreply@anotasi.lbi.ac.id"
```

### Phase 3: Repository Layer

#### Step 3.1: Update app/repositories/user_repository.py

Add create method:

```python
async def create(
    self,
    email: str,
    password_hash: str,
    role: str,
    is_active: bool = True
) -> User:
    """
    Create a new user.
    
    Args:
        email: User email address
        password_hash: Bcrypt password hash
        role: User role
        is_active: Whether account is active
        
    Returns:
        Created User instance
        
    Raises:
        IntegrityError: If email already exists
    """
    user = User(
        email=email.lower().strip(),
        password_hash=password_hash,
        role=role,
        is_active=is_active
    )
    
    self.session.add(user)
    await self.session.flush()
    await self.session.refresh(user)
    
    return user


async def exists_by_email(self, email: str) -> bool:
    """
    Check if user with email exists.
    
    Args:
        email: Email to check
        
    Returns:
        True if user exists, False otherwise
    """
    stmt = select(User.id).where(
        func.lower(User.email) == email.lower().strip()
    )
    result = await self.session.execute(stmt)
    return result.scalar_one_or_none() is not None
```

### Phase 4: Service Layer

#### Step 4.1: Update app/services/user_service.py

Add create_user method:

```python
from typing import Tuple
from uuid import UUID

from app.utils.password import generate_temporary_password, validate_password_strength
from app.services.email_service import email_service


class UserService:
    """Service for user operations."""
    
    # ... existing methods ...
    
    async def create_user(
        self,
        email: str,
        role: str,
        temporary_password: Optional[str] = None
    ) -> Tuple[User, str, bool]:
        """
        Create a new user account.
        
        Args:
            email: User email address
            role: User role (admin, annotator, curator)
            temporary_password: Optional temporary password (auto-generated if None)
            
        Returns:
            Tuple of (created_user, password_used, password_was_generated)
            
        Raises:
            ValueError: If validation fails
            IntegrityError: If email already exists
        """
        # Validate email
        if not email or '@' not in email:
            raise ValueError("Invalid email address")
        
        # Normalize email
        email = email.lower().strip()
        
        # Check if email already exists
        if await self.repository.exists_by_email(email):
            raise ValueError("User with this email already exists")
        
        # Validate role
        allowed_roles = {"admin", "annotator", "curator"}
        if role not in allowed_roles:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(allowed_roles)}")
        
        # Generate or validate password
        password_was_generated = temporary_password is None
        if password_was_generated:
            temporary_password = generate_temporary_password()
        else:
            is_valid, error = validate_password_strength(temporary_password)
            if not is_valid:
                raise ValueError(f"Password validation failed: {error}")
        
        # Hash password
        password_hash = self.hash_password(temporary_password)
        
        # Create user
        user = await self.repository.create(
            email=email,
            password_hash=password_hash,
            role=role,
            is_active=True
        )
        
        # Send invitation email
        await email_service.send_user_invitation(
            to_email=email,
            temporary_password=temporary_password,
            role=role
        )
        
        await self.session.commit()
        
        return user, temporary_password, password_was_generated
```

### Phase 5: API Layer

#### Step 5.1: Update app/models/schemas.py

Add user creation schemas:

```python
from pydantic import EmailStr, Field
from uuid import UUID


class UserCreateRequest(BaseModel):
    """Request body for POST /api/v1/admin/users."""
    email: EmailStr
    role: str = Field(..., pattern="^(admin|annotator|curator)$")
    temporary_password: Optional[str] = Field(
        default=None,
        min_length=8,
        description="Temporary password (auto-generated if not provided)"
    )


class UserCreateResponse(BaseModel):
    """Response for successful user creation."""
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    temporary_password: Optional[str] = Field(
        default=None,
        description="Only returned when password was auto-generated"
    )


class UserResponse(BaseModel):
    """Generic user response (no sensitive data)."""
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
```

#### Step 5.2: Create app/routers/admin.py

```python
"""
Admin Router.

Administrative endpoints for user management.
All endpoints require admin role.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_async_session
from app.models.schemas import (
    UserCreateRequest,
    UserCreateResponse,
    AuthErrorResponse,
)
from app.dependencies import require_admin, CurrentUser
from app.services.user_service import UserService

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post(
    "/users",
    response_model=UserCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        409: {"description": "User already exists"},
        422: {"description": "Validation error"},
    },
)
async def create_user(
    user_data: UserCreateRequest,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Create a new user account (Admin only).
    
    - **email**: User email address (must be unique)
    - **role**: User role (admin, annotator, curator)
    - **temporary_password**: Optional temporary password (auto-generated if not provided)
    
    Returns created user details. If password was auto-generated, it's included in response.
    An invitation email is sent to the new user.
    """
    user_service = UserService(db_session)
    
    try:
        user, password, was_generated = await user_service.create_user(
            email=user_data.email,
            role=user_data.role,
            temporary_password=user_data.temporary_password
        )
        
        return UserCreateResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            created_at=user.created_at,
            temporary_password=password if was_generated else None
        )
        
    except ValueError as e:
        error_msg = str(e)
        
        # Check if it's a duplicate email error
        if "already exists" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User with this email already exists"
            )
        
        # Other validation errors
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg
        )
    
    except IntegrityError:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists"
        )
```

#### Step 5.3: Update app/routers/__init__.py

```python
"""API Routers."""

from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router

__all__ = ["admin_router", "auth_router", "health_router", "jobs_router"]
```

#### Step 5.4: Update app/main.py

Register admin router:

```python
from app.routers import admin, auth, health, jobs

# ... existing code ...

app.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(auth.router, prefix=settings.api_v1_prefix, tags=["authentication"])
app.include_router(admin.router, prefix=settings.api_v1_prefix, tags=["admin"])
app.include_router(jobs.router, prefix=settings.api_v1_prefix, tags=["jobs"])
```

### Phase 6: Testing

#### Step 6.1: Create tests/unit/test_utils/test_password.py

```python
"""Tests for password utilities."""

import pytest
import re

from app.utils.password import (
    generate_temporary_password,
    validate_password_strength
)


class TestGenerateTemporaryPassword:
    """Tests for generate_temporary_password."""
    
    def test_generates_password_of_specified_length(self):
        """Test password is generated with correct length."""
        password = generate_temporary_password(16)
        assert len(password) == 16
    
    def test_generates_different_passwords(self):
        """Test each generated password is unique."""
        passwords = {generate_temporary_password() for _ in range(10)}
        assert len(passwords) == 10  # All unique
    
    def test_includes_required_character_types(self):
        """Test password includes uppercase, lowercase, digit, special."""
        password = generate_temporary_password()
        
        assert any(c.isupper() for c in password), "Missing uppercase"
        assert any(c.islower() for c in password), "Missing lowercase"
        assert any(c.isdigit() for c in password), "Missing digit"
        assert any(c in "!@#$%^&*" for c in password), "Missing special"
    
    def test_raises_error_for_short_length(self):
        """Test error raised for length < 12."""
        with pytest.raises(ValueError, match="at least 12"):
            generate_temporary_password(8)


class TestValidatePasswordStrength:
    """Tests for validate_password_strength."""
    
    def test_valid_password(self):
        """Test valid password passes."""
        is_valid, error = validate_password_strength("ValidPass123")
        assert is_valid is True
        assert error == ""
    
    def test_too_short(self):
        """Test password too short fails."""
        is_valid, error = validate_password_strength("Short1")
        assert is_valid is False
        assert "at least 8" in error
    
    def test_missing_uppercase(self):
        """Test password without uppercase fails."""
        is_valid, error = validate_password_strength("lowercase123")
        assert is_valid is False
        assert "uppercase" in error
    
    def test_missing_lowercase(self):
        """Test password without lowercase fails."""
        is_valid, error = validate_password_strength("UPPERCASE123")
        assert is_valid is False
        assert "lowercase" in error
    
    def test_missing_digit(self):
        """Test password without digit fails."""
        is_valid, error = validate_password_strength("NoDigitsHere")
        assert is_valid is False
        assert "digit" in error
```

#### Step 6.2: Update tests/unit/test_services/test_user_service.py

```python
"""Tests for UserService create_user."""

import pytest
from uuid import uuid4


@pytest.mark.asyncio
class TestUserServiceCreateUser:
    """Tests for UserService.create_user."""
    
    async def test_create_user_success(self, db_session):
        """Test successful user creation."""
        service = UserService(db_session)
        
        user, password, was_generated = await service.create_user(
            email="newuser@example.com",
            role="annotator"
        )
        
        assert user.email == "newuser@example.com"
        assert user.role == "annotator"
        assert user.is_active is True
        assert password is not None
        assert was_generated is True
    
    async def test_create_user_with_provided_password(self, db_session):
        """Test user creation with provided password."""
        service = UserService(db_session)
        
        user, password, was_generated = await service.create_user(
            email="newuser@example.com",
            role="annotator",
            temporary_password="MyPass123!"
        )
        
        assert password == "MyPass123!"
        assert was_generated is False
    
    async def test_create_user_duplicate_email(self, db_session, test_user):
        """Test error on duplicate email."""
        service = UserService(db_session)
        
        with pytest.raises(ValueError, match="already exists"):
            await service.create_user(
                email=test_user.email,
                role="annotator"
            )
    
    async def test_create_user_invalid_email(self, db_session):
        """Test error on invalid email."""
        service = UserService(db_session)
        
        with pytest.raises(ValueError, match="Invalid email"):
            await service.create_user(
                email="not-an-email",
                role="annotator"
            )
    
    async def test_create_user_invalid_role(self, db_session):
        """Test error on invalid role."""
        service = UserService(db_session)
        
        with pytest.raises(ValueError, match="Invalid role"):
            await service.create_user(
                email="user@example.com",
                role="hacker"
            )
    
    async def test_create_user_weak_password(self, db_session):
        """Test error on weak provided password."""
        service = UserService(db_session)
        
        with pytest.raises(ValueError, match="Password validation"):
            await service.create_user(
                email="user@example.com",
                role="annotator",
                temporary_password="weak"
            )
```

#### Step 6.3: Create tests/integration/test_admin_endpoints.py

```python
"""Integration tests for admin endpoints."""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service

client = TestClient(app)


def create_admin_token():
    """Helper to create admin token."""
    return jwt_auth_service.create_access_token(uuid4(), "admin")


def create_annotator_token():
    """Helper to create annotator token."""
    return jwt_auth_service.create_access_token(uuid4(), "annotator")


class TestCreateUserEndpoint:
    """Tests for POST /api/v1/admin/users."""
    
    def test_create_user_success(self):
        """Test successful user creation by admin."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "newuser@example.com",
                "role": "annotator"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert data["role"] == "annotator"
        assert "temporary_password" in data  # Auto-generated
        assert "id" in data
    
    def test_create_user_with_password(self):
        """Test user creation with provided password."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "newuser2@example.com",
                "role": "curator",
                "temporary_password": "SecurePass123!"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        # Password not returned when provided
        assert data.get("temporary_password") is None
    
    def test_create_user_non_admin_forbidden(self):
        """Test 403 when non-admin tries to create user."""
        token = create_annotator_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "newuser@example.com",
                "role": "annotator"
            }
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
    
    def test_create_user_duplicate_email(self, db_session, test_user):
        """Test 409 when creating user with existing email."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": test_user.email,
                "role": "annotator"
            }
        )
        
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
    
    def test_create_user_invalid_email(self):
        """Test 422 when email is invalid."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "not-an-email",
                "role": "annotator"
            }
        )
        
        assert response.status_code == 422
    
    def test_create_user_invalid_role(self):
        """Test 422 when role is invalid."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "user@example.com",
                "role": "superadmin"
            }
        )
        
        assert response.status_code == 422
```

### Phase 7: Documentation

#### Step 7.1: Create docs/admin-api-guide.md

```markdown
# Admin API Guide

This guide covers the administrative API endpoints for user management.

## Authentication

All admin endpoints require admin role:

```bash
Authorization: Bearer <admin-jwt-token>
```

## Endpoints

### Create User

Create a new user account.

```bash
POST /api/v1/admin/users
```

**Request Body:**

```json
{
  "email": "newuser@lbi.ac.id",
  "role": "annotator",
  "temporary_password": "OptionalPass123!"
}
```

**Response (201 Created):**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "newuser@lbi.ac.id",
  "role": "annotator",
  "is_active": true,
  "created_at": "2026-03-19T10:30:00Z",
  "temporary_password": "AutoGeneratedPass123!"
}
```

**Notes:**
- `temporary_password` is optional - auto-generated if not provided
- Password is only returned when auto-generated
- Invitation email is sent to new user
- Roles: `admin`, `annotator`, `curator`

**Errors:**

- `403 Forbidden` - Non-admin access
- `409 Conflict` - Email already exists
- `422 Validation Error` - Invalid email or role

## Password Generation

When not providing a password, the system generates a secure temporary password:
- Minimum 16 characters
- Includes uppercase, lowercase, digits, and special characters
- Cryptographically secure random generation

## Email Notifications

Currently using stub email service (logs only). Production should configure SMTP.

## Testing

Create admin token for testing:

```python
from app.services.auth_service import jwt_auth_service

token = jwt_auth_service.create_access_token(user_id, "admin")
```
```

---

## Implementation Checklist

### Phase 1: Utilities
- [ ] Create `app/utils/__init__.py`
- [ ] Create `app/utils/password.py` with generation and validation

### Phase 2: Email Service
- [ ] Create `app/services/email_service.py` with stub and SMTP implementations
- [ ] Update `app/config.py` with email settings

### Phase 3: Repository Layer
- [ ] Add `create()` method to UserRepository
- [ ] Add `exists_by_email()` method to UserRepository

### Phase 4: Service Layer
- [ ] Add `create_user()` method to UserService
- [ ] Integrate email service

### Phase 5: API Layer
- [ ] Add user creation schemas to `app/models/schemas.py`
- [ ] Create `app/routers/admin.py`
- [ ] Update `app/routers/__init__.py`
- [ ] Register router in `app/main.py`

### Phase 6: Testing
- [ ] Unit tests for password utilities
- [ ] Unit tests for UserService.create_user
- [ ] Integration tests for admin endpoints

### Phase 7: Documentation
- [ ] Create `docs/admin-api-guide.md`

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.2: JWT Authentication Service ✅
- Story 1.3: User Login API Endpoint (recommended)
- Story 1.4: JWT Refresh Token Flow (recommended)
- Story 1.5: Role-Based Access Control Middleware ✅

**Stories that depend on this:**
- Story 1.7: Admin Modify User Roles (uses same admin router)
- Story 1.8: Admin Deactivate User Accounts (uses same admin router)
- Story 1.9: Admin List and View Users (uses same admin router)

---

## Next Story

After completing this story, proceed to:  
**Story 1.7: Admin - Modify User Roles**

This story will add PUT /api/v1/admin/users/{user_id}/role endpoint.

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. **Admin Only**: Always use `require_admin` dependency
2. **Password Security**: Never return password hash in responses
3. **Email Case**: Store and compare emails in lowercase
4. **Transaction**: User creation and email sending should be in same transaction
5. **Duplicate Check**: Check email existence before attempting insert

**Common Mistakes to Avoid:**
- ❌ Returning password hash in API response
- ❌ Not lowercasing email before storage
- ❌ Forgetting to send invitation email
- ❌ Not validating role against allowed set
- ❌ Missing 409 conflict response for duplicates

**Security Checklist:**
- [ ] Endpoint protected with require_admin
- [ ] Password hashed with bcrypt before storage
- [ ] Password not returned in response (unless auto-generated)
- [ ] Email uniqueness enforced
- [ ] Input validation on all fields

**Testing Checklist:**
- [ ] Admin can create user
- [ ] Non-admin gets 403
- [ ] Duplicate email returns 409
- [ ] Invalid email returns 422
- [ ] Invalid role returns 422
- [ ] Weak password returns 422
- [ ] Auto-generated password returned in response
- [ ] Provided password not returned

**Questions?**  
Refer to:
- Architecture: "Authorization Pattern" for RBAC
- Story 1.5 docs for dependency usage
- FastAPI docs for response models
