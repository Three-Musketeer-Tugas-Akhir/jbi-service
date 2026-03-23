from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.formparsers import MultiPartParser

from app.core.config import settings
from app.db.session import engine
from app.db.base import Base
from app.api.v1 import admin, auth, health, jobs, users
from app.services.scheduler import start_cleanup_scheduler, stop_cleanup_scheduler
from app.core.exceptions import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import RequestLoggingMiddleware
from app.middleware.rate_limiter import LoginRateLimitMiddleware

# Initialize logging before anything else
setup_logging()

# Raise Starlette's multipart file-size limit to match our configured max
# (default is 1 GB, which rejects uploads above that with a generic 400)
MultiPartParser.max_file_size = settings.max_upload_size_bytes

import logging
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Starting JBI Detection & Segmentation API — "
        "model=%s, mode=%s, upload_dir=%s, output_dir=%s",
        settings.model_path,
        settings.processing_mode,
        settings.upload_dir,
        settings.output_dir,
    )
    # Create DB tables (safety net — Alembic is the primary migration tool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Eagerly load the YOLO model so the health check reports healthy
    from app.services.detector import get_detector
    get_detector()
    start_cleanup_scheduler()
    yield
    stop_cleanup_scheduler()
    await engine.dispose()
    logger.info("Shutting down")


app = FastAPI(
    title="JBI Detection & Segmentation API",
    version="1.0.0",
    description="API for detecting and segmenting JBI overlays in news broadcast videos.",
    lifespan=lifespan,
)

register_exception_handlers(app)

# Add rate limiting middleware (must be before logging to catch rate limit errors)
app.add_middleware(LoginRateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(auth.router, prefix=settings.api_v1_prefix, tags=["authentication"])
app.include_router(users.router, prefix=settings.api_v1_prefix, tags=["users"])
app.include_router(admin.router, prefix=settings.api_v1_prefix, tags=["admin"])
app.include_router(jobs.router, prefix=settings.api_v1_prefix, tags=["jobs"])


@app.get("/")
async def root():
    return {"message": "JBI Detection & Segmentation API"}
