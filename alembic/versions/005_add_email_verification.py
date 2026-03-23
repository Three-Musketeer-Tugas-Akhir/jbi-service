"""Add email verification tokens table

Revision ID: 005
Revises: 004_add_password_reset_tokens
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '005_add_email_verification'
down_revision: Union[str, None] = '004_add_password_reset_tokens'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create email verification tracking table and add column to users."""
    
    # Add email_verified_at column to users table
    op.add_column(
        'auth_users',
        sa.Column(
            'email_verified_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment="When email was verified (NULL if not verified)"
        )
    )
    
    # Create index on email_verified_at for filtering unverified users
    op.create_index(
        'idx_auth_users_email_verified_at',
        'auth_users',
        ['email_verified_at'],
        postgresql_where=sa.text('email_verified_at IS NULL')
    )
    
    # Create email verification tokens table
    op.create_table(
        'auth_email_verification_tokens',
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
            comment="Bcrypt hash of the verification token"
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
        'idx_email_verification_tokens_user_id',
        'auth_email_verification_tokens',
        ['user_id']
    )
    op.create_index(
        'idx_email_verification_tokens_expires_at',
        'auth_email_verification_tokens',
        ['expires_at']
    )


def downgrade() -> None:
    """Drop email verification table and column."""
    op.drop_index('idx_email_verification_tokens_expires_at', table_name='auth_email_verification_tokens')
    op.drop_index('idx_email_verification_tokens_user_id', table_name='auth_email_verification_tokens')
    op.drop_table('auth_email_verification_tokens')
    
    op.drop_index('idx_auth_users_email_verified_at', table_name='auth_users')
    op.drop_column('auth_users', 'email_verified_at')
