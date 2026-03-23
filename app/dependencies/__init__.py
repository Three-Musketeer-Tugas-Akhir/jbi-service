"""Application dependencies."""

from app.dependencies.auth import (
    CurrentUser,
    get_current_user,
    get_optional_user,
    require_admin,
    require_annotator,
    require_annotator_or_curator,
    require_authenticated,
    require_curator,
    require_permission,
    require_role,
    require_annotation_read_own,
    require_annotation_read_all,
    require_annotation_write_own,
    require_annotation_write_reviews,
)

__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "require_annotator",
    "require_annotator_or_curator",
    "require_authenticated",
    "require_curator",
    "require_permission",
    "require_role",
    "require_annotation_read_own",
    "require_annotation_read_all",
    "require_annotation_write_own",
    "require_annotation_write_reviews",
]
