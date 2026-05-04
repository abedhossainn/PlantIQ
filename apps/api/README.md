# PlantIQ Backend API

## Overview

The PlantIQ backend provides JWT-based authentication, document processing pipeline orchestration, RAG-powered chat, and real-time WebSocket communication for the LNG plant documentation system.

## Quick Start

### Installation

```bash
cd backend
pip install -e .
```

### Configuration

Copy the repo-root `.env.example` to the repo-root `.env` and configure shared runtime settings there. The backend reads text and vision model identifiers from the repo root so backend and pipeline stay aligned.

### Generate JWT Keys

```bash
python scripts/generate_keys.py
```

### Run Development Server

```bash
uvicorn app.main:app --reload --port 8000
```

## API Documentation

Interactive API docs available at:
- Swagger UI: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc

## Architecture Overview

### Components

1. **Authentication Module** - JWT + LDAP/AD integration
2. **Pipeline Orchestration** - Document processing pipeline management
3. **RAG Chat Service** - Vector search + LLM generation
4. **WebSocket Channels** - Real-time status updates and streaming
5. **File Management** - Upload, storage, and artifact retrieval

### Service Layer

```
Frontend → API Gateway → Services → External Systems
                           ├── PipelineService → HITL Pipeline (subprocess)
                           ├── ChatService → Qdrant + vLLM
                           ├── AuthService → LDAP/AD
                           └── EmbeddingService → sentence-transformers
```

## Authentication Module

### 1. JWT Token Management (`app/core/jwt.py`)

**Features:**
- RS256 asymmetric signing (2048-bit RSA)
- 15-minute access token lifetime
- Token validation with issuer/audience verification
- Key rotation support via `kid` header

**Token Claims:**
```json
{
  "sub": "user-uuid",
  "role": "admin|reviewer|user",
  "email": "user@company.com",
  "dept": "Engineering",
  "scope": ["chat.read", "docs.review"],
  "iss": "plantig-auth",
  "aud": "plantig",
  "iat": 1741478400,
  "exp": 1741479300
}
```

### 2. LDAP Integration (`app/core/ldap.py`)

**Features:**
- LDAP/AD authentication support
- Mock LDAP provider for development
- User attribute retrieval (email, full name, department)

**Mock Users (Development):**
- `admin` / `admin123`
- `reviewer` / `review123`
- `user` / `user123`

### 3. Auth Service (`app/services/auth_service.py`)

**Features:**
- User authentication workflow
- Refresh token management (8-hour lifetime)
- Single-use token rotation
- Automatic user provisioning from LDAP

**Role-Based Scopes:**
- **admin**: `chat.read`, `docs.review`, `docs.upload`, `admin.manage`
- **reviewer**: `chat.read`, `docs.review`, `docs.upload`
- **user**: `chat.read`

### 4. Security Dependencies (`app/core/security.py`)

FastAPI dependencies for authentication and authorization:
- `get_current_user_id`: Extract user UUID from JWT
- `get_current_user_role`: Extract user role from JWT
- `require_admin`: Require admin role
- `require_reviewer_or_admin`: Require reviewer or admin role
- `get_token_payload`: Get full JWT payload

### 5. Auth Endpoints (`app/api/auth.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/auth/login` | Authenticate user via LDAP, issue tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token using refresh token |
| POST | `/api/v1/auth/logout` | Revoke refresh token |
| GET | `/api/v1/auth/me` | Get current user information |

## Setup

### 1. Generate JWT Keys

```bash
cd backend
python scripts/generate_keys.py --output-dir /secrets
```

This creates:
- `/secrets/jwt-private.pem` - Private key for signing (FastAPI only)
- `/secrets/jwt-public.pem` - Public key for verification (FastAPI + PostgREST)

### 2. Configure Environment

Copy the repo-root `.env.example` to the repo-root `.env` and update the shared runtime settings there.

Key variables:
- `DATABASE_URL`: PostgreSQL connection string
- `JWT_PRIVATE_KEY_PATH`: Path to private key
- `JWT_PUBLIC_KEY_PATH`: Path to public key
- `USE_MOCK_LDAP`: Set to `true` for development

### 3. Run Tests

```bash
cd backend
python tests/test_auth.py
```

### 4. Start Server

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API documentation available at: `http://localhost:8000/api/docs`

## Authentication Flow

### Login Flow

1. **Frontend** → POST `/api/v1/auth/login` with username/password
2. **Backend** → Authenticate against LDAP/AD
3. **Backend** → Get or create user in PostgreSQL
4. **Backend** → Generate access token (JWT) and refresh token (UUID)
5. **Backend** → Store refresh token in database
6. **Backend** → Return access token + set refresh token as HttpOnly cookie
7. **Frontend** → Store access token in memory/state

### Token Refresh Flow

1. **Frontend** → POST `/api/v1/auth/refresh` (refresh token in cookie)
2. **Backend** → Validate refresh token from database
3. **Backend** → Revoke old refresh token (single-use)
4. **Backend** → Generate new access token and new refresh token
5. **Backend** → Return new access token + set new refresh token cookie

### Logout Flow

1. **Frontend** → POST `/api/v1/auth/logout`
2. **Backend** → Revoke refresh token in database
3. **Backend** → Clear refresh token cookie
4. **Frontend** → Clear access token from memory

### Protected Endpoint Access

1. **Frontend** → Request with `Authorization: Bearer <access_token>`
2. **Backend** → Validate JWT signature and claims
3. **Backend** → Extract user ID and role from token
4. **Backend** → Execute request with user context
5. **Backend** → Return response

## Security Features

### Token Security
- **RS256 Signing**: Asymmetric keys prevent token forgery
- **Short Expiration**: 15-minute access tokens limit exposure
- **HttpOnly Cookies**: Refresh tokens protected from XSS
- **Single-Use Rotation**: Refresh tokens can only be used once

### Database Security
- **Token Hashing**: Refresh tokens stored as SHA-256 hashes
- **Automatic Expiration**: Expired tokens are invalidated
- **Revocation Support**: Tokens can be revoked on logout

### LDAP Security
- **Credential Validation**: Passwords never stored locally
- **Attribute Mapping**: User data synced from LDAP/AD
- **Mock Mode**: Safe development without LDAP access

## PostgreSQL RLS Integration

The JWT token contains claims that map to PostgreSQL roles:

**JWT → PostgreSQL Role Mapping:**
- `"admin"` → `plantig_admin` (full access)
- `"reviewer"` → `plantig_reviewer` (documents + sections)
- `"user"` → `plantig_user` (chat + bookmarks)

**RLS Helper Functions:**
- `plantig_uid()`: Returns `UUID` from JWT `sub` claim
- `plantig_role()`: Returns `TEXT` from JWT `role` claim

See [Database Migrations README](../../infra/docker/migrations/README.md) for full RLS policy details.

## Usage Examples

### Login

```python
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123"
        }
    )
    data = response.json()
    access_token = data["access_token"]
```

### Access Protected Endpoint

```python
headers = {"Authorization": f"Bearer {access_token}"}

response = await client.get(
    "http://localhost:8000/api/v1/auth/me",
    headers=headers
)
user_info = response.json()
```

### Refresh Token

```python
# Refresh token is automatically sent via cookie
response = await client.post("http://localhost:8000/api/v1/auth/refresh")
new_access_token = response.json()["access_token"]
```

### Logout

```python
await client.post("http://localhost:8000/api/v1/auth/logout")
```

## Troubleshooting

### "JWT key file not found"
- Run `python scripts/generate_keys.py` to generate keys
- Verify `JWT_PRIVATE_KEY_PATH` and `JWT_PUBLIC_KEY_PATH` in `.env`

### "Invalid authentication credentials"
- Check token expiration (15 minutes)
- Verify token is passed in `Authorization: Bearer <token>` header
- Check JWT signature with public key

### "LDAP authentication failed"
- In development: Verify `USE_MOCK_LDAP=true` in `.env`
- In production: Check LDAP server URL and bind credentials

### "Database connection failed"
- Verify PostgreSQL is running
- Check `DATABASE_URL` in `.env`
- Run database migrations: `psql -f infra/docker/migrations/001_init_schema.sql`

## Production Checklist

- [ ] Generate production RSA keys (2048-bit minimum)
- [ ] Store private key securely (never commit to git)
- [ ] Configure real LDAP/AD connection
- [ ] Set strong `SECRET_KEY` in environment
- [ ] Enable HTTPS for production API
- [ ] Configure CORS for production frontend domain
- [ ] Set up monitoring and alerting
- [ ] Implement rate limiting on auth endpoints
- [ ] Set up audit logging for authentication events
- [ ] Test token rotation and revocation
- [ ] Document LDAP group → role mapping
- [ ] Test RLS policies in PostgreSQL

---

## Pipeline Orchestration Module

### Overview

The pipeline orchestration module manages document processing through the HITL (Human-in-the-Loop) pipeline, including:
- Document upload and validation
- Subprocess pipeline execution
- Real-time status monitoring
- Artifact retrieval

### Pipeline Service (`app/services/pipeline_service.py`)

**Features:**
- Async subprocess management with timeout protection
- Background task monitoring
- Database-backed status tracking
- Artifact path management

### Pipeline Endpoints (`app/api/pipeline.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/documents/upload` | Upload PDF or XLSX/XLS and trigger source-aware pipeline routing |
| GET | `/api/v1/documents/{id}/status` | Get processing status |
| POST | `/api/v1/documents/{id}/reprocess` | Trigger reprocessing |
| GET | `/api/v1/documents/{id}/artifacts/{type}` | Download artifacts |

### Source-aware routing (PDF vs XLSX)

- **PDF uploads** stay on the existing stable PDF processing path.
- **XLSX/XLS uploads** use a dedicated spreadsheet path (including structured-relation extraction and JSON-first retrieval artifacts).
- **XLSX optimized review flow** may skip editable optimized-review and route directly to QA gates.
- **Rollback posture:** XLSX behavior is additive and flag-gated; disabling XLSX/CE flags does not alter PDF behavior.

### Document Upload Example

```python
import httpx

files = {"file": ("document.pdf", open("document.pdf", "rb"), "application/pdf")}
data = {
    "title": "LNG Operating Procedures",
    "version": "2.1",
    "system": "Process Control",
    "document_type": "SOP"
}

async with httpx.AsyncClient() as client:
    response = await client.post(
        "http://localhost:8000/api/v1/documents/upload",
        files=files,
        data=data,
        headers={"Authorization": f"Bearer {access_token}"}
    )
    result = response.json()
    document_id = result["document_id"]
    print(f"Pipeline started: {result['message']}")
```

### Pipeline Status Example

```python
response = await client.get(
    f"http://localhost:8000/api/v1/documents/{document_id}/status",
    headers={"Authorization": f"Bearer {access_token}"}
)
status = response.json()
print(f"Status: {status['status']}, Progress: {status['progress']}%")
```

### Artifact Download Example

```python
response = await client.get(
    f"http://localhost:8000/api/v1/documents/{document_id}/artifacts/validation",
    headers={"Authorization": f"Bearer {access_token}"}
)
with open("validation_report.json", "wb") as f:
    f.write(response.content)
```

### Available Artifact Types

- `validation`: VLM validation report (JSON)
- `manifest`: Document lineage manifest (JSON)
- `qa_report`: QA metrics and decision (JSON)
- `review`: Review workspace (directory)
- `table_figure`: Table/figure analysis (JSON)
- `structured_relations`: XLSX structured relation artifact (JSON)
- `retrieval_chunks`: Optimized retrieval chunks artifact (JSON)

---

## RAG Chat Module

### Overview

The RAG (Retrieval-Augmented Generation) module provides intelligent chat capabilities powered by:
- Vector similarity search (Qdrant)
- Text generation (vLLM)
- Embedding generation (sentence-transformers)

### Chat Service (`app/services/chat_service.py`)

**RAG Pipeline:**
1. Generate query embedding
2. Search Qdrant for relevant document chunks
3. Build prompt with retrieved context
4. Generate LLM response
5. Extract citations
6. Save conversation to database

**Features:**
- Conversation management
- Citation extraction with relevance scoring
- Context truncation to respect token limits
- Document and system filtering

### Chat Endpoints (`app/api/chat.py`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/query` | Submit RAG query (non-streaming) |
| POST | `/api/v1/chat/stream` | Submit RAG query (streaming SSE) |

### Chat Query Example

```python
query_request = {
    "query": "What is the recommended LNG storage temperature?",
    "conversation_id": None,  # Creates new conversation
    "document_filters": [],  # Search all documents
    "system_filters": ["Process Control"]  # Filter by system
}

response = await client.post(
    "http://localhost:8000/api/v1/chat/query",
    json=query_request,
    headers={"Authorization": f"Bearer {access_token}"}
)

result = response.json()
print(f"Answer: {result['content']}")
print(f"Citations: {len(result['citations'])}")
for citation in result['citations']:
    print(f"  - {citation['document_title']}, Page {citation['page_number']}")
```

### Streaming Chat Example

```python
async with httpx.AsyncClient() as client:
    async with client.stream(
        "POST",
        "http://localhost:8000/api/v1/chat/stream",
        json=query_request,
        headers={"Authorization": f"Bearer {access_token}"}
    ) as response:
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                token = line[6:]  # Remove "data: " prefix
                if token == "[DONE]":
                    break
                print(token, end="", flush=True)
```

### External Services Configuration

**Qdrant (Vector Database):**
```bash
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=plantig_documents
```

**vLLM (LLM Inference):**
```bash
VLLM_HOST=localhost
VLLM_PORT=8001
TEXT_MODEL_ID=Qwen/Qwen3-4B-Instruct
VLLM_MAX_TOKENS=2048
VLLM_TEMPERATURE=0.7
```

**Embedding Model:**
```bash
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
EMBEDDING_DIM=1024
```

---

## WebSocket Channels

### Overview

Real-time bidirectional communication for:
- Pipeline status updates
- Chat token streaming
- Live progress monitoring

### WebSocket Manager (`app/core/websocket.py`)

**Features:**
- Channel-based routing
- Connection pooling
- Thread-safe operations
- Automatic cleanup on disconnect

### WebSocket Endpoints (`app/api/websocket.py`)

| Endpoint | Description |
|----------|-------------|
| `/ws/pipeline/{document_id}` | Pipeline status updates |
| `/ws/chat/{conversation_id}` | Chat streaming |

### Pipeline WebSocket Example

```javascript
// JavaScript/Frontend example
const token = "your-jwt-token";
const documentId = "doc-uuid";
const ws = new WebSocket(`ws://localhost:8000/ws/pipeline/${documentId}?token=${token}`);

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
        case "connected":
            console.log("Connected to pipeline channel");
            break;
        case "progress":
            console.log(`${message.stage}: ${message.progress}%`);
            updateProgressBar(message.progress);
            break;
        case "stage-complete":
            console.log(`Stage complete: ${message.stage} (${message.duration}s)`);
            break;
        case "complete":
            console.log("Pipeline complete!");
            showArtifacts(message.artifacts);
            break;
        case "error":
            console.error(`Pipeline error: ${message.error}`);
            break;
        case "heartbeat":
            ws.send(JSON.stringify({ type: "pong" }));
            break;
    }
};

ws.onerror = (error) => console.error("WebSocket error:", error);
ws.onclose = () => console.log("WebSocket closed");

// Send ping to keep connection alive
setInterval(() => {
    ws.send(JSON.stringify({ type: "ping" }));
}, 25000);
```

### Chat WebSocket Example

```javascript
const conversationId = "conv-uuid";
const ws = new WebSocket(`ws://localhost:8000/ws/chat/${conversationId}?token=${token}`);

ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
        case "connected":
            console.log("Connected to chat channel");
            break;
        case "token":
            appendToken(message.content);
            break;
        case "citation":
            addCitation(message.citation);
            break;
        case "complete":
            showAllCitations(message.citations);
            break;
        case "error":
            showError(message.error);
            break;
    }
};
```

### WebSocket Message Types

**Pipeline Channel:**
- `connected`: Initial connection confirmation
- `progress`: Stage progress update (0-100%)
- `stage-complete`: Stage finished with duration
- `error`: Pipeline execution error
- `complete`: Pipeline fully complete with artifacts
- `heartbeat`: Keepalive signal (every 30s)

**Chat Channel:**
- `connected`: Initial connection confirmation
- `token`: Individual LLM token during generation
- `citation`: Source document citation
- `complete`: Generation complete with all citations
- `error`: Generation error
- `heartbeat`: Keepalive signal (every 30s)

---

## Configuration Reference

### Required Services

1. **PostgreSQL** - Database (port 5432)
2. **Qdrant** - Vector database (port 6333)
3. **vLLM** - LLM inference server (port 8001)
4. **LDAP/AD** - Authentication (port 389)

### Environment Variables

See `.env.example` for complete list. Key categories:

**Database:**
- `DATABASE_URL`: PostgreSQL connection string

**JWT:**
- `JWT_PRIVATE_KEY_PATH`: RSA private key path
- `JWT_PUBLIC_KEY_PATH`: RSA public key path
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`: Access token lifetime (default: 15)

**LDAP:**
- `LDAP_SERVER`: LDAP server URL
- `LDAP_BASE_DN`: Base DN for user search
- `LDAP_MOCK`: Enable mock LDAP for development

**Pipeline:**
- `PIPELINE_WORK_DIR`: Working directory for pipeline artifacts
- `PIPELINE_PYTHON_PATH`: Python interpreter for pipeline subprocess
- `PIPELINE_TIMEOUT_SECONDS`: Maximum pipeline execution time (default: 7200)
- `PIPELINE_XLSX_DISPATCH_ENABLED`: Enable/disable XLSX dispatch path
- `PIPELINE_XLSX_STRUCTURED_RELATIONS_ENABLED` (alias `PIPELINE_CE_EXTRACTION_ENABLED`): Enable structured relation extraction for XLSX
- `PIPELINE_XLSX_RETRIEVAL_ENABLED` (alias `PIPELINE_CE_RETRIEVAL_ENABLED`): Enable XLSX relation-aware retrieval path

**File Storage:**
- `UPLOAD_DIR`: Source upload directory (PDF/XLSX)
- `ARTIFACTS_DIR`: Pipeline artifacts directory
- `MAX_UPLOAD_SIZE_MB`: Maximum file size (default: 100)

**Qdrant:**
- `QDRANT_HOST`: Qdrant server host
- `QDRANT_PORT`: Qdrant server port
- `QDRANT_COLLECTION`: Collection name for documents

**Shared model contract:**
- `VLLM_HOST`: vLLM server host
- `VLLM_PORT`: vLLM server port
- `TEXT_MODEL_ID`: Active text model identifier (repo-root `.env` authority)
- `VISION_MODEL_ID`: Active vision model identifier (repo-root `.env` authority)
- `VLLM_MAX_TOKENS`: Maximum generation tokens
- `VLLM_TEMPERATURE`: Sampling temperature

**RAG:**
- `RAG_TOP_K`: Number of chunks to retrieve (default: 5)
- `RAG_SCORE_THRESHOLD`: Minimum relevance score (default: 0.7)
- `RAG_MAX_CONTEXT_LENGTH`: Maximum context characters (default: 8000)

---

## Development Workflow

### 1. Setup Dependencies

```bash
# Install backend dependencies
cd backend
pip install -e .

# Install pipeline dependencies
cd ../pipeline
pip install -e .
```

### 2. Configure Services

```bash
# Start PostgreSQL
docker-compose up -d postgres

# Start Qdrant
docker-compose up -d qdrant

# (Optional) Start vLLM server
# See vLLM documentation for setup
```

### 3. Generate Keys

```bash
python backend/scripts/generate_keys.py
```

### 4. Run Migrations

```bash
psql $DATABASE_URL -f infra/docker/migrations/001_init_schema.sql
psql $DATABASE_URL -f infra/docker/migrations/002_postgrest_views.sql
```

### 5. Start Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

### 6. Test Endpoints

Visit http://localhost:8000/api/docs for interactive API documentation.

---

## Testing

### Unit Tests

```bash
cd backend
pytest tests/test_auth.py
pytest tests/test_postgrest.py
```

### Integration Tests

```bash
# Run full integration test suite
pytest tests/integration/
```

### Manual Testing

```bash
# Test authentication
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "admin123"}'

# Test document upload (PDF shown; XLSX/XLS also supported)
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer <token>" \
  -F "file=@document.pdf" \
  -F "title=Test Document"

# Test RAG query
curl -X POST http://localhost:8000/api/v1/chat/query \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is LNG?"}'
```

---

## Monitoring and Logging

### Log Levels

```bash
# Set in environment
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
```

### Health Checks

```bash
# Backend health
curl http://localhost:8000/health

# vLLM health  
curl http://localhost:8001/health

# Qdrant health
curl http://localhost:6333
```

### Metrics

Key metrics to monitor:
- Request latency (p50, p95, p99)
- Pipeline success/failure rate
- WebSocket connection count
- Qdrant query performance
- vLLM generation time
- Token refresh rate
- Authentication failures

---

## Troubleshooting

### Pipeline Issues

**"Pipeline timeout":**
- Increase `PIPELINE_TIMEOUT_SECONDS`
- Check pipeline subprocess logs
- Verify GPU/CPU resources

**"Artifact not found":**
- Check `ARTIFACTS_DIR` path
- Verify pipeline completed successfully
- Check file permissions

### RAG Issues

**"No relevant contexts found":**
- Verify documents are indexed in Qdrant
- Check `RAG_SCORE_THRESHOLD` setting
- Try lower threshold or different query phrasing

**"vLLM generation failed":**
- Check vLLM server is running
- Verify `VLLM_HOST` and `VLLM_PORT`
- Check vLLM server logs

**"Embedding generation failed":**
- Verify `EMBEDDING_MODEL` is downloaded
- Check sentence-transformers cache
- Verify sufficient disk space

### WebSocket Issues

**"Connection closed immediately":**
- Verify JWT token is valid
- Check token is passed in query parameter
- Check WebSocket URL format

**"No messages received":**
- Verify channel name matches document/conversation ID
- Check heartbeat is working
- Verify backend is sending messages

---

## Security Best Practices

1. **Never commit secrets** - Use environment variables
2. **Rotate JWT keys** - Use `kid` header for zero-downtime rotation
3. **Enable HTTPS** - All production traffic over TLS
4. **Validate uploads** - Check file types and sizes
5. **Rate limiting** - Implement at infrastructure layer
6. **Monitor logs** - Alert on authentication failures
7. **Regular updates** - Keep dependencies current
8. **Least privilege** - Use PostgreSQL RLS policies

---

## Additional Resources

- [Architecture Documentation](../../PlantIQ_Integration_Architecture.md)
- [Database Migrations](../../infra/docker/migrations/README.md)
- [PostgREST API](../../docs/api/POSTGREST_API.md)
- [Project Status](../../PROJECT_STATUS.md)
- [T-008/T-009 Completion Summary](../../T008_T009_COMPLETION_SUMMARY.md)
