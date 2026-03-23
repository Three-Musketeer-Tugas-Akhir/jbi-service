"""
Email Service.

Provides email sending capabilities for notifications and password reset.
In production, this integrates with SMTP or transactional email services.
"""

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending emails.
    
    Currently supports console logging for development.
    Production should integrate with SMTP (sendgrid, AWS SES, etc.)
    """
    
    def __init__(self) -> None:
        """Initialize email service with configuration."""
        self.from_email = getattr(settings, 'email_from', 'noreply@anotasi.ai')
        self.app_name = getattr(settings, 'app_name', 'Anotasi AI')
        self.frontend_url = getattr(settings, 'frontend_url', 'http://localhost:3000')
    
    async def send_password_reset_email(
        self, 
        to_email: str, 
        reset_token: str,
        user_name: Optional[str] = None
    ) -> bool:
        """
        Send password reset email to user.
        
        Args:
            to_email: Recipient email address
            reset_token: Plain text reset token (will be included in reset URL)
            user_name: Optional user name for personalization
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        reset_url = f"{self.frontend_url}/reset-password?token={reset_token}"
        
        subject = f"Reset your password - {self.app_name}"
        
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        body_text = f"""
{greeting}

You recently requested to reset your password for your {self.app_name} account.

Click the link below to reset your password:
{reset_url}

This link will expire in 1 hour for security reasons.

If you did not request a password reset, please ignore this email or contact support if you have concerns.

Best regards,
The {self.app_name} Team
"""
        
        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{subject}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2c3e50;">{subject}</h2>
        
        <p>{greeting}</p>
        
        <p>You recently requested to reset your password for your {self.app_name} account.</p>
        
        <p style="margin: 30px 0;">
            <a href="{reset_url}" 
               style="background-color: #3498db; color: white; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; display: inline-block;">
                Reset Password
            </a>
        </p>
        
        <p>Or copy and paste this link into your browser:</p>
        <p style="word-break: break-all; color: #666;">{reset_url}</p>
        
        <p style="color: #e74c3c; font-weight: bold;">
            This link will expire in 1 hour for security reasons.
        </p>
        
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        
        <p style="color: #666; font-size: 14px;">
            If you did not request a password reset, please ignore this email or 
            contact support if you have concerns.
        </p>
        
        <p style="color: #666; font-size: 14px;">
            Best regards,<br>
            The {self.app_name} Team
        </p>
    </div>
</body>
</html>
"""
        
        # For now, just log the email content
        # In production, this would send via SMTP or email API
        logger.info(f"=" * 60)
        logger.info(f"PASSWORD RESET EMAIL")
        logger.info(f"=" * 60)
        logger.info(f"To: {to_email}")
        logger.info(f"From: {self.from_email}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Reset URL: {reset_url}")
        logger.info(f"=" * 60)
        
        # TODO: Implement actual email sending
        # Example with SMTP:
        # await self._send_smtp_email(to_email, subject, body_text, body_html)
        
        return True
    
    async def send_verification_email(
        self, 
        to_email: str, 
        verification_token: str,
        user_name: Optional[str] = None
    ) -> bool:
        """
        Send email verification email to user.
        
        Args:
            to_email: Recipient email address
            verification_token: Plain text verification token
            user_name: Optional user name for personalization
            
        Returns:
            True if email was sent successfully, False otherwise
        """
        verify_url = f"{self.frontend_url}/verify-email?token={verification_token}"
        
        subject = f"Verify your email - {self.app_name}"
        
        greeting = f"Hello {user_name}," if user_name else "Hello,"
        
        body_text = f"""
{greeting}

Welcome to {self.app_name}! Please verify your email address to complete your registration.

Click the link below to verify your email:
{verify_url}

This link will expire in 24 hours for security reasons.

If you did not create an account with us, please ignore this email.

Best regards,
The {self.app_name} Team
"""
        
        body_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{subject}</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
    <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2c3e50;">{subject}</h2>
        
        <p>{greeting}</p>
        
        <p>Welcome to {self.app_name}! Please verify your email address to complete your registration.</p>
        
        <p style="margin: 30px 0;">
            <a href="{verify_url}" 
               style="background-color: #27ae60; color: white; padding: 12px 30px; 
                      text-decoration: none; border-radius: 5px; display: inline-block;">
                Verify Email Address
            </a>
        </p>
        
        <p>Or copy and paste this link into your browser:</p>
        <p style="word-break: break-all; color: #666;">{verify_url}</p>
        
        <p style="color: #e74c3c; font-weight: bold;">
            This link will expire in 24 hours for security reasons.
        </p>
        
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        
        <p style="color: #666; font-size: 14px;">
            If you did not create an account with us, please ignore this email.
        </p>
        
        <p style="color: #666; font-size: 14px;">
            Best regards,<br>
            The {self.app_name} Team
        </p>
    </div>
</body>
</html>
"""
        
        # For now, just log the email content
        logger.info(f"=" * 60)
        logger.info(f"EMAIL VERIFICATION EMAIL")
        logger.info(f"=" * 60)
        logger.info(f"To: {to_email}")
        logger.info(f"From: {self.from_email}")
        logger.info(f"Subject: {subject}")
        logger.info(f"Verify URL: {verify_url}")
        logger.info(f"=" * 60)
        
        # TODO: Implement actual email sending
        
        return True
    
    async def _send_smtp_email(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None
    ) -> bool:
        """
        Send email via SMTP (placeholder for production implementation).
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body
            
        Returns:
            True if sent successfully
        """
        # This is a placeholder for actual SMTP implementation
        # Would use aiosmtplib or similar for async SMTP
        
        smtp_host = getattr(settings, 'smtp_host', None)
        smtp_port = getattr(settings, 'smtp_port', 587)
        smtp_user = getattr(settings, 'smtp_user', None)
        smtp_password = getattr(settings, 'smtp_password', None)
        
        if not smtp_host:
            logger.warning("SMTP not configured, email not sent")
            return False
        
        # Implementation would go here
        # import aiosmtplib
        # ...
        
        return True


# Singleton instance for dependency injection
email_service = EmailService()
