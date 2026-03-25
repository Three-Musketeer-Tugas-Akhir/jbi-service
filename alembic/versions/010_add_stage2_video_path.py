"""Add stage2_video_path to pipeline_segments

Revision ID: 010
Revises: 009_add_asr_review_flag
Create Date: 2026-03-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '010_add_stage2_video_path'
down_revision: Union[str, None] = '009_add_asr_review_flag'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add stage2_video_path column to pipeline_segments table."""
    op.add_column(
        'pipeline_segments',
        sa.Column(
            'stage2_video_path',
            sa.String(length=500),
            nullable=True,
            comment='Path to Stage 2 cropped video (timestamp-based with JBI buffer)'
        )
    )


def downgrade() -> None:
    """Remove stage2_video_path column from pipeline_segments table."""
    op.drop_column('pipeline_segments', 'stage2_video_path')
