-- Migration 005: Track publication lifecycle after final approval

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS publication_status VARCHAR(32),
    ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS publication_error TEXT,
    ADD COLUMN IF NOT EXISTS indexed_chunk_count INTEGER,
    ADD COLUMN IF NOT EXISTS qdrant_collection VARCHAR(255);

ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_publication_status_check;

ALTER TABLE documents ADD CONSTRAINT documents_publication_status_check
    CHECK (
        publication_status IS NULL
        OR publication_status IN ('pending', 'publishing', 'published', 'failed')
    );

UPDATE documents
SET publication_status = 'pending'
WHERE status = 'final-approved'
  AND publication_status IS NULL;