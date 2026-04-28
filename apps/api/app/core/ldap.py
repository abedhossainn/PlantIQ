"""LDAP/Active Directory authentication client."""

from dataclasses import dataclass
import logging
import ssl
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LDAPUser:
    """User information from LDAP."""

    username: str
    email: str
    full_name: str
    department: Optional[str] = None


@dataclass(frozen=True)
class LDAPRuntimeConnectionConfig:
    """Resolved runtime LDAP connection settings."""

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
    source: str = "env"


class LDAPClient:
    """LDAP authentication client with mock support for development."""

    _USER_ATTRIBUTES = ["uid", "mail", "cn", "displayName", "givenName", "sn", "department", "ou"]

    # These are intentional development-only mock credentials used only
    # when LDAP_MOCK=true. They are not production secrets. # NOSONAR
    _MOCK_USERS: Dict[str, Dict] = {
        "admin": {
            "password": "admin123",  # NOSONAR — dev mock only
            "email": "admin@plantig.local",
            "full_name": "System Administrator",
            "department": "IT",
        },
        "user": {
            "password": "user123",  # NOSONAR — dev mock only
            "email": "user@plantig.local",
            "full_name": "John User",
            "department": "Operations",
        },
    }

    def __init__(self) -> None:
        """Initialise from application settings."""
        from .config import settings as _settings

        self.server_url: str = _settings.LDAP_SERVER
        self.base_dn: str = _settings.LDAP_BASE_DN
        self.bind_dn: str = _settings.LDAP_BIND_DN
        self._bind_password: str = _settings.LDAP_BIND_PASSWORD
        self.user_search_base: str = _settings.LDAP_USER_SEARCH_BASE
        self.port: int = _settings.LDAP_PORT
        self.use_ssl: bool = _settings.LDAP_USE_SSL
        self.start_tls: bool = _settings.LDAP_START_TLS
        self.verify_cert_mode: str = _settings.LDAP_VERIFY_CERT_MODE
        self.search_filter_template: str = _settings.LDAP_SEARCH_FILTER_TEMPLATE
        self.use_mock: bool = _settings.LDAP_MOCK

        if self.use_mock:
            logger.info("Using mock LDAP provider for development")
        else:
            logger.info("Using LDAP server: %s", self.server_url)

    async def authenticate(
        self,
        username: str,
        password: str,
        runtime_config: Optional[LDAPRuntimeConnectionConfig] = None,
    ) -> Optional[LDAPUser]:
        """Authenticate a user against LDAP/AD."""
        if self.use_mock:
            return self._mock_authenticate(username, password)
        if not username or not password:
            return None

        config = runtime_config or self._env_runtime_config()
        if not self._has_required_real_config(config):
            logger.error("LDAP authenticate unavailable: missing bind/search configuration")
            return None

        return self._authenticate_real(username=username, password=password, config=config)

    def _authenticate_real(
        self,
        *,
        username: str,
        password: str,
        config: LDAPRuntimeConnectionConfig,
    ) -> Optional[LDAPUser]:
        """Authenticate in real LDAP mode using provided runtime config."""

        search_base = self._get_search_base(config)
        service_conn = None
        user_conn = None
        try:
            ldap3 = self._get_ldap3_module()
            service_conn = self._bind_service_connection(ldap3, config)
            if service_conn is None:
                return None

            search_filter = self._build_exact_user_filter(ldap3, username, config.search_filter_template)
            entry = self._search_first_entry(
                service_conn=service_conn,
                search_base=search_base,
                search_filter=search_filter,
                size_limit=2,
            )
            if entry is None:
                return None

            user_dn = getattr(entry, "entry_dn", None)
            if not user_dn:
                return None

            user_conn = ldap3.Connection(
                service_conn.server,
                user=user_dn,
                password=password,
                auto_bind=False,
                raise_exceptions=False,
            )
            if not user_conn.bind():
                return None

            return self._entry_to_user(entry, fallback_username=username)
        except Exception:
            logger.exception("LDAP authentication failed for user %s", username)
            return None
        finally:
            if user_conn is not None:
                try:
                    user_conn.unbind()
                except Exception:
                    pass
            if service_conn is not None:
                try:
                    service_conn.unbind()
                except Exception:
                    pass

    async def list_users(
        self,
        search: Optional[str] = None,
        runtime_config: Optional[LDAPRuntimeConnectionConfig] = None,
    ) -> List[LDAPUser]:
        """List users available in LDAP/AD."""
        if self.use_mock:
            return self._mock_list_users(search)

        config = runtime_config or self._env_runtime_config()
        if not self._has_required_real_config(config):
            logger.error("LDAP list_users unavailable: missing bind/search configuration")
            return []

        search_base = self._get_search_base(config)
        service_conn = None
        try:
            ldap3 = self._get_ldap3_module()
            service_conn = self._bind_service_connection(ldap3, config)
            if service_conn is None:
                return []

            search_filter = self._build_list_filter(ldap3, search)
            searched = service_conn.search(
                search_base=search_base,
                search_filter=search_filter,
                attributes=self._USER_ATTRIBUTES,
            )
            if not searched or not service_conn.entries:
                return []

            users: List[LDAPUser] = []
            for entry in service_conn.entries:
                user = self._entry_to_user(entry)
                if user is not None:
                    users.append(user)

            users.sort(key=lambda user: user.username.lower())
            return users
        except Exception:
            logger.exception("LDAP list_users failed")
            return []
        finally:
            if service_conn is not None:
                try:
                    service_conn.unbind()
                except Exception:
                    pass

    def _env_runtime_config(self) -> LDAPRuntimeConnectionConfig:
        """Build fallback runtime config from environment-backed settings."""
        from urllib.parse import urlparse

        server_url = getattr(self, "server_url", "")
        parsed = urlparse(server_url)
        host = parsed.hostname or server_url
        scheme = parsed.scheme.lower() if parsed.scheme else "ldap"
        use_ssl = bool(getattr(self, "use_ssl", False)) or scheme == "ldaps"
        port = int(getattr(self, "port", 0) or parsed.port or (636 if use_ssl else 389))
        base_dn = getattr(self, "base_dn", "")
        user_search_base = getattr(self, "user_search_base", "") or base_dn
        bind_dn = getattr(self, "bind_dn", "")
        bind_password = getattr(self, "_bind_password", "")
        start_tls = bool(getattr(self, "start_tls", False))
        verify_cert_mode = getattr(self, "verify_cert_mode", "required")
        search_filter_template = getattr(
            self,
            "search_filter_template",
            "(&(objectClass=person)(uid={username}))",
        )

        return LDAPRuntimeConnectionConfig(
            host=host,
            port=port,
            base_dn=base_dn,
            user_search_base=user_search_base,
            bind_dn=bind_dn,
            bind_password=bind_password,
            use_ssl=use_ssl,
            start_tls=start_tls,
            verify_cert_mode=verify_cert_mode,
            search_filter_template=search_filter_template,
            source="env",
        )

    @staticmethod
    def _resolve_verify_mode(config: LDAPRuntimeConnectionConfig) -> int:
        mode = (config.verify_cert_mode or "required").lower()
        if mode == "required":
            return ssl.CERT_REQUIRED
        if mode == "optional":
            return ssl.CERT_OPTIONAL
        if mode == "none":
            return ssl.CERT_NONE
        return ssl.CERT_REQUIRED

    def _get_search_base(self, config: LDAPRuntimeConnectionConfig) -> str:
        return config.user_search_base or config.base_dn

    def _has_required_real_config(self, config: LDAPRuntimeConnectionConfig) -> bool:
        return bool(config.bind_dn and config.bind_password and self._get_search_base(config))

    @staticmethod
    def _get_ldap3_module():
        import ldap3

        return ldap3

    def _bind_service_connection(self, ldap3_module, config: LDAPRuntimeConnectionConfig):
        server_kwargs = {
            "host": config.host,
            "port": config.port,
            "use_ssl": config.use_ssl,
            "get_info": ldap3_module.NONE,
        }
        if hasattr(ldap3_module, "Tls"):
            server_kwargs["tls"] = ldap3_module.Tls(validate=self._resolve_verify_mode(config))

        server = ldap3_module.Server(**server_kwargs)
        connection = ldap3_module.Connection(
            server,
            user=config.bind_dn,
            password=config.bind_password,
            auto_bind=False,
            raise_exceptions=False,
        )
        if not connection.bind():
            logger.warning("LDAP service bind failed")
            return None
        if config.start_tls:
            try:
                if not connection.start_tls():
                    logger.warning("LDAP STARTTLS negotiation failed")
                    connection.unbind()
                    return None
            except Exception:
                logger.exception("LDAP STARTTLS negotiation error")
                try:
                    connection.unbind()
                except Exception:
                    pass
                return None
        return connection

    @staticmethod
    def _build_exact_user_filter(ldap3_module, username: str, template: str) -> str:
        escaped_username = ldap3_module.utils.conv.escape_filter_chars(username)
        if "{username}" in template:
            return template.replace("{username}", escaped_username)
        return f"(&(|(objectClass=inetOrgPerson)(objectClass=person))(uid={escaped_username}))"

    @staticmethod
    def _build_list_filter(ldap3_module, search: Optional[str]) -> str:
        object_filter = "(|(objectClass=inetOrgPerson)(objectClass=person))"
        if not search:
            return f"(&{object_filter}(uid=*))"

        escaped = ldap3_module.utils.conv.escape_filter_chars(search)
        return f"(&{object_filter}(|(uid=*{escaped}*)(cn=*{escaped}*)))"

    def _search_first_entry(self, service_conn, search_base: str, search_filter: str, size_limit: int = 1):
        searched = service_conn.search(
            search_base=search_base,
            search_filter=search_filter,
            attributes=self._USER_ATTRIBUTES,
            size_limit=size_limit,
        )
        if not searched or not service_conn.entries:
            return None
        return service_conn.entries[0]

    def _entry_to_user(self, entry: Any, fallback_username: str = "") -> Optional[LDAPUser]:
        username = self._entry_attr(entry, "uid") or fallback_username
        if not username:
            return None

        full_name = (
            self._entry_attr(entry, "displayName")
            or self._entry_attr(entry, "cn")
            or " ".join(
                part
                for part in [
                    self._entry_attr(entry, "givenName"),
                    self._entry_attr(entry, "sn"),
                ]
                if part
            ).strip()
            or username
        )

        return LDAPUser(
            username=username,
            email=self._entry_attr(entry, "mail") or "",
            full_name=full_name,
            department=self._entry_attr(entry, "department") or self._entry_attr(entry, "ou"),
        )

    @staticmethod
    def _entry_attr(entry: Any, attr_name: str) -> Optional[str]:
        try:
            attr = getattr(entry, attr_name)
        except Exception:
            return None

        value = getattr(attr, "value", None)
        if isinstance(value, list):
            value = value[0] if value else None
        if value is None:
            return None
        return str(value)

    def _mock_authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        user_data = self._MOCK_USERS.get(username)
        if not user_data:
            logger.warning("Mock LDAP: user not found: %s", username)
            return None

        if user_data["password"] != password:
            logger.warning("Mock LDAP: invalid password for user: %s", username)
            return None

        logger.info("Mock LDAP: authentication successful for user: %s", username)
        return LDAPUser(
            username=username,
            email=user_data["email"],
            full_name=user_data["full_name"],
            department=user_data.get("department"),
        )

    def _mock_list_users(self, search: Optional[str]) -> List[LDAPUser]:
        users = [
            LDAPUser(
                username=name,
                email=data["email"],
                full_name=data["full_name"],
                department=data.get("department"),
            )
            for name, data in self._MOCK_USERS.items()
        ]
        if search:
            needle = search.lower()
            users = [user for user in users if needle in user.username.lower() or needle in user.full_name.lower()]
        return users


ldap_client = LDAPClient()
