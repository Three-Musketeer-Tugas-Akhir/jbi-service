"""Add voice_annotations table and job counters.

Revision ID: 019
Revises: 018
Create Date: 2026-05-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers
revision = "019_add_voice_annotation"
down_revision = "018_add_utterance_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create voice_annotations table
    op.create_table(
        "voice_annotations",
        sa.Column("id", UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("transcript_id", UUID(as_uuid=True), sa.ForeignKey("pipeline_transcripts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("pipeline_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asr_text", sa.Text(), nullable=False),
        sa.Column("ground_truth_text", sa.Text(), nullable=False),
        sa.Column("flagged_words", JSONB(), server_default="[]", nullable=True),
        sa.Column("has_flag", sa.Boolean(), nullable=False, default=False),
        sa.Column("voice_annotation_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("annotator_id", UUID(as_uuid=True), sa.ForeignKey("auth_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index("ix_voice_annotations_transcript_id", "voice_annotations", ["transcript_id"])
    op.create_index("ix_voice_annotations_job_id", "voice_annotations", ["job_id"])
    op.create_index("ix_voice_annotations_status", "voice_annotations", ["voice_annotation_status"])

    # 2. Add counter columns to pipeline_jobs
    op.add_column(
        "pipeline_jobs",
        sa.Column("clean_utterance_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "pipeline_jobs",
        sa.Column("flagged_utterance_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("pipeline_jobs", "flagged_utterance_count")
    op.drop_column("pipeline_jobs", "clean_utterance_count")
    op.drop_index("ix_voice_annotations_status", table_name="voice_annotations")
    op.drop_index("ix_voice_annotations_job_id", table_name="voice_annotations")
    op.drop_index("ix_voice_annotations_transcript_id", table_name="voice_annotations")
    op.drop_table("voice_annotations")
