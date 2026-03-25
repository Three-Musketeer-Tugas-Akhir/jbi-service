"""Add annotation domain tables

Revision ID: 012
Revises: 011_add_job_cancellation_fields
Create Date: 2026-03-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = '012_add_annotation_tables'
down_revision = '011_add_job_cancellation_fields'
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # annotation_edits - Stores transcript/timestamp edits by annotators
    # =========================================================================
    op.create_table(
        'annotation_edits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('editor_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Original values (for audit trail)
        sa.Column('old_text', sa.Text(), nullable=True, comment='Original transcript text'),
        sa.Column('old_start', sa.Float(), nullable=True, comment='Original start time in seconds'),
        sa.Column('old_end', sa.Float(), nullable=True, comment='Original end time in seconds'),
        
        # New values
        sa.Column('new_text', sa.Text(), nullable=False, comment='Corrected transcript text'),
        sa.Column('new_start', sa.Float(), nullable=False, comment='Corrected start time in seconds'),
        sa.Column('new_end', sa.Float(), nullable=False, comment='Corrected end time in seconds'),
        
        # Metadata
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', comment='pending, submitted, approved, rejected'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false', comment='Soft delete flag'),
        sa.Column('edited_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for finding edits by segment
    op.create_index('idx_annotation_edits_segment', 'annotation_edits', ['segment_id', 'is_deleted'])
    # Index for finding edits by editor
    op.create_index('idx_annotation_edits_editor', 'annotation_edits', ['editor_id', 'status'])
    
    # =========================================================================
    # annotation_reviews - Curator reviews of annotation edits
    # =========================================================================
    op.create_table(
        'annotation_reviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('edit_id', UUID(as_uuid=True), sa.ForeignKey('annotation_edits.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('curator_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Review details
        sa.Column('status', sa.String(50), nullable=False, comment='approved, rejected'),
        sa.Column('feedback', sa.Text(), nullable=True, comment='Curator feedback to annotator'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    
    # Index for finding reviews by edit
    op.create_index('idx_annotation_reviews_edit', 'annotation_reviews', ['edit_id'])
    
    # =========================================================================
    # annotation_comments - Comments on annotation edits
    # =========================================================================
    op.create_table(
        'annotation_comments',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('edit_id', UUID(as_uuid=True), sa.ForeignKey('annotation_edits.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Comment content
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    
    # Index for finding comments by edit
    op.create_index('idx_annotation_comments_edit', 'annotation_comments', ['edit_id', 'created_at'])
    
    # =========================================================================
    # asr_reviews - Pre-annotation ASR transcript validation
    # =========================================================================
    op.create_table(
        'asr_reviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('reviewer_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # ASR content
        sa.Column('original_text', sa.Text(), nullable=False, comment='Original ASR transcript'),
        sa.Column('corrected_text', sa.Text(), nullable=True, comment='Reviewer corrections'),
        sa.Column('confidence_score', sa.Float(), nullable=True, comment='ASR confidence (0-1)'),
        
        # Review status
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', comment='pending, approved, corrected, flagged'),
        sa.Column('flag_reason', sa.String(255), nullable=True, comment='Reason if flagged'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for ASR review queue
    op.create_index('idx_asr_reviews_status', 'asr_reviews', ['status', 'confidence_score'])
    
    # =========================================================================
    # annotation_queue - Work assignment queue for annotators
    # =========================================================================
    op.create_table(
        'annotation_queue',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('annotator_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False, index=True),
        
        # Queue metadata
        sa.Column('status', sa.String(50), nullable=False, server_default='assigned', comment='assigned, in_progress, completed'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0', comment='Higher = higher priority'),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for annotator queue queries
    op.create_index('idx_annotation_queue_annotator', 'annotation_queue', ['annotator_id', 'status', 'priority', 'assigned_at'])
    # Index for finding unassigned/available work
    op.create_index('idx_annotation_queue_status', 'annotation_queue', ['status', 'priority', 'assigned_at'])


def downgrade():
    # Drop in reverse order to handle FK constraints
    op.drop_index('idx_annotation_queue_status')
    op.drop_index('idx_annotation_queue_annotator')
    op.drop_table('annotation_queue')
    
    op.drop_index('idx_asr_reviews_status')
    op.drop_table('asr_reviews')
    
    op.drop_index('idx_annotation_comments_edit')
    op.drop_table('annotation_comments')
    
    op.drop_index('idx_annotation_reviews_edit')
    op.drop_table('annotation_reviews')
    
    op.drop_index('idx_annotation_edits_editor')
    op.drop_index('idx_annotation_edits_segment')
    op.drop_table('annotation_edits')
