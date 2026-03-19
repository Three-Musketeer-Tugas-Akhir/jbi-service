"""Tests for migration 002: Add auth domain tables."""

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_auth_users_table_exists(db_session: AsyncSession):
    """Test that auth_users table is created with correct columns."""
    
    result = await db_session.execute(text("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = 'auth_users'
        ORDER BY ordinal_position;
    """))
    columns = {row[0]: (row[1], row[2]) for row in result.fetchall()}
    
    # Verify all expected columns exist
    assert 'id' in columns
    assert 'email' in columns
    assert 'password_hash' in columns
    assert 'role' in columns
    assert 'is_active' in columns
    assert 'created_at' in columns
    assert 'updated_at' in columns
    
    # Verify column types
    assert columns['email'][0] == 'character varying'
    assert columns['password_hash'][0] == 'character varying'
    assert columns['role'][0] == 'character varying'
    assert columns['is_active'][0] == 'boolean'


@pytest.mark.asyncio
async def test_auth_roles_table_exists(db_session: AsyncSession):
    """Test that auth_roles table is created with correct columns."""
    
    result = await db_session.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'auth_roles'
        ORDER BY ordinal_position;
    """))
    columns = {row[0]: row[1] for row in result.fetchall()}
    
    # Verify all expected columns exist
    assert 'id' in columns
    assert 'name' in columns
    assert 'permissions' in columns
    assert 'created_at' in columns
    
    # Verify column types
    assert columns['name'] == 'character varying'
    assert columns['permissions'] == 'jsonb'


@pytest.mark.asyncio
async def test_auth_user_roles_table_exists(db_session: AsyncSession):
    """Test that auth_user_roles junction table is created."""
    
    result = await db_session.execute(text("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'auth_user_roles'
        ORDER BY ordinal_position;
    """))
    columns = {row[0]: row[1] for row in result.fetchall()}
    
    # Verify columns exist
    assert 'user_id' in columns
    assert 'role_id' in columns
    assert 'created_at' in columns


@pytest.mark.asyncio
async def test_indexes_created(db_session: AsyncSession):
    """Test that indexes are created on auth_users."""
    
    result = await db_session.execute(text("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'auth_users';
    """))
    indexes = [row[0] for row in result.fetchall()]
    
    # Verify indexes exist
    assert any('idx_auth_users_email' in idx for idx in indexes)
    assert any('idx_auth_users_role' in idx for idx in indexes)
    assert any('idx_auth_users_is_active' in idx for idx in indexes)


@pytest.mark.asyncio
async def test_foreign_key_constraints(db_session: AsyncSession):
    """Test that foreign key constraints are created."""
    
    result = await db_session.execute(text("""
        SELECT
            tc.constraint_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM
            information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_name = 'auth_user_roles';
    """))
    constraints = result.fetchall()
    
    # Should have 2 foreign keys
    assert len(constraints) == 2
    
    # Verify references to correct tables
    foreign_tables = [c[2] for c in constraints]
    assert 'auth_users' in foreign_tables
    assert 'auth_roles' in foreign_tables


@pytest.mark.asyncio
async def test_initial_roles_seeded(db_session: AsyncSession):
    """Test that initial roles are seeded."""
    
    result = await db_session.execute(text("""
        SELECT name, permissions
        FROM auth_roles
        ORDER BY name;
    """))
    roles = {row[0]: row[1] for row in result.fetchall()}
    
    # Verify all three roles exist
    assert 'admin' in roles
    assert 'annotator' in roles
    assert 'curator' in roles
    
    # Verify permissions are set
    assert roles['admin'] == '["*"]'
    assert 'read:own_queue' in roles['annotator']
    assert 'write:reviews' in roles['curator']
