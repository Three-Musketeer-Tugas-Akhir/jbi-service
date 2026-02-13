import threading
import logging
from datetime import datetime, timezone
from typing import Optional

from app.models.job import (
    Job, JobStatus, JobProgress, can_transition, is_terminal,
)

logger = logging.getLogger(__name__)


class JobStore:
    """Thread-safe in-memory job store with transition validation."""

    def __init__(self):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, job: Job) -> Job:
        with self._lock:
            self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update_status(
        self, job_id: str, status: JobStatus, error: str = None,
    ) -> bool:
        """Update job status with transition validation."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            if not can_transition(job.status, status):
                logger.warning(
                    "Invalid transition for job %s: %s -> %s",
                    job_id, job.status.value, status.value,
                )
                return False

            job.status = status
            job.updated_at = datetime.now(timezone.utc)
            if error:
                job.error = error
            return True

    def update_progress(
        self, job_id: str, phase: str, current: int, total: int,
    ):
        with self._lock:
            job = self._jobs.get(job_id)
            if job and not is_terminal(job.status):
                job.progress = JobProgress(
                    phase=phase,
                    current=current,
                    total=total,
                    percent=round((current / total * 100) if total > 0 else 0, 1),
                )
                job.updated_at = datetime.now(timezone.utc)

    def set_result(self, job_id: str, result: object):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.result = result

    def delete(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def list_all(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())


# Module-level singleton
job_store = JobStore()
