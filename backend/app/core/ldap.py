"""
LDAP/Active Directory authentication client.

For development, includes a mock LDAP provider.
For production, integrates with real LDAP/AD server.
"""
from typing import Optional, Dict
from dataclasses import dataclass
import os
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
    """
    
    def __init__(
        self,
        server_url: Optional[str] = None,
        bind_dn: Optional[str] = None,
        bind_password: Optional[str] = None,
        user_search_base: Optional[str] = None,
        use_mock: bool = False,
    ):
        """
        Initialize LDAP client.
        
        Args:
            server_url: LDAP server URL (e.g., ldap://ad.company.local)
            bind_dn: DN for initial bind (e.g., CN=svc_app,OU=Service,DC=company,DC=local)
            bind_password: Password for bind DN
            user_search_base: Base DN for user search (e.g., OU=Users,DC=company,DC=local)
            use_mock: If True, use mock LDAP for development
        """
        self.server_url = server_url or os.getenv("LDAP_SERVER_URL", "")
        self.bind_dn = bind_dn or os.getenv("LDAP_BIND_DN", "")
        self.bind_password = bind_password or os.getenv("LDAP_BIND_PASSWORD", "")
        self.user_search_base = user_search_base or os.getenv(
            "LDAP_USER_SEARCH_BASE", ""
        )
        self.use_mock = use_mock or os.getenv("USE_MOCK_LDAP", "true").lower() == "true"
        
        if self.use_mock:
            logger.info("Using mock LDAP provider for development")
        else:
            logger.info(f"Using LDAP server: {self.server_url}")
            # Initialize real LDAP connection here
            # import ldap3
            # self.conn = ldap3.Connection(...)
    
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
        
        # Real LDAP authentication
        # try:
        #     user_dn = await self._search_user(username)
        #     if not user_dn:
        #         return None
        #     
        #     # Try to bind as user
        #     user_conn = ldap3.Connection(
        #         self.server_url,
        #         user=user_dn,
        #         password=password
        #     )
        #     if not user_conn.bind():
        #         return None
        #     
        #     # Fetch user attributes
        #     return await self._fetch_user_info(username)
        # except Exception as e:
        #     logger.error(f"LDAP authentication failed: {e}")
        #     return None
        
        return None
    
    def _mock_authenticate(self, username: str, password: str) -> Optional[LDAPUser]:
        """
        Mock LDAP authentication for development.
        
        Mock users:
        - admin / admin123
        - user / user123
        """
        mock_users = {
            "admin": {
                "password": "admin123",
                "email": "admin@plantig.local",
                "full_name": "System Administrator",
                "department": "IT",
            },
            "user": {
                "password": "user123",
                "email": "user@plantig.local",
                "full_name": "John User",
                "department": "Operations",
            },
        }
        
        user_data = mock_users.get(username)
        if not user_data:
            logger.warning(f"Mock LDAP: User not found: {username}")
            return None
        
        if user_data["password"] != password:
            logger.warning(f"Mock LDAP: Invalid password for user: {username}")
            return None
        
        logger.info(f"Mock LDAP: Authentication successful for user: {username}")
        return LDAPUser(
            username=username,
            email=user_data["email"],
            full_name=user_data["full_name"],
            department=user_data.get("department"),
        )


# Global LDAP client instance
ldap_client = LDAPClient()
