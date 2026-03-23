# Story 1.7: Admin - Modify User Roles

**Status:** ✅ Completed  
**Assignee:** AI Developer  
**Sprint:** Sprint 1 - Core Platform  

---

## User Story

**As an** administrator  
**I want** to change a user's role  
**So that** I can adjust permissions as team needs change  

---

## Acceptance Criteria (AC)

### AC1: Role Change Endpoint
- ✅ **PUT** `/api/v1/admin/users/{user_id}/role` updates user's role
- ✅ Request body: `{ "role": "curator" }`
- ✅ Response includes `previous_role` for audit purposes
- ✅ Returns 200 on success

### AC2: Admin Only
- ✅ Only admin users can access this endpoint
- ✅ Returns 403 Forbidden for non-admin users
- ✅ Uses `require_admin` dependency

### AC3: Validation
- ✅ Role must be one of: `admin`, `annotator`, `curator`
- ✅ Returns 400 if user not found
- ✅ Returns 400 if admin tries to modify their own role
- ✅ Returns 400 if setting same role user already has
- ✅ Schema validation with Pydantic

### AC4: Audit Logging
- ✅ All role changes are logged to audit_logs table
- ✅ Actor ID (admin) recorded
- ✅ Target user ID recorded
- ✅ Old and new roles recorded in JSONB details
- ✅ IP address captured from request

### AC5: Session Handling
- ✅ Current sessions remain valid after role change
- ✅ New role takes effect on next token refresh
- ✅ No forced logout required

---

## Technical Implementation

### API Endpoint

```python
PUT /api/v1/admin/users/{user_id}/role
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "role": "curator"
}
```

### Response

**Success (200):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "role": "curator",
  "previous_role": "annotator",
  "updated_at": "2024-01-15T10:30:00Z"
}
```

**Error (400 - Self-modification):**
```json
{
  "detail": "Cannot modify your own role."
}
```

**Error (400 - Same role):**
```json
{
  "detail": "User already has role 'curator'."
}
```

**Error (404 - User not found):**
```json
{
  "detail": "User not found."
}
```

**Error (403 - Forbidden):**
```json
{
  "error": "insufficient_permissions",
  "message": "Admin access required"
}
```

### Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Admin Router   │────▶│   UserService    │────▶│ UserRepository  │
│   PUT /role     │     │  update_role()   │     │  update_user()  │
└─────────────────┘     └──────────────────┘     └─────────────────┘
         │                       │                         │
         │                       ▼                         │
         │              ┌──────────────────┐              │
         │              │  AuditService    │              │
         │              │log_user_roles_   │──────────────▶
         │              │  changed()       │    AuditLog
         │              └──────────────────┘    Repository
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────────┐
│           Audit Log Entry                   │
│  action: USER_ROLE_CHANGED                  │
│  actor_id: <admin_id>                       │
│  resource_id: <target_user_id>              │
│  details: {                                 │
│    "old_role": "annotator",                 │
│    "new_role": "curator"                    │
│  }                                          │
│  ip_address: "192.168.1.1"                  │
└─────────────────────────────────────────────┘
```

### Schemas

**UserRoleUpdateRequest:**
```python
class UserRoleUpdateRequest(BaseModel):
    role: str = Field(..., description="New role (admin, annotator, curator)")
    
    @field_validator('role')
    def validate_role(cls, v: str) -> str:
        allowed_roles = {'admin', 'annotator', 'curator'}
        if v not in allowed_roles:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed_roles))}")
        return v
```

**UserRoleUpdateResponse:**
```python
class UserRoleUpdateResponse(BaseModel):
    id: str
    email: str
    role: str
    previous_role: Optional[str]
    updated_at: Optional[str]
```

---

## IP Address Extraction

For audit logging, IP addresses are extracted in this priority:

1. **X-Forwarded-For header**: For users behind proxies/load balancers
   - Takes first IP if multiple are present (chain of proxies)
2. **request.client.host**: Direct connection fallback
3. **None**: If neither is available

```python
x_forwarded_for = request.headers.get("X-Forwarded-For")
if x_forwarded_for:
    ip_address = x_forwarded_for.split(",")[0].strip()
elif request.client:
    ip_address = request.client.host
else:
    ip_address = None
```

---

## Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `app/routers/admin.py` | +93 | Added PUT endpoint and schemas |
| `tests/integration/test_admin_endpoints.py` | +101 | Added 6 new test cases |

### Existing Infrastructure Used

| Component | Location | Purpose |
|-----------|----------|---------|
| Migration | `alembic/versions/006_add_audit_log_table.py` | Creates audit_logs table |
| Model | `app/db/models/audit.py` | AuditLog SQLAlchemy model |
| Repository | `app/db/repositories/audit_log_repository.py` | Audit log CRUD operations |
| Service | `app/services/audit_service.py` | Audit logging methods |
| Service | `app/services/user_service.py` | UserService.update_role() |

---

## Test Coverage

### Integration Tests

| Test | Description |
|------|-------------|
| `test_update_role_success` | Admin successfully updates user role |
| `test_update_role_non_admin_forbidden` | Non-admin gets 403 |
| `test_update_role_user_not_found` | 404 for non-existent user |
| `test_update_role_invalid_role` | 422 for invalid role value |
| `test_update_role_self_modification` | 400 when admin modifies self |
| `test_update_role_same_role` | 400 when setting same role |

### Test Execution

```bash
# Run all admin endpoint tests
uv run pytest tests/integration/test_admin_endpoints.py -v

# Run just role update tests
uv run pytest tests/integration/test_admin_endpoints.py::TestUpdateUserRoleEndpoint -v
```

---

## Security Considerations

1. **Self-modification prevention**: Admins cannot change their own role to prevent lockout
2. **Role validation**: Only valid system roles are accepted
3. **Audit trail**: Every change is logged with actor, timestamp, and IP
4. **RBAC enforcement**: Endpoint uses `require_admin` dependency
5. **Session handling**: Changes don't force logout, providing smooth UX

---

## Related Stories

- Story 1.6: Admin - Create User (shares admin router)
- Story 1.5: RBAC Middleware (provides `require_admin` dependency)
- Story 1.8: Admin - Deactivate User (similar audit logging pattern)
- Story 1.10: View Audit Logs (reads these entries)

---

## Changelog

### 2024-01-XX - Initial Implementation
- Added PUT /api/v1/admin/users/{user_id}/role endpoint
- Added UserRoleUpdateRequest and UserRoleUpdateResponse schemas
- Implemented IP address extraction for audit logging
- Added comprehensive integration tests
