"""
Security dependencies for JWT authentication and authorization.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import uuid

from ..core.jwt import jwt_manager
from jwt.exceptions import InvalidTokenError

security = HTTPBearer()


async def get_jwt_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Extract and validate JWT token, return full payload.
    
    Args:
        credentials: Bearer token from Authorization header
        
    Returns:
        JWT payload dictionary
        
    Raises:
        HTTPException: If token is invalid or missing
    """
    try:
        token = credentials.credentials
        payload = jwt_manager.verify_token(token)
        return payload
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_id(
    payload: dict = Depends(get_jwt_payload)
) -> uuid.UUID:
    """
    Extract user ID from JWT payload.
    
    Args:
        payload: JWT payload from get_jwt_payload
        
    Returns:
        User UUID from token's 'sub' claim
        
    Raises:
        HTTPException: If user ID is missing or invalid
    """
    try:
        user_id = uuid.UUID(payload["sub"])
        return user_id
    except (KeyError, ValueError) as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token payload: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user_role(
    payload: dict = Depends(get_jwt_payload)
) -> str:
    """
    Extract user role from JWT payload.
    
    Args:
        payload: JWT payload from get_jwt_payload
        
    Returns:
        User role from token's 'role' claim
        
    Raises:
        HTTPException: If role is missing
    """
    try:
        role = payload["role"]
        return role
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload: missing role claim",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def require_role(
    required_roles: list[str],
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Require user to have one of the specified roles.
    
    Args:
        required_roles: List of allowed roles
        credentials: Bearer token from Authorization header
        
    Returns:
        User role if authorized
        
    Raises:
        HTTPException: If user doesn't have required role
    """
    try:
        token = credentials.credentials
        payload = jwt_manager.verify_token(token)
        role = payload["role"]
        
        if role not in required_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {required_roles}",
            )
        
        return role
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Require admin role.
    
    Usage:
        @app.get("/admin")
        async def admin_endpoint(role: str = Depends(require_admin)):
            ...
    """
    try:
        token = credentials.credentials
        payload = jwt_manager.verify_token(token)
        role = payload["role"]
        
        if role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        
        return role
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_reviewer_or_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """
    Require reviewer or admin role.
    
    Usage:
        @app.get("/review")
        async def review_endpoint(role: str = Depends(require_reviewer_or_admin)):
            ...
    """
    try:
        token = credentials.credentials
        payload = jwt_manager.verify_token(token)
        role = payload["role"]
        
        if role not in ["reviewer", "admin"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reviewer or admin access required",
            )
        
        return role
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Get full JWT token payload.
    
    Args:
        credentials: Bearer token from Authorization header
        
    Returns:
        Full token payload dictionary
        
    Raises:
        HTTPException: If token is invalid
    """
    try:
        token = credentials.credentials
        payload = jwt_manager.verify_token(token)
        return payload
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid authentication credentials: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def verify_ws_token(token: Optional[str]) -> Optional[tuple[uuid.UUID, str]]:
    """
    Verify JWT token for WebSocket connections.
    
    SECURITY: Returns both user_id and role for authorization checks.
    
    Args:
        token: JWT token from query parameter
        
    Returns:
        Tuple of (user_id, role) if valid, None if invalid
    """
    if not token:
        return None
    
    try:
        payload = jwt_manager.verify_token(token)
        user_id = uuid.UUID(payload.get("sub"))
        role = payload.get("role", "user")
        return (user_id, role)
    except (InvalidTokenError, ValueError):
        return None
    except Exception:
        return None
