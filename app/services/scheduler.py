import asyncio
import logging

from app.config import settings
from app.services.cleanup import cleanup_expired_jobs

logger = logging.getLogger(__name__)

_cleanup_task: asyncio.Task = None


async def _cleanup_loop():
    """Run cleanup_expired_jobs() on a fixed interval."""
    interval = settings.cleanup_interval_minutes * 60  # convert to seconds
    logger.info(
        "Cleanup scheduler started — interval=%dm, TTL=%dh",
        settings.cleanup_interval_minutes, settings.job_ttl_hours,
    )

    while True:
        await asyncio.sleep(interval)
        try:
            cleaned = await cleanup_expired_jobs()
            if cleaned > 0:
                logger.info("Scheduled cleanup removed %d jobs", cleaned)
        except Exception:
            logger.exception("Cleanup cycle failed — will retry next interval")


def start_cleanup_scheduler():
    """Start the background cleanup loop. Call once at app startup."""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        _cleanup_task = asyncio.create_task(_cleanup_loop())
        logger.info("Cleanup scheduler task created")


def stop_cleanup_scheduler():
    """Stop the background cleanup loop. Call at app shutdown."""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
        logger.info("Cleanup scheduler task cancelled")
