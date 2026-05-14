-- ═══════════════════════════════════════════════════════════════════════
-- SQL Migration: SIBI Improvements for JBI Service
-- Run this manually on the SSH server against the PostgreSQL database
-- ═══════════════════════════════════════════════════════════════════════

-- Improvement 3: Trim Audit Trail
-- Adds cascade_info JSONB column to annotation_edits table
-- This column stores the audit trail of cascade effects from trim operations

ALTER TABLE annotation_edits 
ADD COLUMN IF NOT EXISTS cascade_info JSONB DEFAULT NULL;

COMMENT ON COLUMN annotation_edits.cascade_info IS 
'Audit trail of cascade effects from trim operations: {history: [{source_utterance, affected_utterances, shift_amount, timestamp, action}]}';

-- Verify the column was added
SELECT column_name, data_type, is_nullable 
FROM information_schema.columns 
WHERE table_name = 'annotation_edits' AND column_name = 'cascade_info';
