import shutil
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.core.config import settings
from app.db.session import async_session
from app.db.models.pipeline import JobStatus
from app.repositories.job_repository import JobRepository

logger = logging.getLogger(__name__)


async def cleanup_expired_refresh_tokens(batch_size: int = 1000) -> int:
    """
    Clean up expired refresh tokens from the database.
    
    Deletes refresh tokens that have passed their expiration date.
    
    Args:
        batch_size: Maximum number of tokens to delete per run
        
    Returns:
        Number of tokens deleted
    """
    from sqlalchemy import delete
    from app.db.models.auth import RefreshToken
    
    try:
        async with async_session() as session:
            # Delete expired tokens
            stmt = (
                delete(RefreshToken)
                .where(RefreshToken.expires_at < datetime.now(timezone.utc))
                .limit(batch_size)
            )
            result = await session.execute(stmt)
            deleted_count = result.rowcount
            
            if deleted_count > 0:
                await session.commit()
                logger.info(
                    "Cleaned up %d expired refresh tokens",
                    deleted_count
                )
            
            return deleted_count
    except Exception:
        logger.exception("Failed to clean up expired refresh tokens")
        return 0


async def cleanup_expired_jobs() -> int:
    """Delete jobs that have exceeded their TTL.

    Deletes:
    - The job record from the database.
    - The uploaded video file.
    - The output directory and all contents.

    Returns:
        Number of jobs cleaned up.
    """
    ttl = timedelta(hours=settings.job_ttl_hours)
    now = datetime.now(timezone.utc)
    cutoff = now - ttl

    async with async_session() as session:
        repo = JobRepository(session)
        all_jobs = await repo.list_all()
        cleaned = 0

        for record in all_jobs:
            # Never clean up jobs still processing
            if record.status == JobStatus.PROCESSING.value:
                continue

            # Clean up terminal jobs past TTL
            # Also clean up queued jobs past TTL (assumed stuck/orphaned)
            if record.updated_at < cutoff:
                try:
                    _delete_job_files(record.id, record.video_path)
                    await repo.delete(record.id)
                    cleaned += 1
                    logger.info(
                        "Cleaned up expired job %s (status=%s, age=%s)",
                        record.id, record.status, now - record.updated_at,
                    )
                except Exception:
                    logger.exception(
                        "Failed to clean up job %s — will retry next cycle",
                        record.id,
                    )

        await session.commit()

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
