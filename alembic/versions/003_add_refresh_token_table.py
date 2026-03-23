"""Add refresh token table

Revision ID: 003
Revises: 002_add_auth_tables
Create Date: 2026-03-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '003_add_refresh_token_table'
down_revision: Union[str, None] = '002_add_auth_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create refresh token tracking table."""
    
    op.create_table(
        'auth_refresh_tokens',
        sa.Column(
            'jti',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'expires_at',
            sa.DateTime(timezone=True),
            nullable=False
        ),
        sa.Column(
            'revoked_at',
            sa.DateTime(timezone=True),
            nullable=True
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.Column(
            'rotated_to_jti',
            postgresql.UUID(as_uuid=True),
            nullable=True
        ),
        sa.PrimaryKeyConstraint('jti'),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['auth_users.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['rotated_to_jti'],
            ['auth_refresh_tokens.jti'],
            ondelete='SET NULL'
        )
    )
    
    # Create indexes
    op.create_index(
        'idx_auth_refresh_tokens_user_id',
        'auth_refresh_tokens',
        ['user_id']
    )
    op.create_index(
        'idx_auth_refresh_tokens_expires_at',
        'auth_refresh_tokens',
        ['expires_at']
    )
    op.create_index(
        'idx_auth_refresh_tokens_revoked_at',
        'auth_refresh_tokens',
        ['revoked_at'],
        postgresql_where=sa.text('revoked_at IS NOT NULL')
    )


def downgrade() -> None:
    """Drop refresh token table."""
    op.drop_index('idx_auth_refresh_tokens_revoked_at', table_name='auth_refresh_tokens')
    op.drop_index('idx_auth_refresh_tokens_expires_at', table_name='auth_refresh_tokens')
    op.drop_index('idx_auth_refresh_tokens_user_id', table_name='auth_refresh_tokens')
    op.drop_table('auth_refresh_tokens')
