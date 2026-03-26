"""Remove unused fields from pipeline_segments

Revision ID: 011
Revises: 010_add_video_path_to_transcripts
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '011_remove_unused_segment_fields'
down_revision: Union[str, None] = '010_add_video_path_to_transcripts'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Remove unused ASR and cropping fields from pipeline_segments."""
    
    # Drop columns that are now stored in pipeline_transcripts (utterance-level)
    columns_to_drop = [
        'asr_text',
        'asr_confidence', 
        'asr_start',
        'asr_end',
        'jbi_start',
        'jbi_end',
        'stage2_video_path'
    ]
    
    for column in columns_to_drop:
        try:
            op.drop_column('pipeline_segments', column)
            print(f"Dropped column: {column}")
        except Exception as e:
            print(f"Column {column} may not exist: {e}")


def downgrade() -> None:
    """Add back the removed columns."""
    
    # Add columns back (all nullable for safety)
    op.add_column('pipeline_segments', sa.Column('asr_text', sa.Text(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('asr_confidence', sa.Float(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('asr_start', sa.Float(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('asr_end', sa.Float(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('jbi_start', sa.Float(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('jbi_end', sa.Float(), nullable=True))
    op.add_column('pipeline_segments', sa.Column('stage2_video_path', sa.String(500), nullable=True))
