"""Tests for JWT Authentication Service."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4

import jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError

from app.services.auth_service import JWTAuthService, ALLOWED_ROLES


@pytest.fixture
def auth_service():
    """Create JWTAuthService instance for testing."""
    service = JWTAuthService()
    # Use test secret for isolation
    service.secret_key = "test-secret-key-that-is-32-chars-long-for-security"
    return service


@pytest.fixture
def test_user_id():
    """Sample user ID for tests."""
    return uuid4()


@pytest.fixture
def test_role():
    """Sample role for tests."""
    return "annotator"


class TestConfigurationValidation:
    """Tests for configuration validation."""
    
    def test_raises_error_for_empty_secret(self):
        """Test that empty secret key raises ValueError."""
        service = JWTAuthService()
        service.secret_key = ""
        
        with pytest.raises(ValueError, match="JWT_SECRET_KEY must be set"):
            service._validate_configuration()
    
    def test_raises_error_for_short_secret(self):
        """Test that short secret key raises ValueError."""
        service = JWTAuthService()
        service.secret_key = "short"
        
        with pytest.raises(ValueError, match="at least 32 characters"):
            service._validate_configuration()
    
    def test_raises_error_for_zero_expiry(self):
        """Test that zero expiration raises ValueError."""
        service = JWTAuthService()
        service.secret_key = "test-secret-key-that-is-32-chars-long-for-security"
        service.access_token_expire_minutes = 0
        
        with pytest.raises(ValueError, match="must be positive"):
            service._validate_configuration()


class TestRoleValidation:
    """Tests for role parameter validation."""
    
    def test_raises_error_for_empty_role(self, auth_service, test_user_id):
        """Test that empty role raises ValueError."""
        with pytest.raises(ValueError, match="Role cannot be empty"):
            auth_service.create_access_token(test_user_id, "")
    
    def test_raises_error_for_invalid_role(self, auth_service, test_user_id):
        """Test that invalid role raises ValueError."""
        with pytest.raises(ValueError, match="Invalid role"):
            auth_service.create_access_token(test_user_id, "hacker")
    
    def test_accepts_all_allowed_roles(self, auth_service, test_user_id):
        """Test that all allowed roles are accepted."""
        for role in ALLOWED_ROLES:
            token = auth_service.create_access_token(test_user_id, role)
            assert token is not None


class TestUserIdValidation:
    """Tests for user_id parameter validation."""
    
    def test_raises_error_for_none_user_id(self, auth_service, test_role):
        """Test that None user_id raises ValueError."""
        with pytest.raises(ValueError, match="must be a UUID instance"):
            auth_service.create_access_token(None, test_role)
    
    def test_raises_error_for_string_user_id(self, auth_service, test_role):
        """Test that string user_id raises ValueError."""
        with pytest.raises(ValueError, match="must be a UUID instance"):
            auth_service.create_access_token("not-a-uuid", test_role)


class TestCreateAccessToken:
    """Tests for access token creation."""
    
    def test_creates_valid_jwt(self, auth_service, test_user_id, test_role):
        """Test that a valid JWT is created."""
        token = auth_service.create_access_token(test_user_id, test_role)
        
        # Should be able to decode without errors
        payload = jwt.decode(
            token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        assert payload["sub"] == str(test_user_id)
        assert payload["role"] == test_role
        assert payload["type"] == "access"
    
    def test_contains_required_claims(self, auth_service, test_user_id, test_role):
        """Test that token contains all required claims."""
        token = auth_service.create_access_token(test_user_id, test_role)
        
        payload = jwt.decode(
            token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        assert "sub" in payload
        assert "role" in payload
        assert "iat" in payload
        assert "exp" in payload
        assert "type" in payload
        assert "iss" in payload
        assert "aud" in payload
        assert "nbf" in payload
    
    def test_has_correct_expiration(self, auth_service, test_user_id, test_role):
        """Test that token has correct expiration time."""
        before_create = datetime.now(timezone.utc)
        token = auth_service.create_access_token(test_user_id, test_role)
        after_create = datetime.now(timezone.utc)
        
        payload = jwt.decode(
            token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        exp_timestamp = payload["exp"]
        exp_datetime = datetime.fromtimestamp(exp_timestamp, tz=timezone.utc)
        
        expected_exp = before_create + timedelta(
            minutes=auth_service.access_token_expire_minutes
        )
        
        # Allow 1 second tolerance
        assert abs((exp_datetime - expected_exp).total_seconds()) < 1
    
    def test_iat_is_current_timestamp(self, auth_service, test_user_id, test_role):
        """Test that iat claim is set to current timestamp."""
        before_create = datetime.now(timezone.utc)
        token = auth_service.create_access_token(test_user_id, test_role)
        after_create = datetime.now(timezone.utc)
        
        payload = jwt.decode(
            token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        iat_datetime = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
        
        assert before_create <= iat_datetime <= after_create


class TestCreateRefreshToken:
    """Tests for refresh token creation."""
    
    def test_creates_valid_refresh_token(self, auth_service, test_user_id, test_role):
        """Test that a valid refresh token is created."""
        token = auth_service.create_refresh_token(test_user_id, test_role)
        
        payload = jwt.decode(
            token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        assert payload["sub"] == str(test_user_id)
        assert payload["role"] == test_role
        assert payload["type"] == "refresh"
    
    def test_has_longer_expiration(self, auth_service, test_user_id, test_role):
        """Test that refresh token has longer expiration than access token."""
        access_token = auth_service.create_access_token(test_user_id, test_role)
        refresh_token = auth_service.create_refresh_token(test_user_id, test_role)
        
        access_payload = jwt.decode(
            access_token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        refresh_payload = jwt.decode(
            refresh_token,
            auth_service.secret_key,
            algorithms=[auth_service.algorithm]
        )
        
        access_exp = access_payload["exp"]
        refresh_exp = refresh_payload["exp"]
        
        # Refresh token should expire later
        assert refresh_exp > access_exp


class TestVerifyToken:
    """Tests for token verification."""
    
    def test_returns_payload_for_valid_token(self, auth_service, test_user_id, test_role):
        """Test that valid token returns decoded payload."""
        token = auth_service.create_access_token(test_user_id, test_role)
        
        payload = auth_service.verify_token(token)
        
        assert payload["sub"] == str(test_user_id)
        assert payload["role"] == test_role
        assert payload["type"] == "access"
    
    def test_raises_error_for_expired_token(self, auth_service, test_user_id, test_role):
        """Test that expired token raises ExpiredSignatureError."""
        # Create token that expired 1 second ago
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(test_user_id),
            "role": test_role,
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
            algorithm=auth_service.algorithm
        )
        
        with pytest.raises(ExpiredSignatureError):
            auth_service.verify_token(expired_token)
    
    def test_raises_error_for_invalid_signature(self, auth_service, test_user_id, test_role):
        """Test that token with wrong secret raises error."""
        token = auth_service.create_access_token(test_user_id, test_role)
        
        # Try to decode with wrong secret
        with pytest.raises(InvalidTokenError):
            jwt.decode(token, "wrong_secret", algorithms=[auth_service.algorithm])
    
    def test_raises_error_for_malformed_token(self, auth_service):
        """Test that malformed token raises InvalidTokenError."""
        with pytest.raises(InvalidTokenError):
            auth_service.verify_token("not.a.valid.token")
    
    def test_raises_error_for_empty_token(self, auth_service):
        """Test that empty token raises InvalidTokenError."""
        with pytest.raises(InvalidTokenError, match="cannot be empty"):
            auth_service.verify_token("")
    
    def test_raises_error_for_whitespace_token(self, auth_service):
        """Test that whitespace-only token raises InvalidTokenError."""
        with pytest.raises(InvalidTokenError, match="cannot be empty"):
            auth_service.verify_token("   ")
    
    def test_validates_token_type_when_specified(self, auth_service, test_user_id, test_role):
        """Test that token type is validated when expected_type is specified."""
        access_token = auth_service.create_access_token(test_user_id, test_role)
        
        # Should raise error when expecting refresh token but got access token
        with pytest.raises(ValueError, match="Invalid token type"):
            auth_service.verify_token(access_token, expected_type="refresh")
    
    def test_allows_correct_token_type(self, auth_service, test_user_id, test_role):
        """Test that correct token type passes validation."""
        access_token = auth_service.create_access_token(test_user_id, test_role)
        
        # Should not raise error
        payload = auth_service.verify_token(access_token, expected_type="access")
        assert payload["type"] == "access"
    
    def test_raises_error_for_missing_claims(self, auth_service):
        """Test that token missing required claims is rejected."""
        # Create token without 'role' claim
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "type": "access",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int(now.timestamp()),
        }
        token = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm=auth_service.algorithm
        )
        
        with pytest.raises(InvalidTokenError):
            auth_service.verify_token(token)


class TestRefreshAccessToken:
    """Tests for access token refresh flow."""
    
    def test_creates_new_access_token(self, auth_service, test_user_id, test_role):
        """Test that refresh creates new access token."""
        refresh_token = auth_service.create_refresh_token(test_user_id, test_role)
        
        new_access_token = auth_service.refresh_access_token(refresh_token)
        
        # Verify new token is valid
        payload = auth_service.verify_token(new_access_token, expected_type="access")
        assert payload["sub"] == str(test_user_id)
        assert payload["role"] == test_role
    
    def test_requires_refresh_token_type(self, auth_service, test_user_id, test_role):
        """Test that only refresh tokens can be used for refresh."""
        access_token = auth_service.create_access_token(test_user_id, test_role)
        
        with pytest.raises(ValueError, match="Invalid token type"):
            auth_service.refresh_access_token(access_token)
    
    def test_raises_error_for_expired_refresh_token(self, auth_service, test_user_id, test_role):
        """Test that expired refresh token raises error."""
        # Create expired refresh token
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(test_user_id),
            "role": test_role,
            "iat": int((now - timedelta(days=10)).timestamp()),
            "exp": int((now - timedelta(seconds=1)).timestamp()),
            "type": "refresh",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int((now - timedelta(days=10)).timestamp()),
        }
        expired_refresh = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm=auth_service.algorithm
        )
        
        with pytest.raises(ExpiredSignatureError):
            auth_service.refresh_access_token(expired_refresh)
    
    def test_raises_error_for_missing_sub_claim(self, auth_service):
        """Test that refresh token without 'sub' claim raises error."""
        now = datetime.now(timezone.utc)
        payload = {
            "role": "annotator",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
            "type": "refresh",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int(now.timestamp()),
        }
        token = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm=auth_service.algorithm
        )
        
        with pytest.raises(InvalidTokenError, match="missing 'sub' claim"):
            auth_service.refresh_access_token(token)
    
    def test_raises_error_for_invalid_uuid_in_sub(self, auth_service, test_role):
        """Test that invalid UUID in 'sub' claim raises error."""
        now = datetime.now(timezone.utc)
        payload = {
            "sub": "not-a-valid-uuid",
            "role": test_role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
            "type": "refresh",
            "iss": "anotasi-api",
            "aud": "anotasi-client",
            "nbf": int(now.timestamp()),
        }
        token = jwt.encode(
            payload,
            auth_service.secret_key,
            algorithm=auth_service.algorithm
        )
        
        with pytest.raises(InvalidTokenError, match="Invalid user ID"):
            auth_service.refresh_access_token(token)
