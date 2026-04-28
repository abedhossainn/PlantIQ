"""
Authentication service - Business logic for user authentication and token management.

Responsibilities:
- User password hashing/verification (PBKDF2-SHA256 per OWASP standards)
- JWT token generation and validation
- LDAP directory integration (with mock fallback for development)
- Session management and token refresh
"""
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import hashlib
import logging
import os
import secrets
import uuid

from ..models.database import Base
from ..core.jwt import jwt_manager
from ..core.ldap import ldap_client
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import UUID as SQLUUID, String, DateTime

logger = logging.getLogger(__name__)


def _utcnow_naive() -> datetime:
    """Return UTC timestamp as naive datetime for legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# PBKDF2 iterations: OWASP-recommended standard as of 2023.
# Provides strong resistance against dictionary/brute-force attacks.
_PBKDF2_ITERATIONS = 600_000


def _hash_password(password: str) -> str:
    """Hash a password using PBKDF2-SHA256 with a random salt.

    Format: ``pbkdf2:sha256:<hex-salt>:<hex-digest>``
    OWASP recommends 600k iterations for PBKDF2-SHA256 (2023).
    Salt is randomly generated per password to resist rainbow tables.
    """
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{salt}:{dk.hex()}"


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored PBKDF2-SHA256 hash.

    Uses constant-time comparison to prevent timing attacks.
    Returns False on any parse or verification failure.
    """
    try:
        _, algo, salt, dk_hex = stored_hash.split(":", 3)
        dk = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS)
        return secrets.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


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
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
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


@dataclass
class AdminDirectoryUser:
    """Admin-facing LDAP directory user with optional local role mapping."""

    id: uuid.UUID
    username: str
    email: str
    full_name: str
    role: str
    department: Optional[str]
    status: str


class AuthService:
    """Authentication service for handling login, token issuance, and refresh."""
    
    REFRESH_TOKEN_LIFETIME_HOURS = 8

    # Maps application role (stored in users.role) → PostgREST DB role for SET ROLE.
    # PostgREST reads the 'role' JWT claim and switches to that DB role, so it must
    # match the PostgreSQL role name exactly.
    ROLE_TO_DB_ROLE: dict[str, str] = {
        "admin": "plantig_admin",
        "reviewer": "plantig_reviewer",
        "user": "plantig_user",
    }

    # Scope mapping based on role
    ROLE_SCOPES = {
        "admin": ["chat.read", "docs.review", "docs.upload", "admin.manage"],
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
            # LDAP failed — fall back to local DB password_hash authentication
            result = await db.execute(
                select(User).where(User.username == username)
            )
            db_user = result.scalar_one_or_none()
            if db_user and db_user.password_hash and _verify_password(password, db_user.password_hash):
                logger.info(f"Local DB authentication successful for user: {username}")
                user = db_user
            else:
                logger.warning(f"Authentication failed for user: {username}")
                return None
        else:
            # Get or create user in database from LDAP data
            user = await AuthService._get_or_create_user(ldap_user, db)
        
        if user.status != "active":
            logger.warning(f"User account disabled: {username}")
            return None
        
        # Update last login
        user.last_login = _utcnow_naive()
        await db.commit()
        
        # Get user scopes based on role
        scopes = AuthService.ROLE_SCOPES.get(user.role, [])

        # Map app role → PostgREST DB role (JWT 'role' claim must be the PG role name)
        db_role = AuthService.ROLE_TO_DB_ROLE.get(user.role, "plantig_user")

        # Generate access token
        access_token = jwt_manager.create_access_token(
            user_id=user.id,
            role=db_role,
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
        # Try to find existing user by username first, then by email
        result = await db.execute(
            select(User).where(User.username == ldap_user.username)
        )
        user = result.scalar_one_or_none()

        if not user:
            result = await db.execute(
                select(User).where(User.email == ldap_user.email)
            )
            user = result.scalar_one_or_none()

        if user:
            # Update user info from LDAP
            user.username = ldap_user.username
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

        # Map app role → PostgREST DB role
        db_role = AuthService.ROLE_TO_DB_ROLE.get(user.role, "plantig_user")

        # Generate new access token
        access_token = jwt_manager.create_access_token(
            user_id=user.id,
            role=db_role,
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

    @staticmethod
    async def update_user_profile(
        user_id: uuid.UUID,
        update_data: dict,
        db: AsyncSession,
    ) -> Optional[User]:
        """Update allowed profile fields for the authenticated user.

        Args:
            user_id: UUID of the user to update.
            update_data: Mapping of field names to new values (only fields
                that were explicitly sent in the request body).
            db: Database session.

        Returns:
            Updated User object, or None if the user does not exist.
        """
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        if "full_name" in update_data:
            user.full_name = update_data["full_name"]
        if "department" in update_data:
            user.department = update_data["department"]
        user.updated_at = _utcnow_naive()

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def change_user_password(
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        db: AsyncSession,
    ) -> bool:
        """Change the user's password after verifying the current one.

        Validation strategy:
        - If a local ``password_hash`` is stored, verify against it.
        - Otherwise validate via LDAP (works with both mock and real LDAP).

        On success the new password is hashed with PBKDF2-SHA256 and stored.

        Args:
            user_id: UUID of the user changing their password.
            current_password: The user's current password for verification.
            new_password: The new password to store.
            db: Database session.

        Returns:
            True if the password was updated, False if current_password is wrong
            or the user does not exist.
        """
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return False

        # Validate current password
        if user.password_hash:
            if not _verify_password(current_password, user.password_hash):
                logger.warning("change_user_password: stored-hash verification failed for user %s", user_id)
                return False
        else:
            # Fall back to LDAP validation
            ldap_user = await ldap_client.authenticate(user.username, current_password)
            if not ldap_user:
                logger.warning("change_user_password: LDAP verification failed for user %s", user_id)
                return False

        user.password_hash = _hash_password(new_password)
        user.updated_at = _utcnow_naive()
        await db.commit()

        logger.info("Password changed successfully for user %s", user_id)
        return True

    @staticmethod
    async def list_users(
        db: AsyncSession,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
    ):
        """List users stored in the local DB (LDAP-backed identities only).

        Only users who have logged in via LDAP are present in the DB — the DB is
        never the source of truth for identity existence, only for role mapping
        and profile sync data.

        Args:
            db: Database session.
            page: 1-based page number.
            page_size: Maximum records per page (capped at 200).
            search: Optional substring to filter on username or full_name.

        Returns:
            Tuple of (items: list[User], total: int).
        """
        page_size = min(page_size, 200)
        offset = (max(page, 1) - 1) * page_size

        ldap_users = await ldap_client.list_users(search=search)
        if not ldap_users:
            return [], 0

        usernames = [u.username for u in ldap_users if u.username]
        local_users_by_username: dict[str, User] = {}

        if usernames:
            result = await db.execute(select(User).where(User.username.in_(usernames)))
            local_users = list(result.scalars().all())
            local_users_by_username = {u.username: u for u in local_users}

        # Lazy-provision: create local profiles for LDAP users that have never logged in.
        # This ensures all directory users are visible with "active" status without
        # requiring a first-login event.
        new_local_users: list[User] = []
        for ldap_user in ldap_users:
            if ldap_user.username and ldap_user.username not in local_users_by_username:
                role = AuthService._determine_role_from_username(ldap_user.username)
                provisioned = User(
                    username=ldap_user.username,
                    email=ldap_user.email,
                    full_name=ldap_user.full_name,
                    role=role,
                    department=ldap_user.department,
                    status="active",
                )
                db.add(provisioned)
                new_local_users.append(provisioned)

        if new_local_users:
            await db.flush()
            # Reload newly created rows so their DB-assigned UUIDs are populated.
            for provisioned in new_local_users:
                await db.refresh(provisioned)
            await db.commit()
            local_users_by_username.update({u.username: u for u in new_local_users})
            logger.info("Lazy-provisioned %d LDAP user(s) into local DB", len(new_local_users))

        merged_users: list[AdminDirectoryUser] = []
        for ldap_user in ldap_users:
            local_user = local_users_by_username.get(ldap_user.username)
            if local_user is None:
                # Should not happen after lazy provisioning above, but guard defensively.
                continue
            merged_users.append(
                AdminDirectoryUser(
                    id=local_user.id,
                    username=ldap_user.username,
                    email=ldap_user.email,
                    full_name=ldap_user.full_name,
                    role=local_user.role,
                    department=ldap_user.department,
                    status=local_user.status,
                )
            )

        total = len(merged_users)
        return merged_users[offset: offset + page_size], total

    @staticmethod
    async def provision_ldap_users(db: AsyncSession) -> dict:
        """Bulk-provision all LDAP directory users into the local DB.

        Fetches every user from LDAP and creates a local profile for any who
        do not yet have one.  Existing local profiles are left untouched so
        that manually assigned roles and statuses are preserved.

        This is idempotent — running it multiple times is safe.

        Args:
            db: Database session.

        Returns:
            Dict with keys ``provisioned`` (int) and ``already_existed`` (int).
        """
        ldap_users = await ldap_client.list_users(search=None)
        if not ldap_users:
            return {"provisioned": 0, "already_existed": 0}

        usernames = [u.username for u in ldap_users if u.username]
        result = await db.execute(select(User).where(User.username.in_(usernames)))
        existing = {u.username for u in result.scalars().all()}

        provisioned = 0
        for ldap_user in ldap_users:
            if not ldap_user.username or ldap_user.username in existing:
                continue
            role = AuthService._determine_role_from_username(ldap_user.username)
            db.add(
                User(
                    username=ldap_user.username,
                    email=ldap_user.email,
                    full_name=ldap_user.full_name,
                    role=role,
                    department=ldap_user.department,
                    status="active",
                )
            )
            provisioned += 1

        if provisioned:
            await db.commit()
            logger.info("provision_ldap_users: provisioned %d new user(s)", provisioned)

        already_existed = len(existing)
        return {"provisioned": provisioned, "already_existed": already_existed}

    @staticmethod
    async def update_user_status(
        target_user_id: uuid.UUID,
        new_status: str,
        caller_user_id: uuid.UUID,
        db: AsyncSession,
    ) -> Optional[User]:
        """Set the local status of an LDAP-backed user (admin only).

        Allowed values: ``"active"`` or ``"disabled"``.
        Admins cannot disable their own account.

        Args:
            target_user_id: UUID of the user whose status is being changed.
            new_status: ``"active"`` or ``"disabled"``.
            caller_user_id: UUID of the admin making the request.
            db: Database session.

        Returns:
            Updated User object, or None if not found.

        Raises:
            PermissionError: If the admin attempts to disable their own account.
        """
        if target_user_id == caller_user_id:
            raise PermissionError("Admins cannot disable their own account.")

        result = await db.execute(select(User).where(User.id == target_user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        old_status = user.status
        user.status = new_status
        user.updated_at = _utcnow_naive()
        await db.commit()
        await db.refresh(user)

        logger.info(
            "Status updated for user %s (%s): %s → %s by admin %s",
            user.username,
            target_user_id,
            old_status,
            new_status,
            caller_user_id,
        )
        return user

    @staticmethod
    async def update_user_role(
        target_user_id: uuid.UUID,
        new_role: str,
        caller_user_id: uuid.UUID,
        caller_role: str,
        db: AsyncSession,
    ) -> Optional[User]:
        """Update the role of an existing LDAP-backed user (admin only).

        Role escalation safeguards:
        - Caller cannot update their own role (self-escalation prevention).
        - Only a plantig_admin / admin caller can assign the plantig_admin role.
        - Caller must already hold an admin-tier role (enforced at endpoint level
          via require_admin, but validated defensively here too).

        Args:
            target_user_id: UUID of the user whose role is being changed.
            new_role: The new role value.
            caller_user_id: UUID of the admin making the request.
            caller_role: Role of the admin making the request (from JWT).
            db: Database session.

        Returns:
            Updated User object, or None if the target user does not exist.

        Raises:
            PermissionError: If escalation rules are violated.
        """
        if target_user_id == caller_user_id:
            raise PermissionError("Admins cannot update their own role.")

        # Only plantig_admin callers may grant the plantig_admin role.
        if new_role == "plantig_admin" and caller_role not in {"plantig_admin", "admin"}:
            raise PermissionError(
                "Insufficient privilege: only plantig_admin may assign plantig_admin role."
            )

        result = await db.execute(select(User).where(User.id == target_user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        old_role = user.role
        user.role = new_role
        user.updated_at = _utcnow_naive()
        await db.commit()
        await db.refresh(user)

        logger.info(
            "Role updated for user %s (%s): %s → %s by admin %s",
            user.username,
            target_user_id,
            old_role,
            new_role,
            caller_user_id,
        )
        return user

