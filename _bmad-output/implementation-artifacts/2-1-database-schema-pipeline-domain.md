---
story_id: "2.1"
story_key: "2-1-database-schema-pipeline-domain"
epic: 2
status: done
created: "2026-03-24"
last_updated: "2026-03-24"
---

# Story 2.1: Database Schema - Pipeline Domain

## Story Header

**Epic:** 2 - Video Processing Pipeline  
**Story ID:** 2.1  
**Status:** ready-for-dev  
**Priority:** Critical (Foundation)  
**Estimated Effort:** Medium (1-2 days)  
**Dependencies:** 
- Story 1.1: Database Schema Setup - Auth Domain ✅

---

## Story Requirements

### User Story

As a developer,  
I want to create the pipeline database schema,  
So that video processing jobs and segments can be stored and tracked.

### Business Context

This story establishes the foundational database schema for the video processing pipeline. It creates tables to track jobs from upload through detection, ASR transcription, and cropping stages. This schema enables the job queue system and status tracking required for all subsequent Epic 2 stories.

### Acceptance Criteria

**Given** the database migration system is initialized  
**When** I run the pipeline domain migration  
**Then** the following tables are created:

#### Table: pipeline_jobs
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Job identifier |
| video_path | VARCHAR(500) | NOT NULL | MinIO object path |
| original_filename | VARCHAR(255) | NOT NULL | Original upload name |
| status | VARCHAR(50) | NOT NULL, INDEX | Job status enum |
| current_stage | VARCHAR(50) | | Current processing stage |
| error_message | TEXT | | Failure reason |
| created_by | UUID | FK auth_users.id | Uploading user |
| created_at | TIMESTAMP | NOT NULL, INDEX | Creation time |
| updated_at | TIMESTAMP | NOT NULL | Last update |
| completed_at | TIMESTAMP | | Completion time |

**Status values:** UPLOADED, QUEUED, DETECTING, TRANSCRIBING, CROPPING, READY_FOR_ANNOTATION, FAILED, CANCELLED

#### Table: pipeline_segments
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Segment identifier |
| job_id | UUID | FK, INDEX | Parent job |
| segment_index | INTEGER | NOT NULL | Order in video |
| bbox_data | JSONB | | Detection bounding box |
| asr_text | TEXT | | Transcription result |
| asr_confidence | FLOAT | | ASR confidence (0-1) |
| asr_start | FLOAT | | ASR timestamp start (seconds) |
| asr_end | FLOAT | | ASR timestamp end (seconds) |
| jbi_start | FLOAT | | JBI buffer start (seconds) |
| jbi_end | FLOAT | | JBI buffer end (seconds) |
| status | VARCHAR(50) | | Segment status |
| cropped_video_path | VARCHAR(500) | | MinIO path to final clip |

#### Table: pipeline_job_logs
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Log entry ID |
| job_id | UUID | FK, INDEX | Related job |
| stage | VARCHAR(50) | | Processing stage |
| message | TEXT | NOT NULL | Log message |
| created_at | TIMESTAMP | NOT NULL, INDEX | Log time |

#### Table: queue_jobs
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | UUID | PK | Queue job ID |
| queue_name | VARCHAR(100) | NOT NULL, INDEX | Queue identifier |
| payload | JSONB | NOT NULL | Job data |
| status | VARCHAR(50) | NOT NULL, INDEX | Queue status |
| priority | INTEGER | DEFAULT 0 | Job priority |
| attempts | INTEGER | DEFAULT 0 | Retry count |
| max_attempts | INTEGER | DEFAULT 3 | Max retries |
| error_message | TEXT | | Last error |
| created_at | TIMESTAMP | NOT NULL | Creation time |
| scheduled_at | TIMESTAMP | | When to process |
| processed_at | TIMESTAMP | | Completion time |

**Queue status values:** pending, processing, completed, failed

#### Table: config_pipeline_params
| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| key | VARCHAR(100) | PK | Parameter name |
| value | TEXT | NOT NULL | Parameter value |
| description | TEXT | | Human-readable description |
| updated_at | TIMESTAMP | NOT NULL | Last update |

**And** appropriate foreign keys and indexes are created  
**And** status fields use CONSTANT_CASE string values

---

## Developer Context

### Architecture Compliance

**MUST FOLLOW - Architecture Decisions:**

1. **4-Layer Architecture**
   - **API Layer**: (Not applicable - this is schema only)
   - **Service Layer**: (Not applicable - this is schema only)
   - **Repository Layer**: (Not applicable - this is schema only)
   - **Pipeline Layer**: Tables support pipeline processing

2. **Database Patterns**
   - Use Alembic migrations
   - Foreign keys with ON DELETE CASCADE where appropriate
   - Indexes on frequently queried columns (status, job_id, created_at)
   - Use JSONB for flexible data (bbox_data, payload)

3. **Status Management**
   - Use string enums (not database enums) for flexibility
   - CONSTANT_CASE for job statuses
   - lowercase for queue statuses

### Technical Requirements

**Migration Structure:**
```python
# Alembic migration 007_add_pipeline_tables.py
revision = '007_add_pipeline_tables'
down_revision = '006_add_audit_log_table'
```

**Indexes Required:**
```sql
-- Job status lookups
CREATE INDEX idx_pipeline_jobs_status ON pipeline_jobs(status);
CREATE INDEX idx_pipeline_jobs_created_by ON pipeline_jobs(created_by);
CREATE INDEX idx_pipeline_jobs_created_at ON pipeline_jobs(created_at);

-- Segment lookups
CREATE INDEX idx_pipeline_segments_job_id ON pipeline_segments(job_id);

-- Log lookups
CREATE INDEX idx_pipeline_job_logs_job_id ON pipeline_job_logs(job_id);
CREATE INDEX idx_pipeline_job_logs_created_at ON pipeline_job_logs(created_at);

-- Queue processing
CREATE INDEX idx_queue_jobs_status ON queue_jobs(status);
CREATE INDEX idx_queue_jobs_queue_name ON queue_jobs(queue_name);
CREATE INDEX idx_queue_jobs_scheduled_at ON queue_jobs(scheduled_at);
```

**Foreign Keys:**
```sql
-- Job creator reference
ALTER TABLE pipeline_jobs 
  ADD CONSTRAINT fk_pipeline_jobs_created_by 
  FOREIGN KEY (created_by) REFERENCES auth_users(id) ON DELETE SET NULL;

-- Segment parent job
ALTER TABLE pipeline_segments 
  ADD CONSTRAINT fk_pipeline_segments_job_id 
  FOREIGN KEY (job_id) REFERENCES pipeline_jobs(id) ON DELETE CASCADE;

-- Log parent job
ALTER TABLE pipeline_job_logs 
  ADD CONSTRAINT fk_pipeline_job_logs_job_id 
  FOREIGN KEY (job_id) REFERENCES pipeline_jobs(id) ON DELETE CASCADE;
```

---

## Implementation Guide

### Phase 1: Create Migration

#### Step 1.1: Create alembic/versions/007_add_pipeline_tables.py

```python
"""Add pipeline domain tables

Revision ID: 007
Revises: 006_add_audit_log_table
Create Date: 2026-03-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '007_add_pipeline_tables'
down_revision: Union[str, None] = '006_add_audit_log_table'
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    """Create pipeline domain tables."""
    
    # pipeline_jobs table
    op.create_table(
        'pipeline_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('video_path', sa.String(500), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('current_stage', sa.String(50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_jobs
    op.create_index('idx_pipeline_jobs_status', 'pipeline_jobs', ['status'])
    op.create_index('idx_pipeline_jobs_created_by', 'pipeline_jobs', ['created_by'])
    op.create_index('idx_pipeline_jobs_created_at', 'pipeline_jobs', ['created_at'])
    
    # Foreign key to auth_users
    op.create_foreign_key(
        'fk_pipeline_jobs_created_by',
        'pipeline_jobs', 'auth_users',
        ['created_by'], ['id'],
        ondelete='SET NULL'
    )
    
    # pipeline_segments table
    op.create_table(
        'pipeline_segments',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('segment_index', sa.Integer(), nullable=False),
        sa.Column('bbox_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('asr_text', sa.Text(), nullable=True),
        sa.Column('asr_confidence', sa.Float(), nullable=True),
        sa.Column('asr_start', sa.Float(), nullable=True),
        sa.Column('asr_end', sa.Float(), nullable=True),
        sa.Column('jbi_start', sa.Float(), nullable=True),
        sa.Column('jbi_end', sa.Float(), nullable=True),
        sa.Column('status', sa.String(50), nullable=True),
        sa.Column('cropped_video_path', sa.String(500), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_segments
    op.create_index('idx_pipeline_segments_job_id', 'pipeline_segments', ['job_id'])
    
    # Foreign key to pipeline_jobs
    op.create_foreign_key(
        'fk_pipeline_segments_job_id',
        'pipeline_segments', 'pipeline_jobs',
        ['job_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # pipeline_job_logs table
    op.create_table(
        'pipeline_job_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('stage', sa.String(50), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for pipeline_job_logs
    op.create_index('idx_pipeline_job_logs_job_id', 'pipeline_job_logs', ['job_id'])
    op.create_index('idx_pipeline_job_logs_created_at', 'pipeline_job_logs', ['created_at'])
    
    # Foreign key to pipeline_jobs
    op.create_foreign_key(
        'fk_pipeline_job_logs_job_id',
        'pipeline_job_logs', 'pipeline_jobs',
        ['job_id'], ['id'],
        ondelete='CASCADE'
    )
    
    # queue_jobs table
    op.create_table(
        'queue_jobs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('queue_name', sa.String(100), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(50), nullable=False),
        sa.Column('priority', sa.Integer(), server_default='0', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('max_attempts', sa.Integer(), server_default='3', nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for queue_jobs
    op.create_index('idx_queue_jobs_status', 'queue_jobs', ['status'])
    op.create_index('idx_queue_jobs_queue_name', 'queue_jobs', ['queue_name'])
    op.create_index('idx_queue_jobs_scheduled_at', 'queue_jobs', ['scheduled_at'])
    
    # config_pipeline_params table
    op.create_table(
        'config_pipeline_params',
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )
    
    # Insert default pipeline parameters
    op.bulk_insert(
        'config_pipeline_params',
        [
            {
                'key': 'min_segment_duration',
                'value': '3.0',
                'description': 'Minimum segment duration in seconds'
            },
            {
                'key': 'max_concurrent_jobs',
                'value': '3',
                'description': 'Maximum concurrent video processing jobs'
            },
            {
                'key': 'queue_max_depth',
                'value': '50',
                'description': 'Maximum pending jobs in queue'
            },
            {
                'key': 'asr_model_default',
                'value': 'base',
                'description': 'Default ASR model size (tiny/base/small/medium/large-v3)'
            },
            {
                'key': 'jbi_buffer_seconds',
                'value': '2.0',
                'description': 'JBI buffer time added to ASR timestamps'
            }
        ]
    )


def downgrade() -> None:
    """Drop pipeline domain tables."""
    op.drop_table('config_pipeline_params')
    op.drop_table('queue_jobs')
    op.drop_table('pipeline_job_logs')
    op.drop_table('pipeline_segments')
    op.drop_table('pipeline_jobs')
```

### Phase 2: Create SQLAlchemy Models

#### Step 2.1: Create app/db/models/pipeline.py

```python
"""
Pipeline domain models.

Models for video processing pipeline and job queue.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Float, Integer, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PipelineJob(Base):
    """Video processing job."""
    
    __tablename__ = "pipeline_jobs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    video_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    current_stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False,
        index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    # Relationships
    segments: Mapped[List["PipelineSegment"]] = relationship(
        "PipelineSegment",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    logs: Mapped[List["PipelineJobLog"]] = relationship(
        "PipelineJobLog",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<PipelineJob(id={self.id}, status={self.status})>"


class PipelineSegment(Base):
    """Video segment from pipeline processing."""
    
    __tablename__ = "pipeline_segments"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    bbox_data: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    asr_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    asr_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    asr_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    asr_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    jbi_start: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    jbi_end: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cropped_video_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Relationships
    job: Mapped["PipelineJob"] = relationship("PipelineJob", back_populates="segments")
    
    def __repr__(self) -> str:
        return f"<PipelineSegment(id={self.id}, job_id={self.job_id}, index={self.segment_index})>"


class PipelineJobLog(Base):
    """Log entry for pipeline job processing."""
    
    __tablename__ = "pipeline_job_logs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    job_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("pipeline_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    stage: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False,
        index=True
    )
    
    # Relationships
    job: Mapped["PipelineJob"] = relationship("PipelineJob", back_populates="logs")
    
    def __repr__(self) -> str:
        return f"<PipelineJobLog(id={self.id}, job_id={self.job_id}, stage={self.stage})>"


class QueueJob(Base):
    """Job queue entry for async processing."""
    
    __tablename__ = "queue_jobs"
    
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    queue_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True
    )
    
    def __repr__(self) -> str:
        return f"<QueueJob(id={self.id}, queue={self.queue_name}, status={self.status})>"


class ConfigPipelineParam(Base):
    """Pipeline configuration parameter."""
    
    __tablename__ = "config_pipeline_params"
    
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default="NOW()",
        nullable=False
    )
    
    def __repr__(self) -> str:
        return f"<ConfigPipelineParam(key={self.key})>"


# Status constants
class JobStatus:
    """Pipeline job status constants."""
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    DETECTING = "DETECTING"
    TRANSCRIBING = "TRANSCRIBING"
    CROPPING = "CROPPING"
    READY_FOR_ANNOTATION = "READY_FOR_ANNOTATION"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class QueueStatus:
    """Queue job status constants."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
```

### Phase 3: Update Model Exports

#### Step 3.1: Update app/db/models/__init__.py

```python
"""Database models."""

from app.db.models.auth import User, Role, RefreshToken
from app.db.models.audit import AuditLog, AuditAction
from app.db.models.pipeline import (
    PipelineJob,
    PipelineSegment,
    PipelineJobLog,
    QueueJob,
    ConfigPipelineParam,
    JobStatus,
    QueueStatus
)

__all__ = [
    "User",
    "Role",
    "RefreshToken",
    "AuditLog",
    "AuditAction",
    "PipelineJob",
    "PipelineSegment",
    "PipelineJobLog",
    "QueueJob",
    "ConfigPipelineParam",
    "JobStatus",
    "QueueStatus",
]
```

### Phase 4: Testing

#### Step 4.1: Create tests/unit/test_migrations/test_007_pipeline_tables.py

```python
"""Tests for migration 007_add_pipeline_tables."""

import pytest
from sqlalchemy import inspect


class TestPipelineTablesMigration:
    """Tests for pipeline domain migration."""
    
    def test_pipeline_jobs_table_exists(self, db_engine):
        """Test pipeline_jobs table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_jobs" in inspector.get_table_names()
    
    def test_pipeline_segments_table_exists(self, db_engine):
        """Test pipeline_segments table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_segments" in inspector.get_table_names()
    
    def test_pipeline_job_logs_table_exists(self, db_engine):
        """Test pipeline_job_logs table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_job_logs" in inspector.get_table_names()
    
    def test_queue_jobs_table_exists(self, db_engine):
        """Test queue_jobs table was created."""
        inspector = inspect(db_engine)
        assert "queue_jobs" in inspector.get_table_names()
    
    def test_config_pipeline_params_table_exists(self, db_engine):
        """Test config_pipeline_params table was created."""
        inspector = inspect(db_engine)
        assert "config_pipeline_params" in inspector.get_table_names()
    
    def test_default_config_params_exist(self, db_session):
        """Test default configuration parameters were inserted."""
        from app.db.models.pipeline import ConfigPipelineParam
        
        params = db_session.query(ConfigPipelineParam).all()
        param_keys = {p.key for p in params}
        
        expected_keys = {
            "min_segment_duration",
            "max_concurrent_jobs",
            "queue_max_depth",
            "asr_model_default",
            "jbi_buffer_seconds"
        }
        
        assert expected_keys.issubset(param_keys)
```

---

## Implementation Checklist

### Phase 1: Migration
- [ ] Create alembic/versions/007_add_pipeline_tables.py
- [ ] Run migration: `alembic upgrade head`

### Phase 2: Models
- [ ] Create app/db/models/pipeline.py
- [ ] Update app/db/models/__init__.py exports

### Phase 3: Testing
- [ ] Create migration tests
- [ ] Run tests: `pytest tests/unit/test_migrations/`

### Phase 4: Validation
- [ ] Verify tables created in database
- [ ] Verify indexes created
- [ ] Verify foreign keys
- [ ] Verify default config params

---

## Dependencies

**This story depends on:**
- Story 1.1: Database Schema Setup - Auth Domain ✅

**Stories that depend on this:**
- Story 2.2: MinIO Storage Integration
- Story 2.3: Video Upload API
- Story 2.4: PostgreSQL Queue Implementation
- Story 2.5: Detection Worker - YOLOv8
- Story 2.6: ASR Worker - faster-whisper
- Story 2.7: Cropping Worker - JBI Buffer
- Story 2.8: Job Status API & Polling
- Story 2.9: Job Cancellation
- Story 2.10: Health Check & System Monitoring

---

## Next Story

After completing this story, proceed to:  
**Story 2.2: MinIO Storage Integration**

---

## Notes for Developer

**CRITICAL REMINDERS:**
1. This is the foundation for all Epic 2 stories - get it right
2. Use proper indexes for queue performance
3. JSONB for bbox_data allows flexible detection formats
4. Default config params prevent "key not found" errors

**Common Mistakes to Avoid:**
- ❌ Forgetting indexes on status columns (queue performance)
- ❌ Using database enums instead of string constants
- ❌ Missing ON DELETE for foreign keys
- ❌ Not creating default config params

**Performance Considerations:**
- Queue status + scheduled_at index for efficient dequeuing
- Job status index for status filtering
- Job created_at index for recent jobs queries

---

## Dev Agent Record

### Implementation Plan
- **Approach**: Follow Alembic migration pattern, create SQLAlchemy 2.0 models
- **Key Decisions**:
  - String constants for status (flexibility)
  - JSONB for bbox_data and payload
  - ON DELETE CASCADE for segment/log cleanup
  - Default config params in migration

### Files to Create/Modify
| File | Action |
|------|--------|
| `alembic/versions/007_add_pipeline_tables.py` | Create |
| `app/db/models/pipeline.py` | Create |
| `app/db/models/__init__.py` | Update exports |
| `tests/unit/test_migrations/test_007_pipeline_tables.py` | Create |

### Schema Summary
- 5 tables: pipeline_jobs, pipeline_segments, pipeline_job_logs, queue_jobs, config_pipeline_params
- 10+ indexes for query performance
- 3 foreign keys with appropriate cascade rules
- 5 default config parameters
