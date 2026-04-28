"""
Pydantic schemas for authentication requests and responses.
"""
from pydantic import BaseModel, Field
from pydantic import field_validator, model_validator
from typing import List, Optional, Literal
from datetime import datetime
from uuid import UUID
from urllib.parse import urlparse


class LoginRequest(BaseModel):
    """Login request with username and password."""
    username: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserInfo(BaseModel):
    """Current authenticated user information."""
    id: UUID
    username: str
    email: str
    full_name: str
    role: str
    department: Optional[str]
    scope: List[str]
    last_login: Optional[datetime]


class UpdateProfileRequest(BaseModel):
    """Request body for PATCH /api/v1/auth/me."""
    full_name: Optional[str] = Field(None, min_length=1, max_length=255)
    department: Optional[str] = Field(None, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Request body for POST /api/v1/auth/me/change-password."""
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


class RefreshTokenRequest(BaseModel):
    """Refresh token request (token comes from HttpOnly cookie)."""
    pass  # Token extracted from cookie by endpoint


class LogoutRequest(BaseModel):
    """Logout request (token comes from HttpOnly cookie)."""
    pass  # Token extracted from cookie by endpoint


# ---------------------------------------------------------------------------
# Admin — user listing (LDAP-backed identities only; read-only)
# ---------------------------------------------------------------------------

class AdminUserResponse(BaseModel):
    """Single user record returned by admin listing or role-update endpoints."""
    id: UUID
    username: str
    email: str
    full_name: str
    role: str
    department: Optional[str]
    status: str


class AdminUsersListResponse(BaseModel):
    """Paginated list of users returned by GET /api/v1/auth/admin/users."""
    items: List[AdminUserResponse]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------------------
# Admin — role update (the only writable operation allowed on LDAP identities)
# ---------------------------------------------------------------------------

_VALID_ROLES = r"^(admin|user|reviewer|plantig_admin|plantig_reviewer)$"


class AdminUpdateRoleRequest(BaseModel):
    """Request body for PATCH /api/v1/auth/admin/users/{user_id}/role."""
    role: str = Field(..., pattern=_VALID_ROLES)


_VALID_STATUSES = r"^(active|disabled)$"


class AdminUpdateStatusRequest(BaseModel):
    """Request body for PATCH /api/v1/auth/admin/users/{user_id}/status."""
    status: str = Field(..., pattern=_VALID_STATUSES)


_TLS_VERIFY_MODE = Literal["required", "optional", "none"]


class DirectoryConfigBase(BaseModel):
    """Common directory config fields for admin API."""

    host: Optional[str] = Field(None, min_length=1, max_length=255)
    server_url: Optional[str] = Field(None, min_length=1, max_length=512)
    port: Optional[int] = Field(None, ge=1, le=65535)
    base_dn: str = Field(..., min_length=1, max_length=512)
    user_search_base: str = Field(..., min_length=1, max_length=512)
    bind_dn: str = Field(..., min_length=1, max_length=512)
    use_ssl: bool = False
    start_tls: bool = False
    verify_cert_mode: _TLS_VERIFY_MODE = "required"
    search_filter_template: str = Field(
        default="(&(objectClass=person)(uid={username}))",
        min_length=1,
        max_length=512,
    )

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        host = value.strip()
        if not host:
            raise ValueError("host must not be empty")
        return host

    @field_validator("server_url")
    @classmethod
    def validate_server_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"ldap", "ldaps"}:
            raise ValueError("server_url scheme must be ldap or ldaps")
        if not parsed.hostname:
            raise ValueError("server_url must include a host")
        return value

    @field_validator("base_dn", "user_search_base", "bind_dn", "search_filter_template")
    @classmethod
    def strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be empty")
        return stripped

    @model_validator(mode="after")
    def validate_tls_and_endpoint(self):
        if self.use_ssl and self.start_tls:
            raise ValueError("use_ssl and start_tls cannot both be true")
        if self.host is None and self.server_url is None:
            raise ValueError("either host or server_url must be provided")
        return self


class DirectoryConfigUpsertRequest(DirectoryConfigBase):
    """Request body for PUT /api/v1/auth/admin/directory-config."""

    bind_password: Optional[str] = Field(None, min_length=1, max_length=512)


class DirectoryConfigTestRequest(BaseModel):
    """Request body for POST /api/v1/auth/admin/directory-config/test."""

    config: Optional[DirectoryConfigUpsertRequest] = None


class DirectoryConfigResponse(BaseModel):
    """Redacted directory config response body."""

    id: UUID
    host: str
    server_url: Optional[str]
    port: int
    base_dn: str
    user_search_base: str
    bind_dn: str
    has_bind_password: bool
    use_ssl: bool
    start_tls: bool
    verify_cert_mode: _TLS_VERIFY_MODE
    search_filter_template: str
    is_active: bool
    updated_by: Optional[UUID]
    updated_at: datetime
    created_at: datetime


class DirectoryConfigTestResponse(BaseModel):
    """Connectivity test result for directory config."""

    success: bool
    message: str
    source: Literal["supplied", "db", "env"]
