"""Add job cancellation fields to pipeline_jobs

Revision ID: 011
Revises: 010_add_stage2_video_path
Create Date: 2026-03-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = '011_add_job_cancellation_fields'
down_revision = '010_add_stage2_video_path'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_cancelled column
    op.add_column(
        'pipeline_jobs',
        sa.Column(
            'is_cancelled',
            sa.Boolean(),
            nullable=False,
            server_default='false',
            comment='True if job was cancelled by user'
        )
    )
    
    # Add cancelled_at timestamp
    op.add_column(
        'pipeline_jobs',
        sa.Column(
            'cancelled_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='When job was cancelled'
        )
    )
    
    # Add cancelled_by foreign key
    op.add_column(
        'pipeline_jobs',
        sa.Column(
            'cancelled_by',
            UUID(as_uuid=True),
            sa.ForeignKey('auth_users.id', ondelete='SET NULL'),
            nullable=True,
            comment='User who cancelled the job'
        )
    )
    
    # Create partial index for cancelled jobs
    op.create_index(
        'idx_pipeline_jobs_is_cancelled',
        'pipeline_jobs',
        ['is_cancelled'],
        postgresql_where=sa.text('is_cancelled = true')
    )
    
    # Create index on cancelled_at for time-based queries
    op.create_index(
        'idx_pipeline_jobs_cancelled_at',
        'pipeline_jobs',
        ['cancelled_at']
    )


def downgrade():
    # Drop indexes
    op.drop_index('idx_pipeline_jobs_cancelled_at')
    op.drop_index('idx_pipeline_jobs_is_cancelled')
    
    # Drop columns
    op.drop_column('pipeline_jobs', 'cancelled_by')
    op.drop_column('pipeline_jobs', 'cancelled_at')
    op.drop_column('pipeline_jobs', 'is_cancelled')
