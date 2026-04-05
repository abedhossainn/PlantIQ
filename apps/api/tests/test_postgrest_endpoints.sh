#!/bin/bash
# PostgREST API Endpoint Test Script
# Quick validation of PostgREST functionality

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
POSTGREST_URL="${POSTGREST_URL:-http://localhost:3001}"
FASTAPI_URL="${FASTAPI_URL:-http://localhost:8001}"
JWT_TOKEN=""

echo "=================================================="
echo "PostgREST Endpoint Test Script"
echo "=================================================="
echo ""

# Function to print test result
print_result() {
    if [ $1 -eq 0 ]; then
        echo -e "${GREEN}✅ PASS${NC}: $2"
    else
        echo -e "${RED}❌ FAIL${NC}: $2"
    fi
}

# Function to test endpoint
test_endpoint() {
    local method=$1
    local endpoint=$2
    local description=$3
    local expected_status=${4:-200}
    local extra_args=${5:-""}
    
    echo ""
    echo "Testing: $description"
    echo "  $method $endpoint"
    
    if [ -n "$JWT_TOKEN" ]; then
        response=$(curl -s -w "\n%{http_code}" -X $method \
            -H "Authorization: Bearer $JWT_TOKEN" \
            $extra_args \
            "$POSTGREST_URL$endpoint")
    else
        response=$(curl -s -w "\n%{http_code}" -X $method \
            $extra_args \
            "$POSTGREST_URL$endpoint")
    fi
    
    status_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)
    
    if [ "$status_code" = "$expected_status" ]; then
        print_result 0 "$description"
        if [ -n "$body" ]; then
            echo "  Response: ${body:0:100}..."
        fi
        return 0
    else
        print_result 1 "$description (Expected $expected_status, got $status_code)"
        echo "  Response: $body"
        return 1
    fi
}

# Step 1: Get JWT token from FastAPI
echo -e "${YELLOW}Step 1: Obtaining JWT token...${NC}"
login_response=$(curl -s -X POST "$FASTAPI_URL/api/v1/auth/login" \
    -H "Content-Type: application/json" \
    -d '{"username": "admin", "password": "admin123"}')

if echo "$login_response" | grep -q "access_token"; then
    JWT_TOKEN=$(echo "$login_response" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
    print_result 0 "JWT token obtained"
    echo "  Token: ${JWT_TOKEN:0:50}..."
else
    print_result 1 "Failed to get JWT token"
    echo "  Response: $login_response"
    echo ""
    echo -e "${YELLOW}Make sure FastAPI backend is running:${NC}"
    echo "  cd backend && uvicorn app.main:app --reload"
    echo ""
    echo "Continuing without authentication (most tests will fail)..."
    JWT_TOKEN=""
fi

# Step 2: Test basic endpoints
echo ""
echo -e "${YELLOW}Step 2: Testing Basic Endpoints${NC}"

test_endpoint "GET" "/" "Health check" 200

test_endpoint "GET" "/users?select=id,username,email,role&limit=5" \
    "List users with column selection" 200

test_endpoint "GET" "/documents?select=id,title,status&limit=10" \
    "List documents" 200

test_endpoint "GET" "/document_sections?select=id,title,section_number&limit=10" \
    "List document sections" 200

test_endpoint "GET" "/conversations?select=id,title,user_id&limit=10" \
    "List conversations" 200

test_endpoint "GET" "/chat_messages?select=id,role,content&limit=10" \
    "List chat messages" 200

test_endpoint "GET" "/bookmarks?select=id,user_id,message_id&limit=10" \
    "List bookmarks" 200

# Step 3: Test views
echo ""
echo -e "${YELLOW}Step 3: Testing Database Views${NC}"

test_endpoint "GET" "/document_summaries?select=*&limit=5" \
    "Document summaries view" 200

test_endpoint "GET" "/section_summaries?select=*&limit=5" \
    "Section summaries view" 200

test_endpoint "GET" "/conversation_summaries?select=*&limit=5" \
    "Conversation summaries view" 200

test_endpoint "GET" "/bookmark_details?select=*&limit=5" \
    "Bookmark details view" 200

# Step 4: Test filtering
echo ""
echo -e "${YELLOW}Step 4: Testing Filter Operations${NC}"

test_endpoint "GET" "/users?role=eq.admin" \
    "Filter by exact match (role=admin)" 200

test_endpoint "GET" "/documents?status=in.(pending,in-review)" \
    "Filter by IN operator" 200

test_endpoint "GET" "/documents?order=uploaded_at.desc&limit=5" \
    "Sort by date descending" 200

test_endpoint "GET" "/users?select=username,email,role&order=username.asc" \
    "Column selection with sorting" 200

# Step 5: Test RPC functions
echo ""
echo -e "${YELLOW}Step 5: Testing RPC Functions${NC}"

test_endpoint "POST" "/rpc/search_documents" \
    "Search documents function" 200 \
    '-H "Content-Type: application/json" -d "{\"search_term\": \"test\"}"'

test_endpoint "POST" "/rpc/get_user_stats" \
    "Get user stats function" 200 \
    '-H "Content-Type: application/json" -d "{\"user_uuid\": \"00000000-0000-0000-0000-000000000001\"}"'

# Step 6: Test pagination
echo ""
echo -e "${YELLOW}Step 6: Testing Pagination${NC}"

test_endpoint "GET" "/users?limit=2&offset=0" \
    "Pagination: first page (limit=2, offset=0)" 200

test_endpoint "GET" "/users?limit=2&offset=2" \
    "Pagination: second page (limit=2, offset=2)" 200

# Step 7: Test count
echo ""
echo -e "${YELLOW}Step 7: Testing Count Operations${NC}"

test_endpoint "HEAD" "/users" \
    "Count users (HEAD request)" 200

# Summary
echo ""
echo "=================================================="
echo "Test Summary"
echo "=================================================="
echo ""
echo -e "${GREEN}✅ PostgREST API is functional${NC}"
echo ""
echo "Next Steps:"
echo "  1. Review full API documentation: docs/api/POSTGREST_API.md"
echo "  2. Run Python test suite: python backend/tests/test_postgrest.py"
echo "  3. Test with your preferred HTTP client (Postman, Insomnia, etc.)"
echo ""
echo "Key Endpoints:"
echo "  - Users:         $POSTGREST_URL/users"
echo "  - Documents:     $POSTGREST_URL/documents"
echo "  - Sections:      $POSTGREST_URL/document_sections"
echo "  - Conversations: $POSTGREST_URL/conversations"
echo "  - Messages:      $POSTGREST_URL/chat_messages"
echo "  - Bookmarks:     $POSTGREST_URL/bookmarks"
echo ""
echo "API Documentation: http://localhost:3001/"
echo ""
