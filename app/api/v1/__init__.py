"""API v1 Routers."""

from app.api.v1.admin import router as admin_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.users import router as users_router
from app.api.v1.upload import router as upload_router

__all__ = ["admin_router", "auth_router", "health_router", "jobs_router", "users_router", "upload_router"]
