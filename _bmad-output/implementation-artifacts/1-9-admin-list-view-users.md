---
story_id: "1.9"
story_key: "1-9-admin-list-view-users"
epic: 1
status: ready-for-dev
created: "2026-03-19"
last_updated: "2026-03-19"
---

# Story 1.9: Admin - List and View Users

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.9  
**Status:** ready-for-dev  
**Priority:** High  
**Estimated Effort:** Medium (2-3 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts (same admin router) ✅
- Story 1.7: Admin Modify User Roles (same admin router) ✅
- Story 1.8: Admin Deactivate User Accounts (is_active filter) ✅

---

## Story Requirements

### User Story

As an admin,  
I want to view a list of all users and their details,  
So that I can manage the team effectively.

### Business Context

This story completes Epic 1 by providing admin visibility into all user accounts. It enables team management through listing, filtering, and viewing user details. This is the final story for user management functionality before moving to Epic 2 (Video Processing).

### Acceptance Criteria

**Given** I am authenticated as an admin  
**When** I GET `/api/v1/admin/users`  
**Then** I receive a 200 response with paginated user list:  
  - id, email, role, is_active, created_at, last_login  
**And** the list supports pagination (page, page_size params)

**Given** I GET `/api/v1/admin/users` with query param `role=annotator`  
**When** the request is made  
**Then** I receive only users with role "annotator"

**Given** I GET `/api/v1/admin/users` with query param `is_active=false`  
**When** the request is made  
**Then** I receive only deactivated users

**Given** I GET `/api/v1/admin/users/{user_id}`  
**When** the user exists  
**Then** I receive detailed user information including:  
  - All fields from list view  
  - created_at, updated_at timestamps  
  - activity summary (videos annotated, reviews completed)

**Given** I am not an admin  
**When** I attempt to access user list endpoint  
**Then** I receive a 403 response

### Technical Notes from Epic

- Support filtering by role, is_active, created_date
- Support sorting by created_at, last_login
- Default page size: 20, max: 100

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: Admin router list/detail endpoints
   - **Service Layer**: Query building, filtering logic
   - **Repository Layer**: Database queries with pagination
   - **Pipeline Layer**: (Not applicable)

2. **Pagination Pattern**
   - Page-based pagination (page, page_size)
   - Offset-based for simplicity
   - Response includes total count and pagination metadata

3. **Filtering & Sorting**
   - Query parameters for filters
   - Multiple filters can be combined
   - Sort by single field with direction

4. **Response Consistency**
   - List response wrapper with metadata
   - Detail response extends list fields
   - No sensitive data (password_hash excluded)

### Technical Requirements

**Pagination Response Format:**
```json
{
  "items": [...],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "pages": 8,
  "has_next": true,
  "has_prev": false
}
```

**API Specifications:**

```yaml
# List Users
endpoint: GET /api/v1/admin/users
tags: ["admin"]
security:
  - BearerAuth: []
parameters:
  - name: page
    in: query
    schema:
      type: integer
      default: 1
      minimum: 1
  - name: page_size
    in: query
    schema:
      type: integer
      default: 20
      minimum: 1
      maximum: 100
  - name: role
    in: query
    schema:
      type: string
      enum: [admin, annotator, curator]
  - name: is_active
    in: query
    schema:
      type: boolean
  - name: sort_by
    in: query
    schema:
      type: string
      enum: [created_at, email, role]
      default: created_at
  - name: sort_order
    in: query
    schema:
      type: string
      enum: [asc, desc]
      default: desc

responses:
  200:
    description: Paginated list of users
    content:
      application/json:
        schema:
          type: object
          properties:
            items:
              type: array
              items:
                $ref: '#/components/schemas/UserListItem'
            total:
              type: integer
            page:
              type: integer
            page_size:
              type: integer
            pages:
              type: integer
            has_next:
              type: boolean
            has_prev:
              type: boolean

# Get User Detail
endpoint: GET /api/v1/admin/users/{user_id}
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
    description: User details
    content:
      application/json:
        schema:
          $ref: '#/components/schemas/UserDetailResponse'
  404:
    description: User not found
```

### File Structure Requirements

```
jbi-service/
├── app/
│   ├── models/
│   │   └── schemas.py              # UPDATE - Add pagination and user list schemas
│   ├── repositories/
│   │   └── user_repository.py      # UPDATE - Add list and count methods
│   ├── services/
│   │   └── user_service.py         # UPDATE - Add list_users method
│   └── routers/
│       └── admin.py                # UPDATE - Add GET endpoints
├── tests/
│   ├── unit/
│   │   └── test_repositories/
│   │       └── test_user_repository.py  # UPDATE
│   └── integration/
│       └── test_admin_list_users.py    # NEW
└── docs/
    └── admin-user-management-guide.md  # NEW
```

---

## Implementation Guide

### Phase 1: Model & Schema Layer

#### Step 1.1: Update app/models/schemas.py

Add pagination and user list schemas:

```python
from typing import TypeVar, Generic, List
from datetime import datetime
from uuid import UUID

T = TypeVar('T')


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int
    pages: int
    has_next: bool
    has_prev: bool


class UserListItem(BaseModel):
    """User item for list views."""
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    # last_login: Optional[datetime] = None  # Add when login tracking implemented
    
    model_config = {"from_attributes": True}


class UserListResponse(PaginatedResponse[UserListItem]):
    """Response for user list endpoint."""
    pass


class UserDetailResponse(BaseModel):
    """Detailed user response."""
    id: UUID
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    # Activity summary (placeholders for future implementation)
    # videos_annotated: int = 0
    # reviews_completed: int = 0
    
    model_config = {"from_attributes": True}


# Query parameters for list endpoint
class UserListQueryParams:
    """Query parameters for user list endpoint."""
    
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(20, ge=1, le=100, description="Items per page"),
        role: Optional[str] = Query(None, description="Filter by role"),
        is_active: Optional[bool] = Query(None, description="Filter by active status"),
        sort_by: str = Query("created_at", description="Sort field"),
        sort_order: str = Query("desc", description="Sort direction (asc/desc)"),
    ):
        self.page = page
        self.page_size = page_size
        self.role = role
        self.is_active = is_active
        self.sort_by = sort_by
        self.sort_order = sort_order.lower()
```

### Phase 2: Repository Layer

#### Step 2.1: Update app/repositories/user_repository.py

Add list and count methods:

```python
from typing import List, Tuple, Optional
from sqlalchemy import select, func, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import User


class UserRepository:
    """Repository for user database operations."""
    
    # ... existing methods ...
    
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> Tuple[List[User], int]:
        """
        List users with filtering and pagination.
        
        Args:
            page: Page number (1-based)
            page_size: Items per page
            role: Filter by role
            is_active: Filter by active status
            sort_by: Sort field name
            sort_order: Sort direction (asc/desc)
            
        Returns:
            Tuple of (users list, total count)
        """
        # Build base query
        query = select(User)
        count_query = select(func.count(User.id))
        
        # Apply filters
        filters = []
        if role:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active == is_active)
        
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
        
        # Get total count
        total_result = await self.session.execute(count_query)
        total = total_result.scalar_one()
        
        # Apply sorting
        sort_column = getattr(User, sort_by, User.created_at)
        if sort_order == "desc":
            query = query.order_by(desc(sort_column))
        else:
            query = query.order_by(asc(sort_column))
        
        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)
        
        # Execute query
        result = await self.session.execute(query)
        users = result.scalars().all()
        
        return list(users), total
    
    
    async def count_users(
        self,
        role: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> int:
        """
        Count users with optional filtering.
        
        Args:
            role: Filter by role
            is_active: Filter by active status
            
        Returns:
            Total count matching filters
        """
        query = select(func.count(User.id))
        
        filters = []
        if role:
            filters.append(User.role == role)
        if is_active is not None:
            filters.append(User.is_active == is_active)
        
        if filters:
            query = query.where(*filters)
        
        result = await self.session.execute(query)
        return result.scalar_one()
```

### Phase 3: Service Layer

#### Step 3.1: Update app/services/user_service.py

Add list_users method:

```python
from typing import Tuple, List
from math import ceil

from app.repositories.user_repository import UserRepository


class UserListResult:
    """Result container for user list operation."""
    
    def __init__(
        self,
        users: List[User],
        total: int,
        page: int,
        page_size: int
    ):
        self.users = users
        self.total = total
        self.page = page
        self.page_size = page_size
        self.pages = ceil(total / page_size) if page_size > 0 else 0
        self.has_next = page < self.pages
        self.has_prev = page > 1


class UserService:
    """Service for user operations."""
    
    # ... existing methods ...
    
    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        role: Optional[str] = None,
        is_active: Optional[bool] = None,
        sort_by: str = "created_at",
        sort_order: str = "desc"
    ) -> UserListResult:
        """
        List users with filtering and pagination.
        
        Args:
            page: Page number
            page_size: Items per page
            role: Filter by role
            is_active: Filter by active status
            sort_by: Sort field
            sort_order: Sort direction
            
        Returns:
            UserListResult with users and pagination info
        """
        # Validate role filter
        if role and role not in {"admin", "annotator", "curator"}:
            raise ValueError(f"Invalid role filter: {role}")
        
        # Validate sort_by
        valid_sort_fields = {"created_at", "email", "role", "updated_at"}
        if sort_by not in valid_sort_fields:
            sort_by = "created_at"
        
        users, total = await self.repository.list_users(
            page=page,
            page_size=page_size,
            role=role,
            is_active=is_active,
            sort_by=sort_by,
            sort_order=sort_order
        )
        
        return UserListResult(
            users=users,
            total=total,
            page=page,
            page_size=page_size
        )
    
    
    async def get_user_by_id(self, user_id: UUID) -> Optional[User]:
        """
        Get user by ID for detail view.
        
        Args:
            user_id: User UUID
            
        Returns:
            User instance or None
        """
        return await self.repository.get_by_id(user_id)
```

### Phase 4: API Layer

#### Step 4.1: Update app/routers/admin.py

Add list and detail endpoints:

```python
from fastapi import Query
from typing import Optional

from app.models.schemas import (
    UserCreateRequest,
    UserCreateResponse,
    UserRoleUpdateRequest,
    UserRoleUpdateResponse,
    UserDeactivateResponse,
    UserListItem,
    UserListResponse,
    UserDetailResponse,
    UserListQueryParams,
    AuthErrorResponse,
)


@router.get(
    "/users",
    response_model=UserListResponse,
    responses={
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
    },
)
async def list_users(
    params: UserListQueryParams = Depends(),
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    List all users with filtering and pagination (Admin only).
    
    Query Parameters:
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **role**: Filter by role (admin, annotator, curator)
    - **is_active**: Filter by active status (true/false)
    - **sort_by**: Sort field (created_at, email, role)
    - **sort_order**: Sort direction (asc, desc)
    
    Returns paginated list of users.
    """
    user_service = UserService(db_session)
    
    try:
        result = await user_service.list_users(
            page=params.page,
            page_size=params.page_size,
            role=params.role,
            is_active=params.is_active,
            sort_by=params.sort_by,
            sort_order=params.sort_order
        )
        
        # Convert users to response items
        items = [
            UserListItem.model_validate(user)
            for user in result.users
        ]
        
        return UserListResponse(
            items=items,
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
            has_next=result.has_next,
            has_prev=result.has_prev
        )
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.get(
    "/users/{user_id}",
    response_model=UserDetailResponse,
    responses={
        403: {"model": AuthErrorResponse, "description": "Admin access required"},
        404: {"description": "User not found"},
    },
)
async def get_user_detail(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin),
    db_session: AsyncSession = Depends(get_async_session),
):
    """
    Get detailed information about a specific user (Admin only).
    
    - **user_id**: UUID of user to retrieve
    
    Returns detailed user information including timestamps.
    Activity summary (videos annotated, reviews) to be added in future stories.
    """
    user_service = UserService(db_session)
    
    user = await user_service.get_user_by_id(user_id)
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    return UserDetailResponse.model_validate(user)
```

### Phase 5: Testing

#### Step 5.1: Create tests/integration/test_admin_list_users.py

```python
"""Integration tests for admin user list and detail endpoints."""

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


class TestListUsers:
    """Tests for GET /api/v1/admin/users."""
    
    def test_list_users_success(self, db_session, test_user):
        """Test successful user list retrieval."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert isinstance(data["items"], list)
    
    def test_list_users_pagination(self, db_session):
        """Test pagination parameters."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?page=1&page_size=10",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
    
    def test_list_users_filter_by_role(self, db_session, test_user):
        """Test filtering by role."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?role=annotator",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        for user in data["items"]:
            assert user["role"] == "annotator"
    
    def test_list_users_filter_by_is_active(self, db_session, inactive_user):
        """Test filtering by is_active."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?is_active=false",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        for user in data["items"]:
            assert user["is_active"] is False
    
    def test_list_users_sorting(self, db_session):
        """Test sorting."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?sort_by=email&sort_order=asc",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
    
    def test_list_users_non_admin_forbidden(self, db_session):
        """Test non-admin cannot access user list."""
        token = create_annotator_token()
        
        response = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403
    
    def test_list_users_invalid_role_filter(self, db_session):
        """Test 400 for invalid role filter."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?role=superadmin",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 400


class TestGetUserDetail:
    """Tests for GET /api/v1/admin/users/{id}."""
    
    def test_get_user_detail_success(self, db_session, test_user):
        """Test successful user detail retrieval."""
        token = create_admin_token()
        
        response = client.get(
            f"/api/v1/admin/users/{test_user.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(test_user.id)
        assert data["email"] == test_user.email
        assert data["role"] == test_user.role
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_get_user_detail_not_found(self, db_session):
        """Test 404 for non-existent user."""
        token = create_admin_token()
        
        response = client.get(
            f"/api/v1/admin/users/{uuid4()}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 404
    
    def test_get_user_detail_non_admin_forbidden(self, db_session, test_user):
        """Test non-admin cannot access user detail."""
        token = create_annotator_token()
        
        response = client.get(
            f"/api/v1/admin/users/{test_user.id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403
```

### Phase 6: Documentation

#### Step 6.1: Create docs/admin-user-management-guide.md

```markdown
# Admin User Management Guide

Complete guide for managing users via the Admin API.

## Base URL

```
/api/v1/admin
```

All endpoints require admin authentication:
```
Authorization: Bearer <admin-jwt-token>
```

## User Lifecycle

### 1. Create User

```bash
POST /api/v1/admin/users
Content-Type: application/json

{
  "email": "newuser@lbi.ac.id",
  "role": "annotator",
  "temporary_password": "OptionalPass123!"
}
```

### 2. List Users

```bash
GET /api/v1/admin/users?page=1&page_size=20
```

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "email": "user@example.com",
      "role": "annotator",
      "is_active": true,
      "created_at": "2026-03-19T10:30:00Z"
    }
  ],
  "total": 150,
  "page": 1,
  "page_size": 20,
  "pages": 8,
  "has_next": true,
  "has_prev": false
}
```

### 3. View User Details

```bash
GET /api/v1/admin/users/{user_id}
```

### 4. Modify Role

```bash
PUT /api/v1/admin/users/{user_id}/role
Content-Type: application/json

{
  "role": "curator"
}
```

### 5. Deactivate User

```bash
DELETE /api/v1/admin/users/{user_id}
```

## Filtering

### By Role

```bash
GET /api/v1/admin/users?role=annotator
```

### By Active Status

```bash
# Active users only
GET /api/v1/admin/users?is_active=true

# Inactive users only
GET /api/v1/admin/users?is_active=false
```

### Combined Filters

```bash
GET /api/v1/admin/users?role=annotator&is_active=true
```

## Sorting

```bash
# Sort by email ascending
GET /api/v1/admin/users?sort_by=email&sort_order=asc

# Sort by creation date descending (default)
GET /api/v1/admin/users?sort_by=created_at&sort_order=desc
```

## Pagination

```bash
# Page 2 with 50 items per page
GET /api/v1/admin/users?page=2&page_size=50
```

**Limits:**
- Default page size: 20
- Maximum page size: 100
- Minimum page: 1

## Common Workflows

### Onboard New Annotator

```bash
# 1. Create user
POST /api/v1/admin/users
{
  "email": "newannotator@lbi.ac.id",
  "role": "annotator"
}
# Note the temporary password in response

# 2. Share credentials securely
# 3. User logs in and changes password
```

### Promote Annotator to Curator

```bash
PUT /api/v1/admin/users/{annotator_id}/role
{
  "role": "curator"
}
```

Role change takes effect on next login/token refresh.

### Offboard Employee

```bash
# Soft delete (deactivate)
DELETE /api/v1/admin/users/{user_id}
```

User data preserved for audit compliance.

## Error Handling

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad Request (validation error, self-modification) |
| 403 | Forbidden (non-admin access) |
| 404 | Not Found |
| 409 | Conflict (duplicate email) |
| 422 | Validation Error |

## Best Practices

1. **Always verify before modifying**: Use GET detail endpoint first
2. **Use filters for large teams**: Don't fetch all users
3. **Audit trail**: All changes are logged automatically
4. **Soft delete**: Never hard delete users
5. **Secure credentials**: Auto-generated passwords shown only once
```

---

## Implementation Checklist

### Phase 1: Schemas
- [ ] Add PaginatedResponse generic wrapper
- [ ] Add UserListItem schema
- [ ] Add UserListResponse schema
- [ ] Add UserDetailResponse schema
- [ ] Add UserListQueryParams dependency

### Phase 2: Repository
- [ ] Add list_users() method to UserRepository
- [ ] Add count_users() method to UserRepository

### Phase 3: Service
- [ ] Add UserListResult container
- [ ] Add list_users() method to UserService
- [ ] Add get_user_by_id() method to UserService

### Phase 4: API
- [ ] Add GET /admin/users endpoint
- [ ] Add GET /admin/users/{id} endpoint
- [ ] Add filtering and pagination support

### Phase 5: Testing
- [ ] Integration tests for list endpoint
- [ ] Integration tests for detail endpoint
- [ ] Tests for filtering and pagination
- [ ] Tests for admin-only access

### Phase 6: Documentation
- [ ] Create admin-user-management-guide.md

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅
- Story 1.5: Role-Based Access Control Middleware ✅
- Story 1.6: Admin Create User Accounts ✅
- Story 1.7: Admin Modify User Roles ✅
- Story 1.8: Admin Deactivate User Accounts (is_active filter) ✅

**This story completes Epic 1.**

---

## Epic 1 Completion

After completing Story 1.9, Epic 1: Foundation & Authentication will be complete.

**Epic 1 Deliverables:**
- ✅ Database schema for auth domain
- ✅ JWT authentication service
- ✅ User login API
- ✅ Token refresh flow
- ✅ RBAC middleware
- ✅ User management (CRUD operations)

**Next Epic:**
**Epic 2: Video Processing Pipeline**

Proceed to Story 2.1: Database Schema - Pipeline Domain

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. **Pagination**: Always use pagination for list endpoints
2. **Filtering**: Support common filters (role, is_active)
3. **Sorting**: Allow sorting by common fields
4. **No Sensitive Data**: Never include password_hash in responses
5. **Admin Only**: All endpoints must use require_admin

**Performance Considerations:**
- Use database indexes for filtering fields
- Limit max page size to prevent memory issues
- Use count query separate from data query

**Testing Checklist:**
- [ ] Pagination works correctly
- [ ] Filters work individually and combined
- [ ] Sorting works asc and desc
- [ ] Non-admin gets 403
- [ ] Invalid filters return 400
- [ ] Non-existent user returns 404

**Questions?**  
Refer to:
- Previous stories in Epic 1 for patterns
- FastAPI docs for pagination
- Architecture doc for API patterns
