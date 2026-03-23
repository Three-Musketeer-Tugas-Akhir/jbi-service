"""Add audit log table

Revision ID: 006
Revises: 005_add_email_verification
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '006_add_audit_log_table'
down_revision: Union[str, None] = '005_add_email_verification'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create audit log table."""
    
    op.create_table(
        'audit_logs',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False
        ),
        sa.Column(
            'timestamp',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.Column(
            'actor_id',
            postgresql.UUID(as_uuid=True),
            nullable=True  # Nullable for system actions
        ),
        sa.Column(
            'action',
            sa.String(50),
            nullable=False
        ),
        sa.Column(
            'resource_type',
            sa.String(50),
            nullable=False
        ),
        sa.Column(
            'resource_id',
            postgresql.UUID(as_uuid=True),
            nullable=True
        ),
        sa.Column(
            'details',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='{}',
            nullable=False
        ),
        sa.Column(
            'ip_address',
            sa.String(45),  # IPv6 compatible
            nullable=True
        ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for common queries
    op.create_index(
        'idx_audit_logs_timestamp',
        'audit_logs',
        ['timestamp']
    )
    op.create_index(
        'idx_audit_logs_actor_id',
        'audit_logs',
        ['actor_id']
    )
    op.create_index(
        'idx_audit_logs_action',
        'audit_logs',
        ['action']
    )
    op.create_index(
        'idx_audit_logs_resource',
        'audit_logs',
        ['resource_type', 'resource_id']
    )


def downgrade() -> None:
    """Drop audit log table."""
    op.drop_index('idx_audit_logs_resource', table_name='audit_logs')
    op.drop_index('idx_audit_logs_action', table_name='audit_logs')
    op.drop_index('idx_audit_logs_actor_id', table_name='audit_logs')
    op.drop_index('idx_audit_logs_timestamp', table_name='audit_logs')
    op.drop_table('audit_logs')
