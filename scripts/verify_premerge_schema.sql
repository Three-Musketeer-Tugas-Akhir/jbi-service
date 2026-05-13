-- ============================================================
-- Verify premerge columns exist in pipeline_jobs
-- ============================================================

-- 1. Check all premerge columns
SELECT
    column_name,
    data_type || COALESCE('(' || character_maximum_length::text || ')', '') AS data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_name = 'pipeline_jobs'
  AND column_name LIKE 'premerge_%'
ORDER BY ordinal_position;

-- 2. Check index exists
SELECT
    indexname,
    indexdef
FROM pg_indexes
WHERE tablename = 'pipeline_jobs'
  AND indexname = 'ix_pipeline_jobs_premerge_status';

-- 3. Check current premerge data (optional)
SELECT
    premerge_status,
    COUNT(*) AS job_count
FROM pipeline_jobs
WHERE premerge_status IS NOT NULL
GROUP BY premerge_status
ORDER BY job_count DESC;
