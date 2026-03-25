"""Middleware for the JBI API."""

import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("app.middleware")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests."""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        
        # Log request
        logger.debug(f"{request.method} {request.url.path} - Started")
        
        response = await call_next(request)
        
        # Log response
        duration = time.time() - start_time
        logger.debug(
            f"{request.method} {request.url.path} - {response.status_code} ({duration:.3f}s)"
        )
        
        return response
