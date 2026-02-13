import time
import uuid
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_ctx

logger = logging.getLogger("app.requests")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing, and set request_id context."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate unique request ID
        req_id = str(uuid.uuid4())[:8]  # Short ID for readability
        request_id_ctx.set(req_id)

        # Record start time
        start = time.perf_counter()

        # Process request
        response = await call_next(request)

        # Calculate duration
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        # Log request summary
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = req_id

        return response
