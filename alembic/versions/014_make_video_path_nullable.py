"""Make video_path nullable in pipeline_jobs

Revision ID: 014
Revises: 013_add_file_size_column
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '014_make_video_path_nullable'
down_revision: Union[str, None] = '013_add_file_size_column'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Make video_path column nullable."""
    op.alter_column(
        'pipeline_jobs',
        'video_path',
        existing_type=sa.String(500),
        nullable=True
    )


def downgrade() -> None:
    """Make video_path column not null."""
    op.alter_column(
        'pipeline_jobs',
        'video_path',
        existing_type=sa.String(500),
        nullable=False
    )
