"""
Email Service.

Abstract email service with stub and SMTP implementations.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailService(ABC):
    """Abstract base class for email services."""
    
    @abstractmethod
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """
        Send user invitation email.
        
        Args:
            to_email: Recipient email address
            temporary_password: Temporary password for login
            role: Assigned role
            
        Returns:
            True if email queued/sent successfully
        """
        pass


class StubEmailService(EmailService):
    """
    Stub email service for development/MVP.
    
    Logs emails instead of sending them.
    """
    
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """Log invitation instead of sending."""
        logger.info(
            "[STUB EMAIL] Invitation to %s - Role: %s - Temp Password: %s",
            to_email,
            role,
            temporary_password
        )
        return True


class SmtpEmailService(EmailService):
    """
    SMTP email service for production.
    
    Sends actual emails via SMTP.
    """
    
    def __init__(self):
        """Initialize SMTP configuration."""
        self.smtp_host = settings.smtp_host
        self.smtp_port = settings.smtp_port
        self.smtp_user = settings.smtp_user
        self.smtp_password = settings.smtp_password
        self.from_email = settings.from_email
    
    async def send_user_invitation(
        self,
        to_email: str,
        temporary_password: str,
        role: str
    ) -> bool:
        """Send actual invitation email via SMTP."""
        # Implementation for production
        # This is a placeholder - implement with aiosmtplib or similar
        logger.info("Sending email to %s via SMTP", to_email)
        # TODO: Implement actual SMTP sending
        return True


# Factory function to get email service
def get_email_service() -> EmailService:
    """
    Get email service instance based on configuration.
    
    Returns:
        EmailService instance
    """
    if settings.is_production:
        return SmtpEmailService()
    return StubEmailService()


# Singleton instance
email_service = get_email_service()
