import asyncio
import logging

from app.config import settings
from app.services.cleanup import cleanup_expired_jobs, cleanup_expired_refresh_tokens

logger = logging.getLogger(__name__)

_cleanup_task: asyncio.Task = None


async def _cleanup_loop():
    """Run cleanup tasks on a fixed interval."""
    interval = settings.cleanup_interval_minutes * 60  # convert to seconds
    logger.info(
        "Cleanup scheduler started — interval=%dm, job TTL=%dh",
        settings.cleanup_interval_minutes, settings.job_ttl_hours,
    )

    # Track refresh token cleanup - run daily
    refresh_token_cleanup_interval = 24 * 60 * 60  # 24 hours in seconds
    last_refresh_cleanup = 0

    while True:
        await asyncio.sleep(interval)
        
        # Cleanup expired jobs
        try:
            cleaned = await cleanup_expired_jobs()
            if cleaned > 0:
                logger.info("Scheduled cleanup removed %d jobs", cleaned)
        except Exception:
            logger.exception("Job cleanup cycle failed — will retry next interval")
        
        # Cleanup expired refresh tokens (run once per day)
        current_time = asyncio.get_event_loop().time()
        if current_time - last_refresh_cleanup >= refresh_token_cleanup_interval:
            try:
                tokens_cleaned = await cleanup_expired_refresh_tokens()
                if tokens_cleaned > 0:
                    logger.info("Scheduled cleanup removed %d expired refresh tokens", tokens_cleaned)
                last_refresh_cleanup = current_time
            except Exception:
                logger.exception("Refresh token cleanup cycle failed — will retry next interval")


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
