"""Integration tests for RBAC protection."""

import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.main import app
from app.services.auth_service import jwt_auth_service

client = TestClient(app)


def create_token_for_role(role: str) -> str:
    """Helper to create a valid JWT for a specific role."""
    user_id = uuid4()
    return jwt_auth_service.create_access_token(user_id, role)


class TestAuthenticationRequired:
    """Tests that endpoints require authentication."""
    
    def test_protected_endpoint_without_token(self):
        """Test 401 when accessing protected endpoint without token."""
        response = client.get("/api/v1/auth/me")
        
        assert response.status_code == 401
        assert response.json()["error"] == "authentication_required"
    
    def test_protected_endpoint_with_invalid_token(self):
        """Test 401 with invalid token."""
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid.token"}
        )
        
        assert response.status_code == 401


class TestAdminAccess:
    """Tests for admin-only endpoints."""
    
    def test_admin_can_access_admin_endpoint(self):
        """Test admin can access admin-only endpoint."""
        token = create_token_for_role("admin")
        
        response = client.get(
            "/api/v1/auth/admin-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        assert "Admin access granted" in response.json()["message"]
    
    def test_annotator_cannot_access_admin_endpoint(self):
        """Test annotator gets 403 on admin endpoint."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/admin-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403
        assert response.json()["error"] == "insufficient_permissions"
    
    def test_curator_cannot_access_admin_endpoint(self):
        """Test curator gets 403 on admin endpoint."""
        token = create_token_for_role("curator")
        
        response = client.get(
            "/api/v1/auth/admin-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403


class TestAnnotatorAccess:
    """Tests for annotator-only endpoints."""
    
    def test_annotator_can_access_annotator_endpoint(self):
        """Test annotator can access annotator endpoint."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/annotator-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        assert "Annotator access granted" in response.json()["message"]
    
    def test_curator_cannot_access_annotator_only_endpoint(self):
        """Test curator gets 403 on annotator-only endpoint."""
        token = create_token_for_role("curator")
        
        response = client.get(
            "/api/v1/auth/annotator-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403
    
    def test_admin_cannot_access_annotator_only_endpoint(self):
        """Test admin gets 403 on annotator-only endpoint."""
        token = create_token_for_role("admin")
        
        response = client.get(
            "/api/v1/auth/annotator-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403


class TestCuratorAccess:
    """Tests for curator-only endpoints."""
    
    def test_curator_can_access_curator_endpoint(self):
        """Test curator can access curator endpoint."""
        token = create_token_for_role("curator")
        
        response = client.get(
            "/api/v1/auth/curator-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        assert "Curator access granted" in response.json()["message"]
    
    def test_annotator_cannot_access_curator_only_endpoint(self):
        """Test annotator gets 403 on curator-only endpoint."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/curator-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403


class TestMultiRoleAccess:
    """Tests for multi-role endpoints."""
    
    def test_annotator_can_access_annotator_or_curator_endpoint(self):
        """Test annotator can access annotator-or-curator endpoint."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/annotator-or-curator",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
    
    def test_curator_can_access_annotator_or_curator_endpoint(self):
        """Test curator can access annotator-or-curator endpoint."""
        token = create_token_for_role("curator")
        
        response = client.get(
            "/api/v1/auth/annotator-or-curator",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
    
    def test_admin_cannot_access_annotator_or_curator_endpoint(self):
        """Test admin gets 403 on annotator-or-curator endpoint."""
        token = create_token_for_role("admin")
        
        response = client.get(
            "/api/v1/auth/annotator-or-curator",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403


class TestGetCurrentUser:
    """Tests for /auth/me endpoint."""
    
    def test_returns_user_info(self):
        """Test /auth/me returns user info from token."""
        user_id = uuid4()
        token = jwt_auth_service.create_access_token(user_id, "annotator")
        
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(user_id)
        assert data["role"] == "annotator"


class TestMultiRoleDemo:
    """Tests for multi-role demo endpoint (admin or curator)."""
    
    def test_admin_can_access(self):
        """Test admin can access multi-role endpoint."""
        token = create_token_for_role("admin")
        
        response = client.get(
            "/api/v1/auth/multi-role-demo",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
    
    def test_curator_can_access(self):
        """Test curator can access multi-role endpoint."""
        token = create_token_for_role("curator")
        
        response = client.get(
            "/api/v1/auth/multi-role-demo",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 200
    
    def test_annotator_cannot_access(self):
        """Test annotator gets 403 on multi-role endpoint."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/multi-role-demo",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403


class TestErrorResponses:
    """Tests for error response format."""
    
    def test_401_response_format(self):
        """Test 401 response has correct format."""
        response = client.get("/api/v1/auth/me")
        
        assert response.status_code == 401
        data = response.json()
        assert "error" in data
        assert "detail" in data
        assert data["error"] == "authentication_required"
    
    def test_403_response_format(self):
        """Test 403 response has correct format."""
        token = create_token_for_role("annotator")
        
        response = client.get(
            "/api/v1/auth/admin-only",
            headers={"Authorization": f"Bearer {token}"}
        )
        
        assert response.status_code == 403
        data = response.json()
        assert "error" in data
        assert "detail" in data
        assert data["error"] == "insufficient_permissions"
        assert "admin" in data["detail"]
