"""
Authentication service - Business logic for user authentication and token management.
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import uuid
import hashlib
import logging

from ..models.database import Base
from ..core.jwt import jwt_manager
from ..core.ldap import ldap_client
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UUID as SQLUUID, String, DateTime

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    """Return UTC timestamp as naive datetime for legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Import User model (define inline for now, will be moved to models later)
class User(Base):
    """User database model."""
    __tablename__ = "users"
    
    id: Mapped[uuid.UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    department: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)


class RefreshToken(Base):
    """Refresh token database model."""
    __tablename__ = "refresh_tokens"
    
    id: Mapped[uuid.UUID] = mapped_column(SQLUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(SQLUUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow_naive)


class AuthService:
    """Authentication service for handling login, token issuance, and refresh."""
    
    REFRESH_TOKEN_LIFETIME_HOURS = 8
    
    # Scope mapping based on role
    ROLE_SCOPES = {
        "admin": ["chat.read", "docs.review", "docs.upload", "admin.manage"],
        "reviewer": ["chat.read", "docs.review", "docs.upload"],
        "user": ["chat.read"],
    }
    
    @staticmethod
    async def authenticate_user(
        username: str,
        password: str,
        db: AsyncSession
    ) -> Optional[Tuple[User, str, str]]:
        """
        Authenticate user via LDAP and issue tokens.
        
        Args:
            username: Username to authenticate
            password: User password
            db: Database session
            
        Returns:
            Tuple of (User, access_token, refresh_token) if successful, None otherwise
        """
        # Authenticate against LDAP
        ldap_user = await ldap_client.authenticate(username, password)
        if not ldap_user:
            logger.warning(f"Authentication failed for user: {username}")
            return None
        
        # Get or create user in database
        user = await AuthService._get_or_create_user(ldap_user, db)
        
        if user.status != "active":
            logger.warning(f"User account disabled: {username}")
            return None
        
        # Update last login
        user.last_login = _utcnow_naive()
        await db.commit()
        
        # Get user scopes based on role
        scopes = AuthService.ROLE_SCOPES.get(user.role, [])
        
        # Generate access token
        access_token = jwt_manager.create_access_token(
            user_id=user.id,
            role=user.role,
            email=user.email,
            department=user.department,
            scope=scopes,
        )
        
        # Generate refresh token
        refresh_token = await AuthService._create_refresh_token(user.id, db)
        
        logger.info(f"User authenticated successfully: {username}")
        return user, access_token, refresh_token
    
    @staticmethod
    async def _get_or_create_user(ldap_user, db: AsyncSession) -> User:
        """Get existing user or create new one from LDAP data."""
        # Try to find existing user
        result = await db.execute(
            select(User).where(User.username == ldap_user.username)
        )
        user = result.scalar_one_or_none()
        
        if user:
            # Update user info from LDAP
            user.email = ldap_user.email
            user.full_name = ldap_user.full_name
            user.department = ldap_user.department
            user.updated_at = _utcnow_naive()
            return user
        
        # Create new user
        # Determine role from username (in production, this would come from LDAP groups)
        role = AuthService._determine_role_from_username(ldap_user.username)
        
        user = User(
            username=ldap_user.username,
            email=ldap_user.email,
            full_name=ldap_user.full_name,
            role=role,
            department=ldap_user.department,
            status="active",
        )
        db.add(user)
        await db.flush()
        
        logger.info(f"Created new user: {ldap_user.username} with role: {role}")
        return user
    
    @staticmethod
    def _determine_role_from_username(username: str) -> str:
        """
        Determine user role from username (mock logic for development).
        
        In production, this would be determined from LDAP group membership.
        """
        if username == "admin":
            return "admin"
        elif username == "reviewer":
            return "reviewer"
        else:
            return "user"
    
    @staticmethod
    async def _create_refresh_token(user_id: uuid.UUID, db: AsyncSession) -> str:
        """Create a new refresh token for user."""
        # Generate random token
        raw_token = str(uuid.uuid4())
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        
        # Store in database
        refresh_token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=_utcnow_naive() + timedelta(hours=AuthService.REFRESH_TOKEN_LIFETIME_HOURS),
        )
        db.add(refresh_token)
        await db.commit()
        
        return raw_token
    
    @staticmethod
    async def refresh_access_token(
        refresh_token: str,
        db: AsyncSession
    ) -> Optional[Tuple[User, str, str]]:
        """
        Refresh access token using refresh token (single-use rotation).
        
        Args:
            refresh_token: Refresh token string
            db: Database session
            
        Returns:
            Tuple of (User, new_access_token, new_refresh_token) if successful, None otherwise
        """
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        # Find token in database
        result = await db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
        )
        token_record = result.scalar_one_or_none()
        
        if not token_record:
            logger.warning("Refresh token not found or already used")
            return None
        
        # Check expiration
        if token_record.expires_at < _utcnow_naive():
            logger.warning("Refresh token expired")
            token_record.revoked_at = _utcnow_naive()
            await db.commit()
            return None
        
        # Revoke old token (single-use rotation)
        token_record.revoked_at = _utcnow_naive()
        
        # Get user
        result = await db.execute(
            select(User).where(User.id == token_record.user_id)
        )
        user = result.scalar_one_or_none()
        
        if not user or user.status != "active":
            logger.warning(f"User not found or disabled: {token_record.user_id}")
            await db.commit()
            return None
        
        # Get user scopes
        scopes = AuthService.ROLE_SCOPES.get(user.role, [])
        
        # Generate new access token
        access_token = jwt_manager.create_access_token(
            user_id=user.id,
            role=user.role,
            email=user.email,
            department=user.department,
            scope=scopes,
        )
        
        # Generate new refresh token
        new_refresh_token = await AuthService._create_refresh_token(user.id, db)
        
        logger.info(f"Access token refreshed for user: {user.username}")
        return user, access_token, new_refresh_token
    
    @staticmethod
    async def revoke_refresh_token(refresh_token: str, db: AsyncSession) -> bool:
        """
        Revoke a refresh token (logout).
        
        Args:
            refresh_token: Refresh token string
            db: Database session
            
        Returns:
            True if token was revoked, False if not found
        """
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        
        result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=_utcnow_naive())
        )
        
        await db.commit()
        
        if result.rowcount > 0:
            logger.info("Refresh token revoked successfully")
            return True
        
        logger.warning("Refresh token not found or already revoked")
        return False
    
    @staticmethod
    async def get_user_by_id(user_id: uuid.UUID, db: AsyncSession) -> Optional[User]:
        """Get user by ID."""
        result = await db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
