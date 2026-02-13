from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Terminal states — no further transitions allowed
TERMINAL_STATES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

# Valid transitions: source -> set of allowed targets
VALID_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.PROCESSING, JobStatus.CANCELLED},
    JobStatus.PROCESSING: {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}


@dataclass
class JobProgress:
    """Tracks progress within the current pipeline phase."""
    phase: str = ""
    current: int = 0
    total: int = 0
    percent: float = 0.0


@dataclass
class Job:
    """In-memory representation of a processing job."""
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    video_path: str = ""
    output_dir: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    progress: JobProgress = field(default_factory=JobProgress)
    error: Optional[str] = None
    result: Optional[object] = None  # PipelineResult once completed


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    """Check if a state transition is valid."""
    return target in VALID_TRANSITIONS.get(current, set())


def is_terminal(status: JobStatus) -> bool:
    """Check if a status is a terminal state."""
    return status in TERMINAL_STATES
