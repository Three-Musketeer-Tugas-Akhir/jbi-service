import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Text, Float, Integer, DateTime, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True,
    )
    video_title: Mapped[str] = mapped_column(
        Text, nullable=False, default="",
    )
    video_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_dir: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Progress (flattened)
    progress_phase: Mapped[str] = mapped_column(
        String(30), nullable=False, default="",
    )
    progress_current: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    progress_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0,
    )
    progress_percent: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0,
    )

    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Pipeline result stored as JSONB
    result_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("ix_jobs_created_at", "created_at"),
    )
