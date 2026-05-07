"""Add dataset_id to pipeline_jobs

Revision ID: 021
Revises: 020_add_release_date_to_job
Create Date: 2025-05-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '021_add_dataset_id_to_pipeline_jobs'
down_revision = '020_add_release_date_to_job'
branch_labels = None
depends_on = None


def upgrade():
    # Add dataset_id column to pipeline_jobs
    op.add_column(
        'pipeline_jobs',
        sa.Column(
            'dataset_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('datasets.id', ondelete='SET NULL'),
            nullable=True
        )
    )
    # Create index for faster filtering
    op.create_index(
        'idx_pipeline_jobs_dataset_id',
        'pipeline_jobs',
        ['dataset_id']
    )


def downgrade():
    op.drop_index('idx_pipeline_jobs_dataset_id', table_name='pipeline_jobs')
    op.drop_column('pipeline_jobs', 'dataset_id')
