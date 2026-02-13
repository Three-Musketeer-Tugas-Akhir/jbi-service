import logging

from app.logging_config import job_id_ctx
from app.models.job import JobStatus, is_terminal
from app.models.job_store import job_store
from app.services.pipeline import run_pipeline, PipelineError

logger = logging.getLogger(__name__)


class CancelledException(Exception):
    """Raised when a job is cancelled during processing."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job {job_id} cancelled")


def process_job(job_id: str, video_path: str) -> None:
    """Background task that runs the full pipeline for a job.

    Checks for cancellation via job store before and during processing.
    """
    # Set job context for structured logging
    job_id_ctx.set(job_id)

    # Check if already cancelled before starting
    job = job_store.get(job_id)
    if not job or is_terminal(job.status):
        logger.info("Job %s already in terminal state — skipping", job_id)
        return

    logger.info("Starting job %s", job_id)
    job_store.update_status(job_id, JobStatus.PROCESSING)

    def on_progress(phase, current, total):
        # Check for cancellation on each progress callback
        job = job_store.get(job_id)
        if job and job.status == JobStatus.CANCELLED:
            logger.info("Job %s cancelled during %s — aborting", job_id, phase)
            raise CancelledException(job_id)

        job_store.update_progress(job_id, phase=phase, current=current, total=total)

    try:
        result = run_pipeline(
            job_id=job_id,
            video_path=video_path,
            on_progress=on_progress,
        )
        job_store.set_result(job_id, result)
        job_store.update_status(job_id, JobStatus.COMPLETED)
        logger.info(
            "Job %s completed — %d segments",
            job_id, len(result.segmentation.segments),
        )

    except CancelledException:
        logger.info("Job %s aborted due to cancellation", job_id)
        # Status is already CANCELLED — nothing more to do

    except PipelineError as exc:
        logger.exception("Job %s failed at phase %s", job_id, exc.phase)
        job_store.update_status(job_id, JobStatus.FAILED, error=str(exc))

    except Exception as exc:
        logger.exception("Job %s failed with unexpected error", job_id)
        job_store.update_status(job_id, JobStatus.FAILED, error=str(exc))
