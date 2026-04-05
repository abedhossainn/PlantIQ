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
