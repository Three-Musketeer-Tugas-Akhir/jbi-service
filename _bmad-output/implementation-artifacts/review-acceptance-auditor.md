# Acceptance Auditor Review - Story 1.4

## Role
You are an **Acceptance Auditor** - verify implementation against the spec and acceptance criteria.

## Story Context

**Story:** 1.4 JWT Refresh Token Flow
**Status:** Review

### Acceptance Criteria

**AC1:** Given I have a valid refresh token (7-day expiry)  
When I POST to `/api/v1/auth/refresh` with the refresh token  
Then I receive a new access_token and refresh_token pair  
And the new access token has 24-hour expiry  
And the new refresh token has 7-day expiry

**AC2:** Given I have an expired refresh token  
When I attempt to refresh  
Then I receive a 401 response with error "Refresh token expired, please login again"

**AC3:** Given I have a revoked/blacklisted refresh token  
When I attempt to refresh  
Then I receive a 401 response with error "Invalid refresh token"

### Key Requirements from Story
- Store refresh token jti in database for revocation capability
- Rotate refresh tokens (new token issued on each refresh)
- Cleanup expired tokens (daily scheduled job)

## Diff to Review

```diff
diff --git a/app/services/cleanup.py b/app/services/cleanup.py
index 9053698..837d56f 100644
--- a/app/services/cleanup.py
+++ b/app/services/cleanup.py
@@ -1,81 +1,116 @@
-import shutil
-import logging
-from datetime import datetime, timezone, timedelta
-from pathlib import Path
-
-from app.config import settings
-from app.database import async_session
-from app.models.job import JobStatus
-from app.models.job_store import job_store
-
-logger = logging.getLogger(__name__)
-
-
-async def cleanup_expired_jobs() -> int:
-    """Delete jobs that have exceeded their TTL.
-
-    Deletes:
-    - The job record from the database.
-    - The uploaded video file.
-    - The output directory and all contents.
-
-    Returns:
-        Number of jobs cleaned up.
-    """
-    ttl = timedelta(hours=settings.job_ttl_hours)
-    now = datetime.now(timezone.utc)
-    cutoff = now - ttl
-
-    async with async_session() as session:
-        all_jobs = await job_store.list_all(session)
-        cleaned = 0
-
-        for record in all_jobs:
-            # Never clean up jobs still processing
-            if record.status == JobStatus.PROCESSING.value:
-                continue
-
-            # Clean up terminal jobs past TTL
-            # Also clean up queued jobs past TTL (assumed stuck/orphaned)
-            if record.updated_at < cutoff:
-                try:
-                    _delete_job_files(record.id, record.video_path)
-                    await job_store.delete(session, record.id)
-                    cleaned += 1
-                    logger.info(
-                        "Cleaned up expired job %s (status=%s, age=%s)",
-                        record.id, record.status, now - record.updated_at,
-                    )
-                except Exception:
-                    logger.exception(
-                        "Failed to clean up job %s — will retry next cycle",
-                        record.id,
-                    )
-
-        await session.commit()
-
-    if cleaned > 0:
-        logger.info("Cleanup cycle complete: %d jobs removed", cleaned)
-
-    return cleaned
-
-
-def _delete_job_files(job_id: str, video_path: str):
-    """Delete all files associated with a job."""
-    # Delete uploaded video
-    try:
-        upload_path = Path(video_path)
-        if upload_path.exists():
-            upload_path.unlink()
-            logger.debug("Deleted upload: %s", upload_path)
-    except OSError:
-        logger.warning("Failed to delete upload: %s", video_path)
-
-    # Delete output directory (segments + detection_times.txt)
-    try:
-        output_dir = Path(settings.output_dir) / job_id
-        if output_dir.exists():
-            shutil.rmtree(output_dir)
-            logger.debug("Deleted output dir: %s", output_dir)
-    except OSError:
-        logger.warning("Failed to delete output dir for job %s", job_id)
+import shutil
+import logging
+from datetime import datetime, timezone, timedelta
+from pathlib import Path
+
+from app.config import settings
+from app.database import async_session
+from app.models.job import JobStatus
+from app.models.job_store import job_store
+
+logger = logging.getLogger(__name__)
+
+
+async def cleanup_expired_refresh_tokens(batch_size: int = 1000) -> int:
+    """
+    Clean up expired refresh tokens from the database.
+    
+    Deletes refresh tokens that have passed their expiration date.
+    
+    Args:
+        batch_size: Maximum number of tokens to delete per run
+        
+    Returns:
+        Number of tokens deleted
+    """
+    from sqlalchemy import delete
+    from app.db.models.auth import RefreshToken
+    
+    async with async_session() as session:
+        # Delete expired tokens
+        stmt = (
+            delete(RefreshToken)
+            .where(RefreshToken.expires_at < datetime.now(timezone.utc))
+            .limit(batch_size)
+        )
+        result = await session.execute(stmt)
+        deleted_count = result.rowcount
+        await session.commit()
+        
+        if deleted_count > 0:
+            logger.info(
+                "Cleaned up %d expired refresh tokens",
+                deleted_count
+            )
+        
+        return deleted_count
+
+
+async def cleanup_expired_jobs() -> int:
+    """Delete jobs that have exceeded their TTL.
+
+    Deletes:
+    - The job record from the database.
+    - The uploaded video file.
+    - The output directory and all contents.
+
+    Returns:
+        Number of jobs cleaned up.
+    """
+    ttl = timedelta(hours=settings.job_ttl_hours)
+    now = datetime.now(timezone.utc)
+    cutoff = now - ttl
+
+    async with async_session() as session:
+        all_jobs = await job_store.list_all(session)
+        cleaned = 0
+
+        for record in all_jobs:
+            # Never clean up jobs still processing
+            if record.status == JobStatus.PROCESSING.value:
+                continue
+
+            # Clean up terminal jobs past TTL
+            # Also clean up queued jobs past TTL (assumed stuck/orphaned)
+            if record.updated_at < cutoff:
+                try:
+                    _delete_job_files(record.id, record.video_path)
+                    await job_store.delete(session, record.id)
+                    cleaned += 1
+                    logger.info(
+                        "Cleaned up expired job %s (status=%s, age=%s)",
+                        record.id, record.status, now - record.updated_at,
+                    )
+                except Exception:
+                    logger.exception(
+                        "Failed to clean up job %s — will retry next cycle",
+                        record.id,
+                    )
+
+        await session.commit()
+
+    if cleaned > 0:
+        logger.info("Cleanup cycle complete: %d jobs removed", cleaned)
+
+    return cleaned
+
+
+def _delete_job_files(job_id: str, video_path: str):
+    """Delete all files associated with a job."""
+    # Delete uploaded video
+    try:
+        upload_path = Path(video_path)
+        if upload_path.exists():
+            upload_path.unlink()
+            logger.debug("Deleted upload: %s", upload_path)
+    except OSError:
+        logger.warning("Failed to delete upload: %s", video_path)
+
+    # Delete output directory (segments + detection_times.txt)
+    try:
+        output_dir = Path(settings.output_dir) / job_id
+        if output_dir.exists():
+            shutil.rmtree(output_dir)
+            logger.debug("Deleted output dir: %s", output_dir)
+    except OSError:
+        logger.warning("Failed to delete output dir for job %s", job_id)

diff --git a/app/services/scheduler.py b/app/services/scheduler.py
index d17ee53..1e425e2 100644
--- a/app/services/scheduler.py
+++ b/app/services/scheduler.py
@@ -1,43 +1,60 @@
-import asyncio
-import logging
-
-from app.config import settings
-from app.services.cleanup import cleanup_expired_jobs
-
-logger = logging.getLogger(__name__)
-
-_cleanup_task: asyncio.Task = None
-
-
-async def _cleanup_loop():
-    """Run cleanup_expired_jobs() on a fixed interval."""
-    interval = settings.cleanup_interval_minutes * 60  # convert to seconds
-    logger.info(
-        "Cleanup scheduler started — interval=%dm, TTL=%dh",
-        settings.cleanup_interval_minutes, settings.job_ttl_hours,
-    )
-
-    while True:
-        await asyncio.sleep(interval)
-        try:
-            cleaned = await cleanup_expired_jobs()
-            if cleaned > 0:
-                logger.info("Scheduled cleanup removed %d jobs", cleaned)
-        except Exception:
-            logger.exception("Cleanup cycle failed — will retry next interval")
-
-
-def start_cleanup_scheduler():
-    """Start the background cleanup loop. Call once at app startup."""
-    global _cleanup_task
-    if _cleanup_task is None or _cleanup_task.done():
-        _cleanup_task = asyncio.create_task(_cleanup_loop())
-        logger.info("Cleanup scheduler task created")
-
-
-def stop_cleanup_scheduler():
-    """Stop the background cleanup loop. Call at app shutdown."""
-    global _cleanup_task
-    if _cleanup_task and not _cleanup_task.done():
-        _cleanup_task.cancel()
-        logger.info("Cleanup scheduler task cancelled")
+import asyncio
+import logging
+
+from app.config import settings
+from app.services.cleanup import cleanup_expired_jobs, cleanup_expired_refresh_tokens
+
+logger = logging.getLogger(__name__)
+
+_cleanup_task: asyncio.Task = None
+
+
+async def _cleanup_loop():
+    """Run cleanup tasks on a fixed interval."""
+    interval = settings.cleanup_interval_minutes * 60  # convert to seconds
+    logger.info(
+        "Cleanup scheduler started — interval=%dm, job TTL=%dh",
+        settings.cleanup_interval_minutes, settings.job_ttl_hours,
+    )
+
+    # Track refresh token cleanup - run daily
+    refresh_token_cleanup_interval = 24 * 60 * 60  # 24 hours in seconds
+    last_refresh_cleanup = 0
+
+    while True:
+        await asyncio.sleep(interval)
+        
+        # Cleanup expired jobs
+        try:
+            cleaned = await cleanup_expired_jobs()
+            if cleaned > 0:
+                logger.info("Scheduled cleanup removed %d jobs", cleaned)
+        except Exception:
+            logger.exception("Job cleanup cycle failed — will retry next interval")
+        
+        # Cleanup expired refresh tokens (run once per day)
+        current_time = asyncio.get_event_loop().time()
+        if current_time - last_refresh_cleanup >= refresh_token_cleanup_interval:
+            try:
+                tokens_cleaned = await cleanup_expired_refresh_tokens()
+                if tokens_cleaned > 0:
+                    logger.info("Scheduled cleanup removed %d expired refresh tokens", tokens_cleaned)
+                last_refresh_cleanup = current_time
+            except Exception:
+                logger.exception("Refresh token cleanup cycle failed — will retry next interval")
+
+
+def start_cleanup_scheduler():
+    """Start the background cleanup loop. Call once at app startup."""
+    global _cleanup_task
+    if _cleanup_task is None or _cleanup_task.done():
+        _cleanup_task = asyncio.create_task(_cleanup_loop())
+        logger.info("Cleanup scheduler task created")
+
+
+def stop_cleanup_scheduler():
+    """Stop the background cleanup loop. Call at app shutdown."""
+    global _cleanup_task
+    if _cleanup_task and not _cleanup_task.done():
+        _cleanup_task.cancel()
+        logger.info("Cleanup scheduler task cancelled")
```

## New Test Files
- `tests/unit/test_repositories/test_refresh_token_repository.py` (13 tests)
- `tests/unit/test_services/test_token_refresh_service.py` (14 tests)

---

## Your Task

Review the diff against the spec. Check for:
1. **Acceptance Criteria violations** - Does the code satisfy each AC?
2. **Missing implementation** - Is anything from the spec not implemented?
3. **Contradictions** - Does code contradict spec constraints?
4. **Test coverage** - Are all ACs covered by tests?

## Output Format

For each finding:
- **AC VIOLATED**: Which AC (if any)
- **ISSUE**: One-line description
- **EVIDENCE**: Code or lack thereof that demonstrates the issue
- **SEVERITY**: [BLOCKER/HIGH/MED/LOW]

If spec is satisfied, state: "All acceptance criteria met."
