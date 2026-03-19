---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2026-03-18'
inputDocuments:
  - path: jbi-service/_bmad-output/planning-artifacts/prd.md
    type: prd
    loaded: true
  - path: docs/implementation_plan_local_video.md
    type: project-documentation
    loaded: false
  - path: docs/asr_code_documentation.md
    type: project-documentation
    loaded: false
  - path: docs/performance_analysis.md
    type: project-documentation
    loaded: false
  - path: asr_code.ipynb
    type: research-notebook
    loaded: false
  - path: cv_asr_annotation.ipynb
    type: research-notebook
    loaded: false
workflowType: architecture
project_name: 'Unified SIBI Pipeline API'
user_name: 'Arxeno'
date: '2026-03-18'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements (63 total):**

1. **Video Processing Pipeline (12 FRs)** - 3-stage ML pipeline with YOLOv8 detection, faster-whisper ASR, timestamp-based cropping with JBI buffer.

2. **Authentication & Authorization (6 FRs)** - JWT-based auth with 3 roles: Admin, Annotator, Curator.

3. **Annotation & Review Workflow (12 FRs)** - Annotators handle both ASR Review (pre-validation) AND Annotation (sync correction). Curators approve/reject with feedback.

4. **User Management (5 FRs)** - Admin CRUD with invitation workflows.

5. **System Administration (5 FRs)** - Health monitoring, pipeline configuration.

6. **Data Export (4 FRs)** - JSON dataset export.

7. **ASR Review (5 FRs)** - Pre-annotation validation performed by Annotators, not a separate role.

8. **Slang Dictionary & Normalization (5 FRs)** - Indonesian slang conversion for Curator workflow.

9. **Audit Trail (5 FRs)** - Immutable compliance logging.

10. **User Onboarding (4 FRs)** - Interactive tours.

**Non-Functional Requirements:**

- **Performance**: 200ms API responses, 2s upload ack, cached polling
- **Security**: TLS 1.3, bcrypt passwords, 1hr pre-signed URLs
- **Scalability**: 3 concurrent jobs, 50 queue depth, 100 concurrent users
- **Accessibility**: WCAG 2.1 AA, keyboard navigation, playback speed controls
- **Reliability**: 95% job completion, ACID consistency, GPU→CPU fallback

### User Roles & Permissions

| Role | Capabilities |
|------|-------------|
| **Admin** | User CRUD, system config, metrics, audit logs |
| **Annotator** | ASR Review queue, Annotation queue, transcript editing, timestamp adjustment |
| **Curator** | Review queue, approve/reject, slang dictionary, export |

### Technical Constraints & Dependencies

- **Brownfield**: Must extend existing JBI Detection API (FastAPI)
- **Algorithm Freeze**: Must follow notebook implementations exactly
- **Model Requirements**: YOLOv8, faster-whisper (local inference, not API)
- **Storage**: MinIO S3-compatible, PostgreSQL metadata
- **Processing**: FFmpeg for video operations

### Cross-Cutting Concerns Identified

1. **RBAC** - JWT middleware enforcing 3-role permissions
2. **Annotator Dual Mode** - ASR Review → Annotation workflow progression
3. **Audit Logging** - Immutable action logging for compliance
4. **State Management** - Job state machine with PostgreSQL persistence
5. **Async Processing** - Background task queue with failure isolation
6. **Video Streaming** - Pre-signed URL generation and expiration
7. **Error Handling** - User-friendly messages for technical failures
8. **Configuration** - Runtime pipeline parameter adjustment

### Scale Assessment

| Indicator | Assessment |
|-----------|------------|
| **Project Complexity** | **High** (multi-stage ML, collaborative workflows, RBAC) |
| **Primary Domain** | Full-stack API + Web Application |
| **Data Volume** | Video files up to 10GB, 100 concurrent users |
| **Real-time Needs** | Polling (not true real-time), smart intervals |
| **Compliance** | Audit trail retention required |

**Estimated Architectural Components**: ~12 major components (API, Auth, Pipeline, Storage, Queue, Annotation, Curation, Admin, ASR Review, Audit, Export, Monitoring)

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
1. Database schema strategy ✅
2. Authentication & authorization patterns
3. API design patterns
4. Job state machine design
5. Video storage & access patterns

**Important Decisions (Shape Architecture):**
6. Error handling standards
7. Caching strategy
8. Background task architecture
9. Frontend-backend contract

**Deferred Decisions (Post-MVP):**
10. Multi-language ASR support
11. Real-time collaboration (WebSocket)
12. Advanced analytics dashboard

### Data Architecture

#### Database Schema Strategy

**Decision**: Domain-Prefixed Schema Separation (Option B)

**Rationale**: Clear domain boundaries make the system easier to understand and maintain as it grows. Each domain (auth, pipeline, annotation, audit) has distinct responsibilities.

**Table Naming Convention**:
```
{domain}_{entity}
```

**Domains Defined**:

| Domain | Tables | Purpose |
|--------|--------|---------|
| `auth_*` | users, roles, user_roles | Authentication & RBAC |
| `pipeline_*` | jobs, segments, job_logs | Video processing pipeline |
| `annotation_*` | edits, reviews, comments | Annotator & Curator work |
| `audit_*` | logs, actions | Compliance tracking |
| `config_*` | slang_dictionary, pipeline_params | System configuration |

**Example Tables**:
```sql
-- Auth domain
auth_users (id, email, password_hash, role, created_at)
auth_roles (id, name, permissions)

-- Pipeline domain
pipeline_jobs (id, video_path, status, current_stage, created_by)
pipeline_segments (id, job_id, bbox_data, asr_text, jbi_start, jbi_end)

-- Annotation domain
annotation_edits (id, segment_id, editor_id, old_text, new_text, old_start, new_start)
annotation_reviews (id, edit_id, curator_id, status, feedback)

-- Audit domain
audit_logs (id, user_id, action, resource_type, resource_id, timestamp)
```

**Version**: PostgreSQL 15+ (existing)

### Authentication & Security

#### Authentication Method

**Decision**: Custom JWT Implementation (Option B)

**Rationale**: Full control over token structure, custom claims (user_id, role, permissions), and expiration policy. Custom implementation allows tight integration with the 3-role RBAC system and specific security requirements.

**Token Structure**:
```json
{
  "sub": "user_uuid",
  "email": "user@lbi.ac.id",
  "role": "annotator|curator|admin",
  "permissions": ["read:own_queue", "write:annotations"],
  "iat": 1710777600,
  "exp": 1710864000,
  "type": "access|refresh"
}
```

**Security Specifications**:
- **Algorithm**: HS256 (symmetric) or RS256 (asymmetric for multi-service future)
- **Access Token TTL**: 24 hours
- **Refresh Token TTL**: 7 days
- **Password Hashing**: bcrypt with 12+ rounds
- **Rate Limiting**: 5 failed attempts per 15 minutes per IP

**Version**: PyJWT 2.8+, Python-Jose as alternative

#### Authorization Pattern

**Decision**: Middleware-based RBAC with route decorators

**Implementation**:
```python
# Role-based decorator
@require_role("admin", "curator")
async def approve_annotation(...)

# Permission-based decorator  
@require_permission("annotation:write")
async def edit_annotation(...)

# Combined
@require_role("annotator")
@require_permission("asr_review:read")
async def review_asr(...)
```

---

### API & Communication Patterns

#### API Architecture Style

**Decision**: Hybrid Approach - REST for resources, Action-based for workflows

**Rationale**: Combines the clarity of REST for CRUD operations with explicit action endpoints for complex workflow transitions.

**RESTful Resources**:
```
GET    /api/v1/jobs              → List jobs (with filters)
POST   /api/v1/jobs              → Create/upload new job
GET    /api/v1/jobs/{id}         → Get job details & status
GET    /api/v1/jobs/{id}/segments → List segments for job
GET    /api/v1/annotations       → List annotations
POST   /api/v1/annotations       → Create annotation edit
PUT    /api/v1/annotations/{id}  → Update annotation
DELETE /api/v1/annotations/{id}  → Delete annotation (soft delete)
```

**Action-Based Workflow Endpoints**:
```
POST   /api/v1/jobs/{id}/cancel
POST   /api/v1/jobs/{id}/retry
POST   /api/v1/annotations/{id}/submit-for-review
POST   /api/v1/reviews/{id}/approve
POST   /api/v1/reviews/{id}/reject
POST   /api/v1/segments/{id}/refresh-url
```

**API Versioning**: URL-based (`/api/v1/`)

**Error Response Format**:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid timestamp format",
    "details": {
      "field": "end_time",
      "value": "invalid"
    }
  }
}
```

#### Polling Strategy

**Decision**: Smart polling with configurable intervals and backend caching

**Client Polling Intervals**:
- Processing states: 5 seconds
- Queued/Completed states: 30 seconds
- Error states: 60 seconds (with backoff)

**Backend Optimization**:
- Job status cached for 2 seconds (Redis or in-memory)
- Cache key: `job_status:{job_id}`

---

### Pipeline State Machine

#### State Definitions

**Decision**: String-based states in CONSTANT_CASE format for readability

**Pipeline Stage States**:
```
UPLOADED → QUEUED → DETECTING → TRANSCRIBING → CROPPING → READY_FOR_ANNOTATION
                                              ↓           ↓
                                           FAILED      FAILED
```

**Annotation Workflow States** (parallel to pipeline):
```
READY_FOR_ANNOTATION → ASR_REVIEW (optional) → ANNOTATING → PENDING_REVIEW
         │                                            ↑           │
         │                                            └───────────┘
         │                                                  (rejected)
         └────────────────────────────────────────────────────────► APPROVED → EXPORTED
```

**Complete State List**:
| State | Description | Actor |
|-------|-------------|-------|
| `UPLOADED` | Video received, awaiting queue | System |
| `QUEUED` | In processing queue | System |
| `DETECTING` | YOLOv8 CV Detection running | System |
| `TRANSCRIBING` | faster-whisper ASR running | System |
| `CROPPING` | Stage 2 cropping with JBI buffer | System |
| `READY_FOR_ANNOTATION` | Pipeline complete, awaiting annotation | System |
| `ASR_REVIEW` | Optional pre-annotation validation | Annotator |
| `ANNOTATING` | Transcript/timestamp editing | Annotator |
| `PENDING_REVIEW` | Submitted, awaiting curator | Annotator |
| `APPROVED` | Curator approved | Curator |
| `REJECTED` | Curator rejected, back to annotator | Curator |
| `EXPORTED` | Dataset exported | System |
| `FAILED` | Processing failed | System |
| `CANCELLED` | Job cancelled by user | User |

#### Failure Recovery Strategy

**Decision**: Hybrid Smart Detection (Option 3)

**Error Classification**:

| Error Type | Examples | Action |
|------------|----------|--------|
| **Transient** | GPU OOM, timeout, network hiccup | Auto-retry with exponential backoff (3x max) |
| **Permanent** | Corrupt file, unsupported codec, missing audio | Fail fast → Manual review queue |

**Retry Policy**:
```python
Retry 1: after 5 seconds
Retry 2: after 15 seconds  
Retry 3: after 45 seconds
→ Then move to FAILED state with error details
```

**ASR Review Configuration**:
- **Optional per job**: Admin can enable/disable via `config_pipeline_params`
- **Parallel processing**: Annotation can begin while ASR Review is pending
- **Skip option**: Annotators can skip ASR Review and go directly to Annotation

---

### Video Storage & Access

#### Video Segment Access Pattern

**Decision**: Pre-signed URLs with refresh endpoint (Option A)

**Rationale**: Offloads video streaming from API server to MinIO, enabling better scalability and performance.

**Access Flow**:
```
1. Frontend requests: GET /api/v1/segments/{id}/download-url
2. API generates pre-signed URL (valid for 1 hour)
3. Frontend streams directly from MinIO
4. When URL expires, frontend calls refresh endpoint
```

**URL Refresh Strategy**:
```
GET /api/v1/segments/{id}/download-url
Headers: Authorization: Bearer {jwt_token}

Response:
{
  "url": "https://minio.example.com/segments/abc123?X-Amz-Algorithm=...",
  "expires_at": "2026-03-18T21:30:00Z",
  "expires_in_seconds": 3600
}
```

**Security**:
- URLs expire after 1 hour (NFR10)
- Refresh endpoint requires valid JWT + permission check
- MinIO bucket policies restrict direct access

**Version**: MinIO latest (S3-compatible)

---

### Decision Impact Summary

**Implementation Sequence**:
1. Database schema with domain prefixes
2. Custom JWT authentication + RBAC middleware
3. Hybrid API endpoints (REST + Action-based)
4. State machine with string-based states
5. Smart failure recovery with error classification
6. Pre-signed URL video access

**Cross-Component Dependencies**:
- Authentication middleware must be in place before all protected endpoints
- State machine drives polling responses (frontend depends on state values)
- Pre-signed URLs depend on MinIO configuration being ready
- Database schema changes must be applied before API deployment

---

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified**: 15+ areas where AI agents could make different choices

---

### Naming Patterns

#### Database Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| **Tables** | snake_case, domain prefix | `auth_users`, `pipeline_jobs`, `annotation_edits` |
| **Columns** | snake_case | `user_id`, `created_at`, `jbi_start` |
| **Foreign Keys** | `{table}_id` format | `job_id` in `pipeline_segments` |
| **Indexes** | `idx_{table}_{columns}` | `idx_pipeline_jobs_status` |
| **Constraints** | `fk_{table}_{field}` or `chk_{table}_{condition}` | `fk_pipeline_segments_job_id` |
| **Enums** | CONSTANT_CASE values | `UPLOADED`, `DETECTING`, `READY_FOR_ANNOTATION` |

#### API Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| **Endpoints** | kebab-case, plural resources | `/api/v1/jobs`, `/api/v1/annotations` |
| **Path Parameters** | camelCase in docs, accessed as-is | `/jobs/{jobId}` → `job_id` in code |
| **Query Parameters** | snake_case | `?status=pending&limit=10` |
| **JSON Fields** | snake_case (consistent with Python) | `{"user_id": "123", "created_at": "..."}` |
| **Headers** | Pascal-Case with hyphens | `Authorization`, `Content-Type` |

#### Code Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| **Python Classes** | PascalCase | `UserService`, `DetectionWorker`, `JobRepository` |
| **Python Functions** | snake_case | `get_user_by_id()`, `process_detection()` |
| **Python Variables** | snake_case | `user_id`, `segment_count` |
| **Constants** | UPPER_SNAKE_CASE | `MAX_RETRY_ATTEMPTS`, `JWT_EXPIRY_HOURS` |
| **Private Methods** | Leading underscore | `_validate_token()`, `_crop_video()` |
| **Async Functions** | Prefix with verb | `async def fetch_user()`, `async def detect_objects()` |

---

### Structure Patterns

#### Project Organization

```
jbi-service/
├── app/
│   ├── api/                    # HTTP/API Layer (thin controllers)
│   │   ├── deps.py             # FastAPI dependencies
│   │   └── v1/                 # API version 1
│   │       ├── auth.py         # Auth endpoints
│   │       ├── jobs.py         # Job endpoints
│   │       ├── annotations.py  # Annotation endpoints
│   │       └── admin.py        # Admin endpoints
│   │
│   ├── core/                   # Shared infrastructure
│   │   ├── config.py           # Settings (pydantic-settings)
│   │   ├── security.py         # JWT, password hashing
│   │   ├── events.py           # Event bus for decoupling
│   │   └── exceptions.py       # Custom exceptions
│   │
│   ├── db/                     # Database Layer
│   │   ├── base.py             # SQLAlchemy declarative base
│   │   ├── session.py          # AsyncSession management
│   │   └── models/             # SQLAlchemy models
│   │       ├── auth.py         # User, Role
│   │       ├── pipeline.py     # Job, Segment
│   │       └── annotation.py   # Edit, Review
│   │
│   ├── schemas/                # Pydantic Models (API contracts)
│   │   ├── auth.py             # UserCreate, TokenResponse
│   │   ├── job.py              # JobCreate, JobResponse
│   │   └── annotation.py       # AnnotationEdit, ReviewSubmit
│   │
│   ├── services/               # Business Logic Layer
│   │   ├── auth_service.py     # User CRUD, JWT generation
│   │   ├── job_service.py      # Job lifecycle management
│   │   ├── annotation_service.py # Annotation workflow
│   │   └── minio_service.py    # S3/pre-signed URL operations
│   │
│   ├── workers/                # Async Worker Layer (queue consumers)
│   │   ├── base.py             # BaseWorker abstract class
│   │   ├── detection_worker.py # Stage 1: YOLOv8
│   │   ├── asr_worker.py       # Stage 2: faster-whisper
│   │   └── cropping_worker.py  # Stage 3: JBI cropping
│   │
│   ├── pipeline/               # ML Pipeline Logic (pure processing)
│   │   ├── models/             # ML model wrappers
│   │   │   ├── detector.py     # YOLOv8 wrapper
│   │   │   ├── transcriber.py  # faster-whisper wrapper
│   │   │   └── cropper.py      # Video cropping
│   │   ├── stages/             # Stage implementations
│   │   │   ├── stage1_detection.py
│   │   │   ├── stage2_asr.py
│   │   │   └── stage3_cropping.py
│   │   └── utils/              # Pipeline utilities
│   │       ├── video.py        # FFmpeg operations
│   │       └── storage.py      # MinIO operations
│   │
│   └── main.py                 # FastAPI app factory
│
├── tests/
│   ├── unit/                   # Unit tests (services, models)
│   ├── integration/            # API integration tests
│   └── workers/                # Worker-specific tests
│
├── alembic/                    # Database migrations
│
└── docker-compose.yml          # Docker composition
```

#### Layer Responsibilities

| Layer | Responsibility | MUST NOT |
|-------|---------------|----------|
| **API** | HTTP transport, validation, auth check | Business logic, DB queries |
| **Services** | Business logic, orchestration | HTTP concerns, ML processing |
| **Workers** | Queue consumption, job execution | HTTP endpoints, API responses |
| **Pipeline** | Pure ML processing | DB access, HTTP, business rules |
| **Models** | Data persistence only | Business logic |

---

### Worker & Queue Architecture

#### Queue Mechanism

**MVP**: PostgreSQL-backed queue (simple, single dependency)
**Future Upgrade Path**: Redis + Celery (for scale)

**Queue Table Schema**:
```sql
CREATE TABLE queue_jobs (
    id UUID PRIMARY KEY,
    queue_name VARCHAR(50) NOT NULL,  -- 'detection', 'asr', 'cropping'
    payload JSONB NOT NULL,           -- {job_id: "...", stage: "..."}
    status VARCHAR(20) DEFAULT 'pending', -- pending, processing, completed, failed
    priority INTEGER DEFAULT 0,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    scheduled_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

CREATE INDEX idx_queue_pending ON queue_jobs(queue_name, status, scheduled_at)
    WHERE status = 'pending';
```

#### Worker Implementation Pattern

```python
# app/workers/base.py
from abc import ABC, abstractmethod

class BaseWorker(ABC):
    queue_name: str
    
    async def run(self):
        """Main loop - poll queue and process jobs"""
        while True:
            job = await self._dequeue()
            if job:
                await self._process_with_retry(job)
            await asyncio.sleep(1)  # Poll interval
    
    async def _dequeue(self) -> Optional[QueueJob]:
        """Atomically fetch next pending job"""
        # SELECT FOR UPDATE SKIP LOCKED
        ...
    
    @abstractmethod
    async def process(self, payload: dict) -> dict:
        """Override in subclass - actual work"""
        pass

# app/workers/detection_worker.py
class DetectionWorker(BaseWorker):
    queue_name = "detection"
    
    async def process(self, payload: dict) -> dict:
        job_id = payload["job_id"]
        
        # Call pipeline (pure ML, no DB)
        result = await stage1_detection.run(job_id)
        
        # Update job status via service
        await job_service.update_status(job_id, "TRANSCRIBING")
        
        # Queue next stage
        await queue.enqueue("asr", {"job_id": job_id})
        
        return {"segments_detected": len(result.segments)}
```

#### Separation of Concerns

| Component | Owns | Delegates To |
|-----------|------|--------------|
| **API Endpoint** | HTTP request/response, auth check | Service for business logic |
| **Service** | Business rules, DB transactions | Pipeline for ML, Workers for async |
| **Worker** | Queue consumption, retry logic | Pipeline for processing, Service for status updates |
| **Pipeline** | ML model execution, video processing | Utils for I/O (MinIO, FFmpeg) |

---

### Format Patterns

#### API Response Formats

**Success Response** (FastAPI default):
```python
# Return Pydantic model directly
@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(...):
    return job  # FastAPI serializes automatically

# Results in:
{
    "id": "uuid",
    "status": "DETECTING",
    "created_at": "2026-03-18T10:00:00Z"
}
```

**Error Response** (Custom handler):
```python
{
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid timestamp format",
        "details": {
            "field": "end_time",
            "value": "invalid"
        }
    }
}
```

**List Response**:
```python
{
    "items": [...],
    "total": 100,
    "page": 1,
    "page_size": 20
}
```

#### Data Exchange Formats

| Data Type | Format | Example |
|-----------|--------|---------|
| **DateTime** | ISO 8601 UTC | `"2026-03-18T10:00:00Z"` |
| **UUID** | String | `"550e8400-e29b-41d4-a716-446655440000"` |
| **Duration** | Float seconds | `4.5` (not milliseconds) |
| **Booleans** | true/false | JSON native (not 0/1) |
| **Nulls** | null or omitted | Prefer omitting optional fields |
| **Enums** | String values | `"UPLOADED"`, `"ANNOTATING"` |

---

### Communication Patterns

#### Event System

**Event Naming**: `{entity}.{action}`
```python
"job.created"
"job.status_changed"  # payload: {job_id, old_status, new_status}
"annotation.submitted"
"annotation.approved"
"user.login_failed"
```

**Event Payload Structure**:
```python
{
    "event": "job.status_changed",
    "timestamp": "2026-03-18T10:00:00Z",
    "data": {
        "job_id": "uuid",
        "old_status": "DETECTING",
        "new_status": "TRANSCRIBING"
    }
}
```

#### Database Transaction Boundaries

**Pattern**: One transaction per service method
```python
# app/services/job_service.py
async def create_job(db: AsyncSession, ...) -> Job:
    async with db.begin():  # Automatic commit/rollback
        job = PipelineJob(...)
        db.add(job)
        # Other operations...
        return job
```

---

### Process Patterns

#### Error Handling

**Exception Hierarchy**:
```python
# app/core/exceptions.py
class AppException(Exception):
    """Base application exception"""
    status_code: int = 500
    code: str = "INTERNAL_ERROR"

class ValidationError(AppException):
    status_code = 400
    code = "VALIDATION_ERROR"

class NotFoundError(AppException):
    status_code = 404
    code = "NOT_FOUND"

class AuthError(AppException):
    status_code = 401
    code = "UNAUTHORIZED"
```

**Global Exception Handler**:
```python
# app/main.py
@app.exception_handler(AppException)
async def app_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc)
            }
        }
    )
```

#### Loading State Patterns

**Frontend Polling States**:
```javascript
// Polling intervals by job state
const POLL_INTERVALS = {
    DETECTING: 5000,      // 5s - actively processing
    TRANSCRIBING: 5000,   // 5s - actively processing
    CROPPING: 5000,       // 5s - actively processing
    QUEUED: 30000,        // 30s - waiting
    READY_FOR_ANNOTATION: 30000,  // 30s - done processing
    FAILED: 60000,        // 60s - error state
    CANCELLED: 60000      // 60s - terminal state
};
```

---

### Enforcement Guidelines

#### All AI Agents MUST:

1. **Follow naming conventions exactly** - No camelCase in Python, no PascalCase in DB tables
2. **Respect layer boundaries** - API doesn't do ML, Pipeline doesn't touch DB
3. **Use dependency injection** - Don't create DB sessions inline, use `Depends(get_db)`
4. **Handle errors consistently** - Raise custom exceptions, don't return error dicts
5. **Write idempotent workers** - Same job can be retried safely
6. **Log with context** - Include job_id, user_id in all log entries
7. **Use type hints everywhere** - Mypy-compatible code
8. **Follow async patterns** - Use `async/await`, not threading

#### Pattern Violation Process

1. **Detection**: Code review or linter catches violation
2. **Documentation**: Log violation in `docs/ARCHITECTURE_VIOLATIONS.md`
3. **Correction**: Refactor to follow pattern
4. **Prevention**: Update templates/examples to prevent recurrence

---

### Pattern Examples

#### ✅ Good Example: Clean Layer Separation

```python
# api/jobs.py - Thin controller
@router.post("/jobs", response_model=JobResponse)
async def create_job(
    file: UploadFile,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    job = await job_service.create_job(db, file, current_user.id)
    return job

# services/job_service.py - Business logic
async def create_job(db: AsyncSession, file: UploadFile, user_id: str):
    # Validate
    if file.size > MAX_FILE_SIZE:
        raise ValidationError("File too large")
    
    # Save to DB
    job = PipelineJob(status="UPLOADED", created_by=user_id)
    db.add(job)
    await db.flush()
    
    # Upload to storage
    await minio_service.upload(file, job.id)
    
    # Queue for processing
    await queue.enqueue("detection", {"job_id": str(job.id)})
    
    await db.commit()
    return job

# workers/detection_worker.py - Queue consumer
class DetectionWorker(BaseWorker):
    async def process(self, payload: dict):
        job_id = payload["job_id"]
        result = await stage1_detection.run(job_id)
        await job_service.update_status(job_id, "TRANSCRIBING")
        await queue.enqueue("asr", {"job_id": job_id})

# pipeline/stages/stage1_detection.py - Pure ML
async def run(job_id: str) -> DetectionResult:
    video_path = await storage.download(job_id)
    detections = await detector.detect(video_path)
    # ... process ...
    return DetectionResult(segments=segments)
```

#### ❌ Anti-Pattern: Mixed Concerns

```python
# BAD: API doing business logic and ML
@router.post("/jobs")
async def create_job(file: UploadFile, db: AsyncSession = Depends(get_db)):
    # Don't do this - business logic in endpoint
    if not file.filename.endswith('.mp4'):
        return {"error": "Invalid file"}  # Don't return dicts
    
    job = PipelineJob(...)
    db.add(job)
    
    # Don't do this - ML in API layer
    detections = yolo_model(file.file)  # Blocks HTTP thread!
    
    # Don't do this - manual DB session management
    try:
        db.commit()
    except:
        db.rollback()
```

---

## Project Structure & Boundaries

### Complete Project Directory Structure

```
jbi-service/                      # Backend API (FastAPI)
├── README.md
├── pyproject.toml                # Poetry/PDM dependencies
├── requirements.txt              # Alternative: pip requirements
├── .env.example                  # Environment template
├── .env                          # Local environment (gitignored)
├── .gitignore
├── docker-compose.yml            # PostgreSQL + MinIO + API services
├── Dockerfile                    # API container
├── Dockerfile.worker             # Worker container (optional separation)
│
├── alembic/                      # Database migrations
│   ├── alembic.ini
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_add_auth_tables.py
│       ├── 003_add_pipeline_tables.py
│       └── 004_add_annotation_tables.py
│
├── app/                          # Main application
│   ├── __init__.py
│   ├── main.py                   # FastAPI app factory
│   │
│   ├── api/                      # HTTP Layer (thin controllers)
│   │   ├── __init__.py
│   │   ├── deps.py               # FastAPI dependencies (DB, auth)
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── auth.py           # POST /auth/login, /auth/refresh
│   │       ├── jobs.py           # POST /jobs, GET /jobs/{id}
│   │       ├── annotations.py    # POST /annotations, /reviews/{id}/approve
│   │       ├── admin.py          # User mgmt, config, audit logs
│   │       └── health.py         # GET /health
│   │
│   ├── core/                     # Shared infrastructure
│   │   ├── __init__.py
│   │   ├── config.py             # Pydantic-settings (Settings class)
│   │   ├── security.py           # JWT encode/decode, password hashing
│   │   ├── events.py             # Event bus (simple pub/sub)
│   │   └── exceptions.py         # AppException hierarchy
│   │
│   ├── db/                       # Database Layer
│   │   ├── __init__.py
│   │   ├── base.py               # SQLAlchemy declarative base
│   │   ├── session.py            # AsyncSession management
│   │   └── models/
│   │       ├── __init__.py
│   │       ├── auth.py           # User, Role, UserRole
│   │       ├── pipeline.py       # PipelineJob, PipelineSegment
│   │       └── annotation.py     # AnnotationEdit, Review, Comment
│   │
│   ├── schemas/                  # Pydantic Models (API contracts)
│   │   ├── __init__.py
│   │   ├── auth.py               # UserCreate, UserResponse, TokenResponse
│   │   ├── job.py                # JobCreate, JobResponse, JobStatus
│   │   └── annotation.py         # AnnotationEdit, ReviewSubmit, etc.
│   │
│   ├── services/                 # Business Logic Layer
│   │   ├── __init__.py
│   │   ├── auth_service.py       # User CRUD, JWT generation
│   │   ├── job_service.py        # Job lifecycle, status updates
│   │   ├── annotation_service.py # Annotation workflow
│   │   ├── audit_service.py      # Audit logging
│   │   └── minio_service.py      # S3/pre-signed URL operations
│   │
│   ├── workers/                  # Async Worker Layer
│   │   ├── __init__.py
│   │   ├── base.py               # BaseWorker abstract class
│   │   ├── detection_worker.py   # Stage 1: YOLOv8 detection
│   │   ├── asr_worker.py         # Stage 2: faster-whisper
│   │   ├── cropping_worker.py    # Stage 3: JBI buffer cropping
│   │   └── queue/                # PostgreSQL queue implementation
│   │       ├── __init__.py
│   │       ├── models.py         # QueueJob SQLAlchemy model
│   │       └── client.py         # enqueue(), dequeue()
│   │
│   └── pipeline/                 # ML Pipeline Logic (pure processing)
│       ├── __init__.py
│       ├── models/               # ML model wrappers
│       │   ├── __init__.py
│       │   ├── detector.py       # YOLOv8 wrapper
│       │   ├── transcriber.py    # faster-whisper wrapper
│       │   └── cropper.py        # Video cropping with JBI buffer
│       ├── stages/               # Stage orchestration
│       │   ├── __init__.py
│       │   ├── stage1_detection.py
│       │   ├── stage2_asr.py
│       │   └── stage3_cropping.py
│       └── utils/                # Pipeline utilities
│           ├── __init__.py
│           ├── video.py          # FFmpeg operations
│           └── storage.py        # MinIO download/upload
│
├── tests/                        # Test Suite
│   ├── __init__.py
│   ├── conftest.py               # pytest fixtures
│   ├── unit/                     # Unit tests
│   │   ├── test_services/
│   │   ├── test_pipeline/
│   │   └── test_workers/
│   ├── integration/              # API integration tests
│   │   ├── test_auth.py
│   │   ├── test_jobs.py
│   │   └── test_annotations.py
│   └── fixtures/                 # Test data
│       ├── sample_video.mp4
│       └── mock_detections.json
│
└── scripts/                      # Utility scripts
    ├── init_db.sh                # Initialize database
    ├── run_workers.sh            # Start worker processes
    └── seed_data.py              # Seed test data

anotasi.ai-FE/                    # Frontend (NextJS - existing)
├── src/
│   └── features/
│       ├── auth/                 # Login, role-based routing
│       ├── annotation/           # Video player, transcript editor
│       ├── curation/             # Review queue, approve/reject
│       ├── admin/                # User management, audit logs
│       └── asr-review/           # Pre-annotation validation
└── ... (existing structure)

docs/                             # Project Documentation
├── architecture.md               # (this file will be copied here)
├── api/                          # API documentation
│   └── openapi.yaml              # Generated OpenAPI spec
└── deployment/                   # Deployment guides
    ├── local-setup.md
    └── docker-deployment.md
```

---

### Architectural Boundaries

#### API Boundaries

| Boundary | Implementation | Contract |
|----------|---------------|----------|
| **External API** | FastAPI routers in `app/api/v1/` | REST + JSON, JWT auth |
| **Internal (Service→Worker)** | PostgreSQL queue table | Event payload JSON |
| **Worker→Pipeline** | Direct Python function calls | Typed return values |

#### Component Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│  API Layer (app/api/)                                       │
│  - Validates HTTP input                                     │
│  - Checks authentication                                    │
│  - Returns HTTP responses                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │ Calls
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Service Layer (app/services/)                              │
│  - Business logic                                           │
│  - Database transactions                                    │
│  - Orchestrates workers                                     │
└───────────────────────┬─────────────────────────────────────┘
                        │ Enqueues
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Worker Layer (app/workers/)                                │
│  - Polls queue                                              │
│  - Calls pipeline                                           │
│  - Updates status                                           │
└───────────────────────┬─────────────────────────────────────┘
                        │ Calls
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Pipeline Layer (app/pipeline/)                             │
│  - Pure ML processing                                       │
│  - No DB, no HTTP                                           │
│  - Returns results                                          │
└─────────────────────────────────────────────────────────────┘
```

#### Data Boundaries

| Boundary | From | To | Mechanism |
|----------|------|-----|-----------|
| **Upload** | Client | MinIO | Pre-signed PUT URL |
| **Download** | MinIO | Client | Pre-signed GET URL (1hr expiry) |
| **Metadata** | API | PostgreSQL | SQLAlchemy async |
| **Queue** | API/Worker | PostgreSQL | `queue_jobs` table |
| **Video Processing** | Pipeline | MinIO | Direct S3 API |

---

### Requirements to Structure Mapping

#### FR Category → Directory Mapping

| FR Category | Primary Location | Key Files |
|-------------|-----------------|-----------|
| **Video Processing (FR1-FR12)** | `app/pipeline/`, `app/workers/` | `stage*.py`, `*worker.py` |
| **Authentication (FR13-FR18)** | `app/api/v1/auth.py`, `app/core/security.py` | `auth.py`, `security.py` |
| **Annotation Workflow (FR19-FR30)** | `app/api/v1/annotations.py`, `app/services/annotation_service.py` | `annotations.py`, `annotation_service.py` |
| **User Management (FR31-FR35)** | `app/api/v1/admin.py`, `app/services/auth_service.py` | `admin.py`, `auth_service.py` |
| **System Admin (FR36-FR40)** | `app/api/v1/admin.py`, `app/db/models/` | `admin.py`, config tables |
| **ASR Review (FR45-FR49)** | `app/services/annotation_service.py` | ASR review logic in annotation service |
| **Slang Dictionary (FR50-FR54)** | `app/db/models/config.py` | `config_slang_dictionary` table |
| **Audit Trail (FR55-FR59)** | `app/services/audit_service.py`, `app/db/models/audit.py` | `audit_logs` table |
| **Onboarding (FR60-FR63)** | Frontend: `anotasi.ai-FE/src/features/onboarding/` | Tour components |

---

### Integration Points

#### Internal Communication

| From | To | Mechanism | Data |
|------|-----|-----------|------|
| API Endpoint | Service | Direct function call | Pydantic models |
| Service | Database | SQLAlchemy async | SQLAlchemy models |
| Service | Worker | PostgreSQL queue | JSON payload |
| Worker | Pipeline | Direct function call | Typed dicts/dataclasses |
| Pipeline | MinIO | boto3/minio-py | Binary video data |

#### External Integrations

| Service | Integration Point | Library |
|---------|------------------|---------|
| **PostgreSQL** | `app/db/session.py` | `asyncpg` + `SQLAlchemy 2.0` |
| **MinIO** | `app/services/minio_service.py` | `minio` Python SDK |
| **YOLOv8** | `app/pipeline/models/detector.py` | `ultralytics` |
| **faster-whisper** | `app/pipeline/models/transcriber.py` | `faster-whisper` |
| **FFmpeg** | `app/pipeline/utils/video.py` | `subprocess` + `ffmpeg-python` |

#### Data Flow

```
Upload Flow:
  Client → API /jobs → Service.save_job() → DB
                                       → MinIO.upload()
                                       → Queue.enqueue('detection')

Processing Flow:
  DetectionWorker → stage1_detection → YOLOv8 → MinIO.save_crops()
                → Service.update_status('TRANSCRIBING')
                → Queue.enqueue('asr')

  ASRWorker → stage2_asr → faster-whisper → segments.txt
          → Service.update_status('CROPPING')
          → Queue.enqueue('cropping')

  CroppingWorker → stage3_cropping → FFmpeg → Final clips
               → Service.update_status('READY_FOR_ANNOTATION')

Annotation Flow:
  Client → API /annotations → Service.create_edit() → DB
                          → Service.submit_for_review() → DB
                          → Queue (optional: notify curator)

Curation Flow:
  Client → API /reviews/{id}/approve → Service.approve() → DB
                                   → Audit log
                                   → Mark for export
```

---

## Starter Template Evaluation

### Primary Technology Domain

**Brownfield API + Web Application** - This project extends existing foundations.

### Existing Stack Assessment

| Component | Technology | Status |
|-----------|-----------|--------|
| **Backend API** | FastAPI (Python) | ✅ Existing - `jbi-service/` |
| **Frontend** | NextJS + TypeScript | ✅ Existing - `anotasi.ai-FE/` |
| **ML Pipeline** | Python notebooks | ✅ Existing - `*.ipynb` |
| **Database** | PostgreSQL | ✅ Used by existing service |
| **Storage** | MinIO (S3-compatible) | ✅ Used by existing service |

### Architectural Approach

Since this is a **brownfield evolution** (extending existing JBI Service), traditional starter templates don't apply.

**Extension Strategy:**
- Leverage existing FastAPI structure, PostgreSQL models, MinIO integration
- Extend YOLOv8 detection pipeline with ASR integration
- Add Stage 2 cropping (timestamp-based with JBI buffer)
- Implement JWT RBAC middleware
- Expand job state machine for multi-stage pipeline
- Add new domain endpoints (curation, audit, export, slang dictionary)
