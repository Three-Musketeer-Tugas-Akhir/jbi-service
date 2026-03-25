---
story_id: "3.1"
story_key: "3-1-database-schema-annotation-domain"
epic: 3
title: "Database Schema - Annotation Domain"
status: done
created: "2026-03-25"
last_updated: "2026-03-25"
---

# Story 3.1: Database Schema - Annotation Domain

## Story Header

**Epic:** 3 - Annotation Workflow  
**Story ID:** 3.1  
**Status:** done  
**Priority:** High (Foundation)  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.10: Health Check & System Monitoring ✅

---

## Story Requirements

### User Story

As a developer,  
I want to create the annotation database schema,  
So that annotation edits and reviews can be stored and tracked.

### Business Context

This is the foundation for Epic 3 (Annotation Workflow). The annotation domain handles:
- Annotators editing transcripts and timestamps
- ASR reviewers validating transcripts before annotation
- Curators reviewing and approving/rejecting annotations
- Comments and feedback on annotations
- Queue management for work assignment

### Acceptance Criteria

**Given** the database migration system is initialized  
**When** I run the annotation domain migration  
**Then** the following tables are created:
  - `annotation_edits` (id, segment_id, editor_id, old_text, new_text, old_start, old_end, new_start, new_end, edited_at)
  - `annotation_reviews` (id, edit_id, curator_id, status, feedback, reviewed_at)
  - `annotation_comments` (id, edit_id, user_id, comment, created_at)
  - `asr_reviews` (id, segment_id, reviewer_id, original_text, corrected_text, status, confidence_score, reviewed_at)
  - `annotation_queue` (id, segment_id, annotator_id, status, priority, assigned_at, due_date)

**And** foreign keys link to pipeline_segments and auth_users  
**And** appropriate indexes support queue queries

---

## Developer Context

### Architecture Alignment

This story extends the **domain-prefixed schema** pattern:

```
annotation_*   - New annotation domain tables
pipeline_*     - Existing pipeline domain (reference)
auth_*         - Existing auth domain (reference)
```

**Key Pattern:** All annotation tables use `annotation_` prefix and link to `pipeline_segments` and `auth_users`.

### Technical Requirements

1. **Table Naming:** `annotation_{entity}` pattern
2. **Foreign Keys:** Link to `pipeline_segments.id` and `auth_users.id`
3. **Soft Delete:** Edits use `is_deleted` flag to preserve history
4. **Status Enums:** String-based statuses in CONSTANT_CASE
5. **Indexes:** Support queue queries (by annotator_id, status, priority)

---

## Implementation Plan

### Step 1: Alembic Migration (2 hours)

**File:** `alembic/versions/012_add_annotation_tables.py`

```python
"""Add annotation domain tables

Revision ID: 012
Revises: 011_add_job_cancellation_fields
Create Date: 2026-03-25

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers
revision = '012_add_annotation_tables'
down_revision = '011_add_job_cancellation_fields'
branch_labels = None
depends_on = None


def upgrade():
    # =========================================================================
    # annotation_edits - Stores transcript/timestamp edits by annotators
    # =========================================================================
    op.create_table(
        'annotation_edits',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('editor_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Original values (for audit trail)
        sa.Column('old_text', sa.Text(), nullable=True, comment='Original transcript text'),
        sa.Column('old_start', sa.Float(), nullable=True, comment='Original start time in seconds'),
        sa.Column('old_end', sa.Float(), nullable=True, comment='Original end time in seconds'),
        
        # New values
        sa.Column('new_text', sa.Text(), nullable=False, comment='Corrected transcript text'),
        sa.Column('new_start', sa.Float(), nullable=False, comment='Corrected start time in seconds'),
        sa.Column('new_end', sa.Float(), nullable=False, comment='Corrected end time in seconds'),
        
        # Metadata
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', comment='pending, submitted, approved, rejected'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false', comment='Soft delete flag'),
        sa.Column('edited_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for finding edits by segment
    op.create_index('idx_annotation_edits_segment', 'annotation_edits', ['segment_id', 'is_deleted'])
    # Index for finding edits by editor
    op.create_index('idx_annotation_edits_editor', 'annotation_edits', ['editor_id', 'status'])
    
    # =========================================================================
    # annotation_reviews - Curator reviews of annotation edits
    # =========================================================================
    op.create_table(
        'annotation_reviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('edit_id', UUID(as_uuid=True), sa.ForeignKey('annotation_edits.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('curator_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Review details
        sa.Column('status', sa.String(50), nullable=False, comment='approved, rejected'),
        sa.Column('feedback', sa.Text(), nullable=True, comment='Curator feedback to annotator'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    
    # Index for finding reviews by edit
    op.create_index('idx_annotation_reviews_edit', 'annotation_reviews', ['edit_id'])
    
    # =========================================================================
    # annotation_comments - Comments on annotation edits
    # =========================================================================
    op.create_table(
        'annotation_comments',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('edit_id', UUID(as_uuid=True), sa.ForeignKey('annotation_edits.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # Comment content
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    
    # Index for finding comments by edit
    op.create_index('idx_annotation_comments_edit', 'annotation_comments', ['edit_id', 'created_at'])
    
    # =========================================================================
    # asr_reviews - Pre-annotation ASR transcript validation
    # =========================================================================
    op.create_table(
        'asr_reviews',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('reviewer_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='SET NULL'), nullable=True),
        
        # ASR content
        sa.Column('original_text', sa.Text(), nullable=False, comment='Original ASR transcript'),
        sa.Column('corrected_text', sa.Text(), nullable=True, comment='Reviewer corrections'),
        sa.Column('confidence_score', sa.Float(), nullable=True, comment='ASR confidence (0-1)'),
        
        # Review status
        sa.Column('status', sa.String(50), nullable=False, server_default='pending', comment='pending, approved, corrected, flagged'),
        sa.Column('flag_reason', sa.String(255), nullable=True, comment='Reason if flagged'),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for ASR review queue
    op.create_index('idx_asr_reviews_status', 'asr_reviews', ['status', 'confidence_score'])
    
    # =========================================================================
    # annotation_queue - Work assignment queue for annotators
    # =========================================================================
    op.create_table(
        'annotation_queue',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('segment_id', UUID(as_uuid=True), sa.ForeignKey('pipeline_segments.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('annotator_id', UUID(as_uuid=True), sa.ForeignKey('auth_users.id', ondelete='CASCADE'), nullable=False, index=True),
        
        # Queue metadata
        sa.Column('status', sa.String(50), nullable=False, server_default='assigned', comment='assigned, in_progress, completed'),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='0', comment='Higher = higher priority'),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    
    # Index for annotator queue queries
    op.create_index('idx_annotation_queue_annotator', 'annotation_queue', ['annotator_id', 'status', 'priority', 'assigned_at'])
    # Index for finding unassigned/available work
    op.create_index('idx_annotation_queue_status', 'annotation_queue', ['status', 'priority', 'assigned_at'])


def downgrade():
    # Drop in reverse order to handle FK constraints
    op.drop_index('idx_annotation_queue_status')
    op.drop_index('idx_annotation_queue_annotator')
    op.drop_table('annotation_queue')
    
    op.drop_index('idx_asr_reviews_status')
    op.drop_table('asr_reviews')
    
    op.drop_index('idx_annotation_comments_edit')
    op.drop_table('annotation_comments')
    
    op.drop_index('idx_annotation_reviews_edit')
    op.drop_table('annotation_reviews')
    
    op.drop_index('idx_annotation_edits_editor')
    op.drop_index('idx_annotation_edits_segment')
    op.drop_table('annotation_edits')
```

**Verify:**
- Migration runs successfully
- All tables created
- Foreign keys and indexes in place

---

### Step 2: SQLAlchemy Models (2 hours)

**File:** `app/db/models/annotation.py` (new file)

```python
"""
Annotation domain models.

Models for the annotation workflow including:
- Annotation edits (transcript/timestamp corrections)
- Reviews (curator approval/rejection)
- Comments (discussion on edits)
- ASR reviews (pre-annotation validation)
- Queue (work assignment)
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Float, Integer, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AnnotationEdit(Base):
    """Annotation edit - stores transcript/timestamp corrections."""
    
    __tablename__ = "annotation_edits"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    segment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    editor_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    # Original values (for audit trail)
    old_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    old_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    old_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    # New values
    new_text: Mapped[str] = mapped_column(Text, nullable=False)
    new_start: Mapped[float] = mapped_column(Float, nullable=False)
    new_end: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Metadata
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, submitted, approved, rejected"
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Soft delete flag"
    )
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    reviews: Mapped[List["AnnotationReview"]] = relationship(
        "AnnotationReview",
        back_populates="edit",
        cascade="all, delete-orphan"
    )
    comments: Mapped[List["AnnotationComment"]] = relationship(
        "AnnotationComment",
        back_populates="edit",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<AnnotationEdit(id={self.id}, segment_id={self.segment_id}, status={self.status})>"


class AnnotationReview(Base):
    """Curator review of an annotation edit."""
    
    __tablename__ = "annotation_reviews"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    edit_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("annotation_edits.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    curator_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="approved, rejected"
    )
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    
    # Relationships
    edit: Mapped["AnnotationEdit"] = relationship("AnnotationEdit", back_populates="reviews")
    
    def __repr__(self) -> str:
        return f"<AnnotationReview(id={self.id}, edit_id={self.edit_id}, status={self.status})>"


class AnnotationComment(Base):
    """Comment on an annotation edit."""
    
    __tablename__ = "annotation_comments"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    edit_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("annotation_edits.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    
    # Relationships
    edit: Mapped["AnnotationEdit"] = relationship("AnnotationEdit", back_populates="comments")
    
    def __repr__(self) -> str:
        return f"<AnnotationComment(id={self.id}, edit_id={self.edit_id})>"


class ASRReview(Base):
    """Pre-annotation ASR transcript validation."""
    
    __tablename__ = "asr_reviews"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    segment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    reviewer_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    corrected_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, approved, corrected, flagged"
    )
    flag_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    def __repr__(self) -> str:
        return f"<ASRReview(id={self.id}, segment_id={self.segment_id}, status={self.status})>"


class AnnotationQueue(Base):
    """Work assignment queue for annotators."""
    
    __tablename__ = "annotation_queue"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    segment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_segments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )
    annotator_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="assigned",
        comment="assigned, in_progress, completed"
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Higher = higher priority"
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    def __repr__(self) -> str:
        return f"<AnnotationQueue(id={self.id}, segment_id={self.segment_id}, status={self.status})>"


# Status constants
class EditStatus:
    """Annotation edit status constants."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ASRReviewStatus:
    """ASR review status constants."""
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CORRECTED = "CORRECTED"
    FLAGGED = "FLAGGED"


class QueueStatus:
    """Annotation queue status constants."""
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
```

**Verify:**
- Model imports work
- Relationships defined correctly
- Status constants available

---

### Step 3: Update Models Init (30 minutes)

**File:** `app/db/models/__init__.py`

Add annotation models to exports.

```python
# Add to existing imports
from app.db.models.annotation import (
    AnnotationEdit,
    AnnotationReview,
    AnnotationComment,
    ASRReview,
    AnnotationQueue,
    EditStatus,
    ASRReviewStatus,
    QueueStatus,
)

__all__ = [
    # ... existing exports ...
    "AnnotationEdit",
    "AnnotationReview",
    "AnnotationComment",
    "ASRReview",
    "AnnotationQueue",
    "EditStatus",
    "ASRReviewStatus",
    "QueueStatus",
]
```

---

## Testing Checklist

### Migration Tests
- [ ] `test_migration_creates_all_tables()` - All 5 tables exist
- [ ] `test_migration_creates_foreign_keys()` - FKs link correctly
- [ ] `test_migration_creates_indexes()` - Indexes for performance
- [ ] `test_migration_rollback_works()` - Downgrade succeeds

### Model Tests
- [ ] `test_annotation_edit_create()` - Edit model works
- [ ] `test_annotation_review_relationship()` - Review links to edit
- [ ] `test_annotation_queue_unique_segment()` - One queue entry per segment
- [ ] `test_soft_delete_preserves_history()` - is_deleted flag works

---

## Dependencies

### Required Before This Story
- Story 2.1: Database Schema - Pipeline Domain ✅
- Story 2.10: Health Check & System Monitoring ✅

### Required After This Story (depend on this)
- Story 3.2: Annotation Queue API
- Story 3.3: Submit Annotation Edit
- All Epic 3 stories

---

## Deliverables

- [ ] `alembic/versions/012_add_annotation_tables.py` - Migration
- [ ] `app/db/models/annotation.py` - SQLAlchemy models
- [ ] `app/db/models/__init__.py` - Updated exports

---

## Notes

1. **Foreign Key Cascade:** Deleting a segment deletes its annotations (cascade)
2. **Soft Delete:** Edits are soft-deleted to preserve audit history
3. **Unique Constraint:** Each segment can only be in queue once
4. **Status Constants:** Use CONSTANT_CASE for status values
5. **Indexes:** Optimized for annotator queue queries

---

## Dev Agent Record

**To be filled during implementation**

- Developer: 
- Execution Date: 
- Story Status: 
- Implementation Summary: 
- Test Results: 
- Issues Found: 
