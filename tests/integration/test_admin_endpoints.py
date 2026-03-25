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
    
    def test_create_user_duplicate_email(self):
        """Test 409 when creating user with existing email."""
        token = create_admin_token()
        
        # First create a user
        client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "duplicate@example.com",
                "role": "annotator"
            }
        )
        
        # Try to create again with same email
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "duplicate@example.com",
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


class TestUpdateUserRoleEndpoint:
    """Tests for PUT /api/v1/admin/users/{user_id}/role."""
    
    def test_update_role_success(self):
        """Test successful role update by admin."""
        token = create_admin_token()
        
        # First create a user
        create_response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "roletest@example.com",
                "role": "annotator"
            }
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]
        
        # Update the user's role
        response = client.put(
            f"/api/v1/admin/users/{user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user_id
        assert data["email"] == "roletest@example.com"
        assert data["role"] == "curator"
        assert data["previous_role"] == "annotator"
        assert "updated_at" in data
    
    def test_update_role_non_admin_forbidden(self):
        """Test 403 when non-admin tries to update role."""
        annotator_token = create_annotator_token()
        target_user_id = str(uuid4())
        
        response = client.put(
            f"/api/v1/admin/users/{target_user_id}/role",
            headers={"Authorization": f"Bearer {annotator_token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
    
    def test_update_role_user_not_found(self):
        """Test 404 when user doesn't exist."""
        token = create_admin_token()
        non_existent_id = str(uuid4())
        
        response = client.put(
            f"/api/v1/admin/users/{non_existent_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_update_role_invalid_role(self):
        """Test 400 when role is invalid."""
        token = create_admin_token()
        target_user_id = str(uuid4())
        
        response = client.put(
            f"/api/v1/admin/users/{target_user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "superadmin"}
        )
        
        assert response.status_code == 400
        assert "Invalid role specified" in response.json()["detail"]
    
    def test_update_role_self_modification(self):
        """Test 400 when admin tries to modify their own role."""
        from uuid import uuid4
        admin_id = uuid4()
        token = jwt_auth_service.create_access_token(admin_id, "admin")
        
        response = client.put(
            f"/api/v1/admin/users/{admin_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "annotator"}
        )
        
        assert response.status_code == 400
        assert "own role" in response.json()["detail"].lower()
    
    def test_update_role_same_role(self):
        """Test 400 when setting same role user already has."""
        token = create_admin_token()
        
        # Create a user with curator role
        create_response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "sameroletest@example.com",
                "role": "curator"
            }
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]
        
        # Try to set the same role
        response = client.put(
            f"/api/v1/admin/users/{user_id}/role",
            headers={"Authorization": f"Bearer {token}"},
            json={"role": "curator"}
        )
        
        assert response.status_code == 400
        assert "already has role" in response.json()["detail"].lower()
    
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
    
    def test_create_user_missing_email(self):
        """Test 422 when email is missing."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "role": "annotator"
            }
        )
        
        assert response.status_code == 422
    
    def test_create_user_missing_role(self):
        """Test 422 when role is missing."""
        token = create_admin_token()
        
        response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "user@example.com"
            }
        )
        
        assert response.status_code == 422



class TestDeactivateUserEndpoint:
    """Tests for DELETE /api/v1/admin/users/{user_id}."""
    
    def test_deactivate_user_success(self):
        """Test successful user deactivation by admin."""
        token = create_admin_token()
        
        # First create a user
        create_response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "deactivatetest@example.com",
                "role": "annotator"
            }
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]
        
        # Deactivate the user
        response = client.delete(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user_id
        assert data["email"] == "deactivatetest@example.com"
        assert data["is_active"] is False
        assert "deactivated" in data["message"].lower()
        assert "tokens_revoked" in data
    
    def test_deactivate_self_forbidden(self):
        """Test admin cannot deactivate own account."""
        from uuid import uuid4
        admin_id = uuid4()
        token = jwt_auth_service.create_access_token(admin_id, "admin")
        
        response = client.delete(
            f"/api/v1/admin/users/{admin_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 400
        assert "own" in response.json()["detail"].lower()
    
    def test_deactivate_non_admin_forbidden(self):
        """Test non-admin cannot deactivate users."""
        annotator_token = create_annotator_token()
        target_user_id = str(uuid4())
        
        response = client.delete(
            f"/api/v1/admin/users/{target_user_id}",
            headers={"Authorization": f"Bearer {annotator_token}"}
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
    
    def test_deactivate_already_inactive(self):
        """Test deactivating already inactive user returns success (idempotent)."""
        token = create_admin_token()
        
        # Create a user
        create_response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "alreadyinactive@example.com",
                "role": "curator"
            }
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]
        
        # Deactivate once
        response1 = client.delete(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response1.status_code == 200
        
        # Deactivate again (should succeed, idempotent)
        response2 = client.delete(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response2.status_code == 200
        assert "already" in response2.json()["message"].lower()
    
    def test_deactivate_nonexistent_user(self):
        """Test 404 for non-existent user."""
        token = create_admin_token()
        non_existent_id = str(uuid4())
        
        response = client.delete(
            f"/api/v1/admin/users/{non_existent_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestDeactivatedUserLogin:
    """Tests that deactivated users cannot login."""
    
    def test_deactivated_user_cannot_login(self):
        """Test deactivated user gets 401 with specific message on login."""
        # Note: This test requires the user to exist in database
        # In a real test, we'd create a user, deactivate it, then try to login
        # For now, this documents the expected behavior
        pass



class TestListUsersEndpoint:
    """Tests for GET /api/v1/admin/users."""
    
    def test_list_users_success(self):
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
        assert "page_size" in data
        assert "pages" in data
        assert "has_next" in data
        assert "has_prev" in data
    
    def test_list_users_pagination(self):
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
    
    def test_list_users_filter_by_role(self):
        """Test filtering by role."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?role=admin",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # All returned users should have admin role
        for user in data["items"]:
            assert user["role"] == "admin"
    
    def test_list_users_filter_by_is_active(self):
        """Test filtering by active status."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?is_active=true",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        # All returned users should be active
        for user in data["items"]:
            assert user["is_active"] is True
    
    def test_list_users_non_admin_forbidden(self):
        """Test non-admin cannot list users."""
        annotator_token = create_annotator_token()
        
        response = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {annotator_token}"}
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
    
    def test_list_users_invalid_role_filter(self):
        """Test 400 for invalid role filter."""
        token = create_admin_token()
        
        response = client.get(
            "/api/v1/admin/users?role=superadmin",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 400


class TestGetUserEndpoint:
    """Tests for GET /api/v1/admin/users/{user_id}."""
    
    def test_get_user_success(self):
        """Test successful user detail retrieval."""
        token = create_admin_token()
        
        # First create a user
        create_response = client.post(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "email": "detailtest@example.com",
                "role": "annotator"
            }
        )
        assert create_response.status_code == 201
        user_id = create_response.json()["id"]
        
        # Get user details
        response = client.get(
            f"/api/v1/admin/users/{user_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == user_id
        assert data["email"] == "detailtest@example.com"
        assert data["role"] == "annotator"
        assert "is_active" in data
        assert "created_at" in data
        assert "updated_at" in data
    
    def test_get_user_not_found(self):
        """Test 404 for non-existent user."""
        token = create_admin_token()
        non_existent_id = str(uuid4())
        
        response = client.get(
            f"/api/v1/admin/users/{non_existent_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_get_user_non_admin_forbidden(self):
        """Test non-admin cannot get user details."""
        annotator_token = create_annotator_token()
        target_user_id = str(uuid4())
        
        response = client.get(
            f"/api/v1/admin/users/{target_user_id}",
            headers={"Authorization": f"Bearer {annotator_token}"}
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
