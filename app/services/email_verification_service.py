"""
Email Verification Service.

Handles email verification token generation, email sending, and verification.
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

from app.repositories.email_verification_repository import EmailVerificationRepository
from app.repositories.user_repository import UserRepository
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

# Configuration
TOKEN_SECRET_LENGTH = 64  # Length of the random secret part
TOKEN_EXPIRY_HOURS = 24  # Token validity period (longer than password reset)
MAX_RESEND_REQUESTS_PER_DAY = 5  # Rate limiting for resends


class EmailVerificationService:
    """Service for email verification operations."""
    
    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session
        self.token_repo = EmailVerificationRepository(session)
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
    
    async def send_verification_email(
        self, 
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Send verification email to a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Dict with success status and message
        """
        try:
            # Find user
            user = await self.user_repo.get_by_id(user_id)
            
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Check if already verified
            if user.is_email_verified:
                return {
                    "success": False,
                    "message": "Email is already verified."
                }
            
            # Check rate limiting (per day)
            recent_requests = await self.token_repo.count_recent_requests(
                user.id, 
                window_minutes=1440  # 24 hours
            )
            
            if recent_requests >= MAX_RESEND_REQUESTS_PER_DAY:
                logger.warning(f"Rate limit exceeded for verification emails: {user.email}")
                return {
                    "success": False,
                    "message": "Too many verification requests. Please try again later.",
                    "retry_after": 86400  # Seconds (24 hours)
                }
            
            # Calculate expiration
            expires_at = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS)
            
            # Create token record first (to get the ID)
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
            await self.token_repo.invalidate_all_for_user(user.id)
            
            await self.session.commit()
            
            # Send email
            try:
                await email_service.send_verification_email(
                    to_email=user.email,
                    verification_token=plain_token,
                    user_name=user.email  # TODO: Add name field to User model
                )
            except Exception as e:
                logger.error(f"Failed to send verification email: {e}")
                return {
                    "success": False,
                    "message": "Failed to send verification email. Please try again."
                }
            
            return {
                "success": True,
                "message": "Verification email sent. Please check your inbox."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger.exception("Error sending verification email")
            return {
                "success": False,
                "message": "An error occurred. Please try again."
            }
    
    async def verify_email(
        self, 
        token: str
    ) -> Dict[str, Any]:
        """
        Verify email using a valid verification token.
        
        Args:
            token: Plain text verification token
            
        Returns:
            Dict with success status and message
        """
        try:
            # Parse token to get ID and secret
            parsed = self._parse_token(token)
            if parsed is None:
                return {
                    "success": False,
                    "message": "Invalid verification token."
                }
            
            token_id, secret = parsed
            
            # Get token from database
            verification_token = await self.token_repo.get_by_id(token_id)
            
            if verification_token is None:
                return {
                    "success": False,
                    "message": "Invalid or expired verification token."
                }
            
            if verification_token.is_used:
                return {
                    "success": False,
                    "message": "This verification link has already been used."
                }
            
            if verification_token.is_expired:
                return {
                    "success": False,
                    "message": "This verification link has expired. Please request a new one."
                }
            
            # Verify the secret against the hash
            if not self._verify_secret(secret, verification_token.token_hash):
                return {
                    "success": False,
                    "message": "Invalid verification token."
                }
            
            # Get user
            user = await self.user_repo.get_by_id(verification_token.user_id)
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            # Check if already verified
            if user.is_email_verified:
                # Mark token as used anyway
                await self.token_repo.mark_used(verification_token.id)
                await self.session.commit()
                return {
                    "success": True,
                    "message": "Email is already verified."
                }
            
            # Mark email as verified
            user.mark_email_verified()
            
            # Mark token as used
            await self.token_repo.mark_used(verification_token.id)
            
            # Invalidate all other verification tokens for this user
            await self.token_repo.invalidate_all_for_user(user.id)
            
            await self.session.commit()
            
            logger.info(f"Email verified successfully for user: {user.email}")
            
            return {
                "success": True,
                "message": "Email verified successfully. You can now use all features."
            }
            
        except Exception as e:
            await self.session.rollback()
            logger.exception("Error verifying email")
            return {
                "success": False,
                "message": "An error occurred while verifying your email. Please try again."
            }
    
    async def get_verification_status(
        self, 
        user_id: UUID
    ) -> Dict[str, Any]:
        """
        Get email verification status for a user.
        
        Args:
            user_id: User UUID
            
        Returns:
            Dict with verification status
        """
        try:
            user = await self.user_repo.get_by_id(user_id)
            
            if user is None:
                return {
                    "success": False,
                    "message": "User not found."
                }
            
            return {
                "success": True,
                "is_verified": user.is_email_verified,
                "verified_at": user.email_verified_at.isoformat() if user.email_verified_at else None
            }
            
        except Exception as e:
            logger.exception("Error getting verification status")
            return {
                "success": False,
                "message": "An error occurred. Please try again."
            }


# Note: Not a singleton - requires session
# Usage: EmailVerificationService(session)
