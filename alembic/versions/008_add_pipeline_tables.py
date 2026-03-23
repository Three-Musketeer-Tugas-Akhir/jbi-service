"""Add pipeline domain tables

Revision ID: 008
Revises: 007_migrate_to_many_to_many_roles
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '008_add_pipeline_tables'
down_revision: Union[str, None] = '007_migrate_to_many_to_many_roles'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline domain tables."""
    
    # pipeline_jobs table
    op.create_table(
        'pipeline_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('video_path', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('current_stage', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_jobs
    op.create_index('idx_pipeline_jobs_status', 'pipeline_jobs', ['status'])
    op.create_index('idx_pipeline_jobs_created_by', 'pipeline_jobs', ['created_by'])
    op.create_index('idx_pipeline_jobs_created_at', 'pipeline_jobs', ['created_at'])
    
    # Foreign key to auth_users
    op.create_foreign_key(
        'fk_pipeline_jobs_created_by',
        'pipeline_jobs', 'auth_users',
        ['created_by'], ['id'],
        ondelete='SET NULL'
    )
    
    # pipeline_segments table
    op.create_table(
        'pipeline_segments',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('segment_index', sa.Integer(), nullable=False),
        sa.Column('bbox_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('asr_text', sa.Text(), nullable=True),
        sa.Column('asr_confidence', sa.Float(), nullable=True),
        sa.Column('asr_start', sa.Float(), nullable=True),
        sa.Column('asr_end', sa.Float(), nullable=True),
        sa.Column('jbi_start', sa.Float(), nullable=True),
        sa.Column('jbi_end', sa.Float(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('cropped_video_path', sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_segments
    op.create_index('idx_pipeline_segments_job_id', 'pipeline_segments', ['job_id'])
    
    # Foreign key to pipeline_jobs
    op.create_foreign_key(
        'fk_pipeline_segments_job_id',
        'pipeline_segments', 'pipeline_jobs',
        ['job_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # pipeline_job_logs table
    op.create_table(
        'pipeline_job_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage', sa.String(50), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_job_logs
    op.create_index('idx_pipeline_job_logs_job_id', 'pipeline_job_logs', ['job_id'])
    op.create_index('idx_pipeline_job_logs_created_at', 'pipeline_job_logs', ['created_at'])
    
    # Foreign key to pipeline_jobs
    op.create_foreign_key(
        'fk_pipeline_job_logs_job_id',
        'pipeline_job_logs', 'pipeline_jobs',
        ['job_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # queue_jobs table
    op.create_table(
        'queue_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('queue_name', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for queue_jobs
    op.create_index('idx_queue_jobs_status', 'queue_jobs', ['status'])
    op.create_index('idx_queue_jobs_queue_name', 'queue_jobs', ['queue_name'])
    op.create_index('idx_queue_jobs_scheduled_at', 'queue_jobs', ['scheduled_at'])
    
    # config_pipeline_params table
    op.create_table(
        'config_pipeline_params',
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )
    
    # Insert default pipeline parameters
    op.bulk_insert(
        'config_pipeline_params',
        [
            {
                'key': 'min_segment_duration',
                'value': '3.0',
                'description': 'Minimum segment duration in seconds'
            },
            {
                'key': 'max_concurrent_jobs',
                'value': '3',
                'description': 'Maximum concurrent video processing jobs'
            },
            {
                'key': 'queue_max_depth',
                'value': '50',
                'description': 'Maximum pending jobs in queue'
            },
            {
                'key': 'asr_model_default',
                'value': 'base',
                'description': 'Default ASR model size (tiny/base/small/medium/large-v3)'
            },
            {
                'key': 'jbi_buffer_seconds',
                'value': '2.0',
                'description': 'JBI buffer time added to ASR timestamps'
            }
        ]
    )


def downgrade() -> None:
    """Drop pipeline domain tables."""
    op.drop_table('config_pipeline_params')
    op.drop_table('queue_jobs')
    op.drop_table('pipeline_job_logs')
    op.drop_table('pipeline_segments')
    op.drop_table('pipeline_jobs')
