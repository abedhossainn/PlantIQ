"""Focused unit tests for directory_config_service internals."""

from __future__ import annotations

import json
import types
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.services.directory_config_service import (
    DirectoryConfig,
    DirectoryConfigAudit,
    DirectoryConfigEncryptionKeyMissingError,
    DirectoryConfigError,
    DirectoryConfigSecretDecryptError,
    DirectoryConfigService,
    DirectoryConfigValidationError,
    RuntimeDirectoryConfig,
)


def _set_valid_key(monkeypatch):
    # urlsafe-base64 encoded 32-byte key
    monkeypatch.setattr(
        settings,
        "DIRECTORY_CONFIG_ENCRYPTION_KEY",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        raising=False,
    )


class _Scalars:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _Result:
    def __init__(self, value):
        self._value = value

    def scalars(self):
        return _Scalars(self._value)


@pytest.mark.asyncio
async def test_first_scalar_sync_path():
    result = _Result("x")
    out = await DirectoryConfigService._first_scalar(result)
    assert out == "x"


@pytest.mark.asyncio
async def test_first_scalar_awaitable_scalars_and_first():
    class _AwaitScalars:
        async def first(self):
            return "y"

    class _AwaitResult:
        async def scalars(self):
            return _AwaitScalars()

    out = await DirectoryConfigService._first_scalar(_AwaitResult())
    assert out == "y"


def test_utcnow_naive_and_cache_fresh_paths():
    DirectoryConfigService.invalidate_runtime_cache()
    assert DirectoryConfigService._is_cache_fresh() is False

    runtime = RuntimeDirectoryConfig(
        host="h",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="env",
    )
    DirectoryConfigService._runtime_cache_value = runtime
    DirectoryConfigService._runtime_cache_expires_at = None
    assert DirectoryConfigService._is_cache_fresh() is False
    DirectoryConfigService.invalidate_runtime_cache()


def test_safe_changed_fields_masks_secret():
    changed = DirectoryConfigService._safe_changed_fields(
        before={"bind_password_encrypted": "a", "host": "old"},
        after={"bind_password_encrypted": "b", "host": "new"},
    )
    assert changed["bind_password_encrypted"] == "[UPDATED]"
    assert changed["host"] == {"from": "old", "to": "new"}


def test_safe_changed_fields_skips_unchanged_values():
    changed = DirectoryConfigService._safe_changed_fields(before={"host": "same"}, after={"host": "same"})
    assert changed == {}


@pytest.mark.asyncio
async def test_append_audit_adds_audit_row():
    db = AsyncMock()
    db.add = MagicMock()
    await DirectoryConfigService._append_audit(
        db=db,
        directory_config_id=uuid.uuid4(),
        changed_by=uuid.uuid4(),
        change_type="update",
        change_summary="x",
        changed_fields={"a": 1},
    )
    assert db.add.called
    added = db.add.call_args.args[0]
    assert isinstance(added, DirectoryConfigAudit)


def test_get_fernet_missing_key_raises(monkeypatch):
    monkeypatch.setattr(settings, "DIRECTORY_CONFIG_ENCRYPTION_KEY", "", raising=False)
    with pytest.raises(DirectoryConfigEncryptionKeyMissingError):
        DirectoryConfigService._get_fernet()


def test_get_fernet_invalid_key_shape_raises(monkeypatch):
    monkeypatch.setattr(settings, "DIRECTORY_CONFIG_ENCRYPTION_KEY", "abcd", raising=False)
    with pytest.raises(DirectoryConfigEncryptionKeyMissingError):
        DirectoryConfigService._get_fernet()


def test_encrypt_decrypt_roundtrip(monkeypatch):
    _set_valid_key(monkeypatch)
    encrypted = DirectoryConfigService.encrypt_secret("pw")
    assert encrypted != "pw"
    assert DirectoryConfigService.decrypt_secret(encrypted) == "pw"


def test_encrypt_secret_empty_raises(monkeypatch):
    _set_valid_key(monkeypatch)
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService.encrypt_secret("")


def test_decrypt_secret_missing_ciphertext_raises(monkeypatch):
    _set_valid_key(monkeypatch)
    with pytest.raises(DirectoryConfigSecretDecryptError):
        DirectoryConfigService.decrypt_secret("")


def test_decrypt_secret_invalid_token_raises(monkeypatch):
    _set_valid_key(monkeypatch)
    with pytest.raises(DirectoryConfigSecretDecryptError):
        DirectoryConfigService.decrypt_secret("not-a-valid-token")


def test_normalize_from_server_url_ldap():
    host, port, url = DirectoryConfigService._normalize_from_server_url("ldap://ldap.local:389", use_ssl=False)
    assert host == "ldap.local"
    assert port == 389
    assert url == "ldap://ldap.local:389"


def test_normalize_from_server_url_ldaps_forces_ssl():
    host, port, url = DirectoryConfigService._normalize_from_server_url("ldaps://ldap.local", use_ssl=False)
    assert host == "ldap.local"
    assert port == 636
    assert url == "ldaps://ldap.local:636"


def test_normalize_from_server_url_invalid_scheme_raises():
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._normalize_from_server_url("http://ldap.local", use_ssl=False)


def test_normalize_from_server_url_missing_host_raises():
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._normalize_from_server_url("ldap:///", use_ssl=False)


def test_normalize_from_host_defaults_port_by_ssl():
    host, port, url = DirectoryConfigService._normalize_from_host("ldap.local", None, True)
    assert host == "ldap.local"
    assert port == 636
    assert url == "ldaps://ldap.local:636"


def test_normalize_from_host_missing_host_raises():
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._normalize_from_host("", 389, False)


def test_normalize_server_url_prefers_server_url():
    host, port, _ = DirectoryConfigService._normalize_server_url(
        host="ignored.local",
        port=123,
        server_url="ldap://real.local:777",
        use_ssl=False,
    )
    assert host == "real.local"
    assert port == 777


def test_map_verify_mode_variants():
    import ssl

    assert DirectoryConfigService._map_verify_mode("required") == ssl.CERT_REQUIRED
    assert DirectoryConfigService._map_verify_mode("optional") == ssl.CERT_OPTIONAL
    assert DirectoryConfigService._map_verify_mode("none") == ssl.CERT_NONE


def test_map_verify_mode_invalid_raises():
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._map_verify_mode("bad")


def test_validate_runtime_config_conflict_raises():
    runtime = RuntimeDirectoryConfig(
        host="h",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=True,
        start_tls=True,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="db",
    )
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._validate_runtime_config(runtime)


def test_validate_runtime_config_missing_bind_password_raises():
    runtime = RuntimeDirectoryConfig(
        host="h",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="db",
    )
    with pytest.raises(DirectoryConfigValidationError):
        DirectoryConfigService._validate_runtime_config(runtime)


def test_safe_runtime_snapshot_redacts_password():
    runtime = RuntimeDirectoryConfig(
        host="ldap.local",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="secret",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="db",
        profile_id=uuid.uuid4(),
    )
    payload = json.loads(DirectoryConfigService.safe_runtime_snapshot(runtime))
    assert payload["has_bind_password"] is True
    assert "bind_password" not in payload


@pytest.mark.asyncio
async def test_get_runtime_ldap_config_returns_cached_without_db(monkeypatch):
    runtime = RuntimeDirectoryConfig(
        host="cached.local",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="env",
    )
    DirectoryConfigService._set_runtime_cache(runtime)

    class _DB:
        async def execute(self, *args, **kwargs):
            raise AssertionError("DB should not be queried when cache is fresh")

    out = await DirectoryConfigService.get_runtime_ldap_config(_DB())
    assert out.host == "cached.local"
    DirectoryConfigService.invalidate_runtime_cache()


@pytest.mark.asyncio
async def test_get_config_row_returns_none_for_non_directory_instance():
    db = AsyncMock()
    db.execute.return_value = _Result("not-a-row")
    assert await DirectoryConfigService.get_config_row(db) is None


@pytest.mark.asyncio
async def test_get_config_row_returns_directory_instance():
    row = DirectoryConfig(
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="enc",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )
    db = AsyncMock()
    db.execute.return_value = _Result(row)
    assert await DirectoryConfigService.get_config_row(db) is row


@pytest.mark.asyncio
async def test_get_active_config_row_returns_none_for_non_directory_instance():
    db = AsyncMock()
    db.execute.return_value = _Result(123)
    assert await DirectoryConfigService.get_active_config_row(db) is None


@pytest.mark.asyncio
async def test_resolve_runtime_for_test_uses_payload_and_stored_password(monkeypatch):
    _set_valid_key(monkeypatch)
    encrypted = DirectoryConfigService.encrypt_secret("stored-secret")
    stored = DirectoryConfig(
        host="db.local",
        server_url="ldap://db.local:389",
        port=389,
        base_dn="dc=db",
        user_search_base="ou=users,dc=db",
        bind_dn="cn=svc,dc=db",
        bind_password_encrypted=encrypted,
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )

    monkeypatch.setattr(DirectoryConfigService, "get_config_row", AsyncMock(return_value=stored))

    runtime = await DirectoryConfigService._resolve_runtime_for_test(
        db=AsyncMock(),
        payload={
            "host": "supplied.local",
            "port": 1389,
            "base_dn": "dc=s",
            "user_search_base": "ou=users,dc=s",
            "bind_dn": "cn=svc,dc=s",
            "bind_password": "",
            "use_ssl": False,
            "start_tls": False,
            "verify_cert_mode": "required",
            "search_filter_template": "(uid={username})",
        },
    )
    assert runtime.source == "supplied"
    assert runtime.bind_password == "stored-secret"


@pytest.mark.asyncio
async def test_resolve_runtime_for_test_without_payload_uses_runtime_config(monkeypatch):
    expected = RuntimeDirectoryConfig(
        host="x",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="env",
    )
    monkeypatch.setattr(DirectoryConfigService, "get_runtime_ldap_config", AsyncMock(return_value=expected))
    out = await DirectoryConfigService._resolve_runtime_for_test(db=AsyncMock(), payload=None)
    assert out.host == "x"


@pytest.mark.asyncio
async def test_get_runtime_ldap_config_raises_when_active_missing_password_and_env_missing(monkeypatch):
    row = DirectoryConfig(
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )
    monkeypatch.setattr(DirectoryConfigService, "get_active_config_row", AsyncMock(return_value=row))
    monkeypatch.setattr(
        DirectoryConfigService,
        "_env_runtime_config",
        lambda: RuntimeDirectoryConfig(
            host="env",
            port=389,
            base_dn="dc=e",
            user_search_base="ou=users,dc=e",
            bind_dn="cn=svc,dc=e",
            bind_password="",
            use_ssl=False,
            start_tls=False,
            verify_cert_mode="required",
            search_filter_template="(uid={username})",
            source="env",
        ),
    )
    with pytest.raises(DirectoryConfigValidationError):
        await DirectoryConfigService.get_runtime_ldap_config(AsyncMock())


@pytest.mark.asyncio
async def test_upsert_config_create_path(monkeypatch):
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    monkeypatch.setattr(DirectoryConfigService, "get_config_row", AsyncMock(return_value=None))
    monkeypatch.setattr(DirectoryConfigService, "_normalize_server_url", lambda **_k: ("ldap.local", 389, "ldap://ldap.local:389"))
    monkeypatch.setattr(DirectoryConfigService, "encrypt_secret", lambda _p: "enc")
    monkeypatch.setattr(DirectoryConfigService, "_append_audit", AsyncMock())

    row = await DirectoryConfigService.upsert_config(
        db=db,
        payload={
            "host": "ldap.local",
            "port": 389,
            "base_dn": "dc=x",
            "user_search_base": "ou=users,dc=x",
            "bind_dn": "cn=svc,dc=x",
            "bind_password": "pw",
            "use_ssl": False,
            "start_tls": False,
            "verify_cert_mode": "required",
            "search_filter_template": "(uid={username})",
        },
        updated_by=None,
    )
    assert isinstance(row, DirectoryConfig)
    assert db.flush.called and db.commit.called and db.refresh.called


@pytest.mark.asyncio
async def test_activate_config_success_and_missing(monkeypatch):
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    row = DirectoryConfig(
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="enc",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=False,
    )
    monkeypatch.setattr(DirectoryConfigService, "get_config_row", AsyncMock(return_value=row))
    monkeypatch.setattr(DirectoryConfigService, "_append_audit", AsyncMock())
    out = await DirectoryConfigService.activate_config(db=db, activated_by=None)
    assert out.is_active is True

    monkeypatch.setattr(DirectoryConfigService, "get_config_row", AsyncMock(return_value=None))
    with pytest.raises(DirectoryConfigValidationError):
        await DirectoryConfigService.activate_config(db=db, activated_by=None)


def test_redact_for_response_none_and_fields():
    assert DirectoryConfigService.redact_for_response(None) is None
    row = DirectoryConfig(
        id=uuid.uuid4(),
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="enc",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )
    payload = DirectoryConfigService.redact_for_response(row)
    assert payload and payload["has_bind_password"] is True


@pytest.mark.parametrize(
    "field,value,msg",
    [
        ("host", "", "directory host is missing"),
        ("base_dn", "", "base_dn is required"),
        ("user_search_base", "", "user_search_base is required"),
        ("bind_dn", "", "bind_dn is required"),
    ],
)
def test_validate_runtime_config_required_fields(field, value, msg):
    runtime = RuntimeDirectoryConfig(
        host="h",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="supplied",
    )
    runtime = RuntimeDirectoryConfig(**{**runtime.__dict__, field: value})
    with pytest.raises(DirectoryConfigValidationError, match=msg):
        DirectoryConfigService._validate_runtime_config(runtime)


@pytest.mark.asyncio
async def test_test_config_handles_unexpected_exception(monkeypatch):
    monkeypatch.setattr(
        DirectoryConfigService,
        "_resolve_runtime_for_test",
        AsyncMock(side_effect=RuntimeError("boom")),
    )
    ok, msg, source = await DirectoryConfigService.test_config(db=AsyncMock(), payload=None)
    assert ok is False
    assert msg == "Directory connection test failed"
    assert source == "db"


def test_env_runtime_config_parses_server_and_ssl(monkeypatch):
    monkeypatch.setattr(settings, "LDAP_SERVER", "ldaps://ldap.env.local", raising=False)
    monkeypatch.setattr(settings, "LDAP_BIND_DN", "cn=svc,dc=env", raising=False)
    monkeypatch.setattr(settings, "LDAP_BIND_PASSWORD", "env-pw", raising=False)
    monkeypatch.setattr(settings, "LDAP_BASE_DN", "dc=env", raising=False)
    monkeypatch.setattr(settings, "LDAP_USER_SEARCH_BASE", "ou=users,dc=env", raising=False)
    monkeypatch.setattr(settings, "LDAP_PORT", 0, raising=False)
    monkeypatch.setattr(settings, "LDAP_USE_SSL", False, raising=False)
    monkeypatch.setattr(settings, "LDAP_START_TLS", False, raising=False)
    monkeypatch.setattr(settings, "LDAP_VERIFY_CERT_MODE", "required", raising=False)
    monkeypatch.setattr(settings, "LDAP_SEARCH_FILTER_TEMPLATE", "(uid={username})", raising=False)

    runtime = DirectoryConfigService._env_runtime_config()
    assert runtime.host == "ldap.env.local"
    assert runtime.use_ssl is True
    assert runtime.port == 636


def test_test_bind_and_search_success(monkeypatch):
    runtime = RuntimeDirectoryConfig(
        host="ldap.local",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="supplied",
    )

    conn = SimpleNamespace(
        bind=lambda: True,
        start_tls=lambda: True,
        search=lambda **kwargs: True,
        unbind=lambda: None,
    )

    fake_ldap3 = types.SimpleNamespace(
        NONE=0,
        Tls=lambda validate: object(),
        Server=lambda **kwargs: object(),
        Connection=lambda *args, **kwargs: conn,
    )
    monkeypatch.setitem(__import__("sys").modules, "ldap3", fake_ldap3)

    ok, msg = DirectoryConfigService._test_bind_and_search(runtime)
    assert ok is True
    assert msg == "Connection test passed"


def test_test_bind_and_search_bind_failure(monkeypatch):
    runtime = RuntimeDirectoryConfig(
        host="ldap.local",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="supplied",
    )

    conn = SimpleNamespace(
        bind=lambda: False,
        start_tls=lambda: True,
        search=lambda **kwargs: True,
        unbind=lambda: None,
    )

    fake_ldap3 = types.SimpleNamespace(
        NONE=0,
        Tls=lambda validate: object(),
        Server=lambda **kwargs: object(),
        Connection=lambda *args, **kwargs: conn,
    )
    monkeypatch.setitem(__import__("sys").modules, "ldap3", fake_ldap3)

    ok, msg = DirectoryConfigService._test_bind_and_search(runtime)
    assert ok is False
    assert msg == "Bind failed"


def test_test_bind_and_search_starttls_and_search_and_unbind_failures(monkeypatch):
    runtime = RuntimeDirectoryConfig(
        host="ldap.local",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=True,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="supplied",
    )

    conn_tls_fail = SimpleNamespace(bind=lambda: True, start_tls=lambda: False, search=lambda **kwargs: True, unbind=lambda: None)
    fake_ldap3 = types.SimpleNamespace(NONE=0, Tls=lambda validate: object(), Server=lambda **kwargs: object(), Connection=lambda *args, **kwargs: conn_tls_fail)
    monkeypatch.setitem(__import__("sys").modules, "ldap3", fake_ldap3)
    ok, msg = DirectoryConfigService._test_bind_and_search(runtime)
    assert ok is False and msg == "STARTTLS negotiation failed"

    conn_search_fail = SimpleNamespace(bind=lambda: True, start_tls=lambda: True, search=lambda **kwargs: False, unbind=lambda: (_ for _ in ()).throw(RuntimeError("x")))
    fake_ldap3_b = types.SimpleNamespace(NONE=0, Tls=lambda validate: object(), Server=lambda **kwargs: object(), Connection=lambda *args, **kwargs: conn_search_fail)
    monkeypatch.setitem(__import__("sys").modules, "ldap3", fake_ldap3_b)
    ok2, msg2 = DirectoryConfigService._test_bind_and_search(runtime)
    assert ok2 is False and msg2 == "Search failed"


@pytest.mark.asyncio
async def test_test_config_success_and_directory_error_path(monkeypatch):
    runtime = RuntimeDirectoryConfig(
        host="h",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password="pw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="supplied",
    )
    monkeypatch.setattr(DirectoryConfigService, "_resolve_runtime_for_test", AsyncMock(return_value=runtime))
    monkeypatch.setattr(DirectoryConfigService, "_test_bind_and_search", lambda _r: (True, "ok"))
    ok, msg, source = await DirectoryConfigService.test_config(db=AsyncMock(), payload={"x": 1})
    assert (ok, msg, source) == (True, "ok", "supplied")

    monkeypatch.setattr(
        DirectoryConfigService,
        "_resolve_runtime_for_test",
        AsyncMock(side_effect=DirectoryConfigValidationError("bad config")),
    )
    ok2, msg2, source2 = await DirectoryConfigService.test_config(db=AsyncMock(), payload={"x": 1})
    assert ok2 is False and "bad config" in msg2 and source2 == "supplied"


@pytest.mark.asyncio
async def test_resolve_runtime_for_test_decrypt_error_falls_back_empty(monkeypatch):
    stored = DirectoryConfig(
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="enc",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=False,
    )
    monkeypatch.setattr(DirectoryConfigService, "get_config_row", AsyncMock(return_value=stored))
    monkeypatch.setattr(DirectoryConfigService, "decrypt_secret", lambda _s: (_ for _ in ()).throw(DirectoryConfigError("x")))

    runtime = await DirectoryConfigService._resolve_runtime_for_test(
        db=AsyncMock(),
        payload={
            "host": "supplied.local",
            "port": 389,
            "base_dn": "dc=s",
            "user_search_base": "ou=users,dc=s",
            "bind_dn": "cn=svc,dc=s",
            "bind_password": "",
            "use_ssl": False,
            "start_tls": False,
            "verify_cert_mode": "required",
            "search_filter_template": "(uid={username})",
        },
    )
    assert runtime.bind_password == ""


@pytest.mark.asyncio
async def test_get_active_config_row_returns_directory_instance():
    row = DirectoryConfig(
        host="h",
        server_url="ldap://h:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="enc",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )
    db = AsyncMock()
    db.execute.return_value = _Result(row)
    assert await DirectoryConfigService.get_active_config_row(db) is row


@pytest.mark.asyncio
async def test_get_runtime_ldap_config_active_row_uses_db_runtime(monkeypatch):
    _set_valid_key(monkeypatch)
    encrypted = DirectoryConfigService.encrypt_secret("pw")
    row = DirectoryConfig(
        id=uuid.uuid4(),
        host="db.local",
        server_url="ldap://db.local:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted=encrypted,
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )
    DirectoryConfigService.invalidate_runtime_cache()
    monkeypatch.setattr(DirectoryConfigService, "get_active_config_row", AsyncMock(return_value=row))

    runtime = await DirectoryConfigService.get_runtime_ldap_config(AsyncMock())
    assert runtime.source == "db"
    assert runtime.host == "db.local"
    assert runtime.bind_password == "pw"


@pytest.mark.asyncio
async def test_get_runtime_ldap_config_falls_back_to_env_when_active_missing_secret(monkeypatch):
    row = DirectoryConfig(
        id=uuid.uuid4(),
        host="db.local",
        server_url="ldap://db.local:389",
        port=389,
        base_dn="dc=x",
        user_search_base="ou=users,dc=x",
        bind_dn="cn=svc,dc=x",
        bind_password_encrypted="  ",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        is_active=True,
    )
    env_runtime = RuntimeDirectoryConfig(
        host="env.local",
        port=389,
        base_dn="dc=e",
        user_search_base="ou=users,dc=e",
        bind_dn="cn=svc,dc=e",
        bind_password="envpw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="env",
    )

    DirectoryConfigService.invalidate_runtime_cache()
    monkeypatch.setattr(DirectoryConfigService, "get_active_config_row", AsyncMock(return_value=row))
    monkeypatch.setattr(DirectoryConfigService, "_env_runtime_config", lambda: env_runtime)

    runtime = await DirectoryConfigService.get_runtime_ldap_config(AsyncMock())
    assert runtime.source == "env"
    assert runtime.host == "env.local"


@pytest.mark.asyncio
async def test_get_runtime_ldap_config_uses_env_when_no_active_row(monkeypatch):
    env_runtime = RuntimeDirectoryConfig(
        host="env.local",
        port=389,
        base_dn="dc=e",
        user_search_base="ou=users,dc=e",
        bind_dn="cn=svc,dc=e",
        bind_password="envpw",
        use_ssl=False,
        start_tls=False,
        verify_cert_mode="required",
        search_filter_template="(uid={username})",
        source="env",
    )

    DirectoryConfigService.invalidate_runtime_cache()
    monkeypatch.setattr(DirectoryConfigService, "get_active_config_row", AsyncMock(return_value=None))
    monkeypatch.setattr(DirectoryConfigService, "_env_runtime_config", lambda: env_runtime)

    runtime = await DirectoryConfigService.get_runtime_ldap_config(AsyncMock())
    assert runtime.source == "env"
    assert runtime.host == "env.local"
