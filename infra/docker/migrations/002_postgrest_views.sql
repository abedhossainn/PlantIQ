-- ============================================================================
-- PostgREST API Enhancement Migration
-- Migration: 002_postgrest_views.sql
-- Created: 2026-03-09
-- Purpose: Create views and functions for better PostgREST API ergonomics
-- ============================================================================

-- ============================================================================
-- PART 1: Create Materialized Views for Performance
-- ============================================================================

-- Document summary view with upload user details
CREATE OR REPLACE VIEW document_summaries AS
SELECT 
    d.id,
    d.title,
    d.version,
    d.system,
    d.document_type,
    d.status,
    d.total_pages,
    d.total_sections,
    d.review_progress,
    d.qa_score,
    d.uploaded_at,
    d.approved_at,
    d.created_at,
    d.updated_at,
    -- Uploader info
    u_upload.username as uploaded_by_username,
    u_upload.full_name as uploaded_by_name,
    -- Approver info
    u_approve.username as approved_by_username,
    u_approve.full_name as approved_by_name,
    -- Computed fields
    CASE 
        WHEN d.total_sections > 0 THEN 
            ROUND((d.review_progress::numeric / d.total_sections::numeric * 100), 2)
        ELSE 0 
    END as review_progress_percent
FROM documents d
LEFT JOIN users u_upload ON d.uploaded_by = u_upload.id
LEFT JOIN users u_approve ON d.approved_by = u_approve.id;

-- Section summary view with reviewer details
CREATE OR REPLACE VIEW section_summaries AS
SELECT 
    s.id,
    s.document_id,
    s.section_number,
    s.title,
    s.page_range,
    s.status,
    s.current_version,
    s.reviewed_at,
    s.created_at,
    s.updated_at,
    -- Document info
    d.title as document_title,
    d.status as document_status,
    -- Reviewer info
    u.username as reviewed_by_username,
    u.full_name as reviewed_by_name,
    -- Content preview (first 200 chars)
    LEFT(s.content, 200) as content_preview,
    LENGTH(s.content) as content_length
FROM document_sections s
JOIN documents d ON s.document_id = d.id
LEFT JOIN users u ON s.reviewed_by = u.id;

-- Conversation summary view with message count
CREATE OR REPLACE VIEW conversation_summaries AS
SELECT 
    c.id,
    c.user_id,
    c.title,
    c.created_at,
    c.updated_at,
    -- User info
    u.username,
    u.full_name as user_name,
    -- Message stats
    COUNT(m.id) as message_count,
    MAX(m.timestamp) as last_message_at
FROM conversations c
JOIN users u ON c.user_id = u.id
LEFT JOIN chat_messages m ON c.id = m.conversation_id
GROUP BY c.id, c.user_id, c.title, c.created_at, c.updated_at, u.username, u.full_name;

-- Bookmark view with full context
CREATE OR REPLACE VIEW bookmark_details AS
SELECT 
    b.id,
    b.user_id,
    b.conversation_id,
    b.message_id,
    b.tags,
    b.notes,
    b.created_at,
    b.updated_at,
    -- User info
    u.username,
    u.full_name as user_name,
    -- Conversation info
    conv.title as conversation_title,
    -- Message content
    msg.content as message_content,
    msg.role as message_role,
    msg.timestamp as message_timestamp
FROM bookmarks b
JOIN users u ON b.user_id = u.id
JOIN conversations conv ON b.conversation_id = conv.id
JOIN chat_messages msg ON b.message_id = msg.id;

-- ============================================================================
-- PART 2: Create Computed Functions for PostgREST
-- ============================================================================

-- Function to get document sections with content (supports RPC call)
CREATE OR REPLACE FUNCTION get_document_sections(doc_id UUID)
RETURNS TABLE (
    id UUID,
    section_number INTEGER,
    title VARCHAR,
    content TEXT,
    page_range VARCHAR,
    status VARCHAR,
    current_version INTEGER,
    reviewed_by_name VARCHAR,
    reviewed_at TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        s.id,
        s.section_number,
        s.title,
        s.content,
        s.page_range,
        s.status,
        s.current_version,
        u.full_name as reviewed_by_name,
        s.reviewed_at
    FROM document_sections s
    LEFT JOIN users u ON s.reviewed_by = u.id
    WHERE s.document_id = doc_id
    ORDER BY s.section_number;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Function to get conversation messages with timestamps
CREATE OR REPLACE FUNCTION get_conversation_messages(conv_id UUID)
RETURNS TABLE (
    id UUID,
    role VARCHAR,
    content TEXT,
    citations JSONB,
    timestamp TIMESTAMP
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        m.id,
        m.role,
        m.content,
        m.citations,
        m.timestamp
    FROM chat_messages m
    WHERE m.conversation_id = conv_id
    ORDER BY m.timestamp ASC;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Function to search documents by title or content
CREATE OR REPLACE FUNCTION search_documents(search_term TEXT)
RETURNS TABLE (
    id UUID,
    title VARCHAR,
    version VARCHAR,
    system VARCHAR,
    document_type VARCHAR,
    status VARCHAR,
    uploaded_by_name VARCHAR,
    relevance REAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        d.id,
        d.title,
        d.version,
        d.system,
        d.document_type,
        d.status,
        u.full_name as uploaded_by_name,
        -- Simple relevance scoring based on title match
        CASE 
            WHEN LOWER(d.title) LIKE LOWER('%' || search_term || '%') THEN 1.0::REAL
            ELSE 0.5::REAL
        END as relevance
    FROM documents d
    LEFT JOIN users u ON d.uploaded_by = u.id
    WHERE 
        LOWER(d.title) LIKE LOWER('%' || search_term || '%')
        OR LOWER(d.system) LIKE LOWER('%' || search_term || '%')
        OR LOWER(d.document_type) LIKE LOWER('%' || search_term || '%')
    ORDER BY relevance DESC, d.updated_at DESC;
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- Function to get user document statistics
CREATE OR REPLACE FUNCTION get_user_stats(user_uuid UUID)
RETURNS TABLE (
    total_documents INTEGER,
    documents_in_review INTEGER,
    documents_approved INTEGER,
    total_conversations INTEGER,
    total_bookmarks INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (SELECT COUNT(*)::INTEGER FROM documents WHERE uploaded_by = user_uuid),
        (SELECT COUNT(*)::INTEGER FROM documents WHERE uploaded_by = user_uuid AND status = 'in-review'),
        (SELECT COUNT(*)::INTEGER FROM documents WHERE uploaded_by = user_uuid AND status = 'approved'),
        (SELECT COUNT(*)::INTEGER FROM conversations WHERE user_id = user_uuid),
        (SELECT COUNT(*)::INTEGER FROM bookmarks WHERE user_id = user_uuid);
END;
$$ LANGUAGE plpgsql STABLE SECURITY DEFINER;

-- ============================================================================
-- PART 3: Grant Permissions on Views and Functions
-- ============================================================================

-- Grant SELECT on views to appropriate roles
GRANT SELECT ON document_summaries TO plantig_reviewer, plantig_admin;
GRANT SELECT ON section_summaries TO plantig_reviewer, plantig_admin;
GRANT SELECT ON conversation_summaries TO plantig_user, plantig_reviewer, plantig_admin;
GRANT SELECT ON bookmark_details TO plantig_user, plantig_reviewer, plantig_admin;

-- Grant EXECUTE on functions to appropriate roles
GRANT EXECUTE ON FUNCTION get_document_sections(UUID) TO plantig_reviewer, plantig_admin;
GRANT EXECUTE ON FUNCTION get_conversation_messages(UUID) TO plantig_user, plantig_reviewer, plantig_admin;
GRANT EXECUTE ON FUNCTION search_documents(TEXT) TO plantig_reviewer, plantig_admin;
GRANT EXECUTE ON FUNCTION get_user_stats(UUID) TO plantig_user, plantig_reviewer, plantig_admin;

-- ============================================================================
-- PART 4: Add RLS Policies for Views
-- ============================================================================

-- Views inherit RLS from base tables, but we enable RLS explicitly for clarity
ALTER VIEW document_summaries SET (security_barrier = true);
ALTER VIEW section_summaries SET (security_barrier = true);
ALTER VIEW conversation_summaries SET (security_barrier = true, security_invoker = true);
ALTER VIEW bookmark_details SET (security_barrier = true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
