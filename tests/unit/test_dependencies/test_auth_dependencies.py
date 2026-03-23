"""Tests for authentication dependencies."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4, UUID

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.dependencies.auth import (
    get_current_user,
    require_role,
    require_admin,
    CurrentUser,
    _extract_token_from_header,
    _verify_token_and_extract_payload,
    _payload_to_current_user,
    ALLOWED_ROLES,
)
from app.services.auth_service import jwt_auth_service


class TestExtractTokenFromHeader:
    """Tests for _extract_token_from_header."""
    
    def test_extracts_valid_bearer_token(self):
        """Test extraction of valid Bearer token."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="valid.token.here"
        )
        token = _extract_token_from_header(credentials)
        assert token == "valid.token.here"
    
    def test_extracts_case_insensitive_bearer(self):
        """Test Bearer scheme is case-insensitive."""
        credentials = HTTPAuthorizationCredentials(
            scheme="bearer",
            credentials="valid.token.here"
        )
        token = _extract_token_from_header(credentials)
        assert token == "valid.token.here"
        
        credentials = HTTPAuthorizationCredentials(
            scheme="BEARER",
            credentials="valid.token.here"
        )
        token = _extract_token_from_header(credentials)
        assert token == "valid.token.here"
    
    def test_raises_401_for_missing_credentials(self):
        """Test 401 raised when credentials are None."""
        with pytest.raises(HTTPException) as exc_info:
            _extract_token_from_header(None)
        
        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail
        assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}
    
    def test_raises_401_for_wrong_scheme(self):
        """Test 401 raised for non-Bearer scheme."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Basic",
            credentials="user:pass"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            _extract_token_from_header(credentials)
        
        assert exc_info.value.status_code == 401
        assert "Invalid authentication scheme" in exc_info.value.detail
    
    def test_raises_401_for_empty_token(self):
        """Test 401 raised for empty token."""
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=""
        )
        
        with pytest.raises(HTTPException) as exc_info:
            _extract_token_from_header(credentials)
        
        assert exc_info.value.status_code == 401


class TestPayloadToCurrentUser:
    """Tests for _payload_to_current_user."""
    
    def test_converts_valid_payload(self):
        """Test conversion of valid payload to CurrentUser."""
        user_id = uuid4()
        payload = {
            "sub": str(user_id),
            "role": "admin",
            "email": "admin@example.com"
        }
        
        user = _payload_to_current_user(payload)
        
        assert isinstance(user, CurrentUser)
        assert user.id == user_id
        assert user.role == "admin"
        assert user.email == "admin@example.com"
    
    def test_raises_401_for_missing_sub(self):
        """Test 401 raised when sub claim missing."""
        payload = {"role": "admin"}
        
        with pytest.raises(HTTPException) as exc_info:
            _payload_to_current_user(payload)
        
        assert exc_info.value.status_code == 401
        assert "missing user identifier" in exc_info.value.detail
    
    def test_raises_401_for_missing_role(self):
        """Test 401 raised when role claim missing."""
        payload = {"sub": str(uuid4())}
        
        with pytest.raises(HTTPException) as exc_info:
            _payload_to_current_user(payload)
        
        assert exc_info.value.status_code == 401
        assert "missing role claim" in exc_info.value.detail
    
    def test_raises_401_for_invalid_role(self):
        """Test 401 raised for invalid role."""
        payload = {
            "sub": str(uuid4()),
            "role": "hacker"
        }
        
        with pytest.raises(HTTPException) as exc_info:
            _payload_to_current_user(payload)
        
        assert exc_info.value.status_code == 401
        assert "Invalid role" in exc_info.value.detail
    
    def test_raises_401_for_invalid_uuid(self):
        """Test 401 raised for invalid UUID in sub."""
        payload = {
            "sub": "not-a-valid-uuid",
            "role": "admin"
        }
        
        with pytest.raises(HTTPException) as exc_info:
            _payload_to_current_user(payload)
        
        assert exc_info.value.status_code == 401
        assert "Invalid user identifier" in exc_info.value.detail
    
    def test_uses_empty_email_when_not_in_payload(self):
        """Test that empty email is used when not in token."""
        payload = {
            "sub": str(uuid4()),
            "role": "admin"
        }
        
        user = _payload_to_current_user(payload)
        
        assert user.email == ""


class TestCurrentUserModel:
    """Tests for CurrentUser model."""
    
    def test_is_admin_property(self):
        """Test is_admin property."""
        admin = CurrentUser(id=uuid4(), email="a@b.com", role="admin")
        annotator = CurrentUser(id=uuid4(), email="a@b.com", role="annotator")
        
        assert admin.is_admin is True
        assert annotator.is_admin is False
    
    def test_is_annotator_property(self):
        """Test is_annotator property."""
        annotator = CurrentUser(id=uuid4(), email="a@b.com", role="annotator")
        curator = CurrentUser(id=uuid4(), email="a@b.com", role="curator")
        
        assert annotator.is_annotator is True
        assert curator.is_annotator is False
    
    def test_is_curator_property(self):
        """Test is_curator property."""
        curator = CurrentUser(id=uuid4(), email="a@b.com", role="curator")
        admin = CurrentUser(id=uuid4(), email="a@b.com", role="admin")
        
        assert curator.is_curator is True
        assert admin.is_curator is False
    
    def test_has_role_single(self):
        """Test has_role with single role."""
        user = CurrentUser(id=uuid4(), email="a@b.com", role="admin")
        
        assert user.has_role("admin") is True
        assert user.has_role("annotator") is False
    
    def test_has_role_multiple(self):
        """Test has_role with multiple roles."""
        user = CurrentUser(id=uuid4(), email="a@b.com", role="annotator")
        
        assert user.has_role("annotator", "curator") is True
        assert user.has_role("admin", "curator") is False
    
    def test_model_is_immutable(self):
        """Test that CurrentUser is immutable (frozen)."""
        user = CurrentUser(id=uuid4(), email="a@b.com", role="admin")
        
        with pytest.raises(Exception):
            user.role = "annotator"


class TestRequireRole:
    """Tests for require_role dependency factory."""
    
    def test_validates_roles_at_definition(self):
        """Test that invalid roles raise ValueError at definition."""
        with pytest.raises(ValueError, match="Invalid roles"):
            require_role("admin", "invalid_role")
    
    def test_accepts_valid_roles(self):
        """Test that valid roles are accepted."""
        # Should not raise
        dep = require_role("admin")
        dep = require_role("annotator", "curator")
        dep = require_role("admin", "annotator", "curator")
    
    def test_returns_callable(self):
        """Test that require_role returns a callable."""
        dep = require_role("admin")
        assert callable(dep)


class TestAllowedRoles:
    """Tests for ALLOWED_ROLES constant."""
    
    def test_contains_expected_roles(self):
        """Test that allowed roles includes expected values."""
        assert "admin" in ALLOWED_ROLES
        assert "annotator" in ALLOWED_ROLES
        assert "curator" in ALLOWED_ROLES
    
    def test_does_not_contain_invalid_roles(self):
        """Test that invalid roles are not in allowed set."""
        assert "user" not in ALLOWED_ROLES
        assert "superadmin" not in ALLOWED_ROLES
        assert "" not in ALLOWED_ROLES
        assert "ADMIN" not in ALLOWED_ROLES  # Case sensitive


class TestVerifyTokenAndExtractPayload:
    """Tests for _verify_token_and_extract_payload."""
    
    @pytest.fixture
    def auth_service(self):
        """Create auth service with test secret."""
        service = jwt_auth_service
        service.secret_key = "test-secret-key-that-is-32-chars-long-for-security"
        return service
    
    def test_extracts_payload_from_valid_token(self, auth_service):
        """Test payload extraction from valid token."""
        user_id = uuid4()
        token = auth_service.create_access_token(user_id, "admin")
        
        payload = _verify_token_and_extract_payload(token)
        
        assert payload["sub"] == str(user_id)
        assert payload["role"] == "admin"
        assert payload["type"] == "access"
    
    def test_raises_401_for_expired_token(self, auth_service):
        """Test 401 raised for expired token."""
        import jwt
        
        # Create expired token manually
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid4()),
            "role": "admin",
            "iat": int((now - timedelta(hours=2)).timestamp()),
            "exp": int((now - timedelta(seconds=1)).timestamp()),
            "type": "access",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int((now - timedelta(hours=2)).timestamp()),
        }
        expired_token = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm="HS256"
        )
        
        with pytest.raises(HTTPException) as exc_info:
            _verify_token_and_extract_payload(expired_token)
        
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()
    
    def test_raises_401_for_invalid_token(self, auth_service):
        """Test 401 raised for invalid token."""
        with pytest.raises(HTTPException) as exc_info:
            _verify_token_and_extract_payload("invalid.token.here")
        
        assert exc_info.value.status_code == 401


class TestRequireAdmin:
    """Tests for require_admin convenience dependency."""
    
    def test_is_callable(self):
        """Test that require_admin is callable."""
        assert callable(require_admin)
