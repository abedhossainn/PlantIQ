# PostgREST API Documentation

**Version:** 1.0.0  
**Last Updated:** March 9, 2026  
**PostgREST Version:** v14.0

---

## Overview

PostgREST provides a RESTful API for the PlantIQ database with automatic:
- **Row Level Security** enforcement via PostgreSQL RLS
- **JWT authentication** using RS256 tokens
- **Automatic OpenAPI documentation**
- **Filtering, sorting, and pagination**
- **Computed columns and relationships**

**Base URL:** `http://localhost:3001` (development)

---

## Authentication

All PostgREST requests must include a JWT token in the `Authorization` header:

```http
Authorization: Bearer <access_token>
```

The JWT token is issued by FastAPI at `/api/v1/auth/login` and contains:
- `sub`: User UUID (maps to `users.id`)
- `role`: User role (`admin`, `reviewer`, `user`)

PostgREST uses the `role` claim to execute `SET ROLE plantig_<role>` before each request, activating RLS policies.

---

## Resource Endpoints

### Users

**Table:** `users`  
**View:** `N/A` (direct table access)

#### List Users

```http
GET /users
```

**Query Parameters:**
- `select=id,username,email,full_name,role,department` - Column selection
- `role=eq.admin` - Filter by role
- `department=like.*Engineering*` - Filter by department (wildcard)
- `status=eq.active` - Filter by status
- `order=created_at.desc` - Sort by created_at descending
- `limit=50` - Limit results
- `offset=0` - Pagination offset

**Example:**
```bash
curl "http://localhost:3001/users?select=id,username,email,role&role=eq.reviewer&order=username.asc" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "username": "jane.reviewer",
    "email": "jane@plantig.local",
    "role": "reviewer"
  }
]
```

#### Get Single User

```http
GET /users?id=eq.<user-id>
```

**Example:**
```bash
curl "http://localhost:3001/users?id=eq.550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $TOKEN"
```

#### Create User (Admin Only)

```http
POST /users
Content-Type: application/json
Prefer: return=representation
```

**Body:**
```json
{
  "username": "new.user",
  "email": "newuser@plantig.local",
  "full_name": "New User",
  "role": "user",
  "department": "Operations"
}
```

**Example:**
```bash
curl -X POST "http://localhost:3001/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"username":"new.user","email":"newuser@plantig.local","full_name":"New User","role":"user"}'
```

#### Update User

```http
PATCH /users?id=eq.<user-id>
Content-Type: application/json
Prefer: return=representation
```

**Body:**
```json
{
  "department": "Engineering",
  "status": "active"
}
```

#### Deactivate User (Admin Only)

```http
PATCH /users?id=eq.<user-id>
Content-Type: application/json
```

**Body:**
```json
{
  "status": "disabled"
}
```

---

### Documents

**Table:** `documents`  
**View:** `document_summaries` (enhanced with user info)

#### List Documents

```http
GET /document_summaries
```

**Query Parameters:**
- `select=id,title,version,status,uploaded_by_name,review_progress_percent`
- `status=eq.in-review` - Filter by status
- `system=like.*LNG*` - Filter by system
- `uploaded_at=gte.2026-01-01` - Filter by date (>=)
- `order=uploaded_at.desc`
- `limit=20`

**Example:**
```bash
curl "http://localhost:3001/document_summaries?select=*&status=eq.in-review&order=uploaded_at.desc" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
[
  {
    "id": "doc-uuid",
    "title": "LNG System Manual",
    "version": "3.2",
    "system": "LNG",
    "status": "in-review",
    "total_pages": 125,
    "total_sections": 42,
    "review_progress": 15,
    "review_progress_percent": 35.71,
    "uploaded_by_name": "Jane Reviewer",
    "uploaded_at": "2026-03-01T10:00:00Z"
  }
]
```

#### Get Document by ID

```http
GET /documents?id=eq.<doc-id>
```

Or use the view for enhanced data:

```http
GET /document_summaries?id=eq.<doc-id>
```

#### Update Document Metadata

```http
PATCH /documents?id=eq.<doc-id>
Content-Type: application/json
```

**Body:**
```json
{
  "status": "review-complete",
  "notes": "All sections reviewed and approved"
}
```

**Note:** Only admin can set `status=approved`. Reviewers can update other fields.

---

### Document Sections

**Table:** `document_sections`  
**View:** `section_summaries` (enhanced with document and reviewer info)  
**Function:** `get_document_sections(doc_id)` (full content)

#### List Sections for Document

Using view (without content):
```http
GET /section_summaries?document_id=eq.<doc-id>
```

Using RPC function (with full content):
```http
POST /rpc/get_document_sections
Content-Type: application/json
```

**Body:**
```json
{
  "doc_id": "document-uuid-here"
}
```

**Example:**
```bash
curl -X POST "http://localhost:3001/rpc/get_document_sections" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"doc_id":"550e8400-e29b-41d4-a716-446655440001"}'
```

#### Update Section Content

```http
PATCH /document_sections?id=eq.<section-id>
Content-Type: application/json
```

**Body:**
```json
{
  "content": "Updated section content...",
  "status": "approved",
  "reviewed_by": "reviewer-uuid",
  "reviewed_at": "2026-03-09T15:30:00Z",
  "current_version": 2
}
```

#### Get Section Versions

```http
GET /section_versions?section_id=eq.<section-id>&order=version_number.desc
```

---

### Conversations

**Table:** `conversations`  
**View:** `conversation_summaries` (with message count and last message time)  
**Function:** `get_conversation_messages(conv_id)` (all messages)

#### List User Conversations

```http
GET /conversation_summaries?order=updated_at.desc
```

**Note:** RLS automatically filters to current user's conversations.

**Response:**
```json
[
  {
    "id": "conv-uuid",
    "user_id": "user-uuid",
    "title": "LNG System Questions",
    "username": "jane.user",
    "user_name": "Jane User",
    "message_count": 12,
    "last_message_at": "2026-03-09T14:22:00Z",
    "created_at": "2026-03-08T09:00:00Z"
  }
]
```

#### Create Conversation

```http
POST /conversations
Content-Type: application/json
Prefer: return=representation
```

**Body:**
```json
{
  "title": "New Question Thread"
}
```

**Note:** `user_id` is automatically set from JWT token via RLS policy.

#### Get Conversation Messages

```http
POST /rpc/get_conversation_messages
Content-Type: application/json
```

**Body:**
```json
{
  "conv_id": "conversation-uuid"
}
```

**Response:**
```json
[
  {
    "id": "msg-uuid",
    "role": "user",
    "content": "What is the LNG system pressure?",
    "citations": null,
    "timestamp": "2026-03-09T14:20:00Z"
  },
  {
    "id": "msg-uuid-2",
    "role": "assistant",
    "content": "The LNG system operates at 150 psi...",
    "citations": [...],
    "timestamp": "2026-03-09T14:20:15Z"
  }
]
```

#### Add Message to Conversation

```http
POST /chat_messages
Content-Type: application/json
Prefer: return=representation
```

**Body:**
```json
{
  "conversation_id": "conv-uuid",
  "role": "user",
  "content": "Question text here"
}
```

#### Update Conversation Title

```http
PATCH /conversations?id=eq.<conv-id>
Content-Type: application/json
```

**Body:**
```json
{
  "title": "Updated Title"
}
```

#### Delete Conversation

```http
DELETE /conversations?id=eq.<conv-id>
```

**Note:** CASCADE deletes all messages.

---

### Bookmarks

**Table:** `bookmarks`  
**View:** `bookmark_details` (with full context)

#### List User Bookmarks

```http
GET /bookmark_details?order=created_at.desc
```

**Response:**
```json
[
  {
    "id": "bookmark-uuid",
    "user_id": "user-uuid",
    "conversation_id": "conv-uuid",
    "message_id": "msg-uuid",
    "tags": ["important", "lng-system"],
    "notes": "Key information about pressure",
    "username": "jane.user",
    "conversation_title": "LNG Questions",
    "message_content": "The system operates at...",
    "message_role": "assistant",
    "message_timestamp": "2026-03-09T14:00:00Z",
    "created_at": "2026-03-09T14:05:00Z"
  }
]
```

#### Create Bookmark

```http
POST /bookmarks
Content-Type: application/json
Prefer: return=representation
```

**Body:**
```json
{
  "conversation_id": "conv-uuid",
  "message_id": "msg-uuid",
  "tags": ["important", "reference"],
  "notes": "Save this for later"
}
```

#### Update Bookmark

```http
PATCH /bookmarks?id=eq.<bookmark-id>
Content-Type: application/json
```

**Body:**
```json
{
  "tags": ["important", "reviewed"],
  "notes": "Updated notes"
}
```

#### Delete Bookmark

```http
DELETE /bookmarks?id=eq.<bookmark-id>
```

#### Filter Bookmarks by Tag

```http
GET /bookmarks?tags=cs.{important}
```

**Note:** `cs` = contains, searches JSONB/array fields

---

## Advanced Query Patterns

### Filtering

PostgREST supports powerful filtering operators:

| Operator | Example | Description |
|----------|---------|-------------|
| `eq` | `status=eq.active` | Equals |
| `neq` | `status=neq.rejected` | Not equals |
| `gt` | `total_pages=gt.100` | Greater than |
| `gte` | `created_at=gte.2026-01-01` | Greater than or equal |
| `lt` | `review_progress=lt.50` | Less than |
| `lte` | `qa_score=lte.75.0` | Less than or equal |
| `like` | `title=like.*Manual*` | Case-sensitive pattern |
| `ilike` | `title=ilike.*manual*` | Case-insensitive pattern |
| `in` | `status=in.(pending,in-review)` | In list |
| `is` | `approved_at=is.null` | Is null |
| `not.is` | `approved_by=not.is.null` | Is not null |
| `cs` | `tags=cs.{important}` | Contains (arrays/JSONB) |

### Combining Filters

Use `&` to combine filters (AND logic):

```http
GET /documents?status=eq.in-review&total_pages=gt.50&order=uploaded_at.desc
```

Use `or` for OR logic:

```http
GET /documents?or=(status.eq.pending,status.eq.in-review)
```

### Column Selection

Select specific columns to reduce payload:

```http
GET /documents?select=id,title,status,uploaded_at
```

### Sorting

Single column:
```http
GET /documents?order=created_at.desc
```

Multiple columns:
```http
GET /documents?order=status.asc,uploaded_at.desc
```

### Pagination

Use `limit` and `offset`:

```http
GET /documents?limit=20&offset=40
```

Better: Use [Range headers](https://postgrest.org/en/stable/references/api/pagination.html):

```http
GET /documents
Range: 20-39
```

Response includes:
```http
Content-Range: 20-39/150
```

### Counting

Get total count without fetching data:

```http
HEAD /documents
```

Or with data:

```http
GET /documents
Prefer: count=exact
```

Response header:
```http
Content-Range: 0-19/150
```

---

## RPC Functions

Call stored procedures/functions:

```http
POST /rpc/<function_name>
Content-Type: application/json
```

**Body:** Function parameters as JSON

### Available Functions

#### Get Document Sections
```http
POST /rpc/get_document_sections
{"doc_id": "uuid"}
```

#### Get Conversation Messages
```http
POST /rpc/get_conversation_messages
{"conv_id": "uuid"}
```

#### Search Documents
```http
POST /rpc/search_documents
{"search_term": "LNG"}
```

#### Get User Statistics
```http
POST /rpc/get_user_stats
{"user_uuid": "user-id"}
```

**Response:**
```json
{
  "total_documents": 5,
  "documents_in_review": 2,
  "documents_approved": 3,
  "total_conversations": 12,
  "total_bookmarks": 8
}
```

---

## Error Handling

PostgREST returns standard HTTP status codes:

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content (DELETE success) |
| 400 | Bad Request (invalid query) |
| 401 | Unauthorized (missing/invalid JWT) |
| 403 | Forbidden (RLS denied access) |
| 404 | Not Found |
| 416 | Range Not Satisfiable (pagination error) |
| 500 | Internal Server Error |

**Error Response:**
```json
{
  "code": "PGRST301",
  "details": "JWT claims do not match database role",
  "hint": null,
  "message": "JWT expired"
}
```

---

## Security Notes

### RLS Protection
- All queries are automatically filtered by RLS policies
- Users can only see/modify data they're authorized for
- No need for application-level permission checks

### JWT Validation
- PostgREST validates JWT signature using public key
- Expired tokens are automatically rejected
- Invalid audience/issuer rejected

### SQL Injection
- PostgREST parameterizes all queries
- No SQL injection risk

### Best Practices
1. Always use HTTPS in production
2. Set short JWT expiration (15 minutes)
3. Use refresh tokens for long sessions
4. Monitor for suspicious query patterns
5. Rate limit at nginx/proxy layer

---

## Testing

### Using curl

```bash
# Set token
export TOKEN="your-jwt-token-here"

# List documents
curl "http://localhost:3001/document_summaries" \
  -H "Authorization: Bearer $TOKEN"

# Create conversation
curl -X POST "http://localhost:3001/conversations" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Prefer: return=representation" \
  -d '{"title":"Test Conversation"}'
```

### Using httpie

```bash
# Install httpie
pip install httpie

# List users
http GET localhost:3001/users "Authorization:Bearer $TOKEN"

# Create bookmark
http POST localhost:3001/bookmarks \
  "Authorization:Bearer $TOKEN" \
  conversation_id=conv-uuid \
  message_id=msg-uuid \
  tags:='["test"]'
```

### Using Postman

1. Set `Authorization` header: `Bearer <token>`
2. Set `Content-Type: application/json` for POST/PATCH
3. Set `Prefer: return=representation` to get created/updated object back

---

## OpenAPI Documentation

PostgREST generates OpenAPI/Swagger documentation automatically:

```http
GET /
Accept: application/openapi+json
```

View in browser: [http://localhost:3001/](http://localhost:3001/)

---

## Performance Tips

1. **Use column selection** to reduce payload size
2. **Use views** for complex joins instead of client-side merging
3. **Use RPC functions** for complex queries
4. **Use pagination** for large result sets
5. **Use indexes** on frequently filtered columns (already created in migration)
6. **Use `Prefer: count=estimated`** for faster approximate counts

---

## Troubleshooting

### "JWT expired"
- Refresh your access token using `/api/v1/auth/refresh`

### "relation does not exist"
- Check table/view name spelling
- Ensure migration has been run

### "permission denied for table"
- Check your JWT role claim
- Verify RLS policies allow your role to access the table

### "could not parse JWT"
- Verify JWT format: `Bearer <token>`
- Check JWT is not truncated

### Empty results when data exists
- RLS policies are filtering results
- Verify your user ID matches data ownership

---

## Migration from Mock Data

When migrating frontend from mock data:

1. **Update API base URL** from `localhost:8000/api/v1` to `localhost:3001`
2. **Remove `/users`, `/documents` prefixes** (tables are root-level)
3. **Use query params** instead of path params for filters
4. **Add `Authorization` header** to all requests
5. **Handle RLS filtering** gracefully (empty arrays, not 403s)
6. **Use views** for enhanced data (e.g., `document_summaries` instead of `documents`)

---

## Support

For issues or questions:
- Check [PostgREST Documentation](https://postgrest.org/en/stable/)
- Review RLS policies in `infra/docker/migrations/001_init_schema.sql`
- Check database logs: `docker logs plantiq-postgres`
- Check PostgREST logs: `docker logs plantiq-postgrest`

---

**Version:** 1.0.0  
**Last Updated:** March 9, 2026
