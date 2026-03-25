# Code Review Report: Story 2.3 - Video Upload API

**Story ID:** 2.3  
**Review Date:** 2026-03-24  
**Status:** ⚠️ **CHANGES REQUESTED**

---

## Executive Summary

This review identified **16 distinct issues** across three severity levels:

| Severity | Count | Issues |
|----------|-------|--------|
| 🔴 Critical | 5 | Memory exhaustion, transaction boundaries, data loss |
| 🟠 High | 7 | Race conditions, validation gaps, security issues |
| 🟡 Medium | 4 | Code quality, spec compliance |

---

## 🔴 Critical Issues (Must Fix Before Merge)

### 1. Memory Exhaustion via Unbounded File Read
**Location:** `app/api/v1/jobs.py:16`  
**Issue:** `file_data = await video.read()` loads the entire file into memory. With 10GB max file size, this will cause OOM crashes.  
**Fix:** Implement chunked reading or streaming upload with size validation before full read.

### 2. Transaction Boundary Violation (Orphan Data Risk)
**Location:** `app/services/job_service.py:42-47`  
**Issue:** Distributed transaction across DB, MinIO, and Queue without saga/outbox pattern:
```python
job = await self.job_repo.create(...)      # flush only
await self.minio_service.upload_job_video(...)  # external - committed
await queue_service.enqueue(...)           # separate session - committed
await self.db.commit()                     # may fail
```
**Risk:** If final commit fails, we have orphan MinIO files and queue jobs referencing non-existent pipeline jobs.  
**Fix:** Implement SAGA pattern with compensation actions OR use outbox pattern for eventual consistency.

### 3. Queue Service Uses Independent Sessions (Breaks Atomicity)
**Location:** `app/services/queue_service.py:9-10, 35-36`  
**Issue:** Each queue operation creates a NEW database session via `get_db_session()`. If the main transaction rolls back, the queue job remains committed.  
**Fix:** Accept `db: AsyncSession` as parameter to queue methods.

### 4. Response Returns Wrong Status
**Location:** `app/services/job_service.py:54`  
**Issue:** Service updates status to "QUEUED" before returning, so API response shows `status="QUEUED"` instead of required `status="UPLOADED"`.  
**Fix:** Per spec, pipeline_jobs should remain "UPLOADED" until worker picks it up. Queue job is "QUEUED".

### 5. URL Upload Not Implemented (AC5 Violation)
**Location:** `app/services/job_service.py:57-68`  
**Issue:** `create_job_from_url()` raises `NotImplementedError`. This violates AC5.  
**Fix:** Either implement URL download or explicitly defer AC5 to a future story with stakeholder approval.

---

## 🟠 High Issues (Fix Recommended)

### 6. Race Condition in mark_failed
**Location:** `app/services/queue_service.py:66-82`  
**Issue:** `mark_failed()` fetches job without row locking. Between `dequeue()` (locked) and `mark_failed()` (unlocked), another worker could modify the job.  
**Fix:** Accept job object parameter or use `with_for_update()`.

### 7. Content-Type Spoofing Vulnerability
**Location:** `app/api/v1/jobs.py:14-16`, `app/services/job_service.py:18-22`  
**Issue:** Validation relies on client-provided `Content-Type` header and file extension. No magic number/file signature validation.  
**Fix:** Add python-magic or similar library to verify actual file type.

### 8. Path Traversal in Filename
**Location:** `app/services/job_service.py:19-21`  
**Issue:** Filename like `../../../etc/passwd.mp4` passes validation and is stored as-is in database.  
**Fix:** Use `secure_filename()` from werkzeug or similar sanitization.

### 9. video_path Never Updated
**Location:** `app/repositories/job_repository.py:9`  
**Issue:** Repository initializes `video_path=""` but never updates it after MinIO upload. The actual storage path is lost.  
**Fix:** Update job record with MinIO path after successful upload.

### 10. UploadFile Resource Leak
**Location:** `app/api/v1/jobs.py:16`  
**Issue:** `UploadFile` temporary file handle is never explicitly closed. On exception, temp files accumulate.  
**Fix:** Use `async with video:` context manager or `await video.close()` in finally block.

### 11. No Cleanup on Partial Failure
**Location:** `app/services/job_service.py:42-47`  
**Issue:** If MinIO upload succeeds but queue enqueue fails, the uploaded file remains orphaned.  
**Fix:** Implement compensating actions in try/except/finally blocks.

### 12. Negative file_size Accepted
**Location:** `app/services/job_service.py:15-16`  
**Issue:** Negative file_size bypasses MAX_FILE_SIZE check and is stored in DB.  
**Fix:** Add validation: `if file_size <= 0: raise ValidationError(...)`.

---

## 🟡 Medium Issues (Nice to Fix)

### 13. Endpoint Path Mismatch
**Location:** `app/api/v1/jobs.py`  
**Issue:** Spec requires `/api/v1/jobs`, code implements `/pipeline/jobs`.  
**Note:** This may be intentional architecture change - verify with tech lead.

### 14. Deprecated datetime.utcnow()
**Location:** `app/services/queue_service.py` (multiple)  
**Issue:** `datetime.utcnow()` is deprecated in Python 3.12+.  
**Fix:** Use `datetime.now(timezone.utc)`.

### 15. Unused max_attempts Parameter
**Location:** `app/services/queue_service.py:35`  
**Issue:** `dequeue()` accepts `max_attempts` parameter but ignores it in favor of `job.max_attempts`.  
**Fix:** Remove parameter or implement override logic.

### 16. No Idempotency Key
**Location:** `app/api/v1/jobs.py:8-12`  
**Issue:** Network retries create duplicate jobs for same file upload.  
**Fix:** Add optional `Idempotency-Key` header support.

---

## Recommendation

**Do NOT merge** until critical issues #1-5 are addressed:

1. **Immediate fix needed:** Memory exhaustion (Issue #1)
2. **Architectural fix needed:** Transaction boundaries (Issues #2, #3)
3. **Spec compliance fix needed:** Status handling (Issue #4)
4. **Scope clarification needed:** URL upload (Issue #5)

High issues (#6-12) can be addressed in follow-up commits but should be tracked.

---

## Appendix: Review Methodology

This review used 3 parallel adversarial agents:
- **Blind Hunter:** Pure code analysis without context
- **Edge Case Hunter:** Boundary condition and error path analysis
- **Acceptance Auditor:** Spec compliance verification

All findings were cross-referenced and deduplicated.
