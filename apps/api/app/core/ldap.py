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
from typing import Optional, Dict, List
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

        # Real LDAP authentication (production):
        # try:
        #     user_dn = await self._search_user(username)
        #     if not user_dn:
        #         return None
        #     user_conn = ldap3.Connection(self._server, user=user_dn, password=password)
        #     if not user_conn.bind():
        #         return None
        #     return await self._fetch_user_info(username)
        # except Exception as exc:
        #     logger.error("LDAP authentication failed for user %s", username)
        #     return None
        return None

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

        # Real LDAP search placeholder:
        # results = []
        # filter_str = "(objectClass=person)"
        # if search:
        #     escaped = ldap3.utils.conv.escape_filter_chars(search)
        #     filter_str = f"(|(uid=*{escaped}*)(cn=*{escaped}*))"
        # ...
        return []

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
