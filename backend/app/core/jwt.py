"""
JWT token utilities for RS256 signing and validation.
"""
from datetime import datetime, timedelta
from typing import Dict, Optional
import jwt
from jwt.exceptions import InvalidTokenError
from pathlib import Path
import os
import uuid


class JWTManager:
    """
    Manages JWT token generation and validation using RS256 asymmetric signing.
    
    - Private key for signing (FastAPI only)
    - Public key for verification (FastAPI + PostgREST)
    """
    
    def __init__(
        self,
        private_key_path: Optional[str] = None,
        public_key_path: Optional[str] = None,
        issuer: str = "plantig-auth",
        audience: str = "plantig",
        access_token_expire_minutes: int = 15,
    ):
        """
        Initialize JWT manager.
        
        Args:
            private_key_path: Path to RS256 private key (PEM format)
            public_key_path: Path to RS256 public key (PEM format)
            issuer: Token issuer identifier
            audience: Token audience identifier
            access_token_expire_minutes: Access token lifetime in minutes
        """
        self.issuer = issuer
        self.audience = audience
        self.access_token_expire_minutes = access_token_expire_minutes
        
        # Load private key for signing
        if private_key_path:
            self.private_key = self._load_key(private_key_path)
        else:
            # Fallback to environment variable or default path
            default_private_path = os.getenv(
                "JWT_PRIVATE_KEY_PATH",
                "/secrets/jwt-private.pem"
            )
            self.private_key = self._load_key(default_private_path)
        
        # Load public key for verification
        if public_key_path:
            self.public_key = self._load_key(public_key_path)
        else:
            # Fallback to environment variable or default path
            default_public_path = os.getenv(
                "JWT_PUBLIC_KEY_PATH",
                "/secrets/jwt-public.pem"
            )
            self.public_key = self._load_key(default_public_path)

    @staticmethod
    def _candidate_key_paths(key_path: str) -> list[Path]:
        """Build likely key locations for local development and tests."""
        requested_path = Path(key_path)
        module_root = Path(__file__).resolve().parents[2]
        repo_root = module_root.parent

        candidates: list[Path] = []

        if requested_path.is_absolute():
            candidates.append(requested_path)
        else:
            candidates.extend(
                [
                    Path.cwd() / requested_path,
                    module_root / requested_path,
                    repo_root / requested_path,
                ]
            )

        key_name = requested_path.name
        candidates.extend(
            [
                module_root / "secrets" / key_name,
                repo_root / "backend" / "secrets" / key_name,
            ]
        )

        seen: set[Path] = set()
        unique_candidates: list[Path] = []
        for candidate in candidates:
            resolved_candidate = candidate.resolve()
            if resolved_candidate not in seen:
                seen.add(resolved_candidate)
                unique_candidates.append(resolved_candidate)

        return unique_candidates
    
    @staticmethod
    def _load_key(key_path: str) -> str:
        """Load key from file."""
        for candidate in JWTManager._candidate_key_paths(key_path):
            if candidate.exists():
                return candidate.read_text()

        searched_paths = ", ".join(str(path) for path in JWTManager._candidate_key_paths(key_path))
        raise FileNotFoundError(
            f"JWT key file not found for '{key_path}'. Searched: {searched_paths}"
        )
    
    def create_access_token(
        self,
        user_id: uuid.UUID,
        role: str,
        email: str,
        department: Optional[str],
        scope: list[str],
    ) -> str:
        """
        Create a new access token with user claims.
        
        Args:
            user_id: User UUID (maps to users.id)
            role: User role (admin, reviewer, user)
            email: User email
            department: User department (optional)
            scope: List of permission scopes
            
        Returns:
            Signed JWT token string
        """
        now = datetime.utcnow()
        expire = now + timedelta(minutes=self.access_token_expire_minutes)
        
        payload = {
            "sub": str(user_id),  # Subject - user UUID
            "role": role,
            "email": email,
            "dept": department,
            "scope": scope,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
        
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers={"kid": "plantig-2026-v1"}  # Key ID for rotation
        )
        
        return token
    
    def verify_token(self, token: str) -> Dict:
        """
        Verify and decode a JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload
            
        Raises:
            InvalidTokenError: If token is invalid, expired, or has wrong claims
        """
        try:
            payload = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            return payload
        except InvalidTokenError as e:
            raise InvalidTokenError(f"Token validation failed: {str(e)}")
    
    def decode_token_unsafe(self, token: str) -> Dict:
        """
        Decode token without verification (for debugging only).
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload (unverified)
        """
        return jwt.decode(token, options={"verify_signature": False})


# Global JWT manager instance
jwt_manager = JWTManager()
