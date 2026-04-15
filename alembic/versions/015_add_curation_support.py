"""Add curation support columns

Revision ID: 015
Revises: 014_make_video_path_nullable
Create Date: 2026-04-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '015_add_curation_support'
down_revision: Union[str, None] = '014_make_video_path_nullable'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Add curation_status to pipeline_jobs and normalized_text to annotation_edits."""
    # pipeline_jobs
    op.add_column(
        'pipeline_jobs',
        sa.Column(
            'curation_status',
            sa.String(length=50),
            nullable=True,
            comment='Curation workflow status: PENDING, ANNOTATED, NORMALIZING, NORMALIZED, READY_TO_EXPORT'
        )
    )
    op.create_index(
        'idx_pipeline_jobs_curation_status',
        'pipeline_jobs',
        ['curation_status'],
        unique=False
    )

    # annotation_edits
    op.add_column(
        'annotation_edits',
        sa.Column(
            'normalized_text',
            sa.Text(),
            nullable=True,
            comment='Auto-normalized or curator-edited final text for export'
        )
    )
    op.add_column(
        'annotation_edits',
        sa.Column(
            'curation_edited_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Timestamp of last manual curation edit'
        )
    )


def downgrade() -> None:
    """Remove curation support columns."""
    op.drop_column('annotation_edits', 'curation_edited_at')
    op.drop_column('annotation_edits', 'normalized_text')
    op.drop_index('idx_pipeline_jobs_curation_status', table_name='pipeline_jobs')
    op.drop_column('pipeline_jobs', 'curation_status')
