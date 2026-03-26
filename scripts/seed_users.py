#!/usr/bin/env python3
"""
Seed script for creating users with all roles and permissions.

This script creates:
1. All roles (admin, annotator, curator) with their default permissions
2. Seed users for each role with secure passwords
3. Test users with various permission combinations

Usage:
    python scripts/seed_users.py
    
Environment:
    Requires DATABASE_URL to be set in environment or .env file
"""

import asyncio
import sys
import os
from datetime import datetime, timezone
from uuid import uuid4

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import async_session
from app.db.models.auth import User, Role
from app.core.security import hash_password


# =============================================================================
# Role Definitions
# =============================================================================

ROLES = {
    "admin": {
        "name": "admin",
        "permissions": ["*"],  # All permissions
        "description": "System administrator with full access"
    },
    "curator": {
        "name": "curator",
        "permissions": [
            "annotation:read:all",
            "annotation:write:reviews",
            "export:read",
            "slang:read",
        ],
        "description": "Curator who reviews and approves annotations"
    },
    "annotator": {
        "name": "annotator",
        "permissions": [
            "annotation:read:own",
            "annotation:write:own",
            "queue:read:own",
        ],
        "description": "Annotator who creates and edits annotations"
    },
}

# =============================================================================
# Seed User Definitions
# =============================================================================

SEED_USERS = [
    # Admin users
    {
        "email": "admin@anotasi.ai",
        "password": "Admin123!",
        "roles": ["admin"],
        "is_active": True,
    },
    {
        "email": "superadmin@anotasi.ai",
        "password": "SuperAdmin123!",
        "roles": ["admin"],
        "is_active": True,
    },
    
    # Curator users
    {
        "email": "curator@anotasi.ai",
        "password": "Curator123!",
        "roles": ["curator"],
        "is_active": True,
    },
    {
        "email": "curator2@anotasi.ai",
        "password": "Curator123!",
        "roles": ["curator"],
        "is_active": True,
    },
    
    # Annotator users
    {
        "email": "annotator@anotasi.ai",
        "password": "Annotator123!",
        "roles": ["annotator"],
        "is_active": True,
    },
    {
        "email": "annotator2@anotasi.ai",
        "password": "Annotator123!",
        "roles": ["annotator"],
        "is_active": True,
    },
    {
        "email": "annotator3@anotasi.ai",
        "password": "Annotator123!",
        "roles": ["annotator"],
        "is_active": True,
    },
    
    # Multi-role users (for testing role combinations)
    {
        "email": "annotator_curator@anotasi.ai",
        "password": "MultiRole123!",
        "roles": ["annotator", "curator"],
        "is_active": True,
    },
    
    # Inactive users (for testing)
    {
        "email": "inactive@anotasi.ai",
        "password": "Inactive123!",
        "roles": ["annotator"],
        "is_active": False,
    },
]


# =============================================================================
# Seeding Functions
# =============================================================================

async def seed_roles(session: AsyncSession) -> dict:
    """
    Create all roles if they don't exist.
    
    Returns:
        Dictionary mapping role names to Role objects
    """
    print("🎭 Seeding roles...")
    
    roles_by_name = {}
    
    for role_key, role_data in ROLES.items():
        # Check if role already exists
        result = await session.execute(
            select(Role).where(Role.name == role_data["name"])
        )
        existing_role = result.scalar_one_or_none()
        
        if existing_role:
            print(f"   ⚠️  Role '{role_data['name']}' already exists, skipping")
            roles_by_name[role_data["name"]] = existing_role
        else:
            # Create new role
            role = Role(
                id=uuid4(),
                name=role_data["name"],
                permissions=role_data["permissions"],
                created_at=datetime.now(timezone.utc)
            )
            session.add(role)
            roles_by_name[role_data["name"]] = role
            print(f"   ✅ Created role: {role_data['name']}")
    
    await session.commit()
    print(f"🎭 Roles seeding complete!\n")
    return roles_by_name


async def seed_users(session: AsyncSession, roles_by_name: dict) -> list:
    """
    Create all seed users if they don't exist.
    
    Returns:
        List of created User objects
    """
    print("👤 Seeding users...")
    
    created_users = []
    
    for user_data in SEED_USERS:
        # Check if user already exists
        result = await session.execute(
            select(User).where(User.email == user_data["email"])
        )
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            print(f"   ⚠️  User '{user_data['email']}' already exists, skipping")
            continue
        
        # Create new user
        user = User(
            id=uuid4(),
            email=user_data["email"],
            password_hash=hash_password(user_data["password"]),
            is_active=user_data["is_active"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        
        # Assign roles
        for role_name in user_data["roles"]:
            if role_name in roles_by_name:
                user.roles.append(roles_by_name[role_name])
        
        session.add(user)
        created_users.append(user)
        
        status = "active" if user_data["is_active"] else "inactive"
        roles_str = ", ".join(user_data["roles"])
        print(f"   ✅ Created user: {user_data['email']} ({status}) - roles: [{roles_str}]")
    
    await session.commit()
    print(f"👤 Users seeding complete! Created {len(created_users)} users\n")
    return created_users


async def verify_seed_data(session: AsyncSession):
    """Print summary of seeded data for verification."""
    print("📊 Verification Summary:")
    print("=" * 60)
    
    # Count roles
    result = await session.execute(select(Role))
    roles = result.scalars().all()
    print(f"\n🎭 Total Roles: {len(roles)}")
    for role in roles:
        perm_count = len(role.permissions)
        print(f"   - {role.name}: {perm_count} permission(s)")
    
    # Count users by role
    result = await session.execute(select(User))
    users = result.scalars().all()
    
    admin_count = sum(1 for u in users if u.has_role("admin"))
    curator_count = sum(1 for u in users if u.has_role("curator"))
    annotator_count = sum(1 for u in users if u.has_role("annotator"))
    inactive_count = sum(1 for u in users if not u.is_active)
    
    print(f"\n👤 Total Users: {len(users)}")
    print(f"   - Admin users: {admin_count}")
    print(f"   - Curator users: {curator_count}")
    print(f"   - Annotator users: {annotator_count}")
    print(f"   - Inactive users: {inactive_count}")
    
    print("\n" + "=" * 60)
    print("✅ Seed data verification complete!")


async def print_login_credentials():
    """Print login credentials for seeded users."""
    print("\n🔐 Login Credentials:")
    print("=" * 60)
    print(f"{'Email':<35} {'Password':<20} {'Roles'}")
    print("-" * 60)
    
    for user_data in SEED_USERS:
        if user_data["is_active"]:
            roles_str = ", ".join(user_data["roles"])
            print(f"{user_data['email']:<35} {user_data['password']:<20} {roles_str}")
    
    print("=" * 60)


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    """Main entry point for seeding."""
    print("\n" + "=" * 60)
    print("🌱 ANOTASI.AI DATABASE SEEDER")
    print("=" * 60 + "\n")
    
    try:
        async with async_session() as session:
            # Seed roles first
            roles_by_name = await seed_roles(session)
            
            # Seed users
            created_users = await seed_users(session, roles_by_name)
            
            # Verify data
            await verify_seed_data(session)
            
            # Print credentials
            await print_login_credentials()
            
            print("\n🎉 Seeding completed successfully!")
            print("   You can now log in with any of the credentials above.\n")
            
    except Exception as e:
        print(f"\n❌ Error during seeding: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
