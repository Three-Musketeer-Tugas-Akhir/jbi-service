import time
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import request_id_ctx, JSONFormatter

logger = logging.getLogger("app.requests")

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)


def _make_log_filename(req_id: str, method: str, path: str) -> str:
    """Build a descriptive log filename for a request."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    # Sanitise URL path for use in filename
    safe_path = path.strip("/").replace("/", "_") or "root"
    return f"{ts}_{method}_{safe_path}_{req_id}.log"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with timing, and set request_id context.

    Each request also gets its own .log file under logs/.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate unique request ID
        req_id = str(uuid.uuid4())[:8]  # Short ID for readability
        request_id_ctx.set(req_id)

        # --- Attach a per-request file handler ---
        log_filename = _make_log_filename(
            req_id, request.method, request.url.path,
        )
        file_handler = logging.FileHandler(
            LOGS_DIR / log_filename, encoding="utf-8",
        )
        file_handler.setFormatter(JSONFormatter())
        file_handler.setLevel(logging.DEBUG)

        root_logger = logging.getLogger()
        root_logger.addHandler(file_handler)

        # Record start time
        start = time.perf_counter()

        try:
            # Process request
            response = await call_next(request)
        finally:
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

            # --- Detach and close the per-request file handler ---
            file_handler.flush()
            file_handler.close()
            root_logger.removeHandler(file_handler)

        # Add request ID to response headers
        response.headers["X-Request-ID"] = req_id

        return response
