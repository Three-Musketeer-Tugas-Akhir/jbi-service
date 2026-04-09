"""
JBI Detection & Segmentation API

This is the main FastAPI application with comprehensive Swagger/OpenAPI documentation.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from starlette.formparsers import MultiPartParser

from app.core.config import settings
from app.core.swagger_config import TAGS_METADATA, SECURITY_SCHEMES, SWAGGER_UI_CONFIG, REDOC_CONFIG
from app.db.session import engine
from app.db.base import Base
from app.api.v1 import admin, admin_audit, admin_annotations, annotations, annotation_sync, asr_review, assets, auth, health, jobs, users, upload
from app.services.scheduler import start_cleanup_scheduler, stop_cleanup_scheduler
from app.core.exceptions import register_exception_handlers
from app.logging_config import setup_logging
from app.middleware import RequestLoggingMiddleware
from app.middleware.rate_limiter import LoginRateLimitMiddleware
from app.middleware.audit_middleware import AuditLoggingMiddleware

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
    from app.pipeline.models.detector import get_detector
    get_detector()
    start_cleanup_scheduler()
    yield
    stop_cleanup_scheduler()
    await engine.dispose()
    logger.info("Shutting down")


# ============================================================================
# FastAPI Application
# ============================================================================

app = FastAPI(
    title="JBI Detection & Segmentation API",
    version="1.0.0",
    description="""
    **JBI Detection & Segmentation API** provides comprehensive video processing capabilities
    for detecting and segmenting news broadcast overlays.
    
    ## Key Features
    
    - **Video Processing**: Upload and process news broadcast videos with YOLO-based JBI detection
    - **ASR Pipeline**: Automatic speech recognition with confidence scoring
    - **Annotation Workflow**: Collaborative annotation system with draft, review, and approval stages
    - **User Management**: Role-based access control (RBAC) with admin, annotator, and curator roles
    - **System Monitoring**: Health checks, metrics, and administrative endpoints
    
    ## Authentication
    
    All protected endpoints require a Bearer token. Obtain a token via `/api/v1/auth/login`.
    
    ## Roles
    
    - **admin**: Full system access including user management and configuration
    - **annotator**: Can process ASR reviews and create annotations
    - **curator**: Reviews and approves annotation submissions
    
    ## Rate Limiting
    
    Authentication endpoints have rate limiting (5 attempts per 15 minutes).
    """,
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
    docs_url=None,  # Disable default docs URL - we'll create custom ones
    redoc_url=None,  # Disable default redoc URL - we'll create custom ones
    openapi_url="/openapi.json",
    contact={
        "name": "JBI API Support",
        "email": "support@jbi-api.local",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
)

register_exception_handlers(app)

# Add rate limiting middleware (must be before logging to catch rate limit errors)
app.add_middleware(LoginRateLimitMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(AuditLoggingMiddleware)

# Conditionally add CORS middleware
if settings.cors_enabled:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    logger.info(f"CORS enabled with origins: {settings.cors_origins_list}")
else:
    logger.warning("CORS is DISABLED - all origins allowed without CORS checks")

# ============================================================================
# Custom Swagger UI & ReDoc Endpoints
# ============================================================================

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """Custom Swagger UI with enhanced configuration."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - Swagger UI",
        swagger_js_url=SWAGGER_UI_CONFIG["swagger_js_url"],
        swagger_css_url=SWAGGER_UI_CONFIG["swagger_css_url"],
        swagger_favicon_url=SWAGGER_UI_CONFIG["swagger_favicon_url"],
        init_oauth=SWAGGER_UI_CONFIG["init_oauth"],
    )


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    """ReDoc documentation endpoint."""
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=f"{app.title} - ReDoc",
        redoc_js_url=REDOC_CONFIG["redoc_js_url"],
        redoc_favicon_url=REDOC_CONFIG["redoc_favicon_url"],
    )


# ============================================================================
# Custom OpenAPI Schema with Security Schemes
# ============================================================================

def custom_openapi():
    """Generate custom OpenAPI schema with security schemes."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
        tags=TAGS_METADATA,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = SECURITY_SCHEMES
    
    # Add servers configuration
    openapi_schema["servers"] = [
        {
            "url": "/",
            "description": "Current server",
        },
        {
            "url": "http://localhost:8000",
            "description": "Local development server",
        },
    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.include_router(health.router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(auth.router, prefix=settings.api_v1_prefix, tags=["authentication"])
app.include_router(users.router, prefix=settings.api_v1_prefix, tags=["users"])
app.include_router(admin.router, prefix=settings.api_v1_prefix, tags=["admin"])
app.include_router(jobs.router, prefix=settings.api_v1_prefix, tags=["jobs"])
app.include_router(
    annotations.router,
    prefix=f"{settings.api_v1_prefix}/annotations",
    tags=["annotations"]
)
app.include_router(
    asr_review.router,
    prefix=f"{settings.api_v1_prefix}/asr-review",
    tags=["asr-review"]
)
app.include_router(
    upload.router,
    prefix=settings.api_v1_prefix,
    tags=["upload"]
)
app.include_router(
    assets.router,
    prefix=f"{settings.api_v1_prefix}/assets",
    tags=["assets"]
)
app.include_router(
    admin_audit.router,
    prefix=settings.api_v1_prefix,
    tags=["admin-audit"]
)
app.include_router(
    annotation_sync.router,
    prefix=f"{settings.api_v1_prefix}/annotations",
    tags=["annotation-sync"]
)
app.include_router(
    admin_annotations.router,
    prefix=settings.api_v1_prefix,
    tags=["admin-annotations"]
)


@app.get("/")
async def root():
    return {"message": "JBI Detection & Segmentation API"}
