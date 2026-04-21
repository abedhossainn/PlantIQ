-- ============================================================================
-- Conversation scope persistence for workspace-scoped chat
-- Migration: 006_conversation_scope_persistence.sql
-- Created: 2026-03-27
-- Purpose: Persist chat scope on conversations and expose it through
--          conversation_summaries for backend-authoritative chat sessions.
-- ============================================================================

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS workspace VARCHAR(255),
    ADD COLUMN IF NOT EXISTS document_type_filters TEXT[],
    ADD COLUMN IF NOT EXISTS preferred_document_types TEXT[],
    ADD COLUMN IF NOT EXISTS include_shared_documents BOOLEAN;

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
    c.include_shared_documents
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
    c.include_shared_documents;

GRANT SELECT ON conversation_summaries TO plantig_user, plantig_reviewer, plantig_admin;

ALTER VIEW conversation_summaries SET (security_barrier = true, security_invoker = true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================