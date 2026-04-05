# Backend Security Fixes - T-012 Implementation

**Date:** March 10, 2026  
**Status:** ✅ Implemented  
**Agent:** Backend Development

## Overview

This document outlines the security fixes implemented to address the 4 critical/important issues identified in the T-012 security review.

## Issues Addressed

### ✅ Critical Issue #1: DB Role Bypass (RLS)

**Issue:** Backend DB connections use `plantig_authenticator` without per-request `SET ROLE`, bypassing RLS.

**Fix Implemented:**
- Updated `backend/app/models/database.py` to set PostgreSQL role per request based on JWT claims
- Added `get_db()` function that accepts `jwt_claims` parameter
- Implements role mapping: `admin → plantig_admin`, `reviewer → plantig_reviewer`, `user → plantig_user`
- Sets `request.jwt.claims.sub` and `request.jwt.claims.role` for RLS functions
- Automatically resets role after request to prevent session pollution

**Code Changes:**
```python
# Before: Direct connection with no role switching
async with AsyncSessionLocal() as session:
    yield session

# After: Role-based access with RLS enforcement
await session.execute(text(f"SET LOCAL ROLE {db_role}"))
await session.execute(text("SET LOCAL request.jwt.claims.sub = :user_id"), {...})
await session.execute(text("SET LOCAL request.jwt.claims.role = :role"), {...})
```

### ✅ Critical Issue #2: WebSocket Authorization Missing

**Issue:** WebSocket channels validate token signature only; no ownership/role check on `document_id`/`conversation_id`.

**Fix Implemented:**
- Added `check_document_access()` function in `backend/app/api/websocket.py`
- Added `check_conversation_access()` function for conversation ownership verification
- Updated WebSocket handlers to enforce authorization before allowing connection
- Users can only subscribe to documents they have access to (uploader/reviewer/admin)
- Users can only subscribe to conversations they own

**Code Changes:**
```python
# Document access check with RLS enforcement
has_access = await check_document_access(document_id, user_id, user_role)
if not has_access:
    await websocket.close(code=403, reason="Forbidden: No access to this document")
    return

# Conversation ownership check
has_access = await check_conversation_access(conversation_id, user_id)
if not has_access:
    await websocket.close(code=403, reason="Forbidden: No access to this conversation")
    return
```

### ✅ Important Issue #1: JWT Role Mismatch

**Issue:** JWT `role` claim values (`admin/reviewer/user`) don't map to DB roles (`plantig_*`).

**Fix Implemented:**
- Added role mapping dictionary in `database.py`:
  - `admin` → `plantig_admin`
  - `reviewer` → `plantig_reviewer`
  - `user` → `plantig_user`
- Updated `verify_ws_token()` in `backend/app/core/security.py` to return both `user_id` and `role`
- All database sessions now properly map JWT roles to PostgreSQL roles

### ✅ Important Issue #2: Hardcoded Authenticator Password

**Issue:** Authenticator password hard-coded in migration/compose defaults.

**Fix Implemented:**
- **Migration File:** Updated `infra/docker/migrations/001_init_schema.sql`
  - Removed hardcoded password `'change_me_in_production'`
  - Added dynamic password creation from `app.authenticator_password` PostgreSQL setting
  - Added security warnings and notices
  
- **Environment Configuration:** Updated `.env.example`
  - Added critical security warnings for all passwords
  - Emphasized password rotation requirements
  - Added instructions to use `openssl rand -base64 32` for password generation
  
- **Database Module:** Updated `backend/app/models/database.py`
  - Removed default password from DATABASE_URL fallback
  - Added warning log when DATABASE_URL not properly configured
  - Enforces environment variable usage

**Security Best Practices Added:**
1. Passwords must be stored in Docker secrets, Kubernetes secrets, or HashiCorp Vault
2. Generate strong passwords: `openssl rand -base64 32`
3. Rotate authenticator password regularly
4. Never commit actual passwords to version control

## Files Modified

1. `backend/app/models/database.py` - Added per-request role setting, removed hardcoded password
2. `backend/app/core/security.py` - Updated JWT payload extraction, WebSocket token verification
3. `backend/app/api/websocket.py` - Added authorization checks for documents and conversations
4. `infra/docker/migrations/001_init_schema.sql` - Removed hardcoded password, added dynamic creation
5. `.env.example` - Added comprehensive security warnings and instructions

## Testing Required

Before deploying to production, validate:

1. **RLS Enforcement:**
   ```sql
   -- Test as different roles to ensure RLS works
   SET ROLE plantig_user;
   SET request.jwt.claims.sub = 'test-user-uuid';
   SELECT * FROM documents;  -- Should only see own documents
   ```

2. **WebSocket Authorization:**
   - Attempt to connect to document owned by another user → Should be rejected (403)
   - Attempt to connect to own document → Should succeed
   - Admin should have access to all documents

3. **Password Rotation:**
   ```bash
   # Generate new password
   NEW_PASS=$(openssl rand -base64 32)
   
   # Update in PostgreSQL
   psql -U postgres -c "ALTER ROLE plantig_authenticator PASSWORD '$NEW_PASS'"
   
   # Update in environment/secrets
   kubectl create secret generic db-auth --from-literal=password=$NEW_PASS
   ```

## Security Checklist

- [x] Removed all hardcoded passwords from codebase
- [x] Added per-request role enforcement for RLS
- [x] Added WebSocket authorization checks
- [x] Fixed JWT-to-PostgreSQL role mapping
- [x] Added comprehensive security documentation
- [x] Added password rotation instructions
- [ ] Test RLS policies with all role combinations
- [ ] Test WebSocket authorization with multiple users
- [ ] Rotate authenticator password in all environments
- [ ] Set up secrets management (Docker secrets/K8s/Vault)
- [ ] Document password rotation schedule (recommend: every 90 days)

## Production Deployment Notes

### Password Management

**Docker Compose:**
```yaml
secrets:
  postgres_authenticator_password:
    file: ./secrets/postgres_auth_password.txt

services:
  postgres:
    environment:
      - POSTGRES_AUTHENTICATOR_PASSWORD_FILE=/run/secrets/postgres_authenticator_password
    secrets:
      - postgres_authenticator_password
```

**Kubernetes:**
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: postgres-authenticator
type: Opaque
stringData:
  password: <base64-encoded-password>
---
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: postgres
    env:
    - name: POSTGRES_AUTHENTICATOR_PASSWORD
      valueFrom:
        secretKeyRef:
          name: postgres-authenticator
          key: password
```

### Database Migration Execution

When running migrations, set the password via environment variable:

```bash
# Set authenticator password before migration
export POSTGRES_AUTHENTICATOR_PASSWORD=$(openssl rand -base64 32)

# Run migration with password
psql -U postgres -v authenticator_password="$POSTGRES_AUTHENTICATOR_PASSWORD" \
  -f infra/docker/migrations/001_init_schema.sql

# Store password in secrets management
echo "$POSTGRES_AUTHENTICATOR_PASSWORD" | vault kv put secret/postgres/authenticator password=-
```

## References

- **Security Review:** PROJECT_STATUS.md - Backend/PostgREST Security Review (T-012)
- **Architecture:** PlantIQ_Integration_Architecture.md - JWT Claim Contract, Role Mapping
- **RLS Policies:** infra/docker/migrations/001_init_schema.sql
- **Authentication:** backend/README.md - Authentication Guide

## Next Steps

1. ✅ Update PROJECT_STATUS.md with completion status
2. ⏳ Manual testing of all 4 security fixes
3. ⏳ Integration testing with frontend
4. ⏳ Security audit before release gate G2
5. ⏳ Set up production secrets management
6. ⏳ Establish password rotation schedule
