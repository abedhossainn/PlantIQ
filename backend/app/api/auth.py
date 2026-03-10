"""
Authentication API endpoints.

Endpoints:
- POST /api/v1/auth/login - Authenticate user and issue tokens
- POST /api/v1/auth/refresh - Refresh access token
- POST /api/v1/auth/logout - Revoke refresh token
- GET /api/v1/auth/me - Get current user info
"""
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging
import uuid

from ..models.database import get_db
from ..models.auth import (
    LoginRequest,
    TokenResponse,
    UserInfo,
    RefreshTokenRequest,
    LogoutRequest,
)
from ..services.auth_service import AuthService
from ..core.security import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user via LDAP and issue JWT tokens.
    
    - Validates credentials against LDAP/AD
    - Creates or updates user in database
    - Issues access token (15 min) and refresh token (8 hours)
    - Refresh token delivered as HttpOnly cookie
    
    Returns:
        TokenResponse with access token
    """
    result = await AuthService.authenticate_user(
        username=request.username,
        password=request.password,
        db=db,
    )
    
    if not result:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )
    
    user, access_token, refresh_token = result
    
    # Set refresh token as HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,  # HTTPS only in production
        samesite="strict",
        max_age=8 * 60 * 60,  # 8 hours
    )
    
    logger.info(f"User logged in: {user.username}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=15 * 60,  # 15 minutes
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Refresh access token using refresh token.
    
    - Validates refresh token from HttpOnly cookie
    - Revokes old refresh token (single-use rotation)
    - Issues new access token and new refresh token
    
    Returns:
        TokenResponse with new access token
    """
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )
    
    result = await AuthService.refresh_access_token(
        refresh_token=refresh_token,
        db=db,
    )
    
    if not result:
        # Clear invalid cookie
        response.delete_cookie("refresh_token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )
    
    user, access_token, new_refresh_token = result
    
    # Set new refresh token as HttpOnly cookie
    response.set_cookie(
        key="refresh_token",
        value=new_refresh_token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=8 * 60 * 60,  # 8 hours
    )
    
    logger.info(f"Access token refreshed for user: {user.username}")
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=15 * 60,  # 15 minutes
    )


@router.post("/logout")
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db),
):
    """
    Logout user by revoking refresh token.
    
    - Revokes refresh token in database
    - Clears refresh token cookie
    
    Returns:
        Success message
    """
    if refresh_token:
        await AuthService.revoke_refresh_token(
            refresh_token=refresh_token,
            db=db,
        )
    
    # Clear cookie
    response.delete_cookie("refresh_token")
    
    logger.info("User logged out")
    
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserInfo)
async def get_current_user(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current authenticated user information.
    
    - Extracts user ID from JWT token
    - Retrieves full user details from database
    
    Returns:
        UserInfo with user details
    """
    user = await AuthService.get_user_by_id(user_id, db)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Get user scopes
    scopes = AuthService.ROLE_SCOPES.get(user.role, [])
    
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        scope=scopes,
    )
