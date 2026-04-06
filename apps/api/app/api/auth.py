"""
Authentication API endpoints.

Endpoints:
- POST /api/v1/auth/login - Authenticate user and issue tokens
- POST /api/v1/auth/refresh - Refresh access token
- POST /api/v1/auth/logout - Revoke refresh token
- GET /api/v1/auth/me - Get current user info
- PATCH /api/v1/auth/me - Update own profile (full_name, department)
- POST /api/v1/auth/me/change-password - Change own password
"""
from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging
import uuid

from ..models.database import get_db, get_db_public
from ..models.auth import (
    LoginRequest,
    TokenResponse,
    UserInfo,
    RefreshTokenRequest,
    LogoutRequest,
    UpdateProfileRequest,
    ChangePasswordRequest,
)
from ..services.auth_service import AuthService
from ..core.security import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    request: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_public),
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
    db: AsyncSession = Depends(get_db_public),
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
    db: AsyncSession = Depends(get_db_public),
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
        last_login=user.last_login,
    )


@router.patch("/me", response_model=UserInfo)
async def update_profile(
    request: UpdateProfileRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the authenticated user's own profile.

    Allowed fields: full_name, department.
    Only explicitly provided fields are updated (PATCH semantics).

    Returns:
        Updated UserInfo
    """
    update_data = request.model_dump(exclude_unset=True)

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No fields provided for update",
        )

    user = await AuthService.update_user_profile(user_id, update_data, db)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    scopes = AuthService.ROLE_SCOPES.get(user.role, [])

    logger.info("Profile updated for user: %s", user.username)

    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        scope=scopes,
        last_login=user.last_login,
    )


@router.post("/me/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    request: ChangePasswordRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Change the authenticated user's password.

    Validates the current password before accepting the new one.

    Returns:
        200 on success
        400 if current_password is wrong
        422 on validation errors (new_password too short, etc.)
    """
    success = await AuthService.change_user_password(
        user_id=user_id,
        current_password=request.current_password,
        new_password=request.new_password,
        db=db,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    logger.info("Password changed for user_id: %s", user_id)

    return {"message": "Password changed successfully"}
