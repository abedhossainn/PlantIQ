"""Unit tests for app.services.auth_service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.auth_service as auth_module
from app.services.auth_service import (
    AuthService,
    _hash_password,
    _verify_password,
    _utcnow_naive,
)


class _FakeScalarResult:
    def __init__(self, one=None, all_items=None):
        self._one = one
        self._all_items = all_items or []

    def scalar_one_or_none(self):
        return self._one

    def all(self):
        return self._all_items


class _FakeResult:
    def __init__(self, one=None, all_items=None):
        self._scalar = _FakeScalarResult(one=one, all_items=all_items)

    def scalar_one_or_none(self):
        return self._scalar.scalar_one_or_none()

    def scalars(self):
        return self._scalar


class _FakeExecOutcome:
    def __init__(self, rowcount=0):
        self.rowcount = rowcount


class _FakeDB:
    def __init__(self, execute_results=None):
        self._execute_results = list(execute_results or [])
        self.commits = 0
        self.flushes = 0
        self.refreshes = 0
        self.added = []

    async def execute(self, *_args, **_kwargs):
        if self._execute_results:
            return self._execute_results.pop(0)
        return _FakeResult()

    async def commit(self):
        self.commits += 1

    async def flush(self):
        self.flushes += 1

    async def refresh(self, _obj):
        self.refreshes += 1

    def add(self, obj):
        self.added.append(obj)


@dataclass
class _LDAPUser:
    username: str
    email: str
    full_name: str
    department: str | None = None


# ---------------------------------------------------------------------------
# hashing helpers
# ---------------------------------------------------------------------------


def test_hash_and_verify_password_roundtrip():
    hashed = _hash_password("secret-pass")
    assert hashed.startswith("pbkdf2:sha256:")
    assert _verify_password("secret-pass", hashed) is True


def test_verify_password_invalid_hash_returns_false():
    assert _verify_password("pw", "not:a:valid:hash") is False


def test_verify_password_wrong_password_returns_false():
    hashed = _hash_password("good")
    assert _verify_password("bad", hashed) is False


def test_utcnow_naive_returns_naive_datetime():
    dt = _utcnow_naive()
    assert isinstance(dt, datetime)
    assert dt.tzinfo is None


# ---------------------------------------------------------------------------
# simple role mapping helpers
# ---------------------------------------------------------------------------


def test_determine_role_from_username_admin():
    assert AuthService._determine_role_from_username("admin") == "admin"


def test_determine_role_from_username_user_default():
    assert AuthService._determine_role_from_username("alice") == "user"


def test_to_ldap_runtime_config_mapping():
    runtime = SimpleNamespace(
        host="ldap.local",
        port=389,
        base_dn="dc=plantiq,dc=local",
        user_search_base="ou=users,dc=plantiq,dc=local",
        bind_dn="cn=admin,dc=plantiq,dc=local",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(&(objectClass=person)(uid={username}))",
        source="db",
    )
    mapped = AuthService._to_ldap_runtime_config(runtime)
    assert mapped.host == runtime.host
    assert mapped.port == runtime.port
    assert mapped.bind_dn == runtime.bind_dn


# ---------------------------------------------------------------------------
# _get_or_create_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_user_updates_existing_by_username():
    existing = auth_module.User(
        username="alice",
        email="old@example.com",
        full_name="Old Name",
        role="user",
        department="A",
        status="active",
    )
    db = _FakeDB(execute_results=[_FakeResult(one=existing)])
    ldap_user = _LDAPUser("alice", "new@example.com", "New Name", "B")

    user = await AuthService._get_or_create_user(ldap_user, db)
    assert user is existing
    assert user.email == "new@example.com"
    assert user.full_name == "New Name"
    assert user.department == "B"


@pytest.mark.asyncio
async def test_get_or_create_user_creates_new_when_not_found():
    db = _FakeDB(execute_results=[_FakeResult(one=None), _FakeResult(one=None)])
    ldap_user = _LDAPUser("charlie", "charlie@example.com", "Charlie")

    user = await AuthService._get_or_create_user(ldap_user, db)
    assert user.username == "charlie"
    assert user.role == "user"
    assert db.added
    assert db.flushes == 1


# ---------------------------------------------------------------------------
# _create_refresh_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_refresh_token_persists_and_returns_raw_token():
    db = _FakeDB()
    token = await AuthService._create_refresh_token(uuid.uuid4(), db)
    assert isinstance(token, str)
    assert len(token) > 10
    assert db.commits == 1
    assert len(db.added) == 1


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_user_ldap_success(monkeypatch):
    db = _FakeDB()
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required",
        search_filter_template="x", source="db",
    )
    ldap_user = _LDAPUser("alice", "alice@example.com", "Alice", "Ops")
    user = auth_module.User(
        id=uuid.uuid4(),
        username="alice",
        email="alice@example.com",
        full_name="Alice",
        role="admin",
        department="Ops",
        status="active",
    )

    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=ldap_user))
    monkeypatch.setattr(AuthService, "_get_or_create_user", AsyncMock(return_value=user))
    monkeypatch.setattr(AuthService, "_create_refresh_token", AsyncMock(return_value="refresh-token"))
    monkeypatch.setattr(auth_module.jwt_manager, "create_access_token", MagicMock(return_value="access-token"))

    result = await AuthService.authenticate_user("alice", "pw", db)
    assert result is not None
    out_user, access, refresh = result
    assert out_user.username == "alice"
    assert access == "access-token"
    assert refresh == "refresh-token"
    assert db.commits == 1


@pytest.mark.asyncio
async def test_authenticate_user_local_fallback_success(monkeypatch):
    pw_hash = _hash_password("pw")
    db_user = auth_module.User(
        id=uuid.uuid4(),
        username="local",
        email="local@example.com",
        full_name="Local",
        role="user",
        department=None,
        status="active",
        password_hash=pw_hash,
    )
    db = _FakeDB(execute_results=[_FakeResult(one=db_user)])

    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required",
        search_filter_template="x", source="db",
    )

    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=None))
    monkeypatch.setattr(AuthService, "_create_refresh_token", AsyncMock(return_value="r2"))
    monkeypatch.setattr(auth_module.jwt_manager, "create_access_token", MagicMock(return_value="a2"))

    result = await AuthService.authenticate_user("local", "pw", db)
    assert result is not None
    assert result[1] == "a2"
    assert result[2] == "r2"


@pytest.mark.asyncio
async def test_authenticate_user_disabled_returns_none(monkeypatch):
    user = auth_module.User(
        id=uuid.uuid4(),
        username="u1",
        email="u1@example.com",
        full_name="U1",
        role="user",
        department=None,
        status="disabled",
    )
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required",
        search_filter_template="x", source="db",
    )
    db = _FakeDB()

    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=_LDAPUser("u1", "u1@example.com", "U1")))
    monkeypatch.setattr(AuthService, "_get_or_create_user", AsyncMock(return_value=user))

    result = await AuthService.authenticate_user("u1", "pw", db)
    assert result is None


# ---------------------------------------------------------------------------
# refresh_access_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_access_token_not_found_returns_none():
    db = _FakeDB(execute_results=[_FakeResult(one=None)])
    out = await AuthService.refresh_access_token("token", db)
    assert out is None


@pytest.mark.asyncio
async def test_refresh_access_token_expired_revokes_and_returns_none():
    token_record = auth_module.RefreshToken(
        user_id=uuid.uuid4(),
        token_hash="hash",
        expires_at=_utcnow_naive() - timedelta(seconds=1),
    )
    db = _FakeDB(execute_results=[_FakeResult(one=token_record)])

    out = await AuthService.refresh_access_token("token", db)
    assert out is None
    assert token_record.revoked_at is not None
    assert db.commits == 1


@pytest.mark.asyncio
async def test_refresh_access_token_user_disabled_returns_none():
    token_record = auth_module.RefreshToken(
        user_id=uuid.uuid4(),
        token_hash="hash",
        expires_at=_utcnow_naive() + timedelta(hours=1),
    )
    user = auth_module.User(
        id=token_record.user_id,
        username="u",
        email="u@example.com",
        full_name="U",
        role="user",
        department=None,
        status="disabled",
    )
    db = _FakeDB(execute_results=[_FakeResult(one=token_record), _FakeResult(one=user)])

    out = await AuthService.refresh_access_token("token", db)
    assert out is None
    assert db.commits == 1


@pytest.mark.asyncio
async def test_refresh_access_token_success(monkeypatch):
    token_record = auth_module.RefreshToken(
        user_id=uuid.uuid4(),
        token_hash="hash",
        expires_at=_utcnow_naive() + timedelta(hours=1),
    )
    user = auth_module.User(
        id=token_record.user_id,
        username="u",
        email="u@example.com",
        full_name="U",
        role="admin",
        department="Ops",
        status="active",
    )
    db = _FakeDB(execute_results=[_FakeResult(one=token_record), _FakeResult(one=user)])

    monkeypatch.setattr(auth_module.jwt_manager, "create_access_token", MagicMock(return_value="acc"))
    monkeypatch.setattr(AuthService, "_create_refresh_token", AsyncMock(return_value="new-refresh"))

    out = await AuthService.refresh_access_token("token", db)
    assert out is not None
    out_user, access, refresh = out
    assert out_user.username == "u"
    assert access == "acc"
    assert refresh == "new-refresh"


# ---------------------------------------------------------------------------
# revoke_refresh_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_refresh_token_true_when_rowcount_positive():
    db = _FakeDB(execute_results=[_FakeExecOutcome(rowcount=1)])
    ok = await AuthService.revoke_refresh_token("token", db)
    assert ok is True
    assert db.commits == 1


@pytest.mark.asyncio
async def test_revoke_refresh_token_false_when_not_found():
    db = _FakeDB(execute_results=[_FakeExecOutcome(rowcount=0)])
    ok = await AuthService.revoke_refresh_token("token", db)
    assert ok is False
    assert db.commits == 1


# ---------------------------------------------------------------------------
# role/status mutation guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_user_status_self_disable_raises():
    uid = uuid.uuid4()
    db = _FakeDB()
    with pytest.raises(PermissionError):
        await AuthService.update_user_status(uid, "disabled", uid, db)


@pytest.mark.asyncio
async def test_update_user_role_self_update_raises():
    uid = uuid.uuid4()
    db = _FakeDB()
    with pytest.raises(PermissionError):
        await AuthService.update_user_role(uid, "user", uid, "admin", db)


@pytest.mark.asyncio
async def test_update_user_role_assign_admin_requires_admin_role():
    db = _FakeDB()
    with pytest.raises(PermissionError):
        await AuthService.update_user_role(uuid.uuid4(), "plantig_admin", uuid.uuid4(), "plantig_user", db)


@pytest.mark.asyncio
async def test_authenticate_user_local_fallback_failure_logs_warning(monkeypatch, caplog):
    db_user = auth_module.User(
        id=uuid.uuid4(),
        username="local",
        email="local@example.com",
        full_name="Local",
        role="user",
        department=None,
        status="active",
        password_hash=_hash_password("correct"),
    )
    db = _FakeDB(execute_results=[_FakeResult(one=db_user)])
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required", search_filter_template="x", source="db",
    )
    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=None))

    with caplog.at_level("WARNING"):
        out = await AuthService.authenticate_user("local", "wrong", db)
    assert out is None
    assert "Authentication failed for user: local" in caplog.text


@pytest.mark.asyncio
async def test_get_user_by_id_found_and_missing():
    uid = uuid.uuid4()
    user = auth_module.User(
        id=uid,
        username="u",
        email="u@example.com",
        full_name="U",
        role="user",
        department=None,
        status="active",
    )
    db_found = _FakeDB(execute_results=[_FakeResult(one=user)])
    assert await AuthService.get_user_by_id(uid, db_found) is user

    db_missing = _FakeDB(execute_results=[_FakeResult(one=None)])
    assert await AuthService.get_user_by_id(uid, db_missing) is None


@pytest.mark.asyncio
async def test_update_user_profile_missing_and_success():
    uid = uuid.uuid4()
    db_missing = _FakeDB(execute_results=[_FakeResult(one=None)])
    assert await AuthService.update_user_profile(uid, {"full_name": "X"}, db_missing) is None

    user = auth_module.User(
        id=uid,
        username="u",
        email="u@example.com",
        full_name="Old",
        role="user",
        department="Ops",
        status="active",
    )
    db_ok = _FakeDB(execute_results=[_FakeResult(one=user)])
    out = await AuthService.update_user_profile(uid, {"full_name": "New", "department": "R&D"}, db_ok)
    assert out is user
    assert user.full_name == "New"
    assert user.department == "R&D"
    assert db_ok.commits == 1 and db_ok.refreshes == 1


@pytest.mark.asyncio
async def test_change_user_password_no_user_returns_false():
    db = _FakeDB(execute_results=[_FakeResult(one=None)])
    ok = await AuthService.change_user_password(uuid.uuid4(), "old", "new", db)
    assert ok is False


@pytest.mark.asyncio
async def test_change_user_password_bad_stored_hash_returns_false():
    user = auth_module.User(
        id=uuid.uuid4(),
        username="u",
        email="u@example.com",
        full_name="U",
        role="user",
        department=None,
        status="active",
        password_hash="pbkdf2:sha256:bad:hash",
    )
    db = _FakeDB(execute_results=[_FakeResult(one=user)])
    ok = await AuthService.change_user_password(user.id, "old", "new", db)
    assert ok is False


@pytest.mark.asyncio
async def test_change_user_password_ldap_fallback_fail_and_success(monkeypatch):
    user = auth_module.User(
        id=uuid.uuid4(),
        username="ldap-user",
        email="u@example.com",
        full_name="U",
        role="user",
        department=None,
        status="active",
        password_hash=None,
    )

    db_fail = _FakeDB(execute_results=[_FakeResult(one=user)])
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=None))
    ok_fail = await AuthService.change_user_password(user.id, "old", "new", db_fail)
    assert ok_fail is False

    db_ok = _FakeDB(execute_results=[_FakeResult(one=user)])
    monkeypatch.setattr(auth_module.ldap_client, "authenticate", AsyncMock(return_value=SimpleNamespace(username="ldap-user")))
    ok = await AuthService.change_user_password(user.id, "old", "new", db_ok)
    assert ok is True
    assert isinstance(user.password_hash, str) and user.password_hash.startswith("pbkdf2:sha256:")
    assert db_ok.commits == 1


@pytest.mark.asyncio
async def test_list_users_empty_and_defensive_skip(monkeypatch):
    db = _FakeDB()
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required", search_filter_template="x", source="db",
    )
    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=[]))
    items, total = await AuthService.list_users(db)
    assert items == [] and total == 0

    ldap_users = [
        SimpleNamespace(username=None, email="n@example.com", full_name="No Username", department=None),
        SimpleNamespace(username="alice", email="a@example.com", full_name="Alice", department="Ops"),
    ]
    existing = auth_module.User(
        id=uuid.uuid4(),
        username="alice",
        email="a@example.com",
        full_name="Alice",
        role="user",
        department="Ops",
        status="active",
    )
    db2 = _FakeDB(execute_results=[_FakeResult(all_items=[existing])])
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=ldap_users))
    items2, total2 = await AuthService.list_users(db2)
    assert total2 == 1
    assert items2[0].username == "alice"


@pytest.mark.asyncio
async def test_provision_ldap_users_empty_and_mixed(monkeypatch):
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required", search_filter_template="x", source="db",
    )
    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))

    db_empty = _FakeDB()
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=[]))
    out_empty = await AuthService.provision_ldap_users(db_empty)
    assert out_empty == {"provisioned": 0, "already_existed": 0}

    ldap_users = [
        SimpleNamespace(username=None, email="none@example.com", full_name="None", department=None),
        SimpleNamespace(username="exists", email="e@example.com", full_name="Exists", department="Ops"),
        SimpleNamespace(username="newuser", email="n@example.com", full_name="New User", department="R&D"),
    ]
    existing_local = auth_module.User(
        id=uuid.uuid4(),
        username="exists",
        email="e@example.com",
        full_name="Exists",
        role="user",
        department="Ops",
        status="active",
    )
    db_mixed = _FakeDB(execute_results=[_FakeResult(all_items=[existing_local])])
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=ldap_users))
    out = await AuthService.provision_ldap_users(db_mixed)
    assert out["provisioned"] == 1
    assert out["already_existed"] == 1
    assert db_mixed.commits == 1


@pytest.mark.asyncio
async def test_list_users_lazy_provisions_and_paginates(monkeypatch):
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required", search_filter_template="x", source="db",
    )
    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))

    ldap_users = [
        SimpleNamespace(username="alpha", email="a@example.com", full_name="Alpha", department="Ops"),
        SimpleNamespace(username="beta", email="b@example.com", full_name="Beta", department="R&D"),
    ]
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=ldap_users))

    existing_alpha = auth_module.User(
        id=uuid.uuid4(),
        username="alpha",
        email="a@example.com",
        full_name="Alpha",
        role="admin",
        department="Ops",
        status="active",
    )
    db = _FakeDB(execute_results=[_FakeResult(all_items=[existing_alpha])])

    items, total = await AuthService.list_users(db, page=1, page_size=1)
    assert total == 2
    assert len(items) == 1
    assert db.flushes == 1
    assert db.refreshes == 1
    assert db.commits == 1
    assert any(getattr(u, "username", None) == "beta" for u in db.added)


@pytest.mark.asyncio
async def test_provision_ldap_users_all_existing_skips_commit(monkeypatch):
    runtime = SimpleNamespace(
        host="h", port=389, base_dn="b", user_search_base="u", bind_dn="d", bind_password="p",
        use_ssl=False, start_tls=False, verify_cert_mode="required", search_filter_template="x", source="db",
    )
    monkeypatch.setattr(auth_module.DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=runtime))

    ldap_users = [
        SimpleNamespace(username="exists", email="e@example.com", full_name="Exists", department="Ops"),
    ]
    monkeypatch.setattr(auth_module.ldap_client, "list_users", AsyncMock(return_value=ldap_users))

    existing_local = auth_module.User(
        id=uuid.uuid4(),
        username="exists",
        email="e@example.com",
        full_name="Exists",
        role="user",
        department="Ops",
        status="active",
    )
    db = _FakeDB(execute_results=[_FakeResult(all_items=[existing_local])])

    out = await AuthService.provision_ldap_users(db)
    assert out == {"provisioned": 0, "already_existed": 1}
    assert db.commits == 0


@pytest.mark.asyncio
async def test_update_user_status_not_found_and_success():
    target = uuid.uuid4()
    caller = uuid.uuid4()

    db_missing = _FakeDB(execute_results=[_FakeResult(one=None)])
    missing = await AuthService.update_user_status(target, "disabled", caller, db_missing)
    assert missing is None

    user = auth_module.User(
        id=target,
        username="u",
        email="u@example.com",
        full_name="User",
        role="user",
        department=None,
        status="active",
    )
    db_ok = _FakeDB(execute_results=[_FakeResult(one=user)])
    out = await AuthService.update_user_status(target, "disabled", caller, db_ok)
    assert out is user
    assert user.status == "disabled"
    assert db_ok.commits == 1 and db_ok.refreshes == 1


@pytest.mark.asyncio
async def test_update_user_role_not_found_and_success():
    target = uuid.uuid4()
    caller = uuid.uuid4()

    db_missing = _FakeDB(execute_results=[_FakeResult(one=None)])
    missing = await AuthService.update_user_role(target, "reviewer", caller, "admin", db_missing)
    assert missing is None

    user = auth_module.User(
        id=target,
        username="u",
        email="u@example.com",
        full_name="User",
        role="user",
        department=None,
        status="active",
    )
    db_ok = _FakeDB(execute_results=[_FakeResult(one=user)])
    out = await AuthService.update_user_role(target, "reviewer", caller, "admin", db_ok)
    assert out is user
    assert user.role == "reviewer"
    assert db_ok.commits == 1 and db_ok.refreshes == 1
