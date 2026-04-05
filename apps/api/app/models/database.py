"""
Database connection and session management for PlantIQ backend.
"""
from typing import AsyncGenerator, Optional, Dict, Any
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import text
import os

from ..core.security import get_jwt_payload

# Database URL from environment - AUTHENTICATOR PASSWORD MUST BE SET VIA ENV
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://plantig_authenticator@localhost:5432/plantig"
)

if "password" in DATABASE_URL.lower() or not os.getenv("DATABASE_URL"):
    import logging
    logging.warning(
        "⚠️  DATABASE_URL not set or contains literal password. "
        "Set DATABASE_URL env var with authenticator credentials from secrets."
    )

# Create async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_DEBUG", "false").lower() == "true",
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

# Session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for SQLAlchemy models
Base = declarative_base()


async def _db_session(
    jwt_claims: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Internal async database session generator with optional RLS role enforcement.
    
    SECURITY: Sets PostgreSQL role based on JWT claims to activate RLS policies.
    
    Args:
        jwt_claims: JWT payload with 'role' and 'sub' claims
        
    """
    async with AsyncSessionLocal() as session:
        try:
            # Set RLS context if JWT claims provided
            if jwt_claims:
                role = jwt_claims.get("role", "user")
                user_id = jwt_claims.get("sub")
                
                # Map JWT role to PostgreSQL role
                role_map = {
                    "admin": "plantig_admin",
                    "user": "plantig_user",
                }
                db_role = role_map.get(role, "plantig_user")
                
                # Set role and JWT claims for RLS
                await session.execute(text(f"SET LOCAL ROLE {db_role}"))
                if user_id:
                    await session.execute(
                        text("SELECT set_config('request.jwt.claims.sub', :user_id, true)"),
                        {"user_id": str(user_id)}
                    )
                    await session.execute(
                        text("SELECT set_config('request.jwt.claims.role', :role, true)"),
                        {"role": role}
                    )
            
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            # Reset role before returning session to pool
            try:
                await session.execute(text("RESET ROLE"))
            except Exception:
                pass
            await session.close()


async def get_db(
    jwt_claims: dict = Depends(get_jwt_payload),
) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session with JWT-backed RLS.

    This function should be used for request-scoped dependency injection only.
    Internal/background code should use ``get_db_with_claims()`` or ``AsyncSessionLocal``
    so FastAPI dependency markers do not leak into non-request code paths.
    """
    async for session in _db_session(jwt_claims):
        yield session


async def get_db_with_claims(
    jwt_claims: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for non-request callers with optional JWT claims."""
    async for session in _db_session(jwt_claims):
        yield session


async def get_db_with_user(
    user_id: "UUID",  # Forward reference to avoid circular import
    role: str,
) -> AsyncGenerator[AsyncSession, None]:
    """
    Database session with authenticated user context.
    
    This is a convenience wrapper that should be used with security dependencies:
    
    Usage:
        from fastapi import Depends
        from .core.security import get_current_user_id, get_current_user_role
        
        @app.get("/items")
        async def read_items(
            db: AsyncSession = Depends(get_db_with_user),
            user_id: UUID = Depends(get_current_user_id),
            role: str = Depends(get_current_user_role),
        ):
            # RLS is automatically enforced
            ...
    """
    jwt_claims = {"sub": str(user_id), "role": role}
    async for session in get_db_with_claims(jwt_claims):
        yield session
