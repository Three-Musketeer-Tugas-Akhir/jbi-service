"""
Password Reset Service.

Handles password reset token generation, email sending, and password updates.
"""

import base64
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
from uuid import UUID

import bcrypt
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.password_reset_repository import PasswordResetRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

# Configuration
TOKEN_SECRET_LENGTH = 64  # Length of the random secret part
TOKEN_EXPIRY_HOURS = 1  # Token validity period
MAX_REQUESTS_PER_HOUR = 3  # Rate limiting


class PasswordResetService:
    """Service for password reset operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.token_repo = PasswordResetRepository(session)
        self.user_repo = UserRepository(session)
    
    def _generate_token_parts(self, token_id: UUID) -> tuple[str, str]:
        """
        Generate token parts for storage and transmission.
        
        Args:
            token_id: The UUID of the token record
            
        Returns:
            Tuple of (full_token_for_user, secret_for_hashing)
        """
        # Encode token_id as base64 (URL-safe, without padding)
        id_part = base64.urlsafe_b64encode(token_id.bytes).rstrip(b'=').decode('ascii')
        
        # Generate cryptographically secure random secret
        alphabet = string.ascii_letters + string.digits
        secret = ''.join(secrets.choice(alphabet) for _ in range(TOKEN_SECRET_LENGTH))
        
        # Full token format: <base64_id>_<secret>
        full_token = f"{id_part}_{secret}"
        
        return full_token, secret
    
    def _hash_secret(self, secret: str) -> str:
        """
        Hash a secret using bcrypt.
        
        Args:
            secret: Plain text secret
            
        Returns:
            Bcrypt hash of the secret
        """
        return bcrypt.hashpw(
            secret.encode('utf-8'), 
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')
    
    def _verify_secret(self, secret: str, secret_hash: str) -> bool:
        """
        Verify a secret against a hash.
        
        Args:
            secret: Plain text secret
            secret_hash: Bcrypt hash
            
        Returns:
            True if secret matches hash
        """
        return bcrypt.checkpw(
            secret.encode('utf-8'),
            secret_hash.encode('utf-8')
        )
    
    def _parse_token(self, token: str) -> Optional[tuple[UUID, str]]:
        """
        Parse a token into its ID and secret parts.
        
        Args:
            token: Full token string
            
        Returns:
            Tuple of (token_id, secret) or None if invalid
        """
        if '_' not in token:
            return None
        
        parts = token.split('_', 1)
        if len(parts) != 2:
            return None
        
        id_part, secret = parts
        
        try:
            # Add padding back for base64 decoding
            padding_needed = 4 - len(id_part) % 4
            if padding_needed != 4:
                id_part += '=' * padding_needed
            
            token_id_bytes = base64.urlsafe_b64decode(id_part)
            token_id = UUID(bytes=token_id_bytes)
            
            return token_id, secret
        except Exception:
            return None
    
    async def request_password_reset(
        self, 
        email: str
    ) -> Dict[str, Any]:
        """
        Request a password reset for a user.
        
        Args:
            email: User email address
            
        Returns:
            Dict with success status and message
            
        Note:
            Always returns success message even if email not found
            to prevent user enumeration attacks.
        """
        try:
            # Find user by email
            user = await self.user_repo.get_by_email(email)
            
            if user is None:
                # Return generic success to prevent user enumeration
                # But log for monitoring
                logger.info(f"Password reset requested for non-existent email: {email}")
                return {
                    "success": True,
                    "message": "If an account exists with this email, you will receive reset instructions."
                }
            
            # Check rate limiting
            recent_requests = await self.token_repo.count_recent_requests(
                user.id, 
                window_minutes=60
            )
            
            if recent_requests >= MAX_REQUESTS_PER_HOUR:
                logger.warning(f"Rate limit exceeded for password reset: {email}")
                return {
                    "success": False,
                    "message": "Too many reset requests. Please try again later.",
                    "retry_after": 3600  # Seconds
                }
            
            # Calculate expiration
            expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
            
            # Create token record first (to get the ID)
            # Use a placeholder hash initially - we'll update it
            placeholder_hash = bcrypt.hashpw(b'placeholder', bcrypt.gensalt()).decode('utf-8')
            token_record = await self.token_repo.create(
                user_id=user.id,
                token_hash=placeholder_hash,
                expires_at=expires_at
            )
            
            # Generate token parts using the record ID
            plain_token, secret = self._generate_token_parts(token_record.id)
            
            # Hash the secret and update the record
            secret_hash = self._hash_secret(secret)
            token_record.token_hash = secret_hash
            
            # Invalidate any other valid tokens for this user
            # (we already created this one, so it won't be affected)
            await self.token_repo.invalidate_all_for_user(user.id)
            
            await self.session.commit()
            
            # Send email (fire and forget - don't let email failures break the flow)
            try:
                await email_service.send_password_reset_email(
                    to_email=user.email,
                    reset_token=plain_token,
                    user_name=user.email  # TODO: Add name field to User model
                )
            except Exception as e:
                logger.error(f"Failed to send password reset email: {e}")
                # Still return success - user can request again
            
            return {
                "success": True,
                "message": "If an account exists with this email, you will receive reset instructions."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger.exception("Error requesting password reset")
            # Return generic success to prevent information leakage
            return {
                "success": True,
                "message": "If an account exists with this email, you will receive reset instructions."
            }
    
    async def reset_password(
        self, 
        token: str, 
        new_password: str
    ) -> Dict[str, Any]:
        """
        Reset password using a valid reset token.
        
        Args:
            token: Plain text reset token
            new_password: New password to set
            
        Returns:
            Dict with success status and message
        """
        try:
            # Validate password strength
            password_error = self._validate_password(new_password)
            if password_error:
                return {
                    "success": False,
                    "message": password_error
                }
            
            # Parse token to get ID and secret
            parsed = self._parse_token(token)
            if parsed is None:
                return {
                    "success": False,
                    "message": "Invalid reset token."
                }
            
            token_id, secret = parsed
            
            # Get token from database
            reset_token = await self.token_repo.get_by_id(token_id)
            
            if reset_token is None:
                return {
                    "success": False,
                    "message": "Invalid or expired reset token."
                }
            
            if reset_token.is_used:
                return {
                    "success": False,
                    "message": "This reset link has already been used."
                }
            
            if reset_token.is_expired:
                return {
                    "success": False,
                    "message": "This reset link has expired. Please request a new one."
                }
            
            # Verify the secret against the hash
            if not self._verify_secret(secret, reset_token.token_hash):
                return {
                    "success": False,
                    "message": "Invalid reset token."
                }
            
            # Get user
            user = await self.user_repo.get_by_id(reset_token.user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Hash new password
            password_hash = bcrypt.hashpw(
                new_password.encode('utf-8'),
                bcrypt.gensalt()
            ).decode('utf-8')
            
            # Update password
            await self.user_repo.update_password(user.id, password_hash)
            
            # Mark token as used
            await self.token_repo.mark_used(reset_token.id)
            
            # Invalidate all other password reset tokens for this user
            await self.token_repo.invalidate_all_for_user(user.id)
            
            await self.session.commit()
            
            logger.info(f"Password reset successful for user: {user.email}")
            
            return {
                "success": True,
                "message": "Password has been reset successfully. You can now log in with your new password."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger.exception("Error resetting password")
            return {
                "success": False,
                "message": "An error occurred while resetting your password. Please try again."
            }
    
    def _validate_password(self, password: str) -> Optional[str]:
        """
        Validate password strength.
        
        Args:
            password: Password to validate
            
        Returns:
            Error message if invalid, None if valid
        """
        if len(password) < 8:
            return "Password harus terdiri dari minimal 8 karakter."
        
        if len(password) > 128:
            return "Password tidak boleh lebih dari 128 karakter."
        
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in '!@#$%^&*()_+-=[]{}|;:,.<>?' for c in password)
        
        if not (has_upper and has_lower and has_digit):
            return "Password harus mengandung setidaknya satu huruf besar, satu huruf kecil, dan satu angka."
        
        if not has_special:
            return "Password harus mengandung setidaknya satu karakter spesial (!@#$%^&*()_+-=[]{}|;:,.<>?)."
        
        # Check for common patterns
        common_patterns = ['password', '123456', 'qwerty', 'abc123']
        password_lower = password.lower()
        for pattern in common_patterns:
            if pattern in password_lower:
                return "Password terlalu umum. Silakan pilih password yang lebih kuat."
        
        return None


# Note: Not a singleton - requires session
# Usage: PasswordResetService(session)
