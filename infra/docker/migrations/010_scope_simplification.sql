-- Migration 010: Scope Simplification (Candidate 5)
--
-- Purpose: Document the removal of document_type from active scope governance.
-- Scope is now system + area only.
--
-- This migration is intentionally non-destructive:
--   - The `document_type` column in `documents` is NOT dropped.
--   - Existing stored values are preserved for audit and historical query purposes.
--   - The `document_type_filters` and `preferred_document_types` columns in
--     `conversations` are NOT dropped; they may contain legacy persisted scope data.
--
-- Behavioral change (enforced at application layer, not DB layer):
--   - `resolve_query_scope` (rag_helpers.py) always returns document_type_filters=None.
--   - Qdrant search predicates no longer filter by document_type.
--   - document_type relevance weighting (apply_document_type_weighting) receives
--     preferred_document_types=None and is therefore a no-op.
--   - Upload scope enforcement (enforce_upload_scope) remains system-only (unchanged).
--   - API request fields `document_type_filters` and `preferred_document_types` are
--     accepted for backward compatibility but ignored.
--
-- Rollback: revert rag_helpers.py::resolve_query_scope to previous version.
-- No DDL changes to roll back.

-- Annotate conversations table columns as deprecated scope fields (informational only).
COMMENT ON COLUMN conversations.document_type_filters
    IS 'Deprecated (Candidate 5): document_type removed from active scope axis. Retained for historical data only.';

COMMENT ON COLUMN conversations.preferred_document_types
    IS 'Deprecated (Candidate 5): document_type weighting removed from retrieval. Retained for historical data only.';
