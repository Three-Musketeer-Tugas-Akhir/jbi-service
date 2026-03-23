"""Add password reset tokens table

Revision ID: 004
Revises: 003_add_refresh_token_table
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '004_add_password_reset_tokens'
down_revision: Union[str, None] = '003_add_refresh_token_table'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create password reset token tracking table."""
    
    op.create_table(
        'auth_password_reset_tokens',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'token_hash',
            sa.String(255),
            nullable=False,
            comment="Bcrypt hash of the reset token"
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False
        ),
        sa.Column(
            'used_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['auth_users.id'],
            ondelete='CASCADE'
        ),
        sa.UniqueConstraint('token_hash')
    )
    
    # Create indexes
    op.create_index(
        'idx_password_reset_tokens_user_id',
        'auth_password_reset_tokens',
        ['user_id']
    )
    op.create_index(
        'idx_password_reset_tokens_expires_at',
        'auth_password_reset_tokens',
        ['expires_at']
    )
    op.create_index(
        'idx_password_reset_tokens_used_at',
        'auth_password_reset_tokens',
        ['used_at'],
        postgresql_where=sa.text('used_at IS NULL')
    )


def downgrade() -> None:
    """Drop password reset token table."""
    op.drop_index('idx_password_reset_tokens_used_at', table_name='auth_password_reset_tokens')
    op.drop_index('idx_password_reset_tokens_expires_at', table_name='auth_password_reset_tokens')
    op.drop_index('idx_password_reset_tokens_user_id', table_name='auth_password_reset_tokens')
    op.drop_table('auth_password_reset_tokens')
