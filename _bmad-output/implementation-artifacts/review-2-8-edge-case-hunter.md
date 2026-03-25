# Edge Case Hunter Review - Story 2.8

**Task:** Find bugs at boundary conditions, empty states, extreme inputs, and race conditions.

**Approach:** Systematically test boundaries. What happens at limits?

---

## Boundary Analysis

### 1. Pagination Boundaries

**Test Case: page=0**
```python
offset = (page - 1) * page_size  # (0 - 1) * 20 = -20
```
❌ **BUG:** Negative offset causes SQL error or unexpected results

**Test Case: page_size=0**
```python
page_size: int = Query(20, ge=1, le=100)  # ge=1 prevents 0
```
✅ **Protected:** FastAPI validation prevents this

**Test Case: Very large page**
```python
page: int = Query(1, ge=1)  # No upper bound
offset = (9999999 - 1) * 100  # ~1B offset
```
⚠️ **RISK:** Large offsets cause slow queries

### 2. Progress Calculation Boundaries

**Test Case: Zero segments**
```python
progress = 0
if total_segments and total_segments > 0:
    progress = int((completed_segments or 0) / total_segments * 100)
# Returns 0 when total_segments=0
```
✅ **Correct:** No division by zero

**Test Case: completed_segments > total_segments**
```python
# If DB is corrupted or race condition:
# completed_segments=10, total_segments=5
progress = int(10 / 5 * 100)  # 200%
```
❌ **BUG:** Progress can exceed 100%

**Test Case: Negative values**
```python
# DB constraint violation or corruption
# No validation on segment counts
```
⚠️ **RISK:** Negative progress possible

### 3. Cache Key Boundaries

**Test Case: Empty job_id or user_id**
```python
cache_key = f"job:{job_id}:user:{current_user_id}"
# job_id="" → "job::user:abc"
# Both empty → "job::user:"
```
⚠️ **RISK:** Key collisions possible with empty strings

**Test Case: Special characters in UUID**
```python
# UUIDs shouldn't have special chars, but:
job_id = "job:id:with:colons"
cache_key = f"job:{job_id}:user:{user_id}"
# → "job:job:id:with:colons:user:abc"
```
⚠️ **RISK:** Key parsing ambiguity

### 4. Date Range Boundaries

**Test Case: from_date > to_date**
```python
if from_date:
    conditions.append(PipelineJob.created_at >= from_date)
if to_date:
    conditions.append(PipelineJob.created_at <= to_date)
# No validation that from <= to
```
❌ **BUG:** Returns empty results silently, user doesn't know range is invalid

**Test Case: Invalid date format**
```python
from_date: Optional[str] = Query(None, description="Start date (ISO 8601)")
# No validation, passed directly to SQL
```
❌ **BUG:** SQL error on invalid format

### 5. UUID Boundaries

**Test Case: Valid format but non-existent**
```python
try:
    job_uuid = UUID(job_id)
except ValueError:
    raise NotFoundError(f"Job {job_id} not found")
# UUID parses but doesn't exist → proceeds to query
```
✅ **Correct:** Handled by query

**Test Case: Case sensitivity**
```python
UUID("550E8400-E29B-41D4-A716-446655440000")
UUID("550e8400-e29b-41d4-a716-446655440000")  # Same
```
✅ **Correct:** UUID handles case

### 6. Concurrent Access Boundaries

**Test Case: Cache invalidation race**
```python
# Thread 1: get_job() checks cache → miss
# Thread 2: invalidate cache
# Thread 1: queries DB, sets cache with old data
# Cache now has stale data for 2 seconds
```
⚠️ **RISK:** Stale data after invalidation

**Test Case: Permission change mid-request**
```python
# User is admin, polls job
# Admin demoted to annotator
# Cached response still shows admin view
```
⚠️ **RISK:** 2-second window of wrong permissions

### 7. Memory Boundaries

**Test Case: Large job list**
```python
page_size: int = Query(20, ge=1, le=100)  # Max 100
# But if DB has 1M jobs, total_pages = 10,000
```
⚠️ **RISK:** Large `total` counts slow queries

**Test Case: Cache growth**
```python
# Each unique job+user = 1 cache entry
# 1000 users × 1000 jobs = 1M entries
# Each entry ~1KB = 1GB RAM
```
❌ **BUG:** No cache size limits

---

## Edge Case Summary

| Category | Issues Found | Severity |
|----------|--------------|----------|
| Pagination | page=0 causes negative offset | High |
| Progress | Can exceed 100% | Med |
| Date Range | No validation, invalid formats | Med |
| Cache | No size limits | High |
| Race Conditions | Stale data possible | Med |
| Memory | Unbounded growth | High |

**Critical Fixes Needed:**
1. Validate `page >= 1` in service layer (defense in depth)
2. Cap progress at 100%
3. Validate date ranges and formats
4. Add cache size limits or LRU eviction
