"""Add release_date to pipeline_jobs.

Revision ID: 020
Revises: 019
Create Date: 2026-05-03
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = "020_add_release_date_to_job"
down_revision = "019_add_voice_annotation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pipeline_jobs",
        sa.Column("release_date", sa.String(20), nullable=True, comment="Release/Upload date from YouTube or external source (YYYYMMDD)")
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "release_date")
