-- Migration 004: Add optimization tracking columns to documents table
-- These columns track the timing and error state of Stage 10 (Post-Approval Reformatting)
ALTER TABLE documents
  ADD COLUMN IF NOT EXISTS optimization_started_at  TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS optimization_completed_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS optimization_error        TEXT;
