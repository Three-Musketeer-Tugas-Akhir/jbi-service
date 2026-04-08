"""
Audit Logging Middleware.

Automatically logs significant API operations for compliance and security monitoring.
This middleware captures authentication events and important state-changing operations.
"""

import time
from typing import Optional, Callable
from uuid import UUID

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.db.session import async_session_maker
from app.repositories.audit_log_repository import AuditLogRepository
from app.db.models.audit import AuditAction


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for automatic audit logging.
    
    Logs the following events:
    - Failed login attempts (for security monitoring)
    - Successful logouts
    - Token refreshes
    
    Non-blocking: Audit logging failures don't affect the main request.
    """
    
    # Paths that should be audited
    AUDIT_PATHS = {
        "/api/v1/auth/login": AuditAction.USER_LOGIN,
        "/api/v1/auth/logout": AuditAction.USER_LOGOUT,
        "/api/v1/auth/refresh": AuditAction.TOKEN_REFRESHED,
    }
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request and log audit events.
        
        Args:
            request: The incoming request
            call_next: Next middleware/handler in chain
            
        Returns:
            Response from downstream handlers
        """
        start_time = time.time()
        
        # Process the request first
        response = await call_next(request)
        
        # Check if this path should be audited
        path = request.url.path
        if path in self.AUDIT_PATHS:
            await self._log_audit_event(request, response, self.AUDIT_PATHS[path])
        
        # Log failed login attempts (401 on login endpoint)
        if path == "/api/v1/auth/login" and response.status_code == 401:
            await self._log_failed_login(request)
        
        return response
    
    async def _log_audit_event(
        self,
        request: Request,
        response: Response,
        action: str
    ) -> None:
        """
        Log an audit event.
        
        Args:
            request: The HTTP request
            response: The HTTP response
            action: The audit action type
        """
        try:
            # Get user info from request state (set by auth middleware)
            user_id = getattr(request.state, "user_id", None)
            if user_id and isinstance(user_id, str):
                try:
                    user_id = UUID(user_id)
                except ValueError:
                    user_id = None
            
            # Get IP address
            ip_address = self._get_client_ip(request)
            
            # Get user agent
            user_agent = request.headers.get("User-Agent")
            
            # Build details
            details = {
                "method": request.method,
                "path": str(request.url.path),
                "status_code": response.status_code,
            }
            if user_agent:
                details["user_agent"] = user_agent
            
            # Create audit log entry
            async with async_session_maker() as session:
                audit_repo = AuditLogRepository(session)
                await audit_repo.create(
                    action=action,
                    resource_type="auth",
                    actor_id=user_id,
                    resource_id=user_id,  # For auth events, resource is the user
                    details=details,
                    ip_address=ip_address
                )
                await session.commit()
                
        except Exception:
            # Audit logging should never break the main request
            # In production, you might want to log this to a separate error log
            pass
    
    async def _log_failed_login(self, request: Request) -> None:
        """
        Log a failed login attempt for security monitoring.
        
        Args:
            request: The login request that failed
        """
        try:
            # Get IP address
            ip_address = self._get_client_ip(request)
            
            # Get user agent
            user_agent = request.headers.get("User-Agent")
            
            # Try to get attempted email from request body
            attempted_email = None
            try:
                # Only attempt to read body if it's a POST with JSON
                if request.method == "POST":
                    body = await request.body()
                    if body:
                        import json
                        data = json.loads(body)
                        attempted_email = data.get("email")
            except Exception:
                pass
            
            # Build details
            details = {
                "method": request.method,
                "path": str(request.url.path),
                "attempted_email": attempted_email,
            }
            if user_agent:
                details["user_agent"] = user_agent
            
            # Create audit log entry
            async with async_session_maker() as session:
                audit_repo = AuditLogRepository(session)
                await audit_repo.create(
                    action=AuditAction.USER_LOGIN_FAILED,
                    resource_type="auth",
                    actor_id=None,  # No user for failed login
                    resource_id=None,
                    details=details,
                    ip_address=ip_address
                )
                await session.commit()
                
        except Exception:
            # Audit logging should never break the main request
            pass
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Get client IP address from request.
        
        Handles X-Forwarded-For header for requests behind proxies.
        
        Args:
            request: The HTTP request
            
        Returns:
            Client IP address or None
        """
        # Check X-Forwarded-For header first (for users behind proxy/load balancer)
        x_forwarded_for = request.headers.get("X-Forwarded-For")
        if x_forwarded_for:
            # Take the first IP if multiple are present
            return x_forwarded_for.split(",")[0].strip()
        
        # Fall back to direct client
        if request.client:
            return request.client.host
        
        return None


class AuditContext:
    """
    Context manager for manual audit logging in route handlers.
    
    Example:
        async with AuditContext() as audit:
            await audit.log(
                action=AuditAction.JOB_CREATED,
                resource_type="job",
                resource_id=job.id,
                details={"filename": filename}
            )
    """
    
    def __init__(self, user_id: Optional[UUID] = None, ip_address: Optional[str] = None):
        self.user_id = user_id
        self.ip_address = ip_address
        self.session = None
        self.repo = None
    
    async def __aenter__(self):
        self.session = async_session_maker()
        self.repo = AuditLogRepository(self.session)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def log(
        self,
        action: str,
        resource_type: str,
        resource_id: Optional[UUID] = None,
        details: Optional[dict] = None
    ) -> None:
        """
        Create an audit log entry.
        
        Args:
            action: Action type (use AuditAction constants)
            resource_type: Type of resource affected
            resource_id: ID of affected resource
            details: Additional details
        """
        try:
            await self.repo.create(
                action=action,
                resource_type=resource_type,
                actor_id=self.user_id,
                resource_id=resource_id,
                details=details or {},
                ip_address=self.ip_address
            )
            await self.session.commit()
        except Exception:
            # Audit logging should never break the main operation
            pass


def get_audit_logger(
    user_id: Optional[UUID] = None,
    ip_address: Optional[str] = None
) -> AuditContext:
    """
    Get an audit logger context manager.
    
    Args:
        user_id: The user performing the action
        ip_address: Client IP address
        
    Returns:
        AuditContext for logging
        
    Example:
        async with get_audit_logger(user_id=user.id, ip_address=ip) as audit:
            await audit.log(action=AuditAction.JOB_CREATED, ...)
    """
    return AuditContext(user_id=user_id, ip_address=ip_address)
