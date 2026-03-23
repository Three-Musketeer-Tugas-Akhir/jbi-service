"""
Rate Limiting Middleware.

Simple in-memory rate limiter for login attempts.
For production, consider Redis-based rate limiting.
"""

import time
from typing import Dict, Tuple, Optional
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


class RateLimiter:
    """Simple in-memory rate limiter."""
    
    def __init__(self):
        """Initialize rate limiter storage."""
        # Store: {client_ip: [timestamp, timestamp, ...]}
        self._attempts: Dict[str, list] = {}
    
    def is_allowed(self, client_ip: str) -> Tuple[bool, int]:
        """
        Check if request is allowed.
        
        Args:
            client_ip: Client IP address
            
        Returns:
            Tuple of (allowed: bool, remaining_attempts: int)
        """
        now = time.time()
        window = settings.rate_limit_window_seconds
        max_attempts = settings.rate_limit_login_attempts
        
        # Get attempts for this IP
        attempts = self._attempts.get(client_ip, [])
        
        # Filter to only include attempts within the window
        recent_attempts = [
            ts for ts in attempts 
            if now - ts < window
        ]
        
        # Update stored attempts (cleanup old ones)
        self._attempts[client_ip] = recent_attempts
        
        # Check if under limit
        current_count = len(recent_attempts)
        if current_count >= max_attempts:
            return False, 0
        
        return True, max_attempts - current_count
    
    def record_attempt(self, client_ip: str) -> None:
        """Record a failed attempt."""
        now = time.time()
        if client_ip not in self._attempts:
            self._attempts[client_ip] = []
        self._attempts[client_ip].append(now)
        # Cleanup old entries periodically (simple approach)
        self._cleanup_old_entries()
    
    def _cleanup_old_entries(self, max_age: int = 3600) -> None:
        """Remove entries older than max_age seconds to prevent memory leak."""
        now = time.time()
        cutoff = now - max_age
        
        # Remove old timestamps from each IP
        for ip in list(self._attempts.keys()):
            self._attempts[ip] = [ts for ts in self._attempts[ip] if ts > cutoff]
            # Remove IP entirely if no recent attempts
            if not self._attempts[ip]:
                del self._attempts[ip]


# Global rate limiter instance
rate_limiter = RateLimiter()


class LoginRateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to apply rate limiting to login endpoint."""
    
    async def dispatch(self, request: Request, call_next):
        """Process request with rate limiting."""
        # Only apply to login endpoint
        if request.url.path == "/api/v1/auth/login" and request.method == "POST":
            client_ip = self._get_client_ip(request)
            
            allowed, remaining = rate_limiter.is_allowed(client_ip)
            
            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail="Too many attempts, try again later"
                )
            
            # Store rate limit info in request state for response headers
            request.state.rate_limit_remaining = remaining
        
        response = await call_next(request)
        return response
    
    def _get_client_ip(self, request: Request) -> str:
        """Extract client IP from request."""
        # Check for forwarded IP (behind proxy)
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        
        # Fall back to direct connection
        if request.client:
            return request.client.host
        
        return "unknown"


def record_failed_login(request: Request) -> None:
    """Record a failed login attempt."""
    client_ip = _extract_client_ip(request)
    rate_limiter.record_attempt(client_ip)


def _extract_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    
    if request.client:
        return request.client.host
    
    return "unknown"
