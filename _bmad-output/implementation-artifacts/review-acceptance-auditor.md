# Acceptance Auditor Review - Story 1.7

**Task:** Review the code diff AGAINST the story specification. Check for violations of acceptance criteria, deviations from spec intent, and missing implementation.

**Approach:** Compare every line of code against the spec. Flag any discrepancy, no matter how small.

---

## Story Specification

**Story:** 1.7 - Admin - Modify User Roles
**File:** `_bmad-output/implementation-artifacts/1-7-admin-modify-user-roles.md`

### Acceptance Criteria

**AC1: Role Change Endpoint**
- PUT `/api/v1/admin/users/{user_id}/role` updates user's role
- Request body: `{ "role": "curator" }`
- Response includes `previous_role` for audit purposes
- Returns 200 on success

**AC2: Admin Only**
- Only admin users can access this endpoint
- Returns 403 Forbidden for non-admin users
- Uses `require_admin` dependency

**AC3: Validation**
- Role must be one of: `admin`, `annotator`, `curator`
- Returns 400 if user not found
- Returns 400 if admin tries to modify their own role
- Returns 400 if setting same role user already has
- Schema validation with Pydantic

**AC4: Audit Logging**
- All role changes are logged to audit_logs table
- Actor ID (admin) recorded
- Target user ID recorded
- Old and new roles recorded in JSONB details
- IP address captured from request

**AC5: Session Handling**
- Current sessions remain valid after role change
- New role takes effect on next token refresh
- No forced logout required

---

## Code Diff to Review

```diff
commit e931f9636a3f085c12cf310d62b6baffa44c8fd4
Author: Arxeno <raisyamburhani@gmail.com>
Date:   Tue Mar 24 02:01:34 2026 +0700

    feat: Add user role update endpoint and corresponding integration tests

 app/routers/admin.py                              | 127 ++++++++++-
 tests/integration/test_admin_endpoints.py         | 117 ++++++++++
 3 files changed, 496 insertions(+), 1 deletion(-)

diff --git a/app/routers/admin.py b/app/routers/admin.py
index f0484d8..b9b7161 100644
--- a/app/routers/admin.py
+++ b/app/routers/admin.py
@@ -5,7 +5,11 @@ Administrative endpoints for user management.
 All endpoints require admin role.
 """
 
-from fastapi import APIRouter, Depends, HTTPException, status
+from typing import Optional
+from uuid import UUID
+
+from fastapi import APIRouter, Depends, HTTPException, Request, status
+from pydantic import BaseModel, Field, field_validator
 from sqlalchemy.exc import IntegrityError
 from sqlalchemy.ext.asyncio import AsyncSession
 
@@ -13,6 +17,32 @@ from app.database import get_async_session
 from app.dependencies import require_admin, CurrentUser
 from app.services.user_service import UserService
 
+
+# ============================================================================
+# Schemas
+# ============================================================================
+
+class UserRoleUpdateRequest(BaseModel):
+    """Request schema for user role update."""
+    role: str = Field(..., description="New role for the user (admin, annotator, curator)")
+    
+    @field_validator('role')
+    @classmethod
+    def validate_role(cls, v: str) -> str:
+        allowed_roles = {'admin', 'annotator', 'curator'}
+        if v not in allowed_roles:
+            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed_roles))}")
+        return v
+
+
+class UserRoleUpdateResponse(BaseModel):
+    """Response schema for user role update."""
+    id: str = Field(..., description="User ID")
+    email: str = Field(..., description="User email")
+    role: str = Field(..., description="New role")
+    previous_role: Optional[str] = Field(None, description="Previous role")
+    updated_at: Optional[str] = Field(None, description="Update timestamp")
+
 router = APIRouter(prefix="/admin", tags=["admin"])
 
 
@@ -114,3 +144,98 @@ async def create_user(
             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
             detail="An error occurred while creating the user"
         )
+
+
+@router.put(
+    "/users/{user_id}/role",
+    response_model=UserRoleUpdateResponse,
+    responses={
+        400: {"description": "Bad request - self-modification or same role"},
+        403: {"description": "Admin access required"},
+        404: {"description": "User not found"},
+        422: {"description": "Validation error - invalid role"},
+    },
+)
+async def update_user_role(
+    user_id: UUID,
+    role_data: UserRoleUpdateRequest,
+    request: Request,
+    current_user: CurrentUser = Depends(require_admin),
+    db_session: AsyncSession = Depends(get_async_session),
+):
+    """
+    Update a user's role (Admin only).
+    
+    - **user_id**: UUID of the user to update
+    - **role**: New role (admin, annotator, curator)
+    
+    The admin cannot modify their own role. The previous role is returned for audit purposes.
+    Current sessions remain valid (new role takes effect on next token refresh).
+    
+    Returns the updated user with their new role and previous role.
+    """
+    user_service = UserService(db_session)
+    
+    # Extract IP address for audit logging
+    # Check X-Forwarded-For header first (for users behind proxy/load balancer)
+    x_forwarded_for = request.headers.get("X-Forwarded-For")
+    if x_forwarded_for:
+        # Take the first IP if multiple are present
+        ip_address = x_forwarded_for.split(",")[0].strip()
+    elif request.client:
+        ip_address = request.client.host
+    else:
+        ip_address = None
+    
+    result = await user_service.update_role(
+        admin_id=current_user.user_id,
+        target_user_id=user_id,
+        new_role=role_data.role,
+        ip_address=ip_address
+    )
+    
+    if not result["success"]:
+        error_msg = result["message"]
+        
+        # Check for self-modification (400)
+        if "own role" in error_msg.lower():
+            raise HTTPException(
+                status_code=status.HTTP_400_BAD_REQUEST,
+                detail=error_msg
+            )
+        
+        # Check for same role (400)
+        if "already has role" in error_msg.lower():
+            raise HTTPException(
+                status_code=status.HTTP_400_BAD_REQUEST,
+                detail=error_msg
+            )
+        
+        # Check for invalid role (400 - though Pydantic should catch this)
+        if "invalid role" in error_msg.lower():
+            raise HTTPException(
+                status_code=status.HTTP_400_BAD_REQUEST,
+                detail=error_msg
+            )
+        
+        # Check for user not found (404)
+        if "not found" in error_msg.lower():
+            raise HTTPException(
+                status_code=status.HTTP_404_NOT_FOUND,
+                detail=error_msg
+            )
+        
+        # Other errors
+        raise HTTPException(
+            status_code=status.HTTP_400_BAD_REQUEST,
+            detail=error_msg
+        )
+    
+    user = result["user"]
+    return UserRoleUpdateResponse(
+        id=str(user.id),
+        email=user.email,
+        role=role_data.role,
+        previous_role=result.get("previous_role"),
+        updated_at=user.updated_at.isoformat() if user.updated_at else None
+    )

diff --git a/tests/integration/test_admin_endpoints.py b/tests/integration/test_admin_endpoints.py
index c06504c..01f6aa0 100644
--- a/tests/integration/test_admin_endpoints.py
+++ b/tests/integration/test_admin_endpoints.py
@@ -119,6 +119,123 @@ class TestCreateUserEndpoint:
         )
         
         assert response.status_code == 422
+
+
+class TestUpdateUserRoleEndpoint:
+    """Tests for PUT /api/v1/admin/users/{user_id}/role."""
+    
+    def test_update_role_success(self):
+        """Test successful role update by admin."""
+        token = create_admin_token()
+        
+        # First create a user
+        create_response = client.post(
+            "/api/v1/admin/users",
+            headers={"Authorization": f"Bearer {token}"},
+            json={
+                "email": "roletest@example.com",
+                "role": "annotator"
+            }
+        )
+        assert create_response.status_code == 201
+        user_id = create_response.json()["id"]
+        
+        # Update the user's role
+        response = client.put(
+            f"/api/v1/admin/users/{user_id}/role",
+            headers={"Authorization": f"Bearer {token}"},
+            json={"role": "curator"}
+        )
+        
+        assert response.status_code == 200
+        data = response.json()
+        assert data["id"] == user_id
+        assert data["email"] == "roletest@example.com"
+        assert data["role"] == "curator"
+        assert data["previous_role"] == "annotator"
+        assert "updated_at" in data
+    
+    def test_update_role_non_admin_forbidden(self):
+        """Test 403 when non-admin tries to update role."""
+        annotator_token = create_annotator_token()
+        target_user_id = str(uuid4())
+        
+        response = client.put(
+            f"/api/v1/admin/users/{target_user_id}/role",
+            headers={"Authorization": f"Bearer {annotator_token}"},
+            json={"role": "curator"}
+        )
+        
+        assert response.status_code == 403
+        assert response.json()["error"] == "insufficient_permissions"
+    
+    def test_update_role_user_not_found(self):
+        """Test 404 when user doesn't exist."""
+        token = create_admin_token()
+        non_existent_id = str(uuid4())
+        
+        response = client.put(
+            f"/api/v1/admin/users/{non_existent_id}/role",
+            headers={"Authorization": f"Bearer {token}"},
+            json={"role": "curator"}
+        )
+        
+        assert response.status_code == 404
+        assert "not found" in response.json()["detail"].lower()
+    
+    def test_update_role_invalid_role(self):
+        """Test 422 when role is invalid."""
+        token = create_admin_token()
+        target_user_id = str(uuid4())
+        
+        response = client.put(
+            f"/api/v1/admin/users/{target_user_id}/role",
+            headers={"Authorization": f"Bearer {token}"},
+            json={"role": "superadmin"}
+        )
+        
+        assert response.status_code == 422
+    
+    def test_update_role_self_modification(self):
+        """Test 400 when admin tries to modify their own role."""
+        from uuid import uuid4
+        admin_id = uuid4()
+        token = jwt_auth_service.create_access_token(admin_id, "admin")
+        
+        response = client.put(
+            f"/api/v1/admin/users/{admin_id}/role",
+            headers={"Authorization": f"Bearer {token}"},
+            json={"role": "annotator"}
+        )
+        
+        assert response.status_code == 400
+        assert "own role" in response.json()["detail"].lower()
+    
+    def test_update_role_same_role(self):
+        """Test 400 when setting same role user already has."""
+        token = create_admin_token()
+        
+        # Create a user with curator role
+        create_response = client.post(
+            "/api/v1/admin/users",
+            headers={"Authorization": f"Bearer {token}"},
+            json={
+                "email": "sameroletest@example.com",
+                "role": "curator"
+            }
+        )
+        assert create_response.status_code == 201
+        user_id = create_response.json()["id"]
+        
+        # Try to set the same role
+        response = client.put(
+            f"/api/v1/admin/users/{user_id}/role",
+            headers={"Authorization": f"Bearer {token}"},
+            json={"role": "curator"}
+        )
+        
+        assert response.status_code == 400
+        assert "already has role" in response.json()["detail"].lower()
```

---

## Your Task

1. Review the diff against each Acceptance Criterion
2. Flag any deviation from the spec, no matter how small
3. Check: Is every AC satisfied? Is the implementation exactly as specified?

**Format for each finding:**
```markdown
- **[AC-X] [SEVERITY: High/Med/Low]** **File:line** - Brief title
  - Spec Requirement: What the spec says
  - Implementation: What the code does
  - Violation: How they differ
  - Evidence: Specific code lines
```

**Severity Guidelines:**
- **High**: AC violation - feature doesn't work as specified
- **Med**: Deviation from spec intent - works but differently than intended
- **Low**: Spec ambiguity - unclear if violation, needs clarification

**AC Checklist:**
- [ ] AC1: PUT endpoint exists at correct path
- [ ] AC1: Request body accepts `{ "role": "curator" }`
- [ ] AC1: Response includes `previous_role`
- [ ] AC1: Returns 200 on success
- [ ] AC2: Only admins can access
- [ ] AC2: Returns 403 for non-admins
- [ ] AC2: Uses `require_admin` dependency
- [ ] AC3: Role validation for admin/annotator/curator
- [ ] AC3: 400 for user not found
- [ ] AC3: 400 for self-modification
- [ ] AC3: 400 for same role
- [ ] AC3: Pydantic schema validation
- [ ] AC4: Audit log entry created
- [ ] AC4: Actor ID recorded
- [ ] AC4: Target user ID recorded
- [ ] AC4: Old/new roles in details
- [ ] AC4: IP address captured
- [ ] AC5: Sessions remain valid
- [ ] AC5: New role on token refresh

**If all ACs satisfied**, explicitly state: "All acceptance criteria met."

---

## Output Your Findings Below

<!-- ACCEPTANCE AUDITOR FINDINGS START -->

<!-- ACCEPTANCE AUDITOR FINDINGS END -->
