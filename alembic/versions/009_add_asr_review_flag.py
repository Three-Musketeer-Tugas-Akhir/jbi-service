"""Add ASR review flag to pipeline_segments

Revision ID: 009
Revises: 008_add_pipeline_tables
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '009_add_asr_review_flag'
down_revision: Union[str, None] = '008_add_pipeline_tables'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add asr_review_flag column to pipeline_segments table."""
    op.add_column(
        'pipeline_segments',
        sa.Column(
            'asr_review_flag',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('false'),
            comment='True if segment needs ASR review (low confidence or failed)'
        )
    )
    
    # Create index for efficient filtering
    op.create_index(
        'idx_pipeline_segments_asr_review_flag',
        'pipeline_segments',
        ['asr_review_flag']
    )


def downgrade() -> None:
    """Remove asr_review_flag column from pipeline_segments table."""
    op.drop_index('idx_pipeline_segments_asr_review_flag', table_name='pipeline_segments')
    op.drop_column('pipeline_segments', 'asr_review_flag')
