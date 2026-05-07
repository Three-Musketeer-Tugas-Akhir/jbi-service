"""Dataset model for organizing jobs into projects."""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy import DateTime, String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Dataset(Base):
    """A dataset (project) that groups related pipeline jobs.
    
    Examples: "iNews 2025", "TVRI 2024", etc.
    """
    
    __tablename__ = "datasets"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid()
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Dataset/project name"
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Optional description of the dataset"
    )
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    # Relationships
    jobs: Mapped[List["PipelineJob"]] = relationship(
        "PipelineJob",
        back_populates="dataset",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Dataset(id={self.id}, name={self.name})>"
