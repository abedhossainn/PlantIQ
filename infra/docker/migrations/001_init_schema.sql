-- ============================================================================
-- PlantIQ Database Schema Initialization
-- Migration: 001_init_schema.sql
-- Created: 2026-03-09
-- Purpose: Create base schema with all tables, roles, RLS policies
-- ============================================================================

-- ============================================================================
-- PART 1: Create PostgreSQL Roles
-- ============================================================================

-- SECURITY WARNING: The authenticator password MUST be provisioned via secrets management.
-- This migration expects POSTGRES_AUTHENTICATOR_PASSWORD environment variable to be set.
-- For production: Use Docker secrets, Kubernetes secrets, or HashiCorp Vault.
-- NEVER commit the actual password to version control.

-- Authenticator role (PostgREST connects as this role, then switches via SET ROLE)
-- Password will be set from environment variable by init script
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'plantig_authenticator') THEN
        -- Create role with password from environment
        EXECUTE format(
            'CREATE ROLE plantig_authenticator WITH LOGIN PASSWORD %L',
            coalesce(current_setting('app.authenticator_password', true), 'CHANGE_ME_IMMEDIATELY')
        );
        RAISE NOTICE 'Created plantig_authenticator role. ROTATE PASSWORD IMMEDIATELY!';
    END IF;
END
$$;

-- Anonymous role (for unauthenticated requests - no access)
CREATE ROLE plantig_anon NOLOGIN;

-- Application roles (mapped from JWT 'role' claim)
CREATE ROLE plantig_admin NOLOGIN;
CREATE ROLE plantig_reviewer NOLOGIN;
CREATE ROLE plantig_user NOLOGIN;

-- Grant role switching permissions
GRANT plantig_anon TO plantig_authenticator;
GRANT plantig_admin TO plantig_authenticator;
GRANT plantig_reviewer TO plantig_authenticator;
GRANT plantig_user TO plantig_authenticator;

-- ============================================================================
-- PART 2: Create Tables
-- ============================================================================

-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'reviewer', 'user')),
    department VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    last_login TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    version VARCHAR(50),
    system VARCHAR(255),
    document_type VARCHAR(100),
    file_path VARCHAR(1000) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN (
        'pending', 'uploading', 'extracting', 'vlm-validating',
        'validation-complete', 'in-review', 'review-complete',
        'approved', 'rejected'
    )),
    total_pages INTEGER,
    total_sections INTEGER,
    review_progress INTEGER DEFAULT 0,
    qa_score DECIMAL(5,2),
    uploaded_by UUID REFERENCES users(id),
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Document sections table
CREATE TABLE document_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_number INTEGER NOT NULL,
    title VARCHAR(500),
    content TEXT NOT NULL,
    page_range VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'in-review', 'approved', 'rejected'
    )),
    review_checklist JSONB,
    current_version INTEGER DEFAULT 1,
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, section_number)
);

-- Section versions table
CREATE TABLE section_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    reviewed_by UUID REFERENCES users(id),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(section_id, version_number)
);

-- Conversations table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Chat messages table
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Bookmarks table
CREATE TABLE bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    tags TEXT[],
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Refresh tokens table
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 of raw token
    expires_at TIMESTAMP NOT NULL,
    revoked_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- PART 3: Create Indexes for Performance
-- ============================================================================

CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by);
CREATE INDEX idx_sections_document_id ON document_sections(document_id);
CREATE INDEX idx_sections_status ON document_sections(status);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_messages_conversation_id ON chat_messages(conversation_id);
CREATE INDEX idx_bookmarks_user_id ON bookmarks(user_id);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);

-- ============================================================================
-- PART 4: Grant Base Permissions to Roles
-- ============================================================================

-- Grant usage on schema
GRANT USAGE ON SCHEMA public TO plantig_anon, plantig_user, plantig_reviewer, plantig_admin;

-- Anonymous role: no table access
-- (no grants)

-- User role: conversations, messages, bookmarks
GRANT SELECT, INSERT ON conversations TO plantig_user;
GRANT SELECT, INSERT ON chat_messages TO plantig_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON bookmarks TO plantig_user;

-- Reviewer role: users (read), documents, sections, conversations, messages, bookmarks
GRANT SELECT ON users TO plantig_reviewer;
GRANT SELECT, UPDATE ON documents TO plantig_reviewer;
GRANT SELECT, UPDATE ON document_sections TO plantig_reviewer;
GRANT SELECT, INSERT, UPDATE ON section_versions TO plantig_reviewer;
GRANT SELECT, INSERT ON conversations TO plantig_reviewer;
GRANT SELECT, INSERT ON chat_messages TO plantig_reviewer;
GRANT SELECT, INSERT, UPDATE, DELETE ON bookmarks TO plantig_reviewer;

-- Admin role: full access (GRANT ALL)
GRANT ALL ON users TO plantig_admin;
GRANT ALL ON documents TO plantig_admin;
GRANT ALL ON document_sections TO plantig_admin;
GRANT ALL ON section_versions TO plantig_admin;
GRANT ALL ON conversations TO plantig_admin;
GRANT ALL ON chat_messages TO plantig_admin;
GRANT ALL ON bookmarks TO plantig_admin;
GRANT ALL ON refresh_tokens TO plantig_admin;

-- Grant sequence usage for default UUID generation
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO plantig_user, plantig_reviewer, plantig_admin;

-- ============================================================================
-- PART 5: RLS Helper Functions
-- ============================================================================

-- Returns the authenticated user's UUID from the JWT sub claim
CREATE OR REPLACE FUNCTION plantig_uid() RETURNS UUID AS $$
  SELECT COALESCE(
    current_setting('request.jwt.claims', true)::jsonb->>'sub',
    '00000000-0000-0000-0000-000000000000'
  )::UUID;
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- Returns the authenticated user's role from the JWT role claim
CREATE OR REPLACE FUNCTION plantig_role() RETURNS TEXT AS $$
  SELECT COALESCE(
    current_setting('request.jwt.claims', true)::jsonb->>'role',
    'anon'
  );
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- ============================================================================
-- PART 6: Row Level Security Policies
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Users Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- Users can view their own record
CREATE POLICY users_select_own ON users FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (id = plantig_uid());

-- Users can update their own non-role fields
CREATE POLICY users_update_own ON users FOR UPDATE
  TO plantig_user, plantig_reviewer
  USING (id = plantig_uid())
  WITH CHECK (id = plantig_uid() AND role = (SELECT role FROM users WHERE id = plantig_uid()));

-- Reviewers can read all users (for assigning reviews)
CREATE POLICY users_select_all_reviewer ON users FOR SELECT
  TO plantig_reviewer
  USING (true);

-- Admin has full access
CREATE POLICY users_admin_all ON users FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Documents Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- Reviewers and admins can view all documents
CREATE POLICY docs_select_reviewer ON documents FOR SELECT
  TO plantig_reviewer, plantig_admin
  USING (true);

-- Reviewers can update documents but cannot approve
CREATE POLICY docs_update_reviewer ON documents FOR UPDATE
  TO plantig_reviewer
  USING (true)
  WITH CHECK (status NOT IN ('approved'));

-- Only admins can approve documents
CREATE POLICY docs_update_admin ON documents FOR UPDATE
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- Admins can insert and delete
CREATE POLICY docs_insert_admin ON documents FOR INSERT
  TO plantig_admin
  WITH CHECK (true);

CREATE POLICY docs_delete_admin ON documents FOR DELETE
  TO plantig_admin
  USING (true);

-- ----------------------------------------------------------------------------
-- Document Sections Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE document_sections ENABLE ROW LEVEL SECURITY;

-- Reviewers and admins can view all sections
CREATE POLICY sections_select_reviewer ON document_sections FOR SELECT
  TO plantig_reviewer, plantig_admin
  USING (true);

-- Reviewers can update sections (for review workflow)
CREATE POLICY sections_update_reviewer ON document_sections FOR UPDATE
  TO plantig_reviewer
  USING (true)
  WITH CHECK (true);

-- Admins have full access
CREATE POLICY sections_admin_all ON document_sections FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Section Versions Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE section_versions ENABLE ROW LEVEL SECURITY;

-- Reviewers can view and insert versions
CREATE POLICY versions_select_reviewer ON section_versions FOR SELECT
  TO plantig_reviewer, plantig_admin
  USING (true);

CREATE POLICY versions_insert_reviewer ON section_versions FOR INSERT
  TO plantig_reviewer
  WITH CHECK (true);

-- Admins have full access
CREATE POLICY versions_admin_all ON section_versions FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Conversations Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- Users see only their own conversations
CREATE POLICY conv_select_own ON conversations FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid());

-- Users can create their own conversations
CREATE POLICY conv_insert_own ON conversations FOR INSERT
  TO plantig_user, plantig_reviewer
  WITH CHECK (user_id = plantig_uid());

-- Users can update their own conversations (e.g., title)
CREATE POLICY conv_update_own ON conversations FOR UPDATE
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid())
  WITH CHECK (user_id = plantig_uid());

-- Users can delete their own conversations
CREATE POLICY conv_delete_own ON conversations FOR DELETE
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid());

-- Admins see all conversations
CREATE POLICY conv_admin_all ON conversations FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Chat Messages Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;

-- Users can view messages in their own conversations
CREATE POLICY messages_select_own ON chat_messages FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (
    conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  );

-- Users can insert messages in their own conversations
CREATE POLICY messages_insert_own ON chat_messages FOR INSERT
  TO plantig_user, plantig_reviewer
  WITH CHECK (
    conversation_id IN (
      SELECT id FROM conversations WHERE user_id = plantig_uid()
    )
  );

-- Admins see all messages
CREATE POLICY messages_admin_all ON chat_messages FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Bookmarks Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;

-- Users can fully manage their own bookmarks
CREATE POLICY bookmarks_own ON bookmarks FOR ALL
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid())
  WITH CHECK (user_id = plantig_uid());

-- Admins see all bookmarks
CREATE POLICY bookmarks_admin_all ON bookmarks FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ----------------------------------------------------------------------------
-- Refresh Tokens Table RLS
-- ----------------------------------------------------------------------------
ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY;

-- Users can view and delete their own refresh tokens
CREATE POLICY refresh_tokens_own ON refresh_tokens FOR SELECT
  TO plantig_user, plantig_reviewer, plantig_admin
  USING (user_id = plantig_uid());

CREATE POLICY refresh_tokens_delete_own ON refresh_tokens FOR DELETE
  TO plantig_user, plantig_reviewer, plantig_admin
  USING (user_id = plantig_uid());

-- Only admins can insert refresh tokens (auth service uses admin context)
CREATE POLICY refresh_tokens_insert_admin ON refresh_tokens FOR INSERT
  TO plantig_admin
  WITH CHECK (true);

-- Admins can manage all tokens
CREATE POLICY refresh_tokens_admin_all ON refresh_tokens FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- PART 7: Default Data (Optional)
-- ============================================================================

-- Insert default admin user (password should be changed immediately)
INSERT INTO users (id, username, email, full_name, role, department, status)
VALUES (
  '00000000-0000-0000-0000-000000000001',
  'admin',
  'admin@plantig.local',
  'System Administrator',
  'admin',
  'IT',
  'active'
) ON CONFLICT (username) DO NOTHING;

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
