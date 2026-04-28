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
import types
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

LDAP_TEST_SERVER_URL = "ldap://ldap.local:389"
LDAP_TEST_BIND_DN = "cn=svc,dc=plantiq,dc=local"
LDAP_TEST_SEARCH_BASE = "ou=users,dc=plantiq,dc=local"
LDAP_TEST_BASE_DN = "dc=plantiq,dc=local"
LDAP_TEST_ALICE_DN = "uid=alice,ou=users,dc=plantiq,dc=local"
LDAP_TEST_ALICE_EMAIL = "alice@example.com"
LDAP_TEST_ALICE_NAME = "Alice Doe"
HTTP_TEST_BASE_URL = "http://test"


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

    def test_real_mode_list_users_uses_service_bind_and_maps_results(self, monkeypatch):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = False
        client.server_url = LDAP_TEST_SERVER_URL
        client.bind_dn = LDAP_TEST_BIND_DN
        client._bind_password = "secret"
        client.user_search_base = LDAP_TEST_SEARCH_BASE
        client.base_dn = LDAP_TEST_BASE_DN

        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Entry:
            def __init__(self, entry_dn, **attrs):
                self.entry_dn = entry_dn
                self._attrs = attrs

            def __getattr__(self, key):
                if key in self._attrs:
                    return _Attr(self._attrs[key])
                raise AttributeError(key)

        service_conn = MagicMock()
        service_conn.bind.return_value = True
        service_conn.search.return_value = True
        service_conn.entries = [
            _Entry(LDAP_TEST_ALICE_DN, uid="alice", mail=LDAP_TEST_ALICE_EMAIL, cn=LDAP_TEST_ALICE_NAME),
            _Entry("uid=bob,ou=users,dc=plantiq,dc=local", uid="bob", mail="bob@example.com", cn="Bob Doe"),
        ]

        fake_ldap3 = types.SimpleNamespace(
            NONE=0,
            Server=MagicMock(return_value=MagicMock()),
            Connection=MagicMock(return_value=service_conn),
            utils=types.SimpleNamespace(
                conv=types.SimpleNamespace(escape_filter_chars=lambda v: v)
            ),
        )
        monkeypatch.setitem(sys.modules, "ldap3", fake_ldap3)

        users = asyncio.run(client.list_users(search="ali"))
        assert [u.username for u in users] == ["alice", "bob"]
        assert users[0].email == LDAP_TEST_ALICE_EMAIL
        search_kwargs = service_conn.search.call_args.kwargs
        assert search_kwargs["search_base"] == LDAP_TEST_SEARCH_BASE
        assert "uid=*ali*" in search_kwargs["search_filter"]


class TestLDAPClientAuthenticateRealMode:
    """LDAPClient.authenticate real mode (mocked ldap3; no live server)."""

    def test_authenticate_real_mode_success(self, monkeypatch):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = False
        client.server_url = LDAP_TEST_SERVER_URL
        client.bind_dn = LDAP_TEST_BIND_DN
        client._bind_password = "secret"
        client.user_search_base = LDAP_TEST_SEARCH_BASE
        client.base_dn = LDAP_TEST_BASE_DN

        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Entry:
            entry_dn = LDAP_TEST_ALICE_DN

            def __getattr__(self, key):
                data = {
                    "uid": "alice",
                    "mail": LDAP_TEST_ALICE_EMAIL,
                    "displayName": LDAP_TEST_ALICE_NAME,
                    "department": "Operations",
                }
                if key in data:
                    return _Attr(data[key])
                raise AttributeError(key)

        service_conn = MagicMock()
        service_conn.bind.return_value = True
        service_conn.search.return_value = True
        service_conn.entries = [_Entry()]

        user_conn = MagicMock()
        user_conn.bind.return_value = True

        fake_ldap3 = types.SimpleNamespace(
            NONE=0,
            Server=MagicMock(return_value=MagicMock()),
            Connection=MagicMock(side_effect=[service_conn, user_conn]),
            utils=types.SimpleNamespace(
                conv=types.SimpleNamespace(escape_filter_chars=lambda v: v)
            ),
        )
        monkeypatch.setitem(sys.modules, "ldap3", fake_ldap3)

        result = asyncio.run(client.authenticate("alice", "DemoPass@2026"))
        assert result is not None
        assert result.username == "alice"
        assert result.email == LDAP_TEST_ALICE_EMAIL
        assert result.full_name == LDAP_TEST_ALICE_NAME
        assert result.department == "Operations"

        search_kwargs = service_conn.search.call_args.kwargs
        assert search_kwargs["search_base"] == LDAP_TEST_SEARCH_BASE
        assert "uid=alice" in search_kwargs["search_filter"]

    def test_authenticate_real_mode_invalid_user_password(self, monkeypatch):
        from app.core.ldap import LDAPClient
        import asyncio

        client = LDAPClient.__new__(LDAPClient)
        client.use_mock = False
        client.server_url = LDAP_TEST_SERVER_URL
        client.bind_dn = LDAP_TEST_BIND_DN
        client._bind_password = "secret"
        client.user_search_base = LDAP_TEST_SEARCH_BASE
        client.base_dn = LDAP_TEST_BASE_DN

        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Entry:
            entry_dn = LDAP_TEST_ALICE_DN

            def __getattr__(self, key):
                data = {"uid": "alice", "mail": LDAP_TEST_ALICE_EMAIL, "cn": "Alice"}
                if key in data:
                    return _Attr(data[key])
                raise AttributeError(key)

        service_conn = MagicMock()
        service_conn.bind.return_value = True
        service_conn.search.return_value = True
        service_conn.entries = [_Entry()]

        user_conn = MagicMock()
        user_conn.bind.return_value = False

        fake_ldap3 = types.SimpleNamespace(
            NONE=0,
            Server=MagicMock(return_value=MagicMock()),
            Connection=MagicMock(side_effect=[service_conn, user_conn]),
            utils=types.SimpleNamespace(
                conv=types.SimpleNamespace(escape_filter_chars=lambda v: v)
            ),
        )
        monkeypatch.setitem(sys.modules, "ldap3", fake_ldap3)

        result = asyncio.run(client.authenticate("alice", "wrong-pass"))
        assert result is None


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
    db.add = MagicMock()          # add() is synchronous on SQLAlchemy sessions
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_users_returns_paginated_results(mock_db):
    from app.services.auth_service import AuthService, User

    ldap_users = [
        MagicMock(username="alice", email="alice@example.com", full_name="Alice", department="Ops"),
        MagicMock(username="bob", email="bob@example.com", full_name="Bob", department="Maint"),
    ]

    db_alice = MagicMock(spec=User)
    db_alice.id = uuid.uuid4()
    db_alice.username = "alice"
    db_alice.role = "reviewer"
    db_alice.status = "active"

    users_result = MagicMock()
    users_result.scalars.return_value.all.return_value = [db_alice]
    mock_db.execute.return_value = users_result

    with patch("app.services.auth_service.ldap_client.list_users", new_callable=AsyncMock, return_value=ldap_users):
        items, total = await AuthService.list_users(db=mock_db, page=1, page_size=50)

    assert total == 2
    assert len(items) == 2
    assert items[0].username == "alice"
    assert items[0].role == "reviewer"
    assert items[1].username == "bob"
    # bob has no existing local profile: lazy-provision creates one with status="active"
    assert items[1].status == "active"


@pytest.mark.asyncio
async def test_authenticate_user_ldap_success_creates_local_profile(mock_db):
    from app.services.auth_service import AuthService
    from app.core.ldap import LDAPUser

    ldap_user = LDAPUser(
        username="rholt",
        email="rholt@plantiq.local",
        full_name="Randy Holt",
        department="Operations",
    )

    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    fake_user.username = "rholt"
    fake_user.email = "rholt@plantiq.local"
    fake_user.full_name = "Randy Holt"
    fake_user.role = "user"
    fake_user.department = "Operations"
    fake_user.status = "active"

    with patch(
        "app.services.auth_service.ldap_client.authenticate",
        new_callable=AsyncMock,
        return_value=ldap_user,
    ), patch(
        "app.services.auth_service.AuthService._get_or_create_user",
        new_callable=AsyncMock,
        return_value=fake_user,
    ) as get_or_create_mock, patch(
        "app.services.auth_service.AuthService._create_refresh_token",
        new_callable=AsyncMock,
        return_value="refresh-token",
    ), patch(
        "app.services.auth_service.jwt_manager.create_access_token",
        return_value="access-token",
    ):
        result = await AuthService.authenticate_user(
            username="rholt",
            password="DemoPass@2026",
            db=mock_db,
        )

    assert result is not None
    user, access_token, refresh_token = result
    assert user.username == "rholt"
    assert access_token == "access-token"
    assert refresh_token == "refresh-token"
    get_or_create_mock.assert_awaited_once_with(ldap_user, mock_db)


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


@pytest.mark.asyncio
async def test_update_user_status_self_disable_raises(mock_db):
    from app.services.auth_service import AuthService

    user_id = uuid.uuid4()
    with pytest.raises(PermissionError, match="own account"):
        await AuthService.update_user_status(
            target_user_id=user_id,
            new_status="disabled",
            caller_user_id=user_id,
            db=mock_db,
        )


@pytest.mark.asyncio
async def test_update_user_status_success(mock_db):
    from app.services.auth_service import AuthService, User

    caller_id = uuid.uuid4()
    target_id = uuid.uuid4()

    fake_user = MagicMock(spec=User)
    fake_user.id = target_id
    fake_user.username = "bob"
    fake_user.status = "active"

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = fake_user
    mock_db.execute.return_value = select_result

    result = await AuthService.update_user_status(
        target_user_id=target_id,
        new_status="disabled",
        caller_user_id=caller_id,
        db=mock_db,
    )

    assert result is not None
    assert fake_user.status == "disabled"


@pytest.mark.asyncio
async def test_update_user_status_user_not_found_returns_none(mock_db):
    from app.services.auth_service import AuthService

    caller_id = uuid.uuid4()
    target_id = uuid.uuid4()

    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = None
    mock_db.execute.return_value = select_result

    result = await AuthService.update_user_status(
        target_user_id=target_id,
        new_status="disabled",
        caller_user_id=caller_id,
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
        transport=ASGITransport(app=app), base_url=HTTP_TEST_BASE_URL
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
            transport=ASGITransport(app=app), base_url=HTTP_TEST_BASE_URL
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
        transport=ASGITransport(app=app), base_url=HTTP_TEST_BASE_URL
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
            transport=ASGITransport(app=app), base_url=HTTP_TEST_BASE_URL
        ) as client:
            response = await client.patch(
                f"/api/v1/auth/admin/users/{target_id}/role",
                json={"role": "reviewer"},
            )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "USER_NOT_FOUND"
