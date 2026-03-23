# RBAC (Role-Based Access Control) Guide

This guide explains how to use the Role-Based Access Control system in the API.

## Roles

The system has three roles:

| Role | Description | Typical Access |
|------|-------------|----------------|
| `admin` | System administrators | Full access to all endpoints |
| `curator` | Content curators | Review queue, approve/reject annotations |
| `annotator` | Content annotators | ASR review, annotation queue |

## Using Dependencies

### Basic Authentication

Require any authenticated user:

```python
from fastapi import Depends
from app.dependencies import get_current_user, CurrentUser

@router.get("/profile")
async def get_profile(current_user: CurrentUser = Depends(get_current_user)):
    return {"user_id": current_user.id}
```

### Role-Based Protection

Require specific role(s):

```python
from app.dependencies import require_role, require_admin

# Single role
@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_admin)
):
    # Only admins can reach here
    pass

# Multiple roles (any of)
@router.get("/annotations")
async def list_annotations(
    current_user: CurrentUser = Depends(
        require_role("annotator", "curator")
    )
):
    # Both annotators and curators can access
    pass
```

### Convenience Dependencies

Pre-defined dependencies for common cases:

```python
from app.dependencies import (
    require_admin,        # Admin only
    require_annotator,    # Annotator only
    require_curator,      # Curator only
    require_annotator_or_curator,  # Annotator or Curator
)

@router.get("/admin/dashboard")
async def admin_dashboard(current_user: CurrentUser = Depends(require_admin)):
    pass
```

## CurrentUser Model

The `CurrentUser` model provides user information and helper methods:

```python
class CurrentUser:
    id: UUID      # User ID
    email: str    # User email
    role: str     # User role
    
    # Properties
    is_admin: bool
    is_annotator: bool
    is_curator: bool
    
    # Methods
    has_role("admin", "curator") -> bool
```

## Error Responses

### 401 - Authentication Required

Returned when no valid JWT token is provided:

```json
{
  "error": "authentication_required",
  "detail": "Authentication required"
}
```

### 403 - Insufficient Permissions

Returned when user doesn't have required role:

```json
{
  "error": "insufficient_permissions",
  "detail": "Insufficient permissions. Required roles: admin"
}
```

## Testing Protected Endpoints

When testing, create tokens with specific roles:

```python
from app.services.auth_service import jwt_auth_service

token = jwt_auth_service.create_access_token(user_id, "admin")

response = client.get(
    "/api/v1/protected",
    headers={"Authorization": f"Bearer {token}"}
)
```

## Future: Permission-Based Access

The architecture supports future permission-based access:

```python
@router.post("/annotations")
async def create_annotation(
    current_user: CurrentUser = Depends(
        require_permission("annotation:write")
    )
):
    pass
```

This is not yet implemented but the pattern is established.
