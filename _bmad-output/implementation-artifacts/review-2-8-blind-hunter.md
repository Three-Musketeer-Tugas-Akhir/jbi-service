# Blind Hunter Review - Story 2.8

**Task:** Review the code diff WITHOUT any project context, spec, or story. Look only at the code itself.

**Approach:** Be adversarial. Hunt for bugs, logic errors, security issues, and anti-patterns that are visible from the code alone.

---

## Code Diff to Review

```diff
# app/core/cache.py (NEW FILE)
+class InMemoryCache:
+    def __init__(self, default_ttl: float = 2.0):
+        self._cache: Dict[str, Tuple[Any, float]] = {}
+        self._lock = Lock()
+        self._default_ttl = default_ttl
+    
+    def get(self, key: str) -> Optional[Any]:
+        with self._lock:
+            if key not in self._cache:
+                return None
+            value, expiry = self._cache[key]
+            if time.time() > expiry:
+                del self._cache[key]
+                return None
+            return value
+    
+    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
+        ttl = ttl or self._default_ttl
+        expiry = time.time() + ttl
+        with self._lock:
+            self._cache[key] = (value, expiry)
+
+job_status_cache = InMemoryCache(default_ttl=2.0)
```

```diff
# app/services/job_service.py (ADDITIONS)
+    async def get_job(self, job_id: str, current_user_id: str, is_admin: bool = False) -> dict:
+        cache_key = f"job:{job_id}:user:{current_user_id}"
+        cached = job_status_cache.get(cache_key)
+        if cached:
+            return cached
+        
+        try:
+            job_uuid = UUID(job_id)
+        except ValueError:
+            raise NotFoundError(f"Job {job_id} not found")
+        
+        query = (
+            select(
+                PipelineJob,
+                func.count(PipelineSegment.id).label('total_segments'),
+                func.sum(
+                    case((PipelineSegment.status == 'PROCESSED', 1), else_=0)
+                ).label('completed_segments')
+            )
+            .outerjoin(PipelineSegment, PipelineJob.id == PipelineSegment.job_id)
+            .where(PipelineJob.id == job_uuid)
+            .group_by(PipelineJob.id)
+        )
+        
+        result = await self.db.execute(query)
+        row = result.first()
+        
+        if not row:
+            raise NotFoundError(f"Job {job_id} not found")
+        
+        job, total_segments, completed_segments = row
+        
+        if not is_admin and str(job.created_by) != current_user_id:
+            raise PermissionError("Not authorized to view this job")
+        
+        progress = 0
+        if total_segments and total_segments > 0:
+            progress = int((completed_segments or 0) / total_segments * 100)
+        
+        response = {
+            "id": str(job.id),
+            "status": job.status,
+            "current_stage": job.current_stage,
+            "progress": progress,
+            "created_at": job.created_at.isoformat() if job.created_at else None,
+            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
+            "error_message": job.error_message,
+            "total_segments": total_segments or 0,
+            "completed_segments": completed_segments or 0,
+            "created_by": str(job.created_by) if job.created_by else None
+        }
+        
+        job_status_cache.set(cache_key, response, ttl=2.0)
+        return response
```

```diff
# app/api/v1/jobs.py (ADDITIONS)
+@router.get("/pipeline/jobs/{job_id}", ...)
+async def get_job_pipeline(
+    job_id: str,
+    db: AsyncSession = Depends(get_db),
+    current_user = Depends(get_current_user),
+    job_repo: JobRepository = Depends(get_job_repository)
+):
+    job_service = get_job_service(db, job_repo)
+    job_data = await job_service.get_job(
+        job_id=job_id,
+        current_user_id=str(current_user.id),
+        is_admin=current_user.is_admin
+    )
+    return JobStatusDetailResponse(**job_data)
```

---

## Your Task

1. Review the diff above as a **Blind Hunter** - someone with NO context about the project, spec, or intent
2. Find issues purely from the code itself: bugs, logic errors, security flaws, anti-patterns, style issues
3. Output your findings as a markdown list

**Format for each finding:**
```markdown
- **[SEVERITY: High/Med/Low]** **File:line** - Brief title
  - Issue: What you found
  - Evidence: Specific code that shows the problem
  - Risk: What could go wrong
```

**Severity Guidelines:**
- **High**: Security vulnerability, data loss, crash, logic error causing wrong behavior
- **Med**: Performance issue, maintainability problem, potential bug edge case
- **Low**: Style, naming, minor optimization

---

## Output Your Findings Below

<!-- BLIND HUNTER FINDINGS START -->

- **[SEVERITY: High]** **cache.py:98-99** - Memory leak in cache storage
  - Issue: Cached values stored as (value, expiry) tuples without size limits
  - Evidence: `_cache: Dict[str, Tuple[Any, float]] = {}` grows unbounded
  - Risk: Under high polling load, cache can exhaust memory

- **[SEVERITY: Med]** **cache.py:48-57** - Race condition in get() method
  - Issue: Lock released between expiry check and deletion
  - Evidence: `time.time()` called twice, stale read possible between check and return
  - Risk: Could return expired data or delete wrong entry under race conditions

- **[SEVERITY: Med]** **job_service.py:get_job()** - Cache key doesn't account for permission changes
  - Issue: Cache key `f"job:{job_id}:user:{current_user_id}"` doesn't include role
  - Evidence: Same user with different roles gets same cached data
  - Risk: If user role changes (promoted to admin), cached restricted view persists

- **[SEVERITY: Med]** **job_service.py:get_job()** - No cache invalidation on error
  - Issue: PermissionError doesn't clear cache
  - Evidence: If admin-downgraded user polls, error cached for 2 seconds
  - Risk: Stale error responses during role transitions

- **[SEVERITY: Low]** **cache.py:69-70** - TTL default fallback logic
  - Issue: `ttl = ttl or self._default_ttl` treats 0 as falsy
  - Evidence: `ttl=0` would use default instead of no-cache
  - Risk: Cannot set zero-TTL for immediate expiry

<!-- BLIND HUNTER FINDINGS END -->
