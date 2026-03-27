-- Migration 004: Track optimization run timing + terminal error details

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS optimization_started_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS optimization_completed_at TIMESTAMP,
    ADD COLUMN IF NOT EXISTS optimization_error TEXT;