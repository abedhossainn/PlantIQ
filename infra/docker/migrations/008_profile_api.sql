-- Migration 008: Profile API support
--
-- Changes:
--   1. Add password_hash column to users for local password override
--      (used by POST /api/v1/auth/me/change-password; nullable for LDAP users
--       who have not yet set a local password)
--   2. Grant SELECT and UPDATE on users to plantig_user so regular users
--      can read and update their own profile (enforced via existing RLS policies)

-- 1. Add password_hash column
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS password_hash VARCHAR(255);

-- 2. plantig_user needs SELECT (for GET /me) and UPDATE (for PATCH /me and
--    POST /me/change-password). The existing RLS policies already restrict
--    this to the user's own row.
GRANT SELECT, UPDATE ON users TO plantig_user;
