"""Migrate to many-to-many roles

Revision ID: 007
Revises: 006_add_audit_log_table
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import text

# revision identifiers, used by Alembic
revision: str = '007_migrate_to_many_to_many_roles'
down_revision: Union[str, None] = '006_add_audit_log_table'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Migrate from single role column to many-to-many relationship."""
    
    # Step 1: Migrate existing role data to junction table
    # For each user, insert their role into auth_user_roles
    op.execute("""
        INSERT INTO auth_user_roles (user_id, role_id, created_at)
        SELECT 
            u.id,
            r.id,
            NOW()
        FROM auth_users u
        JOIN auth_roles r ON u.role = r.name
        ON CONFLICT (user_id, role_id) DO NOTHING;
    """)
    
    # Step 2: Drop the role column index
    op.drop_index('idx_auth_users_role', table_name='auth_users')
    
    # Step 3: Drop the role column
    op.drop_column('auth_users', 'role')


def downgrade() -> None:
    """Revert to single role column."""
    
    # Step 1: Add back the role column (nullable initially)
    op.add_column(
        'auth_users',
        sa.Column('role', sa.String(20), nullable=True)
    )
    
    # Step 2: Migrate data back from junction table to role column
    # Use the first role found for each user
    op.execute("""
        UPDATE auth_users u
        SET role = (
            SELECT r.name
            FROM auth_user_roles ur
            JOIN auth_roles r ON ur.role_id = r.id
            WHERE ur.user_id = u.id
            ORDER BY ur.created_at
            LIMIT 1
        );
    """)
    
    # Step 3: Make role column non-nullable with default
    op.alter_column('auth_users', 'role', 
                    server_default='annotator',
                    nullable=False)
    
    # Step 4: Recreate the index
    op.create_index(
        'idx_auth_users_role',
        'auth_users',
        ['role']
    )
