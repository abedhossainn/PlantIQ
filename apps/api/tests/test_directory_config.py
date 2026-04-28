"""Tests for admin directory configuration backend foundation."""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings
from app.services.directory_config_service import (
    DirectoryConfig,
    DirectoryConfigEncryptionKeyMissingError,
    DirectoryConfigSecretDecryptError,
    DirectoryConfigService,
)


TEST_SECRET = "SuperSecret!"
TEST_FILTER = "(&(objectClass=person)(uid={username}))"
TEST_BASE_URL = "http://test"
TEST_BASE_DN = "dc=plantiq,dc=local"
TEST_USER_SEARCH_BASE = "ou=users,dc=plantiq,dc=local"
DB_HOST = "db-ldap.local"
MISSING_BIND_PASSWORD_MESSAGE = "encrypted bind password is missing"
TEST_CONFIG_PATCH_PATH = "app.api.auth.DirectoryConfigService.test_config"


def _set_fernet_key(monkeypatch):
    # Deterministic valid Fernet key bytes => urlsafe base64 encoded.
    monkeypatch.setattr(
        settings,
        "DIRECTORY_CONFIG_ENCRYPTION_KEY",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
        raising=False,
    )


def _noop_db_override():
    async def _inner():
        yield SimpleNamespace()

    return _inner


class TestDirectoryConfigHelpers:
    def test_encrypt_decrypt_roundtrip(self, monkeypatch):
        _set_fernet_key(monkeypatch)
        encrypted = DirectoryConfigService.encrypt_secret(TEST_SECRET)
        assert encrypted != TEST_SECRET
        decrypted = DirectoryConfigService.decrypt_secret(encrypted)
        assert decrypted == TEST_SECRET

    def test_encrypt_missing_key_controlled_error(self, monkeypatch):
        monkeypatch.setattr(settings, "DIRECTORY_CONFIG_ENCRYPTION_KEY", "", raising=False)
        with pytest.raises(DirectoryConfigEncryptionKeyMissingError):
            DirectoryConfigService.encrypt_secret("x")

    def test_redacted_response_never_contains_plain_secret(self):
        row = SimpleNamespace(
            id=uuid.uuid4(),
            host="ldap.local",
            server_url="ldap://ldap.local:389",
            port=389,
            base_dn=TEST_BASE_DN,
            user_search_base=TEST_USER_SEARCH_BASE,
            bind_dn="cn=svc,dc=plantiq,dc=local",
            bind_password_encrypted="ciphertext",
            use_ssl=False,
            start_tls=True,
            verify_cert_mode="required",
            search_filter_template=TEST_FILTER,
            is_active=False,
            updated_by=None,
            updated_at=datetime.now(UTC).replace(tzinfo=None),
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        redacted = DirectoryConfigService.redact_for_response(row)
        assert redacted is not None
        assert redacted["has_bind_password"] is True
        assert "bind_password_encrypted" not in redacted


@pytest.mark.asyncio
class TestDirectoryConfigRuntimeFallback:
    async def test_runtime_prefers_active_db_config(self, monkeypatch):
        _set_fernet_key(monkeypatch)
        DirectoryConfigService.invalidate_runtime_cache()

        row = DirectoryConfig(
            host=DB_HOST,
            server_url=f"ldap://{DB_HOST}:389",
            port=389,
            base_dn="dc=db,dc=local",
            user_search_base="ou=users,dc=db,dc=local",
            bind_dn="cn=svc,dc=db,dc=local",
            bind_password_encrypted=DirectoryConfigService.encrypt_secret("db-secret"),
            use_ssl=False,
            start_tls=False,
            verify_cert_mode="required",
            search_filter_template=TEST_FILTER,
            is_active=True,
        )
        row.id = uuid.uuid4()

        db = AsyncMock()
        result = AsyncMock()
        result.scalars.return_value.first.return_value = row
        db.execute.return_value = result

        runtime = await DirectoryConfigService.get_runtime_ldap_config(db)
        assert runtime.source == "db"
        assert runtime.host == DB_HOST
        assert runtime.bind_password == "db-secret"

    async def test_runtime_falls_back_to_env_when_no_active_db(self, monkeypatch):
        DirectoryConfigService.invalidate_runtime_cache()
        monkeypatch.setattr(settings, "LDAP_SERVER", "ldap://env-ldap.local:389", raising=False)
        monkeypatch.setattr(settings, "LDAP_BIND_DN", "cn=env,dc=plantiq,dc=local", raising=False)
        monkeypatch.setattr(settings, "LDAP_BIND_PASSWORD", "env-secret", raising=False)
        monkeypatch.setattr(settings, "LDAP_BASE_DN", TEST_BASE_DN, raising=False)
        monkeypatch.setattr(settings, "LDAP_USER_SEARCH_BASE", TEST_USER_SEARCH_BASE, raising=False)
        monkeypatch.setattr(settings, "LDAP_PORT", 389, raising=False)
        monkeypatch.setattr(settings, "LDAP_USE_SSL", False, raising=False)
        monkeypatch.setattr(settings, "LDAP_START_TLS", False, raising=False)
        monkeypatch.setattr(settings, "LDAP_VERIFY_CERT_MODE", "required", raising=False)
        monkeypatch.setattr(
            settings,
            "LDAP_SEARCH_FILTER_TEMPLATE",
            TEST_FILTER,
            raising=False,
        )

        db = AsyncMock()
        result = AsyncMock()
        result.scalars.return_value.first.return_value = None
        db.execute.return_value = result

        runtime = await DirectoryConfigService.get_runtime_ldap_config(db)
        assert runtime.source == "env"
        assert runtime.host == "env-ldap.local"
        assert runtime.bind_password == "env-secret"

    async def test_runtime_falls_back_to_env_when_active_db_missing_encrypted_bind_password(self, monkeypatch):
        DirectoryConfigService.invalidate_runtime_cache()
        monkeypatch.setattr(settings, "LDAP_SERVER", "ldap://env-ldap.local:389", raising=False)
        monkeypatch.setattr(settings, "LDAP_BIND_DN", "cn=env,dc=plantiq,dc=local", raising=False)
        monkeypatch.setattr(settings, "LDAP_BIND_PASSWORD", "env-secret", raising=False)
        monkeypatch.setattr(settings, "LDAP_BASE_DN", "dc=plantiq,dc=local", raising=False)
        monkeypatch.setattr(settings, "LDAP_USER_SEARCH_BASE", "ou=users,dc=plantiq,dc=local", raising=False)
        monkeypatch.setattr(settings, "LDAP_PORT", 389, raising=False)
        monkeypatch.setattr(settings, "LDAP_USE_SSL", False, raising=False)
        monkeypatch.setattr(settings, "LDAP_START_TLS", False, raising=False)
        monkeypatch.setattr(settings, "LDAP_VERIFY_CERT_MODE", "required", raising=False)
        monkeypatch.setattr(settings, "LDAP_SEARCH_FILTER_TEMPLATE", TEST_FILTER, raising=False)

        row = DirectoryConfig(
            host=DB_HOST,
            server_url=f"ldap://{DB_HOST}:389",
            port=389,
            base_dn="dc=db,dc=local",
            user_search_base="ou=users,dc=db,dc=local",
            bind_dn="cn=svc,dc=db,dc=local",
            bind_password_encrypted=None,
            use_ssl=False,
            start_tls=False,
            verify_cert_mode="required",
            search_filter_template=TEST_FILTER,
            is_active=True,
        )
        row.id = uuid.uuid4()

        db = AsyncMock()
        result = AsyncMock()
        result.scalars.return_value.first.return_value = row
        db.execute.return_value = result

        runtime = await DirectoryConfigService.get_runtime_ldap_config(db)
        assert runtime.source == "env"
        assert runtime.host == "env-ldap.local"
        assert runtime.bind_password == "env-secret"


@pytest.mark.asyncio
async def test_directory_config_test_config_handles_missing_encrypted_bind_password_error():
    db = AsyncMock()
    with patch(
        "app.services.directory_config_service.DirectoryConfigService.get_runtime_ldap_config",
        new_callable=AsyncMock,
        side_effect=DirectoryConfigSecretDecryptError(MISSING_BIND_PASSWORD_MESSAGE),
    ):
        success, message, source = await DirectoryConfigService.test_config(db=db, payload=None)

    assert success is False
    assert message == MISSING_BIND_PASSWORD_MESSAGE
    assert source == "db"


try:
    import httpx
    from fastapi import Depends, FastAPI, HTTPException
    from httpx import ASGITransport

    _HTTPX_AVAILABLE = True
except Exception:
    _HTTPX_AVAILABLE = False


_skip_http = pytest.mark.skipif(not _HTTPX_AVAILABLE, reason="httpx not installed")


@_skip_http
@pytest.mark.asyncio
async def test_directory_config_endpoint_denies_non_admin():
    from app.api.auth import router as auth_router
    from app.models.database import get_db
    from app.core.security import require_admin

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = _noop_db_override()

    def _deny_admin():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[require_admin] = _deny_admin

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL) as client:
        resp = await client.get("/api/v1/auth/admin/directory-config")
    assert resp.status_code == 403


@_skip_http
@pytest.mark.asyncio
async def test_directory_config_test_endpoint_success_shape():
    from app.api.auth import router as auth_router
    from app.models.database import get_db
    from app.core.security import require_admin

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = _noop_db_override()
    app.dependency_overrides[require_admin] = lambda: "admin"

    with patch(
        "app.api.auth.DirectoryConfigService.test_config",
        new_callable=AsyncMock,
        return_value=(True, "Connection test passed", "env"),
    ):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL) as client:
            resp = await client.post("/api/v1/auth/admin/directory-config/test", json={})

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["source"] in {"env", "db", "supplied"}


@_skip_http
@pytest.mark.asyncio
async def test_directory_config_activate_fails_when_test_fails():
    from app.api.auth import router as auth_router
    from app.models.database import get_db
    from app.core.security import require_admin, get_current_user_id

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = _noop_db_override()
    app.dependency_overrides[require_admin] = lambda: "admin"
    app.dependency_overrides[get_current_user_id] = lambda: uuid.uuid4()

    with patch(
        TEST_CONFIG_PATCH_PATH,
        new_callable=AsyncMock,
        return_value=(False, "Bind failed", "db"),
    ):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL) as client:
            resp = await client.post("/api/v1/auth/admin/directory-config/activate")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DIRECTORY_CONFIG_TEST_FAILED"


@_skip_http
@pytest.mark.asyncio
async def test_directory_config_activate_returns_controlled_error_for_missing_bind_password():
    from app.api.auth import router as auth_router
    from app.models.database import get_db
    from app.core.security import require_admin, get_current_user_id

    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_db] = _noop_db_override()
    app.dependency_overrides[require_admin] = lambda: "admin"
    app.dependency_overrides[get_current_user_id] = lambda: uuid.uuid4()

    with patch(
        TEST_CONFIG_PATCH_PATH,
        new_callable=AsyncMock,
        return_value=(False, MISSING_BIND_PASSWORD_MESSAGE, "db"),
    ):
        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url=TEST_BASE_URL) as client:
            resp = await client.post("/api/v1/auth/admin/directory-config/activate")

    assert resp.status_code == 400
    body = resp.json()
    assert body["detail"]["code"] == "DIRECTORY_CONFIG_TEST_FAILED"
    assert body["detail"]["message"] == MISSING_BIND_PASSWORD_MESSAGE
