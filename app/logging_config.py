import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

from app.config import settings

# Context variables for request-scoped data
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
job_id_ctx: ContextVar[str] = ContextVar("job_id", default="")


class JSONFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add request context if available
        req_id = request_id_ctx.get("")
        if req_id:
            log_entry["request_id"] = req_id

        # Add job context if available
        j_id = job_id_ctx.get("")
        if j_id:
            log_entry["job_id"] = j_id

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging():
    """Configure application-wide structured JSON logging."""
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Create JSON formatter
    formatter = JSONFormatter()

    # Configure root logger
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers
    root.handlers.clear()

    # Add stdout handler with JSON formatter
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("ultralytics").setLevel(logging.WARNING)
    logging.getLogger("moviepy").setLevel(logging.WARNING)

    logging.getLogger("app").info(
        "Logging configured — level=%s, format=JSON", settings.log_level,
    )
