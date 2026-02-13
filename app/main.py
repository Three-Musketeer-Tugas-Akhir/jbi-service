from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import health, jobs
from app.services.scheduler import start_cleanup_scheduler, stop_cleanup_scheduler
from app.exception_handlers import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import RequestLoggingMiddleware

# Initialize logging before anything else
setup_logging()

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
    start_cleanup_scheduler()
    yield
    stop_cleanup_scheduler()
    logger.info("Shutting down")


app = FastAPI(
    title="JBI Detection & Segmentation API",
    version="1.0.0",
    description="API for detecting and segmenting JBI overlays in news broadcast videos.",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(jobs.router, prefix=settings.api_v1_prefix, tags=["jobs"])


@app.get("/")
async def root():
    return {"message": "JBI Detection & Segmentation API"}
