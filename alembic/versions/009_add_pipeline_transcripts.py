"""Add pipeline_transcripts table

Revision ID: 009
Revises: 008_add_pipeline_tables
Create Date: 2026-03-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '009_add_pipeline_transcripts'
down_revision: Union[str, None] = '008_add_pipeline_tables'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline_transcripts table for individual ASR utterances."""
    
    # pipeline_transcripts table
    op.create_table(
        'pipeline_transcripts',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('segment_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('utterance_index', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('start', sa.Float(), nullable=False),
        sa.Column('end', sa.Float(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_transcripts
    op.create_index('idx_pipeline_transcripts_segment_id', 'pipeline_transcripts', ['segment_id'])
    op.create_index('idx_pipeline_transcripts_utterance_index', 'pipeline_transcripts', ['utterance_index'])
    
    # Foreign key to pipeline_segments
    op.create_foreign_key(
        'fk_pipeline_transcripts_segment_id',
        'pipeline_transcripts', 'pipeline_segments',
        ['segment_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # Update default ASR model config to medium (matching asr_code.ipynb)
    op.execute("""
        UPDATE config_pipeline_params 
        SET value = 'medium', 
            description = 'Default ASR model size - medium for better accuracy (matching asr_code.ipynb)'
        WHERE key = 'asr_model_default'
    """)


def downgrade() -> None:
    """Drop pipeline_transcripts table."""
    op.drop_table('pipeline_transcripts')
