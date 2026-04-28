"""
LDAP/Active Directory authentication client.

For development, includes a mock LDAP provider.
For production, integrates with real LDAP/AD server.

Configuration is read from the centralised Settings object (config.py) so that
a single env file controls both mock-mode and real-LDAP mode.  Accepted env
vars (see config.py for aliases):
  LDAP_SERVER / LDAP_SERVER_URL     — server URL
  LDAP_BIND_DN                      — service-account DN
  LDAP_BIND_PASSWORD                — service-account password  (never logged)
  LDAP_USER_SEARCH_BASE             — search base for user lookups
  LDAP_MOCK / USE_MOCK_LDAP         — set to "false" to use real LDAP
"""
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LDAPUser:
    """User information from LDAP."""
    username: str
    email: str
    full_name: str
    department: Optional[str] = None


class LDAPClient:
    """
    LDAP authentication client with mock support for development.

    All configuration is sourced from the app Settings object so that
    real-LDAP mode is actually reachable via environment variables without
    code changes.
    """

    def __init__(self) -> None:
        """
        Initialise using the application settings (config.py).

        This deferred import avoids circular imports at module load time.
        """
        from .config import settings as _settings

        self.server_url: str = _settings.LDAP_SERVER
        self.base_dn: str = _settings.LDAP_BASE_DN
        self.bind_dn: str = _settings.LDAP_BIND_DN
        # Bind password is stored in memory but never logged.
        self._bind_password: str = _settings.LDAP_BIND_PASSWORD
        self.user_search_base: str = _settings.LDAP_USER_SEARCH_BASE
        self.use_mock: bool = _settings.LDAP_MOCK

        if self.use_mock:
            logger.info("Using mock LDAP provider for development")
        else:
            logger.info("Using LDAP server: %s", self.server_url)
            # Production LDAP initialisation placeholder:
            # import ldap3
            # self._server = ldap3.Server(self.server_url)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    _USER_ATTRIBUTES = ["uid", "mail", "cn", "displayName", "givenName", "sn", "department", "ou"]

    async def authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """
        Authenticate user against LDAP/AD.

        Args:
            username: Username to authenticate
            password: User password

        Returns:
            LDAPUser if authentication succeeds, None otherwise
        """
        if self.use_mock:
            return self._mock_authenticate(username, password)
        if not username or not password:
            return None

        if not self._has_required_real_config():
            logger.error("LDAP authenticate unavailable: missing bind/search configuration")
            return None

        search_base = self._get_search_base()
        service_conn = None
        user_conn = None
        try:
            ldap3 = self._get_ldap3_module()
            service_conn = self._bind_service_connection(ldap3)
            if service_conn is None:
                return None

            search_filter = self._build_exact_user_filter(ldap3, username)
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

    async def list_users(self, search: Optional[str] = None) -> List[LDAPUser]:
        """
        List users available in LDAP/AD.

        In mock mode returns the built-in mock user set, optionally filtered
        by *search* (substring match on username or full_name).

        In real LDAP mode this would issue an LDAP search against
        ``user_search_base``.

        Args:
            search: Optional substring to filter results.

        Returns:
            List of LDAPUser objects.
        """
        if self.use_mock:
            return self._mock_list_users(search)

        if not self._has_required_real_config():
            logger.error("LDAP list_users unavailable: missing bind/search configuration")
            return []

        search_base = self._get_search_base()
        service_conn = None
        try:
            ldap3 = self._get_ldap3_module()
            service_conn = self._bind_service_connection(ldap3)
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

            users.sort(key=lambda u: u.username.lower())
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

    def _get_search_base(self) -> str:
        """Return the configured LDAP search base for user lookup."""
        return self.user_search_base or self.base_dn

    def _has_required_real_config(self) -> bool:
        """Validate minimum LDAP configuration required for real-mode operations."""
        return bool(self.bind_dn and self._bind_password and self._get_search_base())

    @staticmethod
    def _get_ldap3_module():
        """Import and return ldap3 lazily to keep mock-mode lightweight."""
        import ldap3

        return ldap3

    def _bind_service_connection(self, ldap3_module):
        """Bind and return service account connection, or None on failure."""
        server = ldap3_module.Server(self.server_url, get_info=ldap3_module.NONE)
        connection = ldap3_module.Connection(
            server,
            user=self.bind_dn,
            password=self._bind_password,
            auto_bind=False,
            raise_exceptions=False,
        )
        if not connection.bind():
            logger.warning("LDAP service bind failed")
            return None
        return connection

    @staticmethod
    def _build_exact_user_filter(ldap3_module, username: str) -> str:
        """Build a safe LDAP filter for exact uid match."""
        escaped_username = ldap3_module.utils.conv.escape_filter_chars(username)
        return f"(&(|(objectClass=inetOrgPerson)(objectClass=person))(uid={escaped_username}))"

    @staticmethod
    def _build_list_filter(ldap3_module, search: Optional[str]) -> str:
        """Build LDAP filter for user listing with optional substring search."""
        object_filter = "(|(objectClass=inetOrgPerson)(objectClass=person))"
        if not search:
            return f"(&{object_filter}(uid=*))"

        escaped = ldap3_module.utils.conv.escape_filter_chars(search)
        return f"(&{object_filter}(|(uid=*{escaped}*)(cn=*{escaped}*)))"

    def _search_first_entry(self, service_conn, search_base: str, search_filter: str, size_limit: int = 1):
        """Run an LDAP search and return first entry, or None if no match."""
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
        """Map an ldap3 entry to LDAPUser."""
        username = self._entry_attr(entry, "uid") or fallback_username
        if not username:
            return None

        full_name = (
            self._entry_attr(entry, "displayName")
            or self._entry_attr(entry, "cn")
            or " ".join(
                p
                for p in [
                    self._entry_attr(entry, "givenName"),
                    self._entry_attr(entry, "sn"),
                ]
                if p
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
        """Safely extract a string LDAP attribute value from an ldap3 entry."""
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

    # ------------------------------------------------------------------
    # Mock implementation (development only)
    # ------------------------------------------------------------------

    # These are intentional development-only mock credentials used only
    # when LDAP_MOCK=true.  They are not production secrets.  # NOSONAR
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

    def _mock_authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """Mock LDAP authentication for development."""
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
        """Return mock user list, optionally filtered by *search*."""
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
            q = search.lower()
            users = [u for u in users if q in u.username.lower() or q in u.full_name.lower()]
        return users


# Global LDAP client instance — configuration is read from Settings at import time.
ldap_client = LDAPClient()
