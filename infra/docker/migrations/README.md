# Database Migrations

This directory contains SQL migration files for the PlantIQ database schema.

## Migration Files

| File | Description | Status |
|------|-------------|--------|
| `001_init_schema.sql` | Initial schema with tables, roles, RLS policies | ✅ Ready |
| `002_postgrest_views.sql` | PostgREST views, functions, and enhancements | ✅ Ready |
| `006_conversation_scope_persistence.sql` | Conversation workspace/doc-type scope persistence columns + view update | ✅ Ready |
| `007_conversation_pinning.sql` | Conversation pinning state + view update | ✅ Ready |
| `008_scope_governance.sql` | User system/area scope policy + denied-access audit log tables and RLS | ✅ Ready |

## Running Migrations

### Using Docker Compose

Migrations are automatically applied when the PostgreSQL container starts:

```bash
docker-compose up postgres
```

### Manual Execution

```bash
# Connect to PostgreSQL
psql -h localhost -U postgres -d plantig

# Run migrations in order
\i infra/docker/migrations/001_init_schema.sql
\i infra/docker/migrations/002_postgrest_views.sql
```

### Verify Migration

```sql
-- Check roles
SELECT rolname FROM pg_roles WHERE rolname LIKE 'plantig_%';

-- Check tables
\dt
views
\dv

-- Check functions
\df get_*

-- Check 
-- Check RLS policies
SELECT tablename, policyname FROM pg_policies WHERE tablename IN (
  'users', 'documents', 'document_sections', 'conversations', 
  'chat_messages', 'bookmarks', 'refresh_tokens'
);

-- Test RLS helper functions
SELECT plantig_uid();
SELECT plantig_role();
```

## Schema Overview

### Roles Hierarchy

```
plantig_authenticator (LOGIN role)
├── plantig_anon (no access)
├── plantig_user (chat + bookmarks)
├── plantig_reviewer (documents + sections + chat)
└── plantig_admin (full access)
```

### RLS Policy Summary

| Table | User | Reviewer | Admin |
|-------|------|----------|-------|
| users | Own record | Read all | Full access |
| documents | ❌ | Read + Update (no approve) | Full access |
| document_sections | ❌ | Read + Update | Full access |
| section_versions | ❌ | Read + Insert | Full access |
| conversations | Own conversations | Own conversations | All conversations |
| chat_messages | Own messages | Own messages | All messages |
| bookmarks | Own bookmarks | Own bookmarks | All bookmarks |
| refresh_tokens | Own tokens | Own tokens | All tokens |

### Helper Functions

- `plantig_uid()`: Returns authenticated user's UUID from JWT `sub` claim
- `plantig_role()`: Returns authenticated user's role from JWT `role` claim

## Security Notes

1. **Role Separation**: Application roles (plantig_user, plantig_reviewer, plantig_admin) have NO LOGIN privileges. Only plantig_authenticator can log in.

2. **RLS Enforcement**: Row Level Security is enabled on all tables. Policies enforce access control based on JWT claims.

3. **Password Management**: Change the default authenticator password in production:
   ```sql
   ALTER ROLE plantig_authenticator WITH PASSWORD 'secure_random_password';
   ```

4. **JWT Claims**: All RLS policies depend on `request.jwt.claims` being set by PostgREST or FastAPI middleware.

## Testing RLS Policies

```sql
-- Simulate user context
SET LOCAL request.jwt.claims = '{"sub": "550e8400-e29b-41d4-a716-446655440000", "role": "user"}';

-- Test conversation access
SELECT * FROM conversations;  -- Should only see user's conversations

-- Reset
RESET request.jwt.claims;
```

## Migration Best Practices

1. **Never modify existing migrations** - create new numbered migrations instead
2. **Test locally first** - verify migration in dev environment before production
3. **Backup before migrating** - always have a database backup
4. **Document schema changes** - update this README for each new migration
5. **Version control** - commit migrations alongside application code
