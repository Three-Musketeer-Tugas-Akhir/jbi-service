"""API Routers."""

from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.jobs import router as jobs_router
from app.routers.users import router as users_router

__all__ = ["admin_router", "auth_router", "health_router", "jobs_router", "users_router"]
