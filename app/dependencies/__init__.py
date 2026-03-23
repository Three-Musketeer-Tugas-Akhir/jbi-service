"""FastAPI dependencies for the application."""

from app.dependencies.auth import (
    get_current_user,
    require_role,
    require_admin,
    require_annotator,
    require_curator,
    require_annotator_or_curator,
    CurrentUser,
)

__all__ = [
    "get_current_user",
    "require_role",
    "require_admin",
    "require_annotator",
    "require_curator",
    "require_annotator_or_curator",
    "CurrentUser",
]
