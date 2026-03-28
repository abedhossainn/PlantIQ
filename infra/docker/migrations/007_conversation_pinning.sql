-- ============================================================================
-- Conversation pinning support
-- Migration: 007_conversation_pinning.sql
-- Created: 2026-03-27
-- Purpose: Persist pinned conversation state and expose it via
--          conversation_summaries for chat history prioritization.
-- ============================================================================

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE;

DROP VIEW IF EXISTS conversation_summaries;

CREATE VIEW conversation_summaries AS
SELECT
    c.id,
    c.user_id,
    c.title,
    c.created_at,
    c.updated_at,
    u.username,
    u.full_name AS user_name,
    COUNT(m.id) AS message_count,
    MAX(m.timestamp) AS last_message_at,
    (
        SELECT LEFT(m2.content, 200)
        FROM chat_messages m2
        WHERE m2.conversation_id = c.id
        ORDER BY m2.timestamp DESC
        LIMIT 1
    ) AS last_message_preview,
    c.workspace,
    c.document_type_filters,
    c.preferred_document_types,
    c.include_shared_documents,
    c.is_pinned
FROM conversations c
JOIN users u ON c.user_id = u.id
LEFT JOIN chat_messages m ON c.id = m.conversation_id
GROUP BY
    c.id,
    c.user_id,
    c.title,
    c.created_at,
    c.updated_at,
    u.username,
    u.full_name,
    c.workspace,
    c.document_type_filters,
    c.preferred_document_types,
    c.include_shared_documents,
    c.is_pinned;

GRANT SELECT ON conversation_summaries TO plantig_user, plantig_reviewer, plantig_admin;

ALTER VIEW conversation_summaries SET (security_barrier = true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================