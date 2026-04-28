"""
Pydantic schemas for authentication requests and responses.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
from uuid import UUID


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
