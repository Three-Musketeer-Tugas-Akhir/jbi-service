"""
Compatibility layer for refactoring.

WARNING: This module is temporary and will be removed after refactoring.
It allows gradual migration of imports without breaking the application.
"""

# State machine compatibility - maps old enum to new constants
from app.db.models.pipeline import JobStatus as _JobStatus

# Legacy state names -> New state names
STATE_MAPPING = {
    "queued": _JobStatus.QUEUED,
    "processing": _JobStatus.DETECTING,  # Map to first processing state
    "completed": _JobStatus.READY_FOR_ANNOTATION,
    "failed": _JobStatus.FAILED,
    "cancelled": _JobStatus.CANCELLED,
}

# Reverse mapping for backward compatibility
REVERSE_STATE_MAPPING = {v: k for k, v in STATE_MAPPING.items()}


def migrate_state(old_state: str) -> str:
    """Convert legacy state name to new state constant."""
    return STATE_MAPPING.get(old_state.lower(), old_state)


def compat_state(new_state: str) -> str:
    """Convert new state constant to legacy state name (for过渡期)."""
    return REVERSE_STATE_MAPPING.get(new_state, new_state)
