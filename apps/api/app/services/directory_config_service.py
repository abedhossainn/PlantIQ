"""Directory configuration service for LDAP/Active Directory runtime settings.

This module provides:
- Persistent admin-configurable directory connection profile storage
- Encryption-at-rest for bind credentials
- Safe runtime config resolution (active DB profile -> environment fallback)
- Lightweight config-change audit trail (without secret values)
"""

from __future__ import annotations

import base64
import inspect
import json
import logging
import ssl
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, select
from sqlalchemy import UUID as SQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from ..core.config import settings
from ..models.database import Base

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    """Return UTC timestamp as naive datetime for legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DirectoryConfigError(Exception):
    """Base exception for directory configuration failures."""


class DirectoryConfigEncryptionKeyMissingError(DirectoryConfigError):
    """Raised when DIRECTORY_CONFIG_ENCRYPTION_KEY is missing."""


class DirectoryConfigSecretDecryptError(DirectoryConfigError):
    """Raised when encrypted secret cannot be decrypted."""


class DirectoryConfigValidationError(DirectoryConfigError):
    """Raised when persisted directory config is invalid/incomplete."""


@dataclass(frozen=True)
class RuntimeDirectoryConfig:
    """Normalized runtime LDAP connection settings."""

    host: str
    port: int
    base_dn: str
    user_search_base: str
    bind_dn: str
    bind_password: str
    use_ssl: bool
    start_tls: bool
    verify_cert_mode: str
    search_filter_template: str
    source: str
    profile_id: Optional[uuid.UUID] = None


class DirectoryConfig(Base):
    """Persisted LDAP/AD connection profile (single active profile in v1)."""

    __tablename__ = "directory_configs"

    id: Mapped[uuid.UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    server_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    base_dn: Mapped[str] = mapped_column(String(512), nullable=False)
    user_search_base: Mapped[str] = mapped_column(String(512), nullable=False)
    bind_dn: Mapped[str] = mapped_column(String(512), nullable=False)
    bind_password_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verify_cert_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="required")
    search_filter_template: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        default="(&(objectClass=person)(uid={username}))",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(SQLUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)


class DirectoryConfigAudit(Base):
    """Lightweight audit trail for directory configuration changes."""

    __tablename__ = "directory_config_audits"

    id: Mapped[uuid.UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    directory_config_id: Mapped[Optional[uuid.UUID]] = mapped_column(SQLUUID(as_uuid=True), nullable=True)
    changed_by: Mapped[Optional[uuid.UUID]] = mapped_column(SQLUUID(as_uuid=True), nullable=True)
    change_type: Mapped[str] = mapped_column(String(64), nullable=False)
    change_summary: Mapped[str] = mapped_column(Text, nullable=False)
    changed_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)


class DirectoryConfigService:
    """Business logic for admin-managed directory configuration."""

    _RUNTIME_CACHE_TTL_SECONDS = 30
    _runtime_cache_value: Optional[RuntimeDirectoryConfig] = None
    _runtime_cache_expires_at: Optional[datetime] = None

    @staticmethod
    def invalidate_runtime_cache() -> None:
        """Invalidate runtime LDAP configuration cache."""
        DirectoryConfigService._runtime_cache_value = None
        DirectoryConfigService._runtime_cache_expires_at = None

    @staticmethod
    def _is_cache_fresh() -> bool:
        if DirectoryConfigService._runtime_cache_value is None:
            return False
        if DirectoryConfigService._runtime_cache_expires_at is None:
            return False
        return datetime.now(timezone.utc) < DirectoryConfigService._runtime_cache_expires_at

    @staticmethod
    def _set_runtime_cache(value: RuntimeDirectoryConfig) -> None:
        DirectoryConfigService._runtime_cache_value = value
        DirectoryConfigService._runtime_cache_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=DirectoryConfigService._RUNTIME_CACHE_TTL_SECONDS
        )

    @staticmethod
    def _safe_changed_fields(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Compute changed fields without including sensitive values."""
        changed: dict[str, Any] = {}
        keys = sorted(set(before.keys()) | set(after.keys()))
        for key in keys:
            if before.get(key) == after.get(key):
                continue
            if key == "bind_password_encrypted":
                changed[key] = "[UPDATED]"
            else:
                changed[key] = {"from": before.get(key), "to": after.get(key)}
        return changed

    @staticmethod
    async def _append_audit(
        *,
        db: AsyncSession,
        directory_config_id: Optional[uuid.UUID],
        changed_by: Optional[uuid.UUID],
        change_type: str,
        change_summary: str,
        changed_fields: dict[str, Any],
    ) -> None:
        db.add(
            DirectoryConfigAudit(
                directory_config_id=directory_config_id,
                changed_by=changed_by,
                change_type=change_type,
                change_summary=change_summary,
                changed_fields=changed_fields,
            )
        )

    @staticmethod
    def _get_fernet() -> Fernet:
        key = settings.DIRECTORY_CONFIG_ENCRYPTION_KEY.strip()
        if not key:
            raise DirectoryConfigEncryptionKeyMissingError(
                "DIRECTORY_CONFIG_ENCRYPTION_KEY is required for directory secret encryption"
            )
        try:
            # Validate key shape: URL-safe base64-encoded 32-byte key.
            decoded = base64.urlsafe_b64decode(key.encode("utf-8"))
            if len(decoded) != 32:
                raise ValueError("Invalid Fernet key length")
        except Exception as exc:
            raise DirectoryConfigEncryptionKeyMissingError(
                "DIRECTORY_CONFIG_ENCRYPTION_KEY is invalid (must be urlsafe-base64 32-byte key)"
            ) from exc
        return Fernet(key.encode("utf-8"))

    @staticmethod
    def encrypt_secret(plaintext: str) -> str:
        """Encrypt bind password for at-rest storage."""
        if not plaintext:
            raise DirectoryConfigValidationError("bind password cannot be empty")
        token = DirectoryConfigService._get_fernet().encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    @staticmethod
    def decrypt_secret(ciphertext: str) -> str:
        """Decrypt persisted bind password."""
        if not ciphertext:
            raise DirectoryConfigSecretDecryptError("encrypted bind password is missing")
        try:
            plaintext = DirectoryConfigService._get_fernet().decrypt(ciphertext.encode("utf-8"))
            return plaintext.decode("utf-8")
        except InvalidToken as exc:
            raise DirectoryConfigSecretDecryptError("directory bind password decryption failed") from exc

    @staticmethod
    def _normalize_from_server_url(server_url: str, use_ssl: bool) -> tuple[str, int, str]:
        parsed = urlparse(server_url)
        if parsed.scheme not in {"ldap", "ldaps"}:
            raise DirectoryConfigValidationError("server_url scheme must be ldap or ldaps")
        resolved_host = parsed.hostname or ""
        if not resolved_host:
            raise DirectoryConfigValidationError("server_url must include a host")
        default_port = 636 if parsed.scheme == "ldaps" else 389
        resolved_port = parsed.port or default_port
        resolved_use_ssl = parsed.scheme == "ldaps" or use_ssl
        normalized_url = f"{'ldaps' if resolved_use_ssl else 'ldap'}://{resolved_host}:{resolved_port}"
        return resolved_host, resolved_port, normalized_url

    @staticmethod
    def _normalize_from_host(host: Optional[str], port: Optional[int], use_ssl: bool) -> tuple[str, int, str]:
        resolved_host = (host or "").strip()
        if not resolved_host:
            raise DirectoryConfigValidationError("host is required when server_url is not provided")

        resolved_port = int(port or (636 if use_ssl else 389))
        scheme = "ldaps" if use_ssl else "ldap"
        normalized_url = f"{scheme}://{resolved_host}:{resolved_port}"
        return resolved_host, resolved_port, normalized_url

    @staticmethod
    def _normalize_server_url(
        *,
        host: Optional[str],
        port: Optional[int],
        server_url: Optional[str],
        use_ssl: bool,
    ) -> tuple[str, int, str]:
        """Normalize host/port/url inputs to a consistent runtime tuple."""
        if server_url:
            return DirectoryConfigService._normalize_from_server_url(server_url, use_ssl)
        return DirectoryConfigService._normalize_from_host(host, port, use_ssl)

    @staticmethod
    async def _first_scalar(result: Any) -> Any:
        """Extract first scalar from SQLAlchemy result with AsyncMock-safe handling."""
        scalars = result.scalars()
        if inspect.isawaitable(scalars):
            scalars = await scalars
        first_value = scalars.first()
        if inspect.isawaitable(first_value):
            first_value = await first_value
        return first_value

    @staticmethod
    async def get_config_row(db: AsyncSession) -> Optional[DirectoryConfig]:
        """Return latest persisted directory config row."""
        result = await db.execute(select(DirectoryConfig).order_by(DirectoryConfig.updated_at.desc()))
        row = await DirectoryConfigService._first_scalar(result)
        if isinstance(row, DirectoryConfig):
            return row
        return None

    @staticmethod
    async def get_active_config_row(db: AsyncSession) -> Optional[DirectoryConfig]:
        """Return active directory config row, if any."""
        result = await db.execute(
            select(DirectoryConfig)
            .where(DirectoryConfig.is_active.is_(True))
            .order_by(DirectoryConfig.updated_at.desc())
        )
        row = await DirectoryConfigService._first_scalar(result)
        if isinstance(row, DirectoryConfig):
            return row
        return None

    @staticmethod
    def _env_runtime_config() -> RuntimeDirectoryConfig:
        """Build runtime configuration from environment settings."""
        parsed = urlparse(settings.LDAP_SERVER)
        host = parsed.hostname or settings.LDAP_SERVER
        scheme = parsed.scheme.lower() if parsed.scheme else "ldap"
        use_ssl = settings.LDAP_USE_SSL or scheme == "ldaps"
        port = settings.LDAP_PORT or parsed.port or (636 if use_ssl else 389)

        return RuntimeDirectoryConfig(
            host=host,
            port=port,
            base_dn=settings.LDAP_BASE_DN,
            user_search_base=settings.LDAP_USER_SEARCH_BASE or settings.LDAP_BASE_DN,
            bind_dn=settings.LDAP_BIND_DN,
            bind_password=settings.LDAP_BIND_PASSWORD,
            use_ssl=use_ssl,
            start_tls=settings.LDAP_START_TLS,
            verify_cert_mode=settings.LDAP_VERIFY_CERT_MODE,
            search_filter_template=settings.LDAP_SEARCH_FILTER_TEMPLATE,
            source="env",
            profile_id=None,
        )

    @staticmethod
    def _row_to_runtime(row: DirectoryConfig) -> RuntimeDirectoryConfig:
        bind_password = DirectoryConfigService.decrypt_secret(row.bind_password_encrypted or "")
        return RuntimeDirectoryConfig(
            host=row.host,
            port=row.port,
            base_dn=row.base_dn,
            user_search_base=row.user_search_base,
            bind_dn=row.bind_dn,
            bind_password=bind_password,
            use_ssl=row.use_ssl,
            start_tls=row.start_tls,
            verify_cert_mode=row.verify_cert_mode,
            search_filter_template=row.search_filter_template,
            source="db",
            profile_id=row.id,
        )

    @staticmethod
    async def get_runtime_ldap_config(db: AsyncSession) -> RuntimeDirectoryConfig:
        """Resolve effective runtime LDAP config with cache + fallback.

        Order: active DB profile -> environment settings.
        """
        if DirectoryConfigService._is_cache_fresh():
            cached = DirectoryConfigService._runtime_cache_value
            if cached is not None:
                return cached

        row = await DirectoryConfigService.get_active_config_row(db)
        if row is not None:
            if not (row.bind_password_encrypted or "").strip():
                env_runtime = DirectoryConfigService._env_runtime_config()
                if env_runtime.bind_password:
                    logger.warning(
                        "Active directory profile %s missing encrypted bind password; falling back to env runtime config",
                        row.id,
                    )
                    DirectoryConfigService._set_runtime_cache(env_runtime)
                    return env_runtime
                raise DirectoryConfigValidationError(
                    "active directory profile is missing encrypted bind password and env LDAP_BIND_PASSWORD is not set"
                )
            runtime = DirectoryConfigService._row_to_runtime(row)
            DirectoryConfigService._set_runtime_cache(runtime)
            return runtime

        env_runtime = DirectoryConfigService._env_runtime_config()
        DirectoryConfigService._set_runtime_cache(env_runtime)
        return env_runtime

    @staticmethod
    async def upsert_config(
        *,
        db: AsyncSession,
        payload: dict[str, Any],
        updated_by: Optional[uuid.UUID],
    ) -> DirectoryConfig:
        """Create or update the single v1 persisted directory config."""
        row = await DirectoryConfigService.get_config_row(db)
        creating = row is None
        if row is None:
            row = DirectoryConfig()
            db.add(row)

        before = {
            "host": row.host,
            "server_url": row.server_url,
            "port": row.port,
            "base_dn": row.base_dn,
            "user_search_base": row.user_search_base,
            "bind_dn": row.bind_dn,
            "bind_password_encrypted": row.bind_password_encrypted,
            "use_ssl": row.use_ssl,
            "start_tls": row.start_tls,
            "verify_cert_mode": row.verify_cert_mode,
            "search_filter_template": row.search_filter_template,
            "is_active": row.is_active,
        }

        host, port, normalized_url = DirectoryConfigService._normalize_server_url(
            host=payload.get("host"),
            port=payload.get("port"),
            server_url=payload.get("server_url"),
            use_ssl=bool(payload.get("use_ssl", False)),
        )
        row.host = host
        row.port = port
        row.server_url = normalized_url
        row.base_dn = payload["base_dn"].strip()
        row.user_search_base = payload["user_search_base"].strip()
        row.bind_dn = payload["bind_dn"].strip()
        row.use_ssl = bool(payload.get("use_ssl", False))
        row.start_tls = bool(payload.get("start_tls", False))
        row.verify_cert_mode = payload["verify_cert_mode"]
        row.search_filter_template = payload["search_filter_template"].strip()
        row.updated_by = updated_by
        row.updated_at = _utcnow_naive()

        bind_password = payload.get("bind_password")
        if bind_password:
            row.bind_password_encrypted = DirectoryConfigService.encrypt_secret(bind_password)

        after = {
            "host": row.host,
            "server_url": row.server_url,
            "port": row.port,
            "base_dn": row.base_dn,
            "user_search_base": row.user_search_base,
            "bind_dn": row.bind_dn,
            "bind_password_encrypted": row.bind_password_encrypted,
            "use_ssl": row.use_ssl,
            "start_tls": row.start_tls,
            "verify_cert_mode": row.verify_cert_mode,
            "search_filter_template": row.search_filter_template,
            "is_active": row.is_active,
        }

        changed_fields = DirectoryConfigService._safe_changed_fields(before=before, after=after)

        # Ensure PK/defaults are materialized after required fields are set.
        # Flushing earlier can violate NOT NULL constraints on first save.
        await db.flush()

        await DirectoryConfigService._append_audit(
            db=db,
            directory_config_id=row.id,
            changed_by=updated_by,
            change_type="create" if creating else "update",
            change_summary="Directory configuration upserted",
            changed_fields=changed_fields,
        )

        await db.commit()
        await db.refresh(row)
        DirectoryConfigService.invalidate_runtime_cache()
        return row

    @staticmethod
    async def activate_config(*, db: AsyncSession, activated_by: Optional[uuid.UUID]) -> DirectoryConfig:
        """Mark persisted directory config active."""
        row = await DirectoryConfigService.get_config_row(db)
        if row is None:
            raise DirectoryConfigValidationError("directory configuration is not set")

        row.is_active = True
        row.updated_by = activated_by
        row.updated_at = _utcnow_naive()
        await DirectoryConfigService._append_audit(
            db=db,
            directory_config_id=row.id,
            changed_by=activated_by,
            change_type="activate",
            change_summary="Directory configuration activated",
            changed_fields={"is_active": {"from": False, "to": True}},
        )
        await db.commit()
        await db.refresh(row)
        DirectoryConfigService.invalidate_runtime_cache()
        return row

    @staticmethod
    def redact_for_response(row: Optional[DirectoryConfig]) -> Optional[dict[str, Any]]:
        """Return API-safe redacted shape for config responses."""
        if row is None:
            return None
        return {
            "id": row.id,
            "host": row.host,
            "server_url": row.server_url,
            "port": row.port,
            "base_dn": row.base_dn,
            "user_search_base": row.user_search_base,
            "bind_dn": row.bind_dn,
            "has_bind_password": bool(row.bind_password_encrypted),
            "use_ssl": row.use_ssl,
            "start_tls": row.start_tls,
            "verify_cert_mode": row.verify_cert_mode,
            "search_filter_template": row.search_filter_template,
            "is_active": row.is_active,
            "updated_by": row.updated_by,
            "updated_at": row.updated_at,
            "created_at": row.created_at,
        }

    @staticmethod
    def _validate_runtime_config(runtime: RuntimeDirectoryConfig) -> None:
        if not runtime.host:
            raise DirectoryConfigValidationError("directory host is missing")
        if not runtime.base_dn:
            raise DirectoryConfigValidationError("base_dn is required")
        if not runtime.user_search_base:
            raise DirectoryConfigValidationError("user_search_base is required")
        if not runtime.bind_dn:
            raise DirectoryConfigValidationError("bind_dn is required")
        if not runtime.bind_password:
            raise DirectoryConfigValidationError("bind password is required")
        if runtime.start_tls and runtime.use_ssl:
            raise DirectoryConfigValidationError("use_ssl and start_tls cannot both be true")

    @staticmethod
    def _map_verify_mode(verify_cert_mode: str) -> int:
        mode = verify_cert_mode.lower()
        if mode == "required":
            return ssl.CERT_REQUIRED
        if mode == "optional":
            return ssl.CERT_OPTIONAL
        if mode == "none":
            return ssl.CERT_NONE
        raise DirectoryConfigValidationError("verify_cert_mode must be one of: required, optional, none")

    @staticmethod
    def _test_bind_and_search(runtime: RuntimeDirectoryConfig) -> tuple[bool, str]:
        """Perform bind + lightweight search to validate directory connectivity."""
        DirectoryConfigService._validate_runtime_config(runtime)
        import ldap3

        tls = ldap3.Tls(validate=DirectoryConfigService._map_verify_mode(runtime.verify_cert_mode))
        server = ldap3.Server(
            host=runtime.host,
            port=runtime.port,
            use_ssl=runtime.use_ssl,
            get_info=ldap3.NONE,
            tls=tls,
        )
        conn = ldap3.Connection(
            server,
            user=runtime.bind_dn,
            password=runtime.bind_password,
            auto_bind=False,
            raise_exceptions=False,
        )
        try:
            if not conn.bind():
                return False, "Bind failed"
            if runtime.start_tls and not conn.start_tls():
                return False, "STARTTLS negotiation failed"
            search_filter = runtime.search_filter_template.replace("{username}", "*")
            ok = conn.search(
                search_base=runtime.user_search_base,
                search_filter=search_filter,
                attributes=["uid"],
                size_limit=1,
            )
            if not ok:
                return False, "Search failed"
            return True, "Connection test passed"
        finally:
            try:
                conn.unbind()
            except Exception:
                pass

    @staticmethod
    async def test_config(
        *,
        db: AsyncSession,
        payload: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, str, str]:
        """Test supplied config (if provided) or stored effective config.

        Returns tuple: (success, message, source)
        """
        runtime: Optional[RuntimeDirectoryConfig] = None
        default_source = "supplied" if payload else "db"
        try:
            runtime = await DirectoryConfigService._resolve_runtime_for_test(db=db, payload=payload)
            success, message = DirectoryConfigService._test_bind_and_search(runtime)
            return success, message, runtime.source
        except DirectoryConfigError as exc:
            return False, str(exc), runtime.source if runtime is not None else default_source
        except Exception:
            logger.exception("Directory connection test failed")
            return False, "Directory connection test failed", runtime.source if runtime is not None else default_source

    @staticmethod
    async def _resolve_runtime_for_test(
        *,
        db: AsyncSession,
        payload: Optional[dict[str, Any]] = None,
    ) -> RuntimeDirectoryConfig:
        """Resolve runtime config for connection tests."""
        if payload:
            stored_row = await DirectoryConfigService.get_config_row(db)
            stored_bind_password = ""
            if stored_row and stored_row.bind_password_encrypted:
                try:
                    stored_bind_password = DirectoryConfigService.decrypt_secret(stored_row.bind_password_encrypted)
                except DirectoryConfigError:
                    stored_bind_password = ""

            host, port, _ = DirectoryConfigService._normalize_server_url(
                host=payload.get("host"),
                port=payload.get("port"),
                server_url=payload.get("server_url"),
                use_ssl=bool(payload.get("use_ssl", False)),
            )
            runtime = RuntimeDirectoryConfig(
                host=host,
                port=port,
                base_dn=payload["base_dn"].strip(),
                user_search_base=payload["user_search_base"].strip(),
                bind_dn=payload["bind_dn"].strip(),
                bind_password=payload.get("bind_password") or stored_bind_password,
                use_ssl=bool(payload.get("use_ssl", False)),
                start_tls=bool(payload.get("start_tls", False)),
                verify_cert_mode=payload["verify_cert_mode"],
                search_filter_template=payload["search_filter_template"].strip(),
                source="supplied",
            )
            return runtime
        return await DirectoryConfigService.get_runtime_ldap_config(db)

    @staticmethod
    def safe_runtime_snapshot(runtime: RuntimeDirectoryConfig) -> str:
        """Structured snapshot for diagnostics without exposing secret values."""
        payload = {
            "host": runtime.host,
            "port": runtime.port,
            "base_dn": runtime.base_dn,
            "user_search_base": runtime.user_search_base,
            "bind_dn": runtime.bind_dn,
            "use_ssl": runtime.use_ssl,
            "start_tls": runtime.start_tls,
            "verify_cert_mode": runtime.verify_cert_mode,
            "search_filter_template": runtime.search_filter_template,
            "source": runtime.source,
            "profile_id": str(runtime.profile_id) if runtime.profile_id else None,
            "has_bind_password": bool(runtime.bind_password),
        }
        return json.dumps(payload, sort_keys=True)