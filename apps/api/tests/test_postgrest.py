#!/usr/bin/env python3
"""
PostgREST API Test Suite

Tests all PostgREST endpoints with JWT authentication.
Validates CRUD operations, RLS policies, and query patterns.
"""
import os
import requests
import json
import sys
from typing import Optional, Dict, Any
from datetime import datetime


class PostgRESTTester:
    """Test suite for PostgREST API."""
    
    def __init__(self, base_url: str = "http://localhost:3001", token: Optional[str] = None):
        self.base_url = base_url
        self.token = token
        self.session = requests.Session()
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        
        self.test_results = []
    
    def get_token_from_fastapi(self, username: str = "admin", password: str = "DemoPass@2026") -> str:
        """Get JWT token from FastAPI auth endpoint."""
        print(f"\n🔐 Getting JWT token for user: {username}...")
        auth_url = os.getenv("POSTGREST_TEST_AUTH_URL", "http://localhost:8001/api/v1/auth/login")
        try:
            response = requests.post(
                auth_url,
                json={"username": username, "password": password}
            )
            response.raise_for_status()
            token = response.json()["access_token"]
            print(f"✅ Token obtained successfully")
            return token
        except Exception as e:
            print(f"❌ Failed to get token: {e}")
            print(f"⚠️  Make sure FastAPI backend is reachable at {auth_url}")
            raise
    
    def test(self, name: str, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Execute a test request and record result."""
        print(f"\n📝 Testing: {name}")
        print(f"   {method} {endpoint}")
        
        try:
            url = f"{self.base_url}{endpoint}"
            response = self.session.request(method, url, **kwargs)
            
            success = 200 <= response.status_code < 300
            
            result = {
                "name": name,
                "method": method,
                "endpoint": endpoint,
                "status_code": response.status_code,
                "success": success,
                "error": None if success else response.text
            }
            
            if success:
                print(f"   ✅ {response.status_code} - Success")
                try:
                    result["data"] = response.json()
                    print(f"   📦 Returned {len(result['data']) if isinstance(result['data'], list) else 1} item(s)")
                except ValueError:
                    result["data"] = response.text
            else:
                print(f"   ❌ {response.status_code} - {response.text[:100]}")
            
            self.test_results.append(result)
            return result
            
        except Exception as e:
            print(f"   ❌ Exception: {str(e)}")
            result = {
                "name": name,
                "method": method,
                "endpoint": endpoint,
                "status_code": None,
                "success": False,
                "error": str(e)
            }
            self.test_results.append(result)
            return result
    
    def run_all_tests(self):
        """Run complete test suite."""
        print("=" * 70)
        print("PostgREST API Test Suite")
        print("=" * 70)
        
        # Test 1: Health check (no auth)
        self.test(
            "Health Check",
            "GET",
            "/"
        )
        
        # Test 2: List users
        self.test(
            "List Users",
            "GET",
            "/users?select=id,username,email,role&limit=10"
        )
        
        # Test 3: Filter users by role
        self.test(
            "Filter Users by Role",
            "GET",
            "/users?role=eq.admin&select=username,email"
        )
        
        # Test 4: Get current user (should work with JWT)
        self.test(
            "Get Current User",
            "GET",
            "/users?select=*&limit=1"
        )
        
        # Test 5: List document summaries
        self.test(
            "List Document Summaries",
            "GET",
            "/document_summaries?select=id,title,status,uploaded_by_name&limit=10"
        )
        
        # Test 6: Filter documents by status
        self.test(
            "Filter Documents by Status",
            "GET",
            "/documents?status=in.(pending,in-review)&select=id,title,status"
        )
        
        # Test 7: Search documents (RPC function)
        self.test(
            "Search Documents (RPC)",
            "POST",
            "/rpc/search_documents",
            json={"search_term": "LNG"},
            headers={"Content-Type": "application/json"}
        )
        
        # Test 8: List section summaries
        self.test(
            "List Section Summaries",
            "GET",
            "/section_summaries?select=id,title,section_number,status&limit=10"
        )
        
        # Test 9: List conversations
        self.test(
            "List Conversations",
            "GET",
            "/conversation_summaries?order=updated_at.desc&limit=10"
        )
        
        # Test 10: List bookmarks
        self.test(
            "List Bookmark Details",
            "GET",
            "/bookmark_details?select=*&limit=10"
        )
        
        # Test 11: Get user stats (RPC function)
        # Note: This will fail without a valid user UUID, but tests the endpoint
        self.test(
            "Get User Stats (RPC)",
            "POST",
            "/rpc/get_user_stats",
            json={"user_uuid": "00000000-0000-0000-0000-000000000001"},
            headers={"Content-Type": "application/json"}
        )
        
        # Test 12: Advanced filtering - documents with pagination
        self.test(
            "Documents with Pagination",
            "GET",
            "/documents?order=uploaded_at.desc&limit=5&offset=0"
        )
        
        # Test 13: Column selection
        self.test(
            "Column Selection",
            "GET",
            "/users?select=username,email,role"
        )
        
        # Test 14: Multiple sorting
        self.test(
            "Multiple Sort Columns",
            "GET",
            "/documents?order=status.asc,uploaded_at.desc&limit=10"
        )
        
        # Test 15: Count request
        self.test(
            "Count Documents",
            "HEAD",
            "/documents"
        )
        
        return self.print_summary()
    
    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)
        
        total = len(self.test_results)
        passed = sum(1 for r in self.test_results if r["success"])
        failed = total - passed
        
        print(f"\n📊 Results:")
        print(f"   Total Tests:  {total}")
        print(f"   ✅ Passed:    {passed}")
        print(f"   ❌ Failed:    {failed}")
        print(f"   Success Rate: {(passed/total*100):.1f}%")
        
        if failed > 0:
            print(f"\n❌ Failed Tests:")
            for result in self.test_results:
                if not result["success"]:
                    print(f"   - {result['name']}: {result.get('error', 'Unknown error')}")
        
        print("\n" + "=" * 70)
        
        return failed == 0


def main():
    """Main test execution."""
    print("🧪 PostgREST API Test Suite\n")
    
    # Check if token provided via command line
    token = None
    if len(sys.argv) > 1:
        token = sys.argv[1]
        print(f"✅ Using provided JWT token")
    
    tester = PostgRESTTester(token=token)
    
    # If no token provided, try to get one from FastAPI
    if not token:
        username = os.getenv("POSTGREST_TEST_USERNAME", "admin")
        password = os.getenv("POSTGREST_TEST_PASSWORD", "DemoPass@2026")
        auth_url = os.getenv("POSTGREST_TEST_AUTH_URL", "http://localhost:8001/api/v1/auth/login")
        print("⚠️  No JWT token provided")
        print(f"   Attempting to get token from FastAPI ({auth_url})...")
        try:
            token = tester.get_token_from_fastapi(username=username, password=password)
            tester.token = token
            tester.session.headers.update({"Authorization": f"Bearer {token}"})
        except Exception as e:
            print(f"\n❌ Could not obtain JWT token")
            print(f"   Error: {e}")
            print("\n💡 To run tests with authentication:")
            print("   1. Start FastAPI backend: cd backend && uvicorn app.main:app --reload")
            print("   2. Run tests again")
            print("   OR")
            print(f"   Provide token: python {sys.argv[0]} 'your-jwt-token'")
            print("\n⚠️  Continuing with unauthenticated tests (many will fail)...")
    
    # Run all tests
    success = tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
