"""add_video_title_column

Revision ID: a1b2c3d4e5f6
Revises: 59d50d1e0353
Create Date: 2026-02-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '59d50d1e0353'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add video_title column to jobs table."""
    op.add_column(
        'jobs',
        sa.Column('video_title', sa.Text(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    """Remove video_title column from jobs table."""
    op.drop_column('jobs', 'video_title')
