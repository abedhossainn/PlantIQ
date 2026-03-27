-- Migration 003: Add HITL optimization and QA lifecycle statuses
-- Adds: approved-for-optimization, optimizing, optimization-complete,
--       qa-review, qa-passed, final-approved

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;

ALTER TABLE documents ADD CONSTRAINT documents_status_check
    CHECK (status IN (
        'pending', 'uploading', 'extracting', 'vlm-validating',
        'validation-complete', 'in-review', 'review-complete',
        'approved-for-optimization', 'optimizing', 'optimization-complete',
        'qa-review', 'qa-passed', 'final-approved',
        'approved', 'rejected', 'failed'
    ));
