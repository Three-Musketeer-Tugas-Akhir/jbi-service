"""
Password Utilities.

Provides password generation and validation utilities.
"""

import re
import secrets
import string
from typing import Optional, Tuple


# Password strength requirements
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

# Character sets for password generation
LOWERCASE_CHARS = string.ascii_lowercase
UPPERCASE_CHARS = string.ascii_uppercase
DIGIT_CHARS = string.digits
SPECIAL_CHARS = "!@#$%^&*()_+-=[]{}|;:,.<>?"
ALL_CHARS = LOWERCASE_CHARS + UPPERCASE_CHARS + DIGIT_CHARS + SPECIAL_CHARS

# Common weak passwords to check against
COMMON_PASSWORDS = {
    'password', '123456', '12345678', 'qwerty', 'abc123',
    'monkey', 'letmein', 'dragon', '111111', 'baseball',
    'iloveyou', 'trustno1', 'sunshine', 'princess', 'admin',
    'welcome', 'shadow', 'ashley', 'football', 'jesus',
    'michael', 'ninja', 'mustang', 'password1', '123456789',
    'adobe123', 'admin123', 'root', 'toor', 'guest',
    'default', 'changeme', 'p@ssw0rd', 'passw0rd', 'qwerty123'
}


def generate_temporary_password(length: int = 16) -> str:
    """
    Generate a secure temporary password.
    
    Generates a random password that meets all strength requirements:
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - No ambiguous characters (0, O, 1, l, I) in default generation
    
    Args:
        length: Password length (default: 16, min: 12, max: 128)
        
    Returns:
        Generated password string
        
    Raises:
        ValueError: If length is less than 12 or greater than 128
    """
    if length < 12:
        length = 12
    if length > MAX_PASSWORD_LENGTH:
        length = MAX_PASSWORD_LENGTH
    
    # Remove ambiguous characters for better usability
    safe_lowercase = 'abcdefghjkmnpqrstuvwxyz'  # no: l, o
    safe_uppercase = 'ABCDEFGHJKMNPQRSTUVWXYZ'  # no: L, O, I
    safe_digits = '23456789'  # no: 0, 1
    safe_special = '!@#$%^&*()_+-=[]{}|;:,.<>?'
    
    safe_all = safe_lowercase + safe_uppercase + safe_digits + safe_special
    
    # Ensure we have at least one of each required character type
    password_chars = [
        secrets.choice(safe_uppercase),
        secrets.choice(safe_lowercase),
        secrets.choice(safe_digits),
        secrets.choice(safe_special),
    ]
    
    # Fill the rest with random characters
    remaining_length = length - len(password_chars)
    password_chars.extend(secrets.choice(safe_all) for _ in range(remaining_length))
    
    # Shuffle to randomize positions
    secrets.SystemRandom().shuffle(password_chars)
    
    return ''.join(password_chars)


def validate_password_strength(password: str) -> Tuple[bool, Optional[str]]:
    """
    Validate password strength according to security requirements.
    
    Requirements:
    - Minimum 8 characters
    - Maximum 128 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit
    - At least one special character
    - Not a common/weak password
    - No repeated characters more than 3 times consecutively
    
    Args:
        password: Password to validate
        
    Returns:
        Tuple of (is_valid: bool, error_message: str or None)
        If valid, error_message is None
    """
    # Check length
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    
    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must not exceed {MAX_PASSWORD_LENGTH} characters."
    
    # Check character types
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in SPECIAL_CHARS for c in password)
    
    if not has_upper:
        return False, "Password must contain at least one uppercase letter."
    
    if not has_lower:
        return False, "Password must contain at least one lowercase letter."
    
    if not has_digit:
        return False, "Password must contain at least one digit."
    
    if not has_special:
        return False, f"Password must contain at least one special character ({SPECIAL_CHARS})."
    
    # Check for common passwords (exact match and base word)
    password_lower = password.lower()
    if password_lower in COMMON_PASSWORDS:
        return False, "Password is too common. Please choose a stronger password."
    
    # Check if password starts with or contains common base words
    for common in COMMON_PASSWORDS:
        if len(common) >= 4:  # Only check longer common words
            # Check if common word is at the start or end
            if password_lower.startswith(common) or password_lower.endswith(common):
                return False, "Password is too common. Please choose a stronger password."
            # Check if common word is in the middle (for passwords like "xyzpassword123")
            if common in password_lower:
                return False, "Password is too common. Please choose a stronger password."
    
    # Check for repeated characters (e.g., "aaaa", "1111")
    if re.search(r'(.)\1{3,}', password):
        return False, "Password contains too many repeated characters."
    
    # Check for sequential characters (e.g., "abcd", "1234")
    sequential_patterns = [
        'abcdefghijklmnopqrstuvwxyz',
        'zyxwvutsrqponmlkjihgfedcba',
        '0123456789',
        '9876543210'
    ]
    
    for pattern in sequential_patterns:
        for i in range(len(pattern) - 3):
            if pattern[i:i+4] in password_lower:
                return False, "Password contains sequential characters (e.g., 'abcd', '1234')."
    
    # Check for keyboard patterns (e.g., "qwerty", "asdf")
    keyboard_patterns = ['qwerty', 'asdf', 'zxcv', 'qazwsx', '!@#$%^&*()']
    for pattern in keyboard_patterns:
        if pattern in password_lower:
            return False, "Password contains keyboard patterns."
    
    return True, None


def check_password_entropy(password: str) -> float:
    """
    Calculate password entropy in bits.
    
    Higher entropy means stronger password.
    
    Args:
        password: Password to analyze
        
    Returns:
        Entropy value in bits
    """
    # Determine character set size based on password composition
    charset_size = 0
    if any(c.islower() for c in password):
        charset_size += 26
    if any(c.isupper() for c in password):
        charset_size += 26
    if any(c.isdigit() for c in password):
        charset_size += 10
    if any(c in SPECIAL_CHARS for c in password):
        charset_size += len(SPECIAL_CHARS)
    
    if charset_size == 0:
        return 0.0
    
    # Calculate entropy: log2(charset_size ^ length)
    import math
    entropy = len(password) * math.log2(charset_size)
    return round(entropy, 2)


def is_password_strong(password: str, min_entropy: float = 50.0) -> bool:
    """
    Check if password is strong based on entropy.
    
    Args:
        password: Password to check
        min_entropy: Minimum required entropy (default: 50 bits)
        
    Returns:
        True if password meets entropy requirement
    """
    is_valid, _ = validate_password_strength(password)
    if not is_valid:
        return False
    
    entropy = check_password_entropy(password)
    return entropy >= min_entropy
