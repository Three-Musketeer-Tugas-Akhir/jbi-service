"""Tests for UserService."""

import pytest
import bcrypt
from uuid import UUID, uuid4

from app.services.user_service import UserService


@pytest.fixture
def auth_service():
    """Create UserService instance for testing."""
    # Note: This would need a real or mocked session in practice
    pass


@pytest.fixture
def test_user_id():
    """Sample user ID for tests."""
    return uuid4()


@pytest.fixture
def test_role():
    """Sample role for tests."""
    return "annotator"


class TestUserServiceHashPassword:
    """Tests for password hashing."""
    
    def test_hash_password(self):
        """Test password hashing."""
        password = "testpassword123"
        hashed = UserService.hash_password(password)
        
        # Verify it's a valid bcrypt hash
        assert hashed.startswith("$2b$")
        assert bcrypt.checkpw(password.encode(), hashed.encode())
    
    def test_hash_password_different_salts(self):
        """Test that same password produces different hashes."""
        password = "testpassword123"
        hash1 = UserService.hash_password(password)
        hash2 = UserService.hash_password(password)
        
        # Hashes should be different due to different salts
        assert hash1 != hash2
        
        # But both should verify correctly
        assert bcrypt.checkpw(password.encode(), hash1.encode())
        assert bcrypt.checkpw(password.encode(), hash2.encode())
