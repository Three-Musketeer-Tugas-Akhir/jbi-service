import shutil
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.config import settings
from app.models.job import JobStatus
from app.models.job_store import job_store

logger = logging.getLogger(__name__)


def cleanup_expired_jobs() -> int:
    """Delete jobs that have exceeded their TTL.

    Deletes:
    - The job record from the in-memory store.
    - The uploaded video file.
    - The output directory and all contents.

    Returns:
        Number of jobs cleaned up.
    """
    ttl = timedelta(hours=settings.job_ttl_hours)
    now = datetime.now(timezone.utc)
    cutoff = now - ttl

    all_jobs = job_store.list_all()
    cleaned = 0

    for job in all_jobs:
        # Never clean up jobs still processing
        if job.status == JobStatus.PROCESSING:
            continue

        # Clean up terminal jobs past TTL
        # Also clean up queued jobs past TTL (assumed stuck/orphaned)
        if job.updated_at < cutoff:
            try:
                _delete_job_files(job.job_id, job.video_path)
                job_store.delete(job.job_id)
                cleaned += 1
                logger.info(
                    "Cleaned up expired job %s (status=%s, age=%s)",
                    job.job_id, job.status.value, now - job.updated_at,
                )
            except Exception:
                logger.exception(
                    "Failed to clean up job %s — will retry next cycle",
                    job.job_id,
                )

    if cleaned > 0:
        logger.info("Cleanup cycle complete: %d jobs removed", cleaned)

    return cleaned


def _delete_job_files(job_id: str, video_path: str):
    """Delete all files associated with a job."""
    # Delete uploaded video
    try:
        upload_path = Path(video_path)
        if upload_path.exists():
            upload_path.unlink()
            logger.debug("Deleted upload: %s", upload_path)
    except OSError:
        logger.warning("Failed to delete upload: %s", video_path)

    # Delete output directory (segments + detection_times.txt)
    try:
        output_dir = Path(settings.output_dir) / job_id
        if output_dir.exists():
            shutil.rmtree(output_dir)
            logger.debug("Deleted output dir: %s", output_dir)
    except OSError:
        logger.warning("Failed to delete output dir for job %s", job_id)
