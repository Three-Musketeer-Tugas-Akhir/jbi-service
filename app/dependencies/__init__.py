"""
Dependencies package.

NOTE: Dependencies have been moved to app.api.deps per architecture.
This module re-exports for backward compatibility.
"""

from app.api.deps import (
    CurrentUser,
    get_current_user,
    require_role,
    require_admin,
    require_annotator,
    require_curator,
    require_annotator_or_curator,
    ALLOWED_ROLES,
    security_scheme,
)

__all__ = [
    "CurrentUser",
    "get_current_user",
    "require_role",
    "require_admin",
    "require_annotator",
    "require_curator",
    "require_annotator_or_curator",
    "ALLOWED_ROLES",
    "security_scheme",
]
