"""Add utterance_corrections to annotation_edits

Revision ID: 018_add_utterance_corrections
Revises: 017_add_audio_path_and_notifications
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '018_add_utterance_corrections'
down_revision: Union[str, None] = '017_add_audio_path_and_notifications'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add utterance_corrections JSONB column to annotation_edits."""
    
    # Add utterance_corrections JSONB column
    op.add_column(
        'annotation_edits',
        sa.Column(
            'utterance_corrections',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment='List of corrected utterances: [{utterance_index, text, start, end}]'
        )
    )
    
    # Add GIN index for JSONB query performance
    op.create_index(
        'ix_annotation_edits_utterance_corrections',
        'annotation_edits',
        ['utterance_corrections'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    """Remove utterance_corrections from annotation_edits."""
    op.drop_index('ix_annotation_edits_utterance_corrections')
    op.drop_column('annotation_edits', 'utterance_corrections')
