---
story_id: "1.1"
story_key: "1-1-database-schema-setup-auth-domain"
epic: 1
status: done
created: "2026-03-18"
last_updated: "2026-03-18"
completed: "2026-03-18"
code_review_completed: "2026-03-19"
---

# Story 1.1: Database Schema Setup - Auth Domain

## Story Header

**Epic:** 1 - Foundation & Authentication  
**Story ID:** 1.1  
**Status:** done  
**Priority:** Critical (Foundation Story)  
**Estimated Effort:** Medium (2-3 days)

---

## Story Requirements

### User Story

As a developer,  
I want to create the authentication database schema,  
So that user data and roles can be stored and managed.

### Business Context

This is the **FIRST story** in the entire project. It establishes the foundational database schema for user authentication and authorization. Without this schema, no other story can proceed. The auth domain must be completely functional before any user-facing features can be built.

### Acceptance Criteria

**Given** the database migration system is initialized  
**When** I run the auth domain migration  
**Then** the following tables are created:
  - `auth_users` (id, email, password_hash, role, is_active, created_at, updated_at)
  - `auth_roles` (id, name, permissions)
  - `auth_user_roles` (user_id, role_id) - junction table
**And** appropriate indexes are created on email and role fields  
**And** the schema follows domain-prefixed naming convention

### Technical Notes from Epic

- Use Alembic for migration
- Password hash field must support bcrypt (min 60 chars)
- Role enum: 'admin', 'annotator', 'curator'

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **Domain-Prefixed Schema (CRITICAL)**
   - All auth tables MUST use `auth_*` prefix
   - This is non-negotiable per architecture decision
   - Correct: `auth_users`, `auth_roles`, `auth_user_roles`
   - Wrong: `users`, `User`, `AuthUsers`

2. **Naming Conventions**
   - Table names: snake_case (e.g., `auth_users`)
   - Column names: snake_case (e.g., `password_hash`)
   - Foreign keys: `{table}_id` format (e.g., `user_id`)
   - Enums: CONSTANT_CASE string values

3. **SQLAlchemy 2.0 Pattern**
   ```python
   class User(Base):
       __tablename__ = "auth_users"
       id: Mapped[str] = mapped_column(primary_key=True)
   ```

4. **Alembic Migration Structure**
   - Migration file: `alembic/versions/002_add_auth_tables.py`
   - Follow existing project conventions
   - Include both upgrade() and downgrade()

### Technical Requirements

**Required Technologies:**
- PostgreSQL 15+
- SQLAlchemy 2.0+ (async support)
- Alembic (database migrations)
- asyncpg (async PostgreSQL driver)

**Table Specifications:**

```sql
-- auth_users
CREATE TABLE auth_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt produces ~60 chars
    role VARCHAR(20) NOT NULL CHECK (role IN ('admin', 'annotator', 'curator')),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_auth_users_email ON auth_users(email);
CREATE INDEX idx_auth_users_role ON auth_users(role);
CREATE INDEX idx_auth_users_is_active ON auth_users(is_active);

-- auth_roles (for future extensibility, even if using enum now)
CREATE TABLE auth_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(20) NOT NULL UNIQUE,
    permissions JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- auth_user_roles (junction table)
CREATE TABLE auth_user_roles (
    user_id UUID NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES auth_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

-- Initial seed data
INSERT INTO auth_roles (name, permissions) VALUES 
    ('admin', '["*"]'),
    ('annotator', '["read:own_queue", "write:annotations"]'),
    ('curator', '["read:all_annotations", "write:reviews", "read:slang_dictionary"]');
```

### File Structure Requirements

**Required Directory Structure:**
```
jbi-service/
├── alembic/
│   ├── versions/
│   │   └── 002_add_auth_tables.py      # NEW - This migration
│   ├── env.py                           # EXISTING
│   └── script.py.mako                   # EXISTING
├── app/
│   └── db/
│       ├── models/
│       │   ├── __init__.py              # UPDATE - Export auth models
│       │   └── auth.py                  # NEW - Auth models
│       ├── base.py                      # EXISTING - SQLAlchemy base
│       └── session.py                   # EXISTING - AsyncSession
```

### Testing Requirements

**Required Tests:**
1. Migration runs successfully (upgrade)
2. Migration rollback works (downgrade)
3. Tables have correct columns and types
4. Indexes are created
5. Foreign key constraints work
6. Initial seed data is inserted

**Test Location:** `tests/unit/test_migrations/`

---

## Implementation Guide

### Step 1: Create SQLAlchemy Models

File: `app/db/models/auth.py`

```python
from sqlalchemy import String, Boolean, DateTime, ForeignKey, Table, Column
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from app.db.base import Base
import uuid

class User(Base):
    __tablename__ = "auth_users"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), 
        primary_key=True, 
        default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), 
        unique=True, 
        nullable=False,
        index=True
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),  # bcrypt hash ~60 chars
        nullable=False
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

class Role(Base):
    __tablename__ = "auth_roles"
    
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(
        String(20),
        unique=True,
        nullable=False
    )
    permissions: Mapped[dict] = mapped_column(
        JSONB,
        default=list,
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False
    )

# Junction table
user_roles = Table(
    "auth_user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("auth_users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("auth_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("created_at", DateTime(timezone=True), default=datetime.utcnow, nullable=False)
)
```

### Step 2: Create Alembic Migration

Generate migration:
```bash
cd jbi-service
alembic revision --autogenerate -m "Add auth domain tables"
```

Edit generated file in `alembic/versions/002_add_auth_tables.py`:

```python
"""Add auth domain tables

Revision ID: 002
Revises: 001_initial_schema
Create Date: 2026-03-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '002_add_auth_tables'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None

def upgrade():
    # Create auth_roles table
    op.create_table(
        'auth_roles',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(20), nullable=False),
        sa.Column('permissions', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    
    # Create auth_users table
    op.create_table(
        'auth_users',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    
    # Create indexes
    op.create_index('idx_auth_users_email', 'auth_users', ['email'])
    op.create_index('idx_auth_users_role', 'auth_users', ['role'])
    op.create_index('idx_auth_users_is_active', 'auth_users', ['is_active'])
    
    # Create auth_user_roles junction table
    op.create_table(
        'auth_user_roles',
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['role_id'], ['auth_roles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['auth_users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id')
    )
    
    # Seed initial roles
    op.execute("""
        INSERT INTO auth_roles (name, permissions) VALUES 
        ('admin', '["*"]'),
        ('annotator', '["read:own_queue", "write:annotations"]'),
        ('curator', '["read:all_annotations", "write:reviews", "read:slang_dictionary"]');
    """)

def downgrade():
    # Drop in reverse order
    op.drop_table('auth_user_roles')
    op.drop_index('idx_auth_users_is_active', table_name='auth_users')
    op.drop_index('idx_auth_users_role', table_name='auth_users')
    op.drop_index('idx_auth_users_email', table_name='auth_users')
    op.drop_table('auth_users')
    op.drop_table('auth_roles')
```

### Step 3: Update Model Exports

File: `app/db/models/__init__.py`

```python
from app.db.models.auth import User, Role, user_roles

__all__ = ["User", "Role", "user_roles"]
```

### Step 4: Run Migration

```bash
cd jbi-service
alembic upgrade 002_add_auth_tables

# Verify
psql $DATABASE_URL -c "\dt auth_*"
psql $DATABASE_URL -c "SELECT * FROM auth_roles;"
```

---

## Verification Checklist

Before marking this story as complete:

- [ ] `auth_users` table exists with correct columns
- [ ] `auth_roles` table exists with correct columns  
- [ ] `auth_user_roles` junction table exists
- [ ] Indexes created on email, role, is_active
- [ ] Foreign key constraints are working
- [ ] Initial roles seeded (admin, annotator, curator)
- [ ] Migration runs without errors
- [ ] Migration rollback works (downgrade)
- [ ] Models exported in `app/db/models/__init__.py`
- [ ] SQLAlchemy 2.0 syntax used (Mapped, mapped_column)
- [ ] UUID primary keys (not auto-increment integers)
- [ ] Domain-prefixed table names (`auth_*`)

---

## Dependencies

**This story has NO dependencies** - it's the first story.

**Stories that depend on this:**
- Story 1.2: JWT Authentication Service (needs User model)
- Story 1.3: User Login API (needs auth_users table)
- Story 1.6: Admin Create User (needs auth_users table)
- All future stories that require authentication

---

## Next Story

After completing this story, proceed to:  
**Story 1.2: JWT Authentication Service**

This story will implement the JWT token generation and validation service that uses the `auth_users` table created here.

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. This is the FOUNDATION story - get it right!
2. All table names MUST start with `auth_`
3. Use SQLAlchemy 2.0 syntax (not legacy 1.x style)
4. bcrypt hash field needs minimum 60 characters
5. Test the downgrade migration works before marking done
6. Don't skip the initial role seeding - other stories depend on it

**Common Mistakes to Avoid:**
- ❌ Creating tables without `auth_` prefix
- ❌ Using auto-increment integers instead of UUID
- ❌ Using SQLAlchemy 1.x declarative_base() style
- ❌ Forgetting to create indexes
- ❌ Missing the downgrade() function
- ❌ Not seeding initial roles

**Questions?**  
Refer to: `architecture.md` section "Data Architecture" for database conventions.


---

## Implementation Summary

### Files Created/Modified

| File | Status | Description |
|------|--------|-------------|
| `app/db/base.py` | ✅ Created | SQLAlchemy DeclarativeBase |
| `app/db/models/auth.py` | ✅ Created | User, Role, user_roles models |
| `app/db/models/__init__.py` | ✅ Modified | Export auth models |
| `alembic/versions/002_add_auth_tables.py` | ✅ Created | Migration for auth tables |
| `tests/conftest.py` | ✅ Created | Pytest fixtures |
| `tests/unit/test_migrations/test_002_add_auth_tables.py` | ✅ Created | Migration tests |
| `requirements-dev.txt` | ✅ Created | Dev dependencies |

### Tables Created

| Table | Columns | Purpose |
|-------|---------|---------|
| `auth_users` | id, email, password_hash, role, is_active, created_at, updated_at | User accounts |
| `auth_roles` | id, name, permissions, created_at | RBAC roles |
| `auth_user_roles` | user_id, role_id, created_at | User-role assignments |

### Indexes Created

- `idx_auth_users_email` on auth_users.email
- `idx_auth_users_role` on auth_users.role  
- `idx_auth_users_is_active` on auth_users.is_active

### Seed Data

Initial roles inserted:
- `admin` with `["*"]` permissions
- `annotator` with `["read:own_queue", "write:annotations"]`
- `curator` with `["read:all_annotations", "write:reviews", "read:slang_dictionary"]`

### Acceptance Criteria Status

- [x] auth_users table created with correct columns
- [x] auth_roles table created with correct columns
- [x] auth_user_roles junction table created
- [x] Indexes created on email, role, is_active
- [x] Schema follows domain-prefixed naming convention
- [x] Migration runs successfully
- [x] Migration rollback works (downgrade)
- [x] Tests created for migration verification

---

## Dev Agent Record

### Implementation Notes

This story establishes the foundational database schema for authentication. Key decisions:

1. **SQLAlchemy 2.0 Syntax**: Used `Mapped[]` and `mapped_column()` instead of legacy Column() syntax
2. **UUID Primary Keys**: All tables use UUID instead of auto-increment integers for security and distributed system compatibility
3. **Domain Prefixing**: All tables use `auth_*` prefix per architecture decision
4. **Server Defaults**: Used `server_default=func.now()` for timestamps to ensure database-level consistency
5. **JSONB for Permissions**: Role permissions stored as JSONB array for flexibility

### Testing Approach

Created comprehensive tests covering:
- Table existence verification
- Column type validation
- Index creation verification
- Foreign key constraint validation
- Initial seed data verification

### Next Story Dependencies

This story enables:
- Story 1.2: JWT Authentication Service (needs User model)
- Story 1.3: User Login API (needs auth_users table)
- Story 1.6: Admin Create User (needs auth_users table)

---


---

## Code Review Report

**Review Date:** 2026-03-19  
**Review Mode:** Full (Blind Hunter, Edge Case Hunter, Acceptance Auditor)  
**Final Status:** ✅ Approved with fixes

### Review Layers Executed

| Layer | Status | Findings |
|-------|--------|----------|
| Blind Hunter | ✅ Complete | 6 issues found (2 High, 2 Medium, 2 Low) |
| Edge Case Hunter | ✅ Complete | 13 issues found (3 Critical, 10 various) |
| Acceptance Auditor | ✅ Complete | All acceptance criteria satisfied |

### Critical Issues Fixed

| Issue | Severity | Fix Applied |
|-------|----------|-------------|
| UUID type annotation mismatch | High | Changed `Mapped[str]` → `Mapped[UUID]` |
| Role.permissions type mismatch | High | Changed `Mapped[dict]` → `Mapped[List[str]]` |
| Missing onupdate trigger | Medium | Added PostgreSQL trigger function |
| Missing FK indexes | Medium | Added `index=True` to junction table FKs |

### Files Modified During Review

1. `app/db/models/auth.py`
   - Fixed type annotations for UUID fields
   - Fixed permissions type to match JSONB array format

2. `alembic/versions/002_add_auth_tables.py`
   - Added PostgreSQL auto-update trigger for `updated_at`
   - Added indexes on foreign key columns
   - Updated downgrade to clean up trigger

### Deferred Issues (Non-Critical)

The following issues were identified but deferred as they don't block story completion:

| Issue | Severity | Rationale |
|-------|----------|-----------|
| Dual role architecture | Medium | Design decision - requires product input |
| Case-sensitive email | Low | Can be handled at application layer |
| No CHECK constraints | Low | Validated at application layer |
| OAuth compatibility | Low | Future story scope |

### Acceptance Criteria Verification

- [x] All acceptance criteria satisfied
- [x] Critical issues resolved
- [x] Code compiles without errors
- [x] Migration tested (upgrade/downgrade)

### Sign-off

**Code Review:** ✅ Passed  
**Ready for Merge:** Yes  

---
