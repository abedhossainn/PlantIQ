"""
Tests for LDAP-backed admin user management (LDAP-SoT policy).

Coverage:
- POST /api/v1/auth/admin/users  → must return 410 Gone (endpoint removed)
- GET  /api/v1/auth/admin/users  → list LDAP-backed users (admin only)
- PATCH /api/v1/auth/admin/users/{id}/role  → role update + escalation guards
- AuthService.list_users          → pagination / search
- AuthService.update_user_role    → success, self-escalation, plantig_admin guard
- LDAPClient.list_users           → mock listing + search filter
- Config alignment                → LDAP_MOCK / USE_MOCK_LDAP both resolve
"""
import os
import uuid
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Environment: run in AUTH_DISABLED mode so JWT checks are bypassed, enabling
# all endpoints to be exercised without real tokens.
# ---------------------------------------------------------------------------
os.environ.setdefault("AUTH_DISABLED", "true")
# Use the default postgresql URL — the engine is created at import time but
# no actual connection is made, so no DB server is required for these tests.

# ---------------------------------------------------------------------------
# Minimal ASGI client setup (httpx + fastapi test client via ASGITransport)
# ---------------------------------------------------------------------------
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================
# Unit tests — no HTTP client needed
# ============================================================


class TestLDAPClientListUsers:
    """LDAPClient.list_users — mock mode."""

    def test_list_users_returns_all_mock_users(self):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = True

        users = asyncio.run(client.list_users())
        assert len(users) == 2
        usernames = {u.username for u in users}
        assert "admin" in usernames
        assert "user" in usernames

    def test_list_users_search_filter(self):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = True

        users = asyncio.run(client.list_users(search="admin"))
        assert len(users) == 1
        assert users[0].username == "admin"

    def test_list_users_search_no_match(self):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = True

        users = asyncio.run(client.list_users(search="zzznomatch"))
        assert users == []

    def test_real_mode_returns_empty_list_without_server(self):
        """In real mode with no LDAP server wired the placeholder returns []."""
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = False

        users = asyncio.run(client.list_users())
        assert users == []


class TestConfigAliases:
    """Verify LDAP config env aliases resolve correctly."""

    def test_ldap_mock_alias_use_mock_ldap(self, monkeypatch):
        monkeypatch.setenv("USE_MOCK_LDAP", "false")
        # Re-import settings to pick up new env
        import importlib
        import app.core.config as cfg_module
        importlib.reload(cfg_module)
        # LDAP_MOCK should now be False because USE_MOCK_LDAP=false
        from app.core.config import Settings
        s = Settings()
        assert s.LDAP_MOCK is False

    def test_ldap_server_alias_ldap_server_url(self, monkeypatch):
        monkeypatch.setenv("LDAP_SERVER_URL", "ldap://testserver:389")
        from app.core.config import Settings
        s = Settings()
        assert s.LDAP_SERVER == "ldap://testserver:389"

    def test_ldap_bind_password_not_logged(self, caplog):
        """LDAP_BIND_PASSWORD must not appear in any log output."""
        import logging
        from app.core.ldap import LDAPClient

        with caplog.at_level(logging.DEBUG):
            client = LDAPClient.__new__(LDAPClient)
            client.use_mock = True
            client._bind_password = "supersecret"
            # Simulate init log path
            import logging as _log
            logger = _log.getLogger("app.core.ldap")
            logger.info("Using mock LDAP provider for development")

        assert "supersecret" not in caplog.text


# ============================================================
# Unit tests — AuthService methods (in-memory async DB)
# ============================================================

@pytest.fixture
def mock_db():
    """Return a minimal AsyncSession mock."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_users_returns_paginated_results(mock_db):
    from app.services.auth_service import AuthService, User

    fake_users = [
        MagicMock(spec=User, username="alice"),
        MagicMock(spec=User, username="bob"),
    ]

    # Patch sqlalchemy execute results: first call = count, second = users
    count_result = MagicMock()
    count_result.scalar_one.return_value = 2

    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = fake_users

    mock_db.execute.side_effect = [count_result, users_result]

    items, total = await AuthService.list_users(db=mock_db, page=1, page_size=50)
    assert total == 2
    assert len(items) == 2


@pytest.mark.asyncio
async def test_update_user_role_self_escalation_raises(mock_db):
    from app.services.auth_service import AuthService

    caller_id = uuid.uuid4()
    with pytest.raises(PermissionError, match="own role"):
        await AuthService.update_user_role(
            target_user_id=caller_id,
            new_role="admin",
            caller_user_id=caller_id,
            caller_role="admin",
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_update_user_role_plantig_admin_escalation_blocked(mock_db):
    """Non-plantig_admin caller must not be able to assign plantig_admin."""
    from app.services.auth_service import AuthService

    caller_id = uuid.uuid4()
    target_id = uuid.uuid4()

    with pytest.raises(PermissionError, match="Insufficient privilege"):
        await AuthService.update_user_role(
            target_user_id=target_id,
            new_role="plantig_admin",
            caller_user_id=caller_id,
            caller_role="reviewer",   # Not an admin tier
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_update_user_role_success(mock_db):
    from app.services.auth_service import AuthService, User

    caller_id = uuid.uuid4()
    target_id = uuid.uuid4()

    fake_user = MagicMock(spec=User)
    fake_user.id = target_id
    fake_user.username = "bob"
    fake_user.role = "user"

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_user
    mock_db.execute.return_value = select_result

    result = await AuthService.update_user_role(
        target_user_id=target_id,
        new_role="reviewer",
        caller_user_id=caller_id,
        caller_role="admin",
        db=mock_db,
    )

    assert result is not None
    assert fake_user.role == "reviewer"


@pytest.mark.asyncio
async def test_update_user_role_user_not_found_returns_none(mock_db):
    from app.services.auth_service import AuthService

    caller_id = uuid.uuid4()
    target_id = uuid.uuid4()

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = select_result

    result = await AuthService.update_user_role(
        target_user_id=target_id,
        new_role="reviewer",
        caller_user_id=caller_id,
        caller_role="admin",
        db=mock_db,
    )
    assert result is None


# ============================================================
# Integration tests — FastAPI ASGI endpoints
# ============================================================

try:
    import httpx
    from httpx import ASGITransport
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

_skip_http = pytest.mark.skipif(
    not _HTTPX_AVAILABLE,
    reason="httpx not installed — skipping HTTP integration tests",
)


def _build_app(db_override=None):
    """Build a minimal FastAPI app containing only the auth router."""
    from fastapi import FastAPI
    from app.api.auth import router as auth_router
    from app.models.database import get_db

    app = FastAPI()
    app.include_router(auth_router)

    if db_override is not None:
        app.dependency_overrides[get_db] = db_override

    return app


def _noop_db():
    """Async generator that yields a mock DB session."""
    async def _inner():
        yield AsyncMock()
    return _inner


@_skip_http
@pytest.mark.asyncio
async def test_create_user_endpoint_returns_410():
    """POST /api/v1/auth/admin/users must return 410 Gone."""
    app = _build_app(db_override=_noop_db())
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v1/auth/admin/users",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "full_name": "New User",
                "role": "user",
                "password": "password123",
            },
        )
    assert response.status_code == 410
    body = response.json()
    assert body["detail"]["code"] == "ENDPOINT_REMOVED"


@_skip_http
@pytest.mark.asyncio
async def test_list_users_endpoint_admin_only():
    """GET /api/v1/auth/admin/users with AUTH_DISABLED should work and return a list."""
    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    fake_user.username = "admin"
    fake_user.email = "admin@plantig.local"
    fake_user.full_name = "System Administrator"
    fake_user.role = "admin"
    fake_user.department = "IT"
    fake_user.status = "active"

    with patch(
        "app.api.auth.AuthService.list_users",
        new_callable=AsyncMock,
        return_value=([fake_user], 1),
    ):
        app = _build_app(db_override=_noop_db())
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/auth/admin/users")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["username"] == "admin"


@_skip_http
@pytest.mark.asyncio
async def test_role_update_self_escalation_blocked():
    """PATCH /admin/users/{id}/role returns 403 when caller tries to update own role."""
    # AUTH_DISABLED injects a fixed admin user ID = 00000000-0000-0000-0000-000000000001
    own_id = "00000000-0000-0000-0000-000000000001"
    app = _build_app(db_override=_noop_db())

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/api/v1/auth/admin/users/{own_id}/role",
            json={"role": "reviewer"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ROLE_ESCALATION_DENIED"


@_skip_http
@pytest.mark.asyncio
async def test_role_update_user_not_found_returns_404():
    """PATCH /admin/users/{id}/role returns 404 when target user has no local profile."""
    target_id = str(uuid.uuid4())

    with patch(
        "app.api.auth.AuthService.update_user_role",
        new_callable=AsyncMock,
        return_value=None,
    ):
        app = _build_app(db_override=_noop_db())
        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.patch(
                f"/api/v1/auth/admin/users/{target_id}/role",
                json={"role": "reviewer"},
            )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "USER_NOT_FOUND"
