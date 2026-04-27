"""
Authentication API endpoints.

Endpoints:
- POST /api/v1/auth/login - Authenticate user and issue tokens
- POST /api/v1/auth/refresh - Refresh access token
- POST /api/v1/auth/logout - Revoke refresh token
- GET /api/v1/auth/me - Get current user info
- PATCH /api/v1/auth/me - Update own profile (full_name, department)
- POST /api/v1/auth/me/change-password - Change own password
- POST /api/v1/auth/admin/users - REMOVED (410 Gone) — LDAP is identity source of truth
- GET /api/v1/auth/admin/users - List LDAP-backed users (admin only)
- PATCH /api/v1/auth/admin/users/{user_id}/role - Update user role (admin only)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status, Response, Cookie
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
    AdminUserResponse,
    AdminUsersListResponse,
    AdminUpdateRoleRequest,
)
from ..services.auth_service import AuthService
from ..core.security import get_current_user_id, get_current_user_role, require_admin

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


@router.post(
    "/admin/users",
    status_code=status.HTTP_410_GONE,
    include_in_schema=True,
    deprecated=True,
)
async def admin_create_user_deprecated():
    """
    **DEPRECATED — endpoint removed.**

    User creation via the PlantIQ API is no longer permitted.
    LDAP is the sole source of truth for identity existence.
    Users are provisioned in LDAP/AD by the directory administrator;
    PlantIQ syncs identity on first successful login.

    To manage role assignments use:
      PATCH /api/v1/auth/admin/users/{user_id}/role
    """
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "ENDPOINT_REMOVED",
            "message": (
                "User creation via the PlantIQ API has been removed. "
                "LDAP is the source of truth for identity existence. "
                "Provision users in your LDAP/AD directory; PlantIQ syncs identity on first login."
            ),
        },
    )


@router.get("/admin/users", response_model=AdminUsersListResponse)
async def admin_list_users(
    page: int = Query(default=1, ge=1, description="1-based page number"),
    page_size: int = Query(default=50, ge=1, le=200, description="Records per page"),
    search: Optional[str] = Query(default=None, max_length=255, description="Substring filter on username or full_name"),
    _role: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List LDAP-backed users known to PlantIQ (admin only).

    Returns users who have logged in at least once (i.e. have a local profile
    record created by the LDAP sync on first login).  This endpoint does NOT
    create, import, or delete user accounts.

    Supports pagination and optional substring search on username / full_name.
    """
    users, total = await AuthService.list_users(
        db=db,
        page=page,
        page_size=page_size,
        search=search or None,
    )

    items = [
        AdminUserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            role=u.role,
            department=u.department,
            status=u.status,
        )
        for u in users
    ]

    logger.info("Admin listed users: page=%s, page_size=%s, total=%s", page, page_size, total)

    return AdminUsersListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/admin/users/{user_id}/role", response_model=AdminUserResponse)
async def admin_update_user_role(
    user_id: uuid.UUID,
    request: AdminUpdateRoleRequest,
    caller_user_id: uuid.UUID = Depends(get_current_user_id),
    caller_role: str = Depends(get_current_user_role),
    _admin_check: str = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Update the role of an existing LDAP-backed user (admin only).

    Role escalation safeguards:
    - Admins cannot update their own role.
    - Only plantig_admin callers may assign the plantig_admin role.

    Returns 404 if the target user has not yet logged in (no local profile).
    Returns 403 if escalation rules are violated.
    """
    try:
        user = await AuthService.update_user_role(
            target_user_id=user_id,
            new_role=request.role,
            caller_user_id=caller_user_id,
            caller_role=caller_role,
            db=db,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "ROLE_ESCALATION_DENIED", "message": str(exc)},
        )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "USER_NOT_FOUND",
                "message": (
                    "User not found in PlantIQ. "
                    "The user must log in at least once via LDAP before their role can be managed here."
                ),
            },
        )

    logger.info(
        "Admin %s updated role for user %s to %s",
        caller_user_id,
        user_id,
        request.role,
    )

    return AdminUserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        department=user.department,
        status=user.status,
    )

