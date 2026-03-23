import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import JobStatus, can_transition, is_terminal
from app.models.job_model import JobRecord

logger = logging.getLogger(__name__)


class JobStore:
    """PostgreSQL-backed job store with async SQLAlchemy."""

    async def create(
        self, session: AsyncSession, job_id: str, video_path: str,
        video_title: str = "",
    ) -> JobRecord:
        """Create a new job record."""
        record = JobRecord(id=job_id, video_path=video_path, video_title=video_title)
        session.add(record)
        await session.flush()
        return record

    async def get(
        self, session: AsyncSession, job_id: str,
    ) -> Optional[JobRecord]:
        """Fetch a single job by ID."""
        result = await session.execute(
            select(JobRecord).where(JobRecord.id == job_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, session: AsyncSession, job_id: str,
        status: JobStatus, error: str = None,
    ) -> bool:
        """Update job status with transition validation."""
        record = await self.get(session, job_id)
        if not record:
            return False

        current = JobStatus(record.status)
        if not can_transition(current, status):
            logger.warning(
                "Invalid transition for job %s: %s -> %s",
                job_id, current.value, status.value,
            )
            return False

        record.status = status.value
        record.updated_at = datetime.now(timezone.utc)
        if error:
            record.error = error
        await session.flush()
        return True

    async def update_progress(
        self, session: AsyncSession, job_id: str,
        phase: str, current: int, total: int,
    ):
        """Update progress fields for a running job."""
        record = await self.get(session, job_id)
        if record and not is_terminal(JobStatus(record.status)):
            record.progress_phase = phase
            record.progress_current = current
            record.progress_total = total
            record.progress_percent = round(
                (current / total * 100) if total > 0 else 0, 1,
            )
            record.updated_at = datetime.now(timezone.utc)
            await session.flush()

    async def set_result(
        self, session: AsyncSession, job_id: str, result_data: dict,
    ):
        """Store the serialized pipeline result as JSONB."""
        record = await self.get(session, job_id)
        if record:
            record.result_data = result_data
            await session.flush()

    async def delete(
        self, session: AsyncSession, job_id: str,
    ) -> bool:
        """Delete a job record."""
        result = await session.execute(
            delete(JobRecord).where(JobRecord.id == job_id)
        )
        return result.rowcount > 0

    async def list_all(
        self, session: AsyncSession,
    ) -> list[JobRecord]:
        """Return all jobs sorted newest first."""
        result = await session.execute(
            select(JobRecord).order_by(JobRecord.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_filtered(
        self, session: AsyncSession,
        status: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[JobRecord], int]:
        """Return paginated jobs with optional status filter.

        Returns (page_of_records, total_count).
        """
        query = select(JobRecord)
        count_query = select(func.count()).select_from(JobRecord)

        if status:
            query = query.where(JobRecord.status == status)
            count_query = count_query.where(JobRecord.status == status)

        query = query.order_by(JobRecord.created_at.desc())
        query = query.limit(limit).offset(offset)

        result = await session.execute(query)
        records = list(result.scalars().all())

        count_result = await session.execute(count_query)
        total = count_result.scalar()

        return records, total


# Module-level singleton
job_store = JobStore()
