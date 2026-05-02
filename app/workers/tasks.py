import asyncio
import logging

from app.logging_config import job_id_ctx
from app.db.session import async_session
from app.db.models.pipeline import JobStatus
from app.repositories.job_repository import JobRepository
from app.pipeline.utils.result_serializer import serialize_pipeline_result
from app.services.pipeline import run_pipeline, PipelineError

# Terminal states - no further transitions allowed
TERMINAL_STATES = {JobStatus.READY_FOR_ANNOTATION, JobStatus.NEEDS_VOICE_ANNOTATION, JobStatus.FAILED, JobStatus.CANCELLED}

def is_terminal(status: str) -> bool:
    """Check if a status is a terminal state."""
    return status in TERMINAL_STATES

logger = logging.getLogger(__name__)


class CancelledException(Exception):
    """Raised when a job is cancelled during processing."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        super().__init__(f"Job {job_id} cancelled")


async def _update_progress(job_id: str, phase: str, current: int, total: int):
    """Open a fresh session to persist progress update."""
    async with async_session() as session:
        repo = JobRepository(session)
        await repo.update_progress(job_id, phase, current, total)
        await session.commit()


async def _check_cancelled(job_id: str) -> bool:
    """Open a fresh session to check if the job was cancelled."""
    async with async_session() as session:
        repo = JobRepository(session)
        record = await repo.get_by_id(job_id)
        return record is not None and record.status == JobStatus.CANCELLED


async def _process_job_async(job_id: str, video_path: str) -> None:
    """Async implementation of job processing."""
    job_id_ctx.set(job_id)

    # Check if already cancelled before starting
    async with async_session() as session:
        repo = JobRepository(session)
        record = await repo.get_by_id(job_id)
        if not record or is_terminal(record.status):
            logger.info("Job %s already in terminal state — skipping", job_id)
            return

        await repo.update_status(job_id, JobStatus.DETECTING)
        await session.commit()

    logger.info("Starting job %s", job_id)

    def on_progress(phase, current, total):
        """Sync callback invoked by the pipeline — bridges to async."""
        loop = asyncio.new_event_loop()
        try:
            # Check for cancellation
            cancelled = loop.run_until_complete(_check_cancelled(job_id))
            if cancelled:
                logger.info("Job %s cancelled during %s — aborting", job_id, phase)
                raise CancelledException(job_id)

            loop.run_until_complete(
                _update_progress(job_id, phase, current, total)
            )
        finally:
            loop.close()

    try:
        result = run_pipeline(
            job_id=job_id,
            video_path=video_path,
            on_progress=on_progress,
        )
        result_data = serialize_pipeline_result(result)

        async with async_session() as session:
            repo = JobRepository(session)
            await repo.set_result(job_id, result_data)
            await repo.update_status(job_id, JobStatus.READY_FOR_ANNOTATION)
            await session.commit()

        logger.info(
            "Job %s completed — %d segments",
            job_id, len(result.segmentation.segments),
        )

    except CancelledException:
        logger.info("Job %s aborted due to cancellation", job_id)
        # Status is already CANCELLED — nothing more to do

    except PipelineError as exc:
        logger.exception("Job %s failed at phase %s", job_id, exc.phase)
        async with async_session() as session:
            repo = JobRepository(session)
            await repo.update_status(job_id, JobStatus.FAILED, error=str(exc))
            await session.commit()

    except Exception as exc:
        logger.exception("Job %s failed with unexpected error", job_id)
        async with async_session() as session:
            repo = JobRepository(session)
            await repo.update_status(job_id, JobStatus.FAILED, error=str(exc))
            await session.commit()


def process_job(job_id: str, video_path: str) -> None:
    """Entry point for BackgroundTasks — bridges sync → async."""
    asyncio.run(_process_job_async(job_id, video_path))
