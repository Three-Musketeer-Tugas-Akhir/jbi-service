# POST /api/v1/pipeline/jobs - Complete Process Flow Analysis

## Executive Summary

This document provides a detailed analysis of the complete process flow when a user uploads a video via `POST /api/v1/pipeline/jobs`. The endpoint initiates a video processing job that goes through a 3-stage ML pipeline (Detection → ASR → Cropping) using PostgreSQL-backed queue and MinIO object storage.

---

## 📊 High-Level Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT REQUEST                                          │
│  POST /api/v1/pipeline/jobs                                                          │
│  Headers: Authorization: Bearer <JWT>                                                │
│  Body: multipart/form-data with video file                                           │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         1. REQUEST VALIDATION LAYER                                  │
│  ├── FastAPI parses multipart/form-data                                              │
│  ├── Content-Type validation (must be video/*)                                       │
│  └── File size detection (seek to end, get position)                                 │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         2. AUTHENTICATION LAYER                                      │
│  ├── Extract Bearer token from Authorization header                                  │
│  ├── Verify JWT signature and expiration                                             │
│  ├── Extract claims: sub (user_id), role                                             │
│  └── Build CurrentUser object                                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         3. DEPENDENCY INJECTION                                      │
│  ├── get_db → AsyncSession (PostgreSQL)                                              │
│  ├── get_job_repository → JobRepository                                              │
│  └── get_current_user → CurrentUser                                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         4. BUSINESS LOGIC (JobService)                               │
│  ├── File validation (format, size limits)                                           │
│  ├── Create PipelineJob record (status: UPLOADED)                                    │
│  ├── Upload video to MinIO                                                           │
│  ├── Update video_path in DB                                                         │
│  ├── Enqueue detection job                                                           │
│  └── Commit transaction                                                              │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         5. RESPONSE                                                  │
│  └── Return JobCreateResponse with job_id, status, timestamps                        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔍 Detailed Step-by-Step Analysis

### Step 1: Request Reception & Initial Validation

**Location:** `app/api/v1/jobs.py:603-679`

```python
@router.post("/pipeline/jobs", ...)
async def upload_video_pipeline(
    video: Annotated[UploadFile, File(...)],
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    job_repo: JobRepository = Depends(get_job_repository)
):
```

**Process:**

1. **FastAPI UploadFile Processing**
   - FastAPI receives `multipart/form-data` request
   - `UploadFile` handles file streaming via `SpooledTemporaryFile`
   - Large files are written to disk, small files kept in memory

2. **Content-Type Validation**
   ```python
   if video.content_type and not video.content_type.startswith("video/"):
       raise ValidationError("Invalid content type, expected video file")
   ```
   - Validates the file is a video type
   - Returns 400 Bad Request if invalid

3. **File Size Detection (Memory Efficient)**
   ```python
   video_file = video.file
   video_file.seek(0, 2)      # Seek to end
   file_size = video_file.tell()
   video_file.seek(0)         # Reset to beginning
   ```
   - Does NOT load entire file into memory
   - Uses file descriptor seeking for O(1) size detection

---

### Step 2: Authentication Flow

**Location:** `app/api/deps.py:201-228`

```
┌────────────────────────────────────────────────────────────┐
│  Authentication Flow                                       │
├────────────────────────────────────────────────────────────┤
│  1. Extract Bearer Token                                   │
│     └── Authorization: Bearer <token>                      │
│                                                            │
│  2. Verify Token                                           │
│     ├── Check signature (HS256)                            │
│     ├── Check expiration                                   │
│     └── Verify token type = "access"                       │
│                                                            │
│  3. Extract Claims                                         │
│     ├── sub: User UUID                                     │
│     ├── role: User role (admin/annotator/curator)          │
│     └── email: User email (optional)                       │
│                                                            │
│  4. Build CurrentUser                                      │
│     └── id, email, role                                    │
└────────────────────────────────────────────────────────────┘
```

**Error Scenarios:**
| Scenario | Status Code | Response |
|----------|-------------|----------|
| Missing header | 401 | `{"error": "authentication_required"}` |
| Invalid scheme | 401 | `{"error": "Invalid authentication scheme"}` |
| Expired token | 401 | `{"error": "Token has expired"}` |
| Invalid signature | 401 | `{"error": "Invalid token"}` |
| Missing role claim | 401 | `{"error": "Token missing role claim"}` |

---

### Step 3: Dependency Injection Setup

**Location:** `app/db/session.py:23-35`

```python
async def get_db():
    """FastAPI dependency that yields a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

**Injected Dependencies:**

| Dependency | Source | Purpose |
|------------|--------|---------|
| `db` | `get_db()` | Async PostgreSQL session |
| `current_user` | `get_current_user()` | Authenticated user context |
| `job_repo` | `get_job_repository()` | Data access layer |

---

### Step 4: Business Logic Execution (JobService)

**Location:** `app/services/job_service.py:77-152`

#### 4.1 File Validation (`_validate_file`)

```python
def _validate_file(self, filename: str, file_size: int) -> None:
    # Validation checks:
    1. Filename is not empty
    2. File size > 0 (not empty file)
    3. File size <= 10GB (MAX_FILE_SIZE)
    4. Extension in {".mp4", ".avi", ".mkv", ".mov"}
```

**Validation Errors:**
| Check | Error Code | Message |
|-------|------------|---------|
| Empty filename | `VALIDATION_ERROR` | "Filename is required" |
| Empty file | `VALIDATION_ERROR` | "File is empty" |
| File > 10GB | `VALIDATION_ERROR` | "File too large, maximum size is 10GB" |
| Invalid format | `VALIDATION_ERROR` | "Unsupported file format: {ext}" |

#### 4.2 Database Record Creation

**Location:** `app/repositories/job_repository.py:20-54`

```python
async def create(
    self,
    original_filename: str,
    file_size: int,
    created_by: Optional[UUID] = None,
    status: str = "UPLOADED",
) -> PipelineJob:
```

**SQL Executed:**
```sql
INSERT INTO pipeline_jobs (
    id,                    -- gen_random_uuid()
    original_filename,     -- "video.mp4"
    file_size,             -- 104857600 (100MB)
    created_by,            -- "550e8400-e29b-41d4-a716-446655440000"
    status,                -- "UPLOADED"
    current_stage,         -- "upload"
    category,              -- NULL
    created_at,            -- NOW()
    updated_at             -- NOW()
) VALUES (...)
RETURNING *;
```

**Record State After Creation:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "UPLOADED",
  "current_stage": "upload",
  "original_filename": "news_video.mp4",
  "file_size": 104857600,
  "video_path": null,
  "created_by": "user-uuid-here",
  "created_at": "2026-03-27T01:02:50.741115",
  "category": null
}
```

#### 4.3 MinIO Upload

**Location:** `app/services/minio_service.py:365-397`

```python
async def upload_job_video(
    self,
    job_id: str,
    file_data: Union[bytes, BinaryIO],
    original_filename: str,
) -> str:
```

**Upload Process:**

1. **Filename Sanitization**
   ```python
   safe_filename = self._sanitize_filename(original_filename)
   # Removes path traversal attempts, keeps only basename
   # Allows: alphanumeric, dots, dashes, underscores
   ```

2. **Object Name Construction**
   ```
   jobs/{job_id}/original/{safe_filename}
   
   Example: jobs/550e8400-e29b-41d4-a716-446655440000/original/news_video.mp4
   ```

3. **Async Upload to MinIO**
   ```python
   await asyncio.to_thread(
       self._upload_file_sync,
       file_data,
       object_name,
       content_type,
       metadata={"job_id": job_id, "type": "original"}
   )
   ```
   - Runs blocking MinIO operation in thread pool
   - Preserves file streaming (no memory bloat)
   - Metadata attached for traceability

**MinIO Object Structure:**
```
Bucket: anotasi-videos
└── jobs/
    └── {job_id}/
        └── original/
            └── news_video.mp4
```

#### 4.4 Update Video Path

**Location:** `app/repositories/job_repository.py:116-136`

```python
async def update_video_path(job_id: UUID, video_path: str) -> bool:
    UPDATE pipeline_jobs
    SET video_path = 'jobs/{job_id}/original/news_video.mp4'
    WHERE id = '{job_id}';
```

#### 4.5 Queue Job for Processing

**Location:** `app/services/queue_service.py:20-76`

```python
async def enqueue(
    self,
    queue_name: str,        # "detection"
    payload: Dict[str, Any],
    db: AsyncSession,       # Same session for atomicity
    priority: int = 0,
    max_attempts: int = 3
) -> QueueJob:
```

**SQL Executed:**
```sql
INSERT INTO queue_jobs (
    id,                    -- gen_random_uuid()
    queue_name,            -- 'detection'
    payload,               -- '{"job_id": "...", "stage": "detection", "video_key": "jobs/..."}'
    status,                -- 'pending'
    priority,              -- 0
    attempts,              -- 0
    max_attempts,          -- 3
    scheduled_at,          -- NOW()
    created_at             -- NOW()
) VALUES (...)
RETURNING *;
```

**Queue Job Payload:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "stage": "detection",
  "video_key": "jobs/550e8400-e29b-41d4-a716-446655440000/original/news_video.mp4"
}
```

#### 4.6 Transaction Commit

**Atomic Transaction:**
```python
await self.db.commit()
```

All operations (job creation, video upload, queue insertion) are committed atomically. If any step fails, the entire transaction rolls back.

**Rollback Scenarios:**
- MinIO upload fails → DB transaction rolls back, no orphaned records
- Queue insertion fails → Job record and MinIO object cleaned up
- DB connection lost → All changes discarded

---

### Step 5: Response Generation

**Response Schema:** `app/schemas/job.py:26-37`

```python
class JobCreateResponse(BaseModel):
    id: UUID
    status: str                    # "UPLOADED"
    original_filename: str
    file_size: int
    category: Optional[str]        # null
    created_at: datetime
    message: str
```

**Example Response (201 Created):**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "UPLOADED",
  "original_filename": "news_video.mp4",
  "file_size": 104857600,
  "category": null,
  "created_at": "2026-03-27T01:02:50.741115",
  "message": "Video uploaded successfully, processing will begin shortly"
}
```

---

## 🗄️ Database State After Request

### pipeline_jobs Table

| Column | Value |
|--------|-------|
| id | 550e8400-e29b-41d4-a716-446655440000 |
| original_filename | news_video.mp4 |
| video_path | jobs/550e8400-e29b-41d4-a716-446655440000/original/news_video.mp4 |
| status | UPLOADED |
| current_stage | upload |
| file_size | 104857600 |
| category | NULL |
| created_by | user-uuid |
| is_cancelled | false |
| created_at | 2026-03-27 01:02:50 |
| updated_at | 2026-03-27 01:02:50 |

### queue_jobs Table

| Column | Value |
|--------|-------|
| id | (new uuid) |
| queue_name | detection |
| payload | `{"job_id": "...", "stage": "detection", "video_key": "..."}` |
| status | pending |
| priority | 0 |
| attempts | 0 |
| max_attempts | 3 |
| scheduled_at | 2026-03-27 01:02:50 |
| created_at | 2026-03-27 01:02:50 |

---

## 📦 MinIO State After Request

```
Bucket: anotasi-videos
├── jobs/
│   └── 550e8400-e29b-41d4-a716-446655440000/
│       └── original/
│           └── news_video.mp4    (100MB, content-type: video/mp4)
│               Metadata:
│               - job_id: 550e8400-e29b-41d4-a716-446655440000
│               - type: original
```

---

## 🔄 What Happens Next (Background Processing)

After the API returns, the **Detection Worker** picks up the queued job:

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Detection Worker (runs independently)                                    │
├──────────────────────────────────────────────────────────────────────────┤
│  1. Poll queue_jobs table for pending detection jobs                      │
│     └── SELECT ... FROM queue_jobs WHERE queue_name='detection'          │
│         AND status='pending' FOR UPDATE SKIP LOCKED                       │
│                                                                           │
│  2. Download video from MinIO                                             │
│     └── jobs/{job_id}/original/news_video.mp4                            │
│                                                                           │
│  3. Run YOLO detection                                                    │
│     └── Detect JBI overlays frame-by-frame                               │
│                                                                           │
│  4. Create PipelineSegment records                                        │
│     └── One record per detected segment                                  │
│                                                                           │
│  5. Crop segments and upload to MinIO                                     │
│     └── jobs/{job_id}/stage1/segment_0000.mp4                            │
│                                                                           │
│  6. Queue ASR stage                                                       │
│     └── INSERT INTO queue_jobs (queue_name='asr', ...)                   │
│                                                                           │
│  7. Mark detection queue job complete                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## ⚠️ Error Handling

### Validation Errors (400 Bad Request)

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Unsupported file format: .txt",
    "details": {
      "filename": "document.txt",
      "supported_formats": [".mp4", ".avi", ".mkv", ".mov"]
    }
  }
}
```

### Authentication Errors (401 Unauthorized)

```json
{
  "error": "authentication_required",
  "detail": "Authentication required"
}
```

### Storage Errors (503 Service Unavailable)

```json
{
  "error": "STORAGE_UNAVAILABLE",
  "detail": "Failed to initialize MinIO bucket: Connection refused"
}
```

### Server Errors (500 Internal Server Error)

```json
{
  "error": "UPLOAD_FAILED",
  "message": "Failed to upload video: Connection timeout"
}
```

---

## 📈 Performance Characteristics

| Metric | Target | Implementation |
|--------|--------|----------------|
| Response Time | < 200ms | Async streaming, no file buffering |
| Max File Size | 10GB | Streaming upload to MinIO |
| Memory Usage | O(1) | File streaming, no in-memory storage |
| Concurrent Uploads | Limited by DB pool | 5 connections + 10 overflow |
| Transaction Safety | ACID | Single DB transaction |

---

## 🔒 Security Considerations

1. **Authentication Required**
   - JWT Bearer token mandatory
   - Token validated on every request

2. **File Validation**
   - Content-Type checked (video/*)
   - Extension whitelist enforced
   - Filename sanitized (path traversal protection)

3. **Size Limits**
   - 10GB maximum file size
   - Prevents resource exhaustion

4. **User Isolation**
   - Jobs associated with `created_by` user
   - Users can only view/cancel their own jobs (unless admin)

5. **Transaction Safety**
   - Atomic operations prevent orphaned records
   - Rollback on any failure

---

## 📝 Code References

| Component | File | Lines |
|-----------|------|-------|
| API Endpoint | `app/api/v1/jobs.py` | 603-679 |
| Job Service | `app/services/job_service.py` | 77-152 |
| Job Repository | `app/repositories/job_repository.py` | 20-54 |
| MinIO Service | `app/services/minio_service.py` | 365-397 |
| Queue Service | `app/services/queue_service.py` | 20-76 |
| Auth Dependencies | `app/api/deps.py` | 201-228 |
| DB Session | `app/db/session.py` | 23-35 |
| Response Schema | `app/schemas/job.py` | 26-37 |

---

## 🎯 Summary

The `POST /api/v1/pipeline/jobs` endpoint:

1. **Accepts** a video file via multipart upload
2. **Validates** file type, size, and user authentication
3. **Creates** a database record with `UPLOADED` status
4. **Uploads** the video to MinIO object storage
5. **Enqueues** a detection job in PostgreSQL queue
6. **Commits** all changes atomically
7. **Returns** job ID for client tracking

The actual video processing (detection, ASR, cropping) happens **asynchronously** via background workers that poll the queue.
