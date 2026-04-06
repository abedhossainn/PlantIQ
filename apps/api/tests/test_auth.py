#!/usr/bin/env python3
"""
Test script for authentication implementation.

Tests:
1. JWT key generation
2. JWT token creation and validation
3. Mock LDAP authentication
4. Auth service functionality
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.jwt import JWTManager
from app.core.ldap import LDAPClient
import uuid

_AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"


@pytest.mark.skipif(_AUTH_DISABLED, reason="JWT operations disabled when AUTH_DISABLED=true")
def test_jwt_operations():
    """Test JWT token creation and validation."""
    print("\n🔐 Testing JWT Operations...")
    
    # Create test keys directory
    test_keys_dir = Path(__file__).parent.parent / "test_keys"
    test_keys_dir.mkdir(exist_ok=True)
    
    # Generate test keys if they don't exist
    from scripts.generate_keys import generate_rsa_keypair
    if not (test_keys_dir / "jwt-private.pem").exists():
        print("Generating test keys...")
        generate_rsa_keypair(test_keys_dir)
    
    # Initialize JWT manager with test keys
    jwt_mgr = JWTManager(
        private_key_path=str(test_keys_dir / "jwt-private.pem"),
        public_key_path=str(test_keys_dir / "jwt-public.pem"),
    )
    
    # Create a test token
    test_user_id = uuid.uuid4()
    token = jwt_mgr.create_access_token(
        user_id=test_user_id,
        role="reviewer",
        email="test@plantig.local",
        department="Engineering",
        scope=["chat.read", "docs.review"],
    )
    
    print(f"✅ Token created: {token[:50]}...")
    
    # Validate token
    payload = jwt_mgr.verify_token(token)
    assert str(test_user_id) == payload["sub"]
    assert payload["role"] == "reviewer"
    assert payload["email"] == "test@plantig.local"
    assert payload["iss"] == "plantig-auth"
    assert payload["aud"] == "plantig"
    print("✅ Token validation passed")
    print(f"   User ID: {payload['sub']}")
    print(f"   Role: {payload['role']}")
    print(f"   Scopes: {payload['scope']}")


async def test_ldap_authentication():
    """Test LDAP authentication (mock mode)."""
    print("\n👤 Testing LDAP Authentication (Mock Mode)...")
    
    ldap = LDAPClient(use_mock=True)
    
    # Test successful authentication
    result = await ldap.authenticate("admin", "admin123")
    if result:
        print(f"✅ Authentication successful for: {result.username}")
        print(f"   Email: {result.email}")
        print(f"   Full name: {result.full_name}")
        print(f"   Department: {result.department}")
    else:
        raise AssertionError("Authentication failed")
    
    # Test failed authentication
    result = await ldap.authenticate("admin", "wrong_password")
    if result is None:
        print("✅ Failed authentication correctly rejected")
    else:
        raise AssertionError("Failed authentication was accepted (should have been rejected)")


async def main():
    """Run all tests."""
    print("=" * 60)
    print("PlantIQ Backend Authentication Test Suite")
    print("=" * 60)
    
    # Test JWT operations
    try:
        test_jwt_operations()
        jwt_ok = True
    except Exception:
        jwt_ok = False
    
    # Test LDAP authentication
    try:
        await test_ldap_authentication()
        ldap_ok = True
    except Exception:
        ldap_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)
    print(f"JWT Operations:        {'✅ PASS' if jwt_ok else '❌ FAIL'}")
    print(f"LDAP Authentication:   {'✅ PASS' if ldap_ok else '❌ FAIL'}")
    print("=" * 60)
    
    if jwt_ok and ldap_ok:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
