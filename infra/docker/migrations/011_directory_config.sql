-- ============================================================================
-- Migration 011: Admin-managed LDAP/AD directory configuration
-- Created: 2026-04-27
-- Purpose: Persist runtime directory connection profile with encrypted bind secret
--          and lightweight non-secret audit trail for admin changes.
-- ============================================================================

CREATE TABLE IF NOT EXISTS directory_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host VARCHAR(255) NOT NULL,
    server_url VARCHAR(512),
    port INTEGER NOT NULL CHECK (port > 0 AND port <= 65535),
    base_dn VARCHAR(512) NOT NULL,
    user_search_base VARCHAR(512) NOT NULL,
    bind_dn VARCHAR(512) NOT NULL,
    bind_password_encrypted TEXT,
    use_ssl BOOLEAN NOT NULL DEFAULT FALSE,
    start_tls BOOLEAN NOT NULL DEFAULT FALSE,
    verify_cert_mode VARCHAR(32) NOT NULL DEFAULT 'required'
        CHECK (verify_cert_mode IN ('required', 'optional', 'none')),
    search_filter_template VARCHAR(512) NOT NULL DEFAULT '(&(objectClass=person)(uid={username}))',
    is_active BOOLEAN NOT NULL DEFAULT FALSE,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (NOT (use_ssl = TRUE AND start_tls = TRUE))
);

-- v1 guardrail: only one active profile at a time.
CREATE UNIQUE INDEX IF NOT EXISTS uq_directory_configs_single_active
    ON directory_configs((1))
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_directory_configs_updated_at
    ON directory_configs(updated_at DESC);

CREATE TABLE IF NOT EXISTS directory_config_audits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    directory_config_id UUID REFERENCES directory_configs(id) ON DELETE SET NULL,
    changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    change_type VARCHAR(64) NOT NULL,
    change_summary TEXT NOT NULL,
    changed_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_directory_config_audits_config_id
    ON directory_config_audits(directory_config_id);
CREATE INDEX IF NOT EXISTS idx_directory_config_audits_created_at
    ON directory_config_audits(created_at DESC);

GRANT SELECT ON directory_configs TO plantig_user, plantig_reviewer;
GRANT SELECT, INSERT, UPDATE, DELETE ON directory_configs TO plantig_admin;

GRANT SELECT ON directory_config_audits TO plantig_reviewer;
GRANT SELECT, INSERT, UPDATE, DELETE ON directory_config_audits TO plantig_admin;

ALTER TABLE directory_configs ENABLE ROW LEVEL SECURITY;
ALTER TABLE directory_config_audits ENABLE ROW LEVEL SECURITY;

CREATE POLICY directory_configs_select_non_admin ON directory_configs FOR SELECT
    TO plantig_user, plantig_reviewer
    USING (false);

CREATE POLICY directory_configs_admin_all ON directory_configs FOR ALL
    TO plantig_admin
    USING (true)
    WITH CHECK (true);

CREATE POLICY directory_config_audits_select_non_admin ON directory_config_audits FOR SELECT
    TO plantig_reviewer
    USING (false);

CREATE POLICY directory_config_audits_admin_all ON directory_config_audits FOR ALL
    TO plantig_admin
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
