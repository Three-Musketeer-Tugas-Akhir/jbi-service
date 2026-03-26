"""Add video_path and status to pipeline_transcripts

Revision ID: 010
Revises: 009_add_pipeline_transcripts
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '010_add_video_path_to_transcripts'
down_revision: Union[str, None] = '009_add_pipeline_transcripts'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add video_path and status columns to pipeline_transcripts."""
    
    # Add video_path column
    op.add_column(
        'pipeline_transcripts',
        sa.Column(
            'video_path',
            sa.String(500),
            nullable=True,
            comment='MinIO key to cropped video for this utterance'
        )
    )
    
    # Add status column
    op.add_column(
        'pipeline_transcripts',
        sa.Column(
            'status',
            sa.String(50),
            nullable=True,
            server_default='pending',
            comment='Cropping status: pending, cropped, failed'
        )
    )
    
    # Create index on video_path for faster lookups
    op.create_index(
        'idx_pipeline_transcripts_video_path',
        'pipeline_transcripts',
        ['video_path']
    )


def downgrade() -> None:
    """Remove video_path and status columns."""
    op.drop_index('idx_pipeline_transcripts_video_path', table_name='pipeline_transcripts')
    op.drop_column('pipeline_transcripts', 'video_path')
    op.drop_column('pipeline_transcripts', 'status')
