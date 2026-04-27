-- ============================================================================
-- System/Area scope governance and denial audit logging
-- Migration: 008_scope_governance.sql
-- Created: 2026-04-26
-- Purpose: Persist per-user system/area access policy and audit denied scope
--          attempts for ingestion/chat enforcement.
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_scope_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    system_scope VARCHAR(255),
    area_scope VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CHECK (system_scope IS NOT NULL OR area_scope IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_user_scope_policy
    ON user_scope_policies (
        user_id,
        COALESCE(LOWER(system_scope), ''),
        COALESCE(LOWER(area_scope), '')
    );

CREATE INDEX IF NOT EXISTS idx_user_scope_policies_user_id ON user_scope_policies(user_id);
CREATE INDEX IF NOT EXISTS idx_user_scope_policies_active ON user_scope_policies(is_active);

CREATE TABLE IF NOT EXISTS access_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action VARCHAR(120) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    requested_system VARCHAR(255),
    requested_area VARCHAR(255),
    reason_code VARCHAR(80) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_audit_logs_user_id ON access_audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_access_audit_logs_created_at ON access_audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_audit_logs_reason_code ON access_audit_logs(reason_code);

GRANT SELECT ON user_scope_policies TO plantig_user, plantig_reviewer;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_scope_policies TO plantig_admin;

GRANT INSERT ON access_audit_logs TO plantig_user, plantig_reviewer, plantig_admin;
GRANT SELECT ON access_audit_logs TO plantig_user, plantig_reviewer;
GRANT SELECT, UPDATE, DELETE ON access_audit_logs TO plantig_admin;

ALTER TABLE user_scope_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE access_audit_logs ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_scope_policies_select_own ON user_scope_policies FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid());

CREATE POLICY user_scope_policies_admin_all ON user_scope_policies FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

CREATE POLICY access_audit_logs_insert_own ON access_audit_logs FOR INSERT
  TO plantig_user, plantig_reviewer, plantig_admin
  WITH CHECK (user_id = plantig_uid() OR plantig_role() = 'plantig_admin');

CREATE POLICY access_audit_logs_select_own ON access_audit_logs FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid());

CREATE POLICY access_audit_logs_admin_all ON access_audit_logs FOR ALL
  TO plantig_admin
  USING (true)
  WITH CHECK (true);

-- ============================================================================
-- END OF MIGRATION
-- ============================================================================