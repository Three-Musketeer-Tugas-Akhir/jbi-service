"""
Entry point for starting the JBI Detection & Segmentation API.

Configures uvicorn based on the ENVIRONMENT setting:
  - development: auto-reload, access logs, DEBUG-friendly
  - production:  no reload, no access log (structured JSON logging handles it)

Usage:
  python run.py                          # Uses defaults from .env
  ENVIRONMENT=production python run.py   # Production mode
"""

import uvicorn

from app.core.config import settings


def main():
    """Start uvicorn with environment-aware configuration."""
    is_prod = settings.is_production

    uvicorn_config = {
        "app": "app.main:app",
        "host": settings.uvicorn_host,
        "port": settings.uvicorn_port,
        # --- Workers ---
        # MVP uses 1 worker because the in-memory job store is per-process.
        # Multiple workers would each have their own job store, breaking
        # job status polling. When migrating to Redis/DB-backed job store,
        # increase workers to: min(2 * cpu_count + 1, 8)
        "workers": 1,
        # --- Reload ---
        # Development: watch for file changes and auto-restart.
        # Production: never reload — it disrupts active connections.
        "reload": not is_prod,
        # --- Access log ---
        # Production: disabled — Story 6.4 RequestLoggingMiddleware handles
        # request logging with request_id, timing, and JSON format.
        # Development: enabled — useful to see raw uvicorn access logs
        # alongside structured logs during debugging.
        "access_log": not is_prod,
        # --- Log level ---
        # Controls uvicorn's own logger. Application log level is set
        # separately by LOG_LEVEL via setup_logging() in Story 6.4.
        "log_level": settings.log_level.lower(),
    }

    print(
        f"Starting server — environment={settings.environment}, "
        f"host={settings.uvicorn_host}:{settings.uvicorn_port}, "
        f"reload={uvicorn_config['reload']}, "
        f"log_level={settings.log_level}"
    )

    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
