"""Tests for password utilities."""

import pytest
import re

from app.core.security import (
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
