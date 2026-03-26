"""Add file_size column to pipeline_jobs

Revision ID: 013
Revises: 012_add_annotation_tables
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '013_add_file_size_column'
down_revision: Union[str, None] = '012_add_annotation_tables'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add file_size column to pipeline_jobs table."""
    op.add_column(
        'pipeline_jobs',
        sa.Column('file_size', sa.Integer(), nullable=False, server_default='0')
    )


def downgrade() -> None:
    """Remove file_size column from pipeline_jobs table."""
    op.drop_column('pipeline_jobs', 'file_size')
