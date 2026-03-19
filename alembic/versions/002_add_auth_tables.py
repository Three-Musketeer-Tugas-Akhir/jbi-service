"""Add auth domain tables

Revision ID: 002
Revises: 001_initial_schema
Create Date: 2026-03-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic
revision: str = '002_add_auth_tables'
down_revision: Union[str, None] = '001_initial_schema'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create auth domain tables."""
    
    # Create auth_roles table
    op.create_table(
        'auth_roles',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False
        ),
        sa.Column(
            'name',
            sa.String(20),
            nullable=False
        ),
        sa.Column(
            'permissions',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default='[]',
            nullable=False
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create auth_users table
    op.create_table(
        'auth_users',
        sa.Column(
            'id',
            postgresql.UUID(as_uuid=True),
            server_default=sa.text('gen_random_uuid()'),
            nullable=False
        ),
        sa.Column(
            'email',
            sa.String(255),
            nullable=False
        ),
        sa.Column(
            'password_hash',
            sa.String(255),
            nullable=False
        ),
        sa.Column(
            'role',
            sa.String(20),
            nullable=False
        ),
        sa.Column(
            'is_active',
            sa.Boolean(),
            server_default='true',
            nullable=False
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    
    # Create indexes for auth_users
    op.create_index(
        'idx_auth_users_email',
        'auth_users',
        ['email']
    )
    op.create_index(
        'idx_auth_users_role',
        'auth_users',
        ['role']
    )
    op.create_index(
        'idx_auth_users_is_active',
        'auth_users',
        ['is_active']
    )
    
    # Create auth_user_roles junction table
    op.create_table(
        'auth_user_roles',
        sa.Column(
            'user_id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'role_id',
            postgresql.UUID(as_uuid=True),
            nullable=False
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('NOW()'),
            nullable=False
        ),
        sa.ForeignKeyConstraint(
            ['role_id'],
            ['auth_roles.id'],
            ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['auth_users.id'],
            ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    
    # Seed initial roles
    op.execute("""
        INSERT INTO auth_roles (name, permissions) VALUES 
        ('admin', '["*"]'),
        ('annotator', '["read:own_queue", "write:annotations"]'),
        ('curator', '["read:all_annotations", "write:reviews", "read:slang_dictionary"]');
    """)


def downgrade() -> None:
    """Drop auth domain tables."""
    
    # Drop in reverse order to respect foreign key constraints
    op.drop_table('auth_user_roles')
    op.drop_index('idx_auth_users_is_active', table_name='auth_users')
    op.drop_index('idx_auth_users_role', table_name='auth_users')
    op.drop_index('idx_auth_users_email', table_name='auth_users')
    op.drop_table('auth_users')
    op.drop_table('auth_roles')
