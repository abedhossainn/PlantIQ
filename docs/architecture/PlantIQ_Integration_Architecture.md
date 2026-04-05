# PlantIQ - Frontend-Backend Integration Architecture

**Created:** March 9, 2026  
**Status:** Integration Architecture Plan  
**Purpose:** Connect Next.js Hi-Fi Prototype with FastAPI Backend & HITL Pipeline

---

## Executive Summary

This architecture plan defines a comprehensive integration strategy for connecting the PlantIQ frontend (Next.js TypeScript) with the backend systems (FastAPI middleware, HITL pipeline, Vector DB). The frontend is currently a hi-fi prototype using mock data, while the backend API layer is scaffolded but empty. The HITL document processing pipeline is fully implemented and operational.

This plan is now updated to a **pragmatic hybrid architecture**:
- **PostgreSQL remains the primary system of record**
- **PostgREST is adopted for data-centric modules** (users, documents, sections/review metadata, bookmarks, conversations/messages)
- **FastAPI remains for orchestration-heavy modules** (RAG, pipeline triggering, streaming, integration workflows)
- Delivery is handled as a **phased enhancement**, not a rewrite

The integration strategy follows a **clean, layered approach** with clear separation between:
1. **Presentation Layer** (Next.js UI)
2. **API Gateway Layer** (FastAPI REST + WebSocket)
3. **Service Layer** (Business logic, RAG orchestration)
4. **Data Layer** (PostgreSQL, Qdrant, File System)
5. **Processing Layer** (HITL Pipeline)

---

## System Context

```mermaid
flowchart TB
    subgraph ClientLayer["🖥️ CLIENT LAYER"]
        User([User: Technician/Reviewer/Admin])
        Browser[Next.js React App<br/>TypeScript + Shadcn UI]
    end
    
    subgraph BackendLayer["⚙️ BACKEND LAYER - TO BE IMPLEMENTED"]
        Gateway[FastAPI Gateway<br/>REST + WebSocket]
        AuthService[Auth Service<br/>JWT + LDAP]
        ChatService[Chat Service<br/>RAG Orchestration]
        DocService[Document Service<br/>Upload + Status]
        ReviewService[Review Service<br/>Section Management]
    end
    
    subgraph DataLayer["💾 DATA LAYER"]
        Postgres[(PostgreSQL<br/>Users, Metadata)]
        Qdrant[(Qdrant Vector DB<br/>Embeddings)]
        FileStore[(File System<br/>PDFs, Workspaces)]
    end
    
    subgraph ProcessingLayer["🔄 PROCESSING LAYER - EXISTING"]
        Pipeline[HITL Pipeline<br/>Python Modules]
        VLM[VLM Models<br/>Qwen2.5-VL/32B]
    end
    
    User <--> Browser
    Browser <--> Gateway
    Gateway --> AuthService
    Gateway --> ChatService
    Gateway --> DocService
    Gateway --> ReviewService
    
    AuthService --> Postgres
    ChatService --> Qdrant
    DocService --> Postgres
    DocService --> FileStore
    DocService --> Pipeline
    ReviewService --> Postgres
    ReviewService --> FileStore
    
    Pipeline --> FileStore
    Pipeline --> VLM
    ChatService --> VLM

    style ClientLayer fill:#e8f4f8
    style BackendLayer fill:#fff4e1
    style DataLayer fill:#f0f0f0
    style ProcessingLayer fill:#e1f5e1
```

**Overview:** The system architecture shows the integration between the existing frontend prototype, the to-be-implemented backend API layer, existing data stores, and the operational HITL pipeline.

**Key Components:**
- **Frontend**: Next.js 16 with TypeScript, Shadcn UI, mock data to be replaced with real API calls
- **Backend Gateway**: FastAPI with REST endpoints and WebSocket for real-time updates (to be implemented)
- **Services**: Modular business logic for auth, chat, documents, and review (to be implemented)
- **Data Stores**: PostgreSQL for relational data, Qdrant for vectors, file system for artifacts
- **HITL Pipeline**: Fully implemented Python pipeline for document processing

**Relationships:**
- Frontend makes REST/WebSocket calls to Gateway
- Gateway delegates to specialized services
- Services interact with data stores and processing pipeline
- Pipeline writes artifacts to file system

**Design Decisions:**
- **Single Responsibility**: Each service handles one domain
- **API Gateway Pattern**: Centralized entry point for all frontend requests
- **Event-Driven**: WebSocket for pipeline status updates
- **Separation of Concerns**: Clear boundaries between layers

---

## Architecture Overview

The integration follows a **layered, service-oriented architecture** with these principles:

1. **Clean API Design**: RESTful endpoints following OpenAPI 3.0 specification
2. **Real-Time Updates**: WebSocket for live pipeline progress and chat streaming
3. **Modular Services**: Independent services for auth, chat, documents, and review
4. **Type Safety**: Pydantic models for request/response validation matching TypeScript types
5. **Security First**: JWT authentication, role-based access control, input sanitization
6. **Scalability**: Stateless services, connection pooling, async operations
7. **Observability**: Structured logging, error tracking, performance metrics

Updated boundary decisions for implementation:
- **PostgREST owns CRUD/data access** for PostgreSQL-backed entities
- **FastAPI owns workflows and integrations** requiring business orchestration, async execution, and streaming
- **Frontend migration path**: move from mock data to PostgREST-backed resources first, then wire FastAPI orchestration endpoints

---

## Hybrid API Boundary (PostgREST + FastAPI)

```mermaid
flowchart LR
  FE[Next.js Frontend]
  PGR[PostgREST\nData API]
  FA[FastAPI\nOrchestration API]
  PG[(PostgreSQL)]
  QD[(Qdrant)]
  HP[HITL Pipeline]
  VLM[vLLM/Ollama]

  FE --> PGR
  FE --> FA

  PGR --> PG

  FA --> PG
  FA --> QD
  FA --> HP
  FA --> VLM
```

### Endpoint Ownership Matrix

| Domain | Endpoint Pattern | Owner | Rationale |
|---|---|---|---|
| User Admin | `/users`, `/roles`, `/departments` | PostgREST | Pure relational CRUD + policy-driven access |
| Documents Metadata | `/documents`, `/documents?status=...` | PostgREST | Filter/sort/paginate directly from PostgreSQL |
| Review Metadata | `/document_sections`, `/section_versions` | PostgREST | Versioned CRUD, checklist updates, audit reads |
| Bookmarks | `/bookmarks` | PostgREST | Straightforward user-scoped CRUD |
| Conversations/Messages | `/conversations`, `/chat_messages` | PostgREST | Data persistence + query access |
| Auth Session Bootstrap | `/api/v1/auth/*` | FastAPI | LDAP integration + token issuance logic |
| Pipeline Trigger/Control | `/api/v1/pipeline/*`, `/api/v1/documents/{id}/reprocess` | FastAPI | Subprocess orchestration and error handling |
| RAG Query | `/api/v1/chat/query` | FastAPI | Retrieval + prompt assembly + model invocation |
| Streaming | `/ws/chat/*`, `/ws/pipeline/*` | FastAPI | Real-time token and status streaming |
| Artifact Download | `/api/v1/documents/{id}/artifacts` | FastAPI | Filesystem integration and access checks |

### Security Boundary

- PostgREST uses PostgreSQL role/RLS policies as the authorization source of truth.
- FastAPI issues JWT and forwards claims-compatible context for PostgreSQL role mapping.
- Sensitive orchestration endpoints remain behind FastAPI middleware and service-level controls.

---

## Component Architecture

```mermaid
flowchart TB
    subgraph Frontend["🎨 FRONTEND (Existing - Mock Data)"]
        Pages[Next.js Pages<br/>Login, Chat, Admin]
        Components[Shadcn Components<br/>UI Library]
        Context[Auth Context<br/>State Management]
        MockData[Mock Data Store<br/>TO BE REPLACED]
        Types[TypeScript Types<br/>Shared Interfaces]
    end
    
    subgraph Backend["⚙️ BACKEND API (TO BE BUILT)"]
        subgraph APILayer["API Layer"]
            RestAPI[REST Endpoints<br/>/api/v1/*]
            WSEndpoint[WebSocket<br/>/ws/pipeline, /ws/chat]
            Middleware[Middleware<br/>Auth, CORS, Logging]
        end
        
        subgraph ServiceLayer["Service Layer"]
            AuthSvc[AuthService<br/>Login, JWT, LDAP]
            ChatSvc[ChatService<br/>RAG, Streaming]
            DocSvc[DocumentService<br/>Upload, Status]
            ReviewSvc[ReviewService<br/>Sections, Approval]
            BookmarkSvc[BookmarkService<br/>Save, Retrieve]
        end
        
        subgraph RepositoryLayer["Repository Layer"]
            UserRepo[UserRepository<br/>CRUD Users]
            DocRepo[DocumentRepository<br/>CRUD Documents]
            ChatRepo[ConversationRepository<br/>CRUD Chats]
            ReviewRepo[ReviewRepository<br/>CRUD Sections]
        end
        
        subgraph IntegrationLayer["Integration Layer"]
            PipelineClient[Pipeline Client<br/>Subprocess Manager]
            VectorDBClient[Qdrant Client<br/>Embed + Search]
            LDAPClient[LDAP Client<br/>AD Integration]
        end
    end
    
    subgraph DataStores["💾 DATA STORES"]
        DB[(PostgreSQL)]
        VDB[(Qdrant)]
        Files[(File System)]
    end
    
    subgraph External["🔄 EXTERNAL SYSTEMS"]
        HitlPipeline[HITL Pipeline<br/>Python Modules]
        AD[Active Directory<br/>LDAP Server]
    end
    
    Pages --> RestAPI
    Pages --> WSEndpoint
    Context --> RestAPI
    MockData -.Replace.-> RestAPI
    
    RestAPI --> Middleware
    WSEndpoint --> Middleware
    Middleware --> ServiceLayer
    
    AuthSvc --> UserRepo
    AuthSvc --> LDAPClient
    ChatSvc --> ChatRepo
    ChatSvc --> VectorDBClient
    DocSvc --> DocRepo
    DocSvc --> PipelineClient
    ReviewSvc --> ReviewRepo
    ReviewSvc --> DocRepo
    BookmarkSvc --> ChatRepo
    
    UserRepo --> DB
    DocRepo --> DB
    ChatRepo --> DB
    ReviewRepo --> DB
    
    VectorDBClient --> VDB
    PipelineClient --> Files
    PipelineClient --> HitlPipeline
    LDAPClient --> AD
    
    HitlPipeline --> Files

    style Frontend fill:#e8f4f8
    style Backend fill:#fff4e1
    style DataStores fill:#f0f0f0
    style External fill:#e1f5e1
```

**Overview:** Detailed component architecture showing the complete system decomposition from frontend to external systems.

**Key Components:**

**Frontend Layer (Existing):**
- **Pages**: Login, Chat, Admin/Documents, Bookmarks
- **Components**: Reusable UI components from Shadcn
- **Mock Data**: Currently provides fake data - will be replaced with API calls
- **Types**: TypeScript interfaces for data structures

**Backend API Layer (To Be Built):**
- **REST Endpoints**: CRUD operations for all entities
- **WebSocket Endpoints**: Real-time updates for pipeline and chat
- **Middleware**: Cross-cutting concerns (auth, logging, error handling)

**Service Layer (To Be Built):**
- **AuthService**: Handles login, JWT generation/validation, LDAP integration
- **ChatService**: Orchestrates RAG queries, manages streaming responses
- **DocumentService**: Manages document uploads, triggers pipeline, tracks status
- **ReviewService**: Manages section review workflow, approvals
- **BookmarkService**: CRUD operations for saved conversations

**Repository Layer (To Be Built):**
- Data access layer abstractions
- SQLAlchemy ORM for PostgreSQL
- Encapsulates database queries

**Integration Layer (To Be Built):**
- **PipelineClient**: Python subprocess manager for HITL pipeline
- **VectorDBClient**: Qdrant SDK for embeddings and similarity search
- **LDAPClient**: LDAP3 library for Active Directory authentication

**Relationships:**
- Frontend makes API calls to REST/WebSocket endpoints
- Middleware processes all requests (auth, logging, error handling)
- Services contain business logic and orchestrate workflows
- Repositories handle data persistence
- Integration layer communicates with external systems

**Design Decisions:**
1. **Layered Architecture**: Clear separation of concerns, testable, maintainable
2. **Repository Pattern**: Decouples business logic from data access
3. **Service Layer**: Encapsulates complex workflows (RAG, pipeline management)
4. **Client Abstractions**: External systems accessed through well-defined interfaces

**NFR Considerations:**
- **Scalability**: Services are stateless, can be horizontally scaled
- **Performance**: Async operations, connection pooling, caching
- **Security**: JWT auth, role-based access control, input validation
- **Reliability**: Error handling, retries, circuit breakers for external calls
- **Maintainability**: Clear boundaries, dependency injection, testable components

**Trade-offs:**
- More layers = more complexity but better separation and testability
- Async operations = better performance but harder debugging
- Repository pattern = additional abstraction but decoupled data access

**Risks and Mitigations:**
- **Pipeline subprocess failures**: Implement robust error handling, status tracking, retry logic
- **WebSocket connection drops**: Implement reconnection logic, fallback to polling
- **LDAP integration issues**: Provide fallback local auth for development/testing

---

## Data Flow Diagram

### Flow 1: User Authentication

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Gateway
    participant AuthService
    participant LDAP
    participant DB
    
    User->>Frontend: Enter credentials
    Frontend->>Gateway: POST /api/v1/auth/login
    Gateway->>AuthService: authenticate(credentials)
    AuthService->>LDAP: Verify AD credentials
    LDAP-->>AuthService: User info
    AuthService->>DB: Get/Create user record
    DB-->>AuthService: User entity
    AuthService->>AuthService: Generate JWT token
    AuthService-->>Gateway: {token, user}
    Gateway-->>Frontend: 200 OK + Set-Cookie
    Frontend->>Frontend: Store token, update AuthContext
    Frontend-->>User: Redirect to dashboard
```

### Flow 2: Document Upload & Processing

```mermaid
sequenceDiagram
    participant Admin
    participant Frontend
    participant Gateway
    participant DocService
    participant DB
    participant FileStore
    participant Pipeline
    participant WebSocket
    
    Admin->>Frontend: Upload PDF
    Frontend->>Gateway: POST /api/v1/documents/upload
    Gateway->>DocService: create_document(file, metadata)
    DocService->>FileStore: Save PDF to raw/
    DocService->>DB: INSERT document (status: uploading)
    DB-->>DocService: Document ID
    DocService-->>Gateway: {documentId, status}
    Gateway-->>Frontend: 201 Created
    
    DocService->>Pipeline: subprocess.Popen([HITL pipeline])
    Pipeline->>Pipeline: Stage 1: Lineage
    Pipeline->>WebSocket: Progress update (Stage 1)
    WebSocket-->>Frontend: Live status update
    
    Pipeline->>Pipeline: Stage 2: VLM Validation
    Pipeline->>WebSocket: Progress update (Stage 2)
    WebSocket-->>Frontend: Live status update
    
    Pipeline->>FileStore: Save artifacts
    Pipeline->>DB: Update status (validation-complete)
    Pipeline-->>DocService: Completion callback
    
    DocService->>WebSocket: Final status
    WebSocket-->>Frontend: Document ready for review
    Frontend-->>Admin: Notification
```

### Flow 3: RAG Chat Query

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Gateway
    participant ChatService
    participant DB
    participant Qdrant
    participant vLLM
    
    User->>Frontend: Type question
    Frontend->>Gateway: POST /api/v1/chat/query
    Gateway->>ChatService: process_query(question, conversationId)
    
    ChatService->>DB: INSERT message (role: user)
    ChatService->>ChatService: Generate query embedding
    ChatService->>Qdrant: Search similar chunks (top_k=5)
    Qdrant-->>ChatService: Relevant chunks + metadata
    
    ChatService->>ChatService: Build RAG prompt with context
    ChatService->>vLLM: Stream LLM generation
    
    loop Streaming tokens
        vLLM-->>ChatService: Token chunk
        ChatService-->>Gateway: SSE event
        Gateway-->>Frontend: Display token
        Frontend-->>User: Real-time response
    end
    
    vLLM-->>ChatService: Complete response
    ChatService->>DB: INSERT message (role: assistant, citations)
    ChatService-->>Gateway: {message, citations}
    Gateway-->>Frontend: 200 OK
    Frontend-->>User: Show citations
```

### Flow 4: Section Review Workflow

```mermaid
sequenceDiagram
    participant Reviewer
    participant Frontend
    participant Gateway
    participant ReviewService
    participant DB
    participant FileStore
    
    Reviewer->>Frontend: Open document for review
    Frontend->>Gateway: GET /api/v1/documents/{id}/sections
    Gateway->>ReviewService: get_sections(documentId)
    ReviewService->>DB: Query sections
    DB-->>ReviewService: List of sections
    ReviewService-->>Gateway: {sections}
    Gateway-->>Frontend: 200 OK
    Frontend-->>Reviewer: Display section list
    
    Reviewer->>Frontend: Edit section content
    Reviewer->>Frontend: Mark checklist items
    Frontend->>Gateway: PATCH /api/v1/sections/{id}
    Gateway->>ReviewService: update_section(id, changes)
    ReviewService->>DB: UPDATE section
    ReviewService->>FileStore: Save version (v2, v3...)
    DB-->>ReviewService: Updated section
    ReviewService-->>Gateway: {section}
    Gateway-->>Frontend: 200 OK
    Frontend-->>Reviewer: Show saved changes
    
    Reviewer->>Frontend: Approve section
    Frontend->>Gateway: POST /api/v1/sections/{id}/approve
    Gateway->>ReviewService: approve_section(id)
    ReviewService->>DB: UPDATE section (status: approved)
    ReviewService->>DB: Check if all sections approved
    
    alt All sections approved
        ReviewService->>DB: UPDATE document (status: review-complete)
        ReviewService->>FileStore: Trigger reformatting (Stage 10)
    end
    
    ReviewService-->>Gateway: {section, documentStatus}
    Gateway-->>Frontend: 200 OK
    Frontend-->>Reviewer: Show approval confirmation
```

**Explanations:**

**Flow 1: Authentication**
- User enters credentials in frontend
- Gateway forwards to AuthService
- AuthService validates against LDAP/AD
- On success, generates JWT token and stores user in DB
- Frontend stores token and redirects to appropriate dashboard

**Flow 2: Document Upload**
- Admin uploads PDF through frontend
- Backend saves file and creates database record
- Triggers HITL pipeline as subprocess
- Pipeline sends real-time progress updates via WebSocket
- Frontend displays live status updates to admin
- When complete, document is ready for review

**Flow 3: RAG Chat Query**
- User submits question through chat interface
- Backend generates embedding and searches Qdrant for relevant chunks
- Constructs RAG prompt with retrieved context
- Streams LLM response back to frontend in real-time
- Saves conversation with citations to database
- Frontend displays answer with source references

**Flow 4: Section Review**
- Reviewer opens document and fetches all sections
- Edits section content and marks checklist items
- Backend saves changes and creates version history
- Reviewer approves section
- When all sections approved, triggers final reformatting
- Document moves to approved state

---

## Deployment Architecture

```mermaid
flowchart TB
    subgraph AirGappedFacility["🏭 AIR-GAPPED FACILITY NETWORK"]
        subgraph DMZ["DMZ - Web Tier"]
            LB[Load Balancer<br/>Nginx/HAProxy]
            FE1[Frontend Container<br/>Next.js:3000]
            FE2[Frontend Container<br/>Next.js:3000]
        end
        
        subgraph AppTier["Application Tier"]
            API1[Backend API<br/>FastAPI:8000]
            API2[Backend API<br/>FastAPI:8000]
            Worker1[Pipeline Worker<br/>GPU-enabled]
            Worker2[Pipeline Worker<br/>GPU-enabled]
        end
        
        subgraph DataTier["Data Tier"]
            PG[(PostgreSQL:5432<br/>Primary + Replica)]
            QD[(Qdrant:6333<br/>Vector DB)]
            FS[(Shared Storage<br/>NFS/Ceph)]
        end
        
        subgraph GPUNodes["GPU Compute"]
            GPU1[VLLM Server 1<br/>vLLM:8001]
            GPU2[VLLM Server 2<br/>vLLM:8001]
        end
        
        subgraph Monitoring["Observability"]
            Logs[Log Aggregator<br/>Loki/ELK]
            Metrics[Metrics<br/>Prometheus]
            Tracing[Tracing<br/>Langfuse]
        end
        
        AD[Active Directory<br/>LDAP:389]
    end
    
    Technician([Technician]) --> LB
    LB --> FE1
    LB --> FE2
    FE1 --> API1
    FE2 --> API2
    
    API1 --> PG
    API1 --> QD
    API1 --> FS
    API1 --> GPU1
    API1 --> Worker1
    API1 --> AD
    
    API2 --> PG
    API2 --> QD
    API2 --> FS
    API2 --> GPU2
    API2 --> Worker2
    API2 --> AD
    
    Worker1 --> FS
    Worker1 --> GPU1
    Worker2 --> FS
    Worker2 --> GPU2
    
    API1 --> Logs
    API2 --> Logs
    API1 --> Metrics
    API2 --> Metrics
    API1 --> Tracing
    API2 --> Tracing
    
    style DMZ fill:#e8f4f8
    style AppTier fill:#fff4e1
    style DataTier fill:#f0f0f0
    style GPUNodes fill:#ffe1e1
    style Monitoring fill:#f5e1ff
```

**Overview:** Physical deployment architecture for the air-gapped LNG facility environment.

**Key Components:**

**DMZ - Web Tier:**
- Load balancer for high availability
- Multiple frontend containers for redundancy
- Nginx/HAProxy for SSL termination and routing

**Application Tier:**
- Multiple FastAPI backend instances (stateless, horizontally scalable)
- Dedicated pipeline worker nodes with GPU access
- Async task queue for pipeline jobs

**Data Tier:**
- PostgreSQL with primary-replica setup for HA
- Qdrant vector database for semantic search
- Shared file storage (NFS/Ceph) for PDFs and artifacts

**GPU Compute:**
- Dedicated GPU nodes running vLLM servers
- NVIDIA RTX A4000 (24GB VRAM) or better
- Load balanced across multiple GPU nodes

**Monitoring:**
- Log aggregation for troubleshooting
- Prometheus metrics for system health
- Langfuse for LLM tracing and observability

**Design Decisions:**
1. **High Availability**: Multiple instances of all stateless services
2. **GPU Isolation**: Dedicated GPU nodes prevent resource contention
3. **Air-Gapped**: All components run on internal network, no external connectivity
4. **Shared Storage**: Centralized file storage for pipeline artifacts

**NFR Considerations:**
- **Scalability**: Horizontal scaling of frontend and backend, GPU queue for pipeline
- **Performance**: Load balancing, connection pooling, caching layers
- **Security**: Network segmentation, SSL/TLS, LDAP integration, no external access
- **Reliability**: Redundant components, database replication, health checks
- **Maintainability**: Container orchestration (Docker Compose/K8s), automated deployments

**Trade-offs:**
- High availability adds complexity and infrastructure cost
- Shared storage is a potential bottleneck but simplifies file management
- GPU queue may cause delays during peak loads

**Risks and Mitigations:**
- **GPU node failure**: Multiple GPU nodes, queue failover
- **Database failure**: Primary-replica setup, automated failover
- **Storage failure**: RAID configuration, regular backups
- **Network issues**: Redundant network paths, health checks

---

## API Specification

### REST API Endpoints

#### Authentication Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| POST | `/api/v1/auth/login` | Authenticate user | `{username, password}` | `{token, user}` |
| POST | `/api/v1/auth/logout` | Invalidate session | - | `204 No Content` |
| GET | `/api/v1/auth/me` | Get current user | - | `{user}` |
| POST | `/api/v1/auth/refresh` | Refresh JWT token | `{refreshToken}` | `{token}` |

#### User Management Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/users` | List all users (admin only) | - | `{users[]}` |
| GET | `/api/v1/users/{id}` | Get user details | - | `{user}` |
| POST | `/api/v1/users` | Create new user (admin only) | `{username, email, role, ...}` | `{user}` |
| PATCH | `/api/v1/users/{id}` | Update user | `{field: value}` | `{user}` |
| DELETE | `/api/v1/users/{id}` | Deactivate user (admin only) | - | `204 No Content` |

#### Document Management Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/documents` | List all documents | Query: `?status=, ?system=` | `{documents[], total, page}` |
| GET | `/api/v1/documents/{id}` | Get document details | - | `{document}` |
| POST | `/api/v1/documents/upload` | Upload new PDF | `multipart/form-data` | `{documentId, status}` |
| PATCH | `/api/v1/documents/{id}` | Update document metadata | `{field: value}` | `{document}` |
| DELETE | `/api/v1/documents/{id}` | Delete document (admin only) | - | `204 No Content` |
| GET | `/api/v1/documents/{id}/status` | Get processing status | - | `{status, progress, stage}` |
| POST | `/api/v1/documents/{id}/reprocess` | Trigger reprocessing | - | `{jobId}` |
| GET | `/api/v1/documents/{id}/artifacts` | Download artifacts | Query: `?type=validation,manifest` | File download |

#### Section Review Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/documents/{id}/sections` | Get all sections | - | `{sections[]}` |
| GET | `/api/v1/sections/{id}` | Get section details | - | `{section, versions[]}` |
| PATCH | `/api/v1/sections/{id}` | Update section content | `{content, checklist}` | `{section}` |
| POST | `/api/v1/sections/{id}/approve` | Approve section | `{notes}` | `{section}` |
| POST | `/api/v1/sections/{id}/reject` | Reject section | `{reason, notes}` | `{section}` |
| GET | `/api/v1/sections/{id}/versions` | Get version history | - | `{versions[]}` |

#### Chat/RAG Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/conversations` | List user's conversations | - | `{conversations[]}` |
| GET | `/api/v1/conversations/{id}` | Get conversation details | - | `{conversation, messages[]}` |
| POST | `/api/v1/conversations` | Create new conversation | `{title?}` | `{conversation}` |
| POST | `/api/v1/chat/query` | Submit RAG query | `{query, conversationId}` | `{message, citations[]}` |
| POST | `/api/v1/chat/stream` | Stream RAG response | `{query, conversationId}` | SSE stream |
| DELETE | `/api/v1/conversations/{id}` | Delete conversation | - | `204 No Content` |

#### Bookmark Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/bookmarks` | List user's bookmarks | Query: `?tag=` | `{bookmarks[]}` |
| GET | `/api/v1/bookmarks/{id}` | Get bookmark details | - | `{bookmark}` |
| POST | `/api/v1/bookmarks` | Create bookmark | `{conversationId, messageId, tags?, notes?}` | `{bookmark}` |
| PATCH | `/api/v1/bookmarks/{id}` | Update bookmark | `{tags?, notes?}` | `{bookmark}` |
| DELETE | `/api/v1/bookmarks/{id}` | Delete bookmark | - | `204 No Content` |

#### QA Metrics Endpoints

| Method | Endpoint | Description | Request Body | Response |
|--------|----------|-------------|--------------|----------|
| GET | `/api/v1/documents/{id}/qa-metrics` | Get QA report | - | `{metrics, decision, recommendations}` |
| GET | `/api/v1/documents/{id}/validation` | Get validation report | - | `{validation, issues[], confidence}` |

### WebSocket Endpoints

#### Pipeline Status WebSocket

**Endpoint:** `ws://backend:8000/ws/pipeline/{documentId}`

**Purpose:** Real-time updates for document processing pipeline status.

**Messages from Server:**
```json
{
  "type": "progress",
  "documentId": "doc-123",
  "stage": "vlm-validating",
  "progress": 45,
  "message": "Processing page 23 of 51"
}

{
  "type": "stage-complete",
  "documentId": "doc-123",
  "stage": "vlm-validating",
  "duration": 4235,
  "output": {...}
}

{
  "type": "error",
  "documentId": "doc-123",
  "stage": "vlm-validating",
  "error": "VLM model timed out"
}

{
  "type": "complete",
  "documentId": "doc-123",
  "status": "validation-complete",
  "artifacts": ["validation.json", "manifest.json"]
}
```

#### Chat Streaming WebSocket

**Endpoint:** `ws://backend:8000/ws/chat/{conversationId}`

**Purpose:** Real-time streaming of LLM responses during chat queries.

**Messages from Server:**
```json
{
  "type": "token",
  "content": "LNG density",
  "conversationId": "conv-456",
  "messageId": "msg-789"
}

{
  "type": "citation",
  "citation": {
    "id": "cite-1",
    "documentTitle": "...",
    "pageNumber": 12,
    "excerpt": "...",
    "relevanceScore": 0.94
  }
}

{
  "type": "complete",
  "messageId": "msg-789",
  "citations": [...]
}
```

---

## Data Models

### Database Schema (PostgreSQL)

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    full_name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL CHECK (role IN ('admin', 'reviewer', 'user')),
    department VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    last_login TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Documents table
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500) NOT NULL,
    version VARCHAR(50),
    system VARCHAR(255),
    document_type VARCHAR(100),
    file_path VARCHAR(1000) NOT NULL,
    status VARCHAR(50) NOT NULL CHECK (status IN (
        'pending', 'uploading', 'extracting', 'vlm-validating',
        'validation-complete', 'in-review', 'review-complete',
        'approved', 'rejected'
    )),
    total_pages INTEGER,
    total_sections INTEGER,
    review_progress INTEGER DEFAULT 0,
    qa_score DECIMAL(5,2),
    uploaded_by UUID REFERENCES users(id),
    uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Document sections table
CREATE TABLE document_sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_number INTEGER NOT NULL,
    title VARCHAR(500),
    content TEXT NOT NULL,
    page_range VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'in-review', 'approved', 'rejected'
    )),
    review_checklist JSONB,
    current_version INTEGER DEFAULT 1,
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMP,
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, section_number)
);

-- Section versions table
CREATE TABLE section_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES document_sections(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    content TEXT NOT NULL,
    reviewed_by UUID REFERENCES users(id),
    timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(section_id, version_number)
);

-- Conversations table
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Chat messages table
CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    citations JSONB,
    timestamp TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Bookmarks table
CREATE TABLE bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    tags TEXT[],
    notes TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_documents_status ON documents(status);
CREATE INDEX idx_documents_uploaded_by ON documents(uploaded_by);
CREATE INDEX idx_sections_document_id ON document_sections(document_id);
CREATE INDEX idx_sections_status ON document_sections(status);
CREATE INDEX idx_conversations_user_id ON conversations(user_id);
CREATE INDEX idx_messages_conversation_id ON chat_messages(conversation_id);
CREATE INDEX idx_bookmarks_user_id ON bookmarks(user_id);
```

### Pydantic Models (Backend)

```python
from typing import List, Optional, Literal
from datetime import datetime
from pydantic import BaseModel, EmailStr, UUID4

# User models
class UserRole(str, Enum):
    ADMIN = "admin"
    REVIEWER = "reviewer"
    USER = "user"

class UserBase(BaseModel):
    username: str
    email: EmailStr
    full_name: str
    role: UserRole
    department: Optional[str] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: UUID4
    status: Literal["active", "disabled"]
    last_login: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

# Document models
class DocumentStatus(str, Enum):
    PENDING = "pending"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    VLM_VALIDATING = "vlm-validating"
    VALIDATION_COMPLETE = "validation-complete"
    IN_REVIEW = "in-review"
    REVIEW_COMPLETE = "review-complete"
    APPROVED = "approved"
    REJECTED = "rejected"

class DocumentBase(BaseModel):
    title: str
    version: Optional[str]
    system: Optional[str]
    document_type: Optional[str]

class DocumentCreate(DocumentBase):
    pass

class Document(DocumentBase):
    id: UUID4
    status: DocumentStatus
    total_pages: Optional[int]
    total_sections: Optional[int]
    review_progress: int
    qa_score: Optional[float]
    uploaded_by: UUID4
    uploaded_at: datetime
    approved_by: Optional[UUID4]
    approved_at: Optional[datetime]
    notes: Optional[str]
    
    class Config:
        from_attributes = True

# Section models
class ReviewChecklist(BaseModel):
    text_accuracy_confirmed: bool = False
    tables_verified: bool = False
    images_described: bool = False
    formatting_correct: bool = False
    technical_terms_accurate: bool = False

class SectionBase(BaseModel):
    title: Optional[str]
    content: str
    page_range: Optional[str]
    review_checklist: Optional[ReviewChecklist]

class Section(SectionBase):
    id: UUID4
    document_id: UUID4
    section_number: int
    status: Literal["pending", "in-review", "approved", "rejected"]
    current_version: int
    reviewed_by: Optional[UUID4]
    reviewed_at: Optional[datetime]
    notes: Optional[str]
    
    class Config:
        from_attributes = True

# Citation models
class Citation(BaseModel):
    id: str
    document_id: UUID4
    document_title: str
    section_heading: str
    page_number: int
    excerpt: str
    relevance_score: float

# Chat models
class ChatMessage(BaseModel):
    id: UUID4
    role: Literal["user", "assistant"]
    content: str
    citations: Optional[List[Citation]]
    timestamp: datetime
    
    class Config:
        from_attributes = True

class Conversation(BaseModel):
    id: UUID4
    user_id: UUID4
    title: Optional[str]
    messages: List[ChatMessage]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class ChatQueryRequest(BaseModel):
    query: str
    conversation_id: Optional[UUID4]

class ChatQueryResponse(BaseModel):
    message: ChatMessage
    conversation_id: UUID4

# Bookmark models
class BookmarkCreate(BaseModel):
    conversation_id: UUID4
    message_id: UUID4
    tags: Optional[List[str]]
    notes: Optional[str]

class Bookmark(BookmarkCreate):
    id: UUID4
    user_id: UUID4
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True
```

---

## Security Architecture

### Authentication & Authorization

```mermaid
flowchart TB
    subgraph AuthFlow["🔐 Authentication Flow"]
        User[User Login]
        Frontend[Frontend]
        Gateway[API Gateway]
        AuthService[Auth Service]
        LDAP[LDAP/AD]
        DB[(PostgreSQL)]
        
        User --> Frontend
        Frontend --> Gateway
        Gateway --> AuthService
        AuthService --> LDAP
        AuthService --> DB
    end
    
    subgraph JWTStructure["🎫 JWT Token Structure"]
        Header[Header<br/>Algorithm: RS256]
        Payload[Payload<br/>user_id, role, exp]
        Signature[Signature<br/>Private Key]
    end
    
    subgraph RBACPolicy["👥 Role-Based Access Control"]
        Admin[Admin<br/>Full access]
        Reviewer[Reviewer<br/>Review + Chat]
        User2[User<br/>Chat only]
    end
    
    AuthService --> JWTStructure
    Gateway --> RBACPolicy
    
    style AuthFlow fill:#e8f4f8
    style JWTStructure fill:#fff4e1
    style RBACPolicy fill:#f0f0f0
```

**Security Measures:**

1. **Authentication:**
   - LDAP/Active Directory integration for SSO
   - JWT tokens with RS256 signing (asymmetric keys)
   - Refresh tokens with rotation
   - Session timeout (15 minutes inactivity, 8 hours max)

2. **Authorization:**
   - Role-based access control (Admin, Reviewer, User)
   - Route guards on frontend and backend
   - Database row-level security policies

3. **Data Protection:**
   - TLS 1.3 for all HTTP traffic
   - Encrypted database connections
   - Passwords hashed with bcrypt (cost factor 12)
   - No sensitive data in JWT payload

4. **Input Validation:**
   - Pydantic models for request validation
   - SQL injection prevention via SQLAlchemy ORM
   - XSS prevention via React escaping + Content Security Policy
   - File upload validation (MIME type, size limits, virus scanning)

5. **API Security:**
   - Rate limiting (100 req/min per user)
   - CORS policy (whitelist only)
   - API versioning for backward compatibility
   - Audit logging for all mutations

6. **Infrastructure:**
   - Network segmentation (DMZ, App, Data tiers)
   - Firewall rules (minimal open ports)
   - Secrets management (environment variables, not in code)
   - Regular security updates

**Access Control Matrix:**

| Resource | Admin | Reviewer | User |
|----------|-------|----------|------|
| Upload documents | ✅ | ✅ | ❌ |
| View documents | ✅ | ✅ | ❌ |
| Review sections | ✅ | ✅ | ❌ |
| Approve sections | ✅ | ✅ | ❌ |
| Delete documents | ✅ | ❌ | ❌ |
| Manage users | ✅ | ❌ | ❌ |
| Chat queries | ✅ | ✅ | ✅ |
| View own bookmarks | ✅ | ✅ | ✅ |
| View system metrics | ✅ | ❌ | ❌ |

---

## Finalized Endpoint Ownership Map (T-001)

**Status:** ✅ Approved — 2026-03-09  
**Owner:** Architecture Planning

### URL Namespace Separation

All traffic enters through Nginx, which routes by path prefix:

```
/api/v1/*   →  FastAPI   (orchestration, auth, streaming, file I/O)
/rest/*     →  PostgREST  (pure CRUD / data access for PostgreSQL-backed entities)
/ws/*       →  FastAPI   (WebSocket channels)
```

Clients MUST use the correct base URL for each category. No endpoint is served by both. This is the **conflict-free rule** — the path prefix enforces exclusive ownership at the network layer.

### Nginx Routing Rules

```nginx
# PostgREST data API
location /rest/ {
    proxy_pass http://postgrest:3000/;
    proxy_set_header Authorization $http_authorization;  # Forward JWT
}

# FastAPI orchestration + auth
location /api/v1/ {
    proxy_pass http://backend:8000/api/v1/;
}

# FastAPI WebSocket channels
location /ws/ {
    proxy_pass http://backend:8000/ws/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}
```

### Endpoint Ownership Matrix (Conflict-Free)

#### PostgREST Endpoints (`/rest/` prefix)

| Method(s) | Path | Description | Notes |
|---|---|---|---|
| GET, POST | `/rest/users` | List / Create users | Admin-only writes via RLS |
| GET, PATCH, DELETE | `/rest/users?id=eq.{id}` | Get / Update / Deactivate user | Self or admin via RLS |
| GET, POST | `/rest/documents` | List / Create document record | POST only by pipeline after upload |
| GET, PATCH | `/rest/documents?id=eq.{id}` | Get / Update document metadata | Admin + reviewer via RLS |
| GET, POST | `/rest/document_sections` | List / Create sections | POST only by pipeline |
| PATCH | `/rest/document_sections?id=eq.{id}` | Edit section content + checklist | Content edit, not status change |
| GET | `/rest/section_versions?section_id=eq.{id}` | Section version history | Read-only |
| POST | `/rest/section_versions` | Insert new version snapshot | Triggered by review service |
| GET, POST | `/rest/conversations` | List / Create conversations | User-scoped via RLS |
| GET, DELETE | `/rest/conversations?id=eq.{id}` | Get / Delete conversation | Owner-scoped via RLS |
| GET, POST | `/rest/chat_messages` | List / Append messages | Conversation-scoped via RLS |
| GET, POST, PATCH, DELETE | `/rest/bookmarks` | Full CRUD on bookmarks | User-scoped via RLS |

> **PostgREST filtering convention:**  Use PostgREST query operators (`?id=eq.`, `?document_id=eq.`, `?status=eq.`, `?order=created_at.desc`, `?limit=20&offset=0`) instead of custom pagination parameters.

#### FastAPI Endpoints (`/api/v1/` prefix)

| Method | Path | Description | Rationale for FastAPI |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Authenticate via LDAP + issue JWT | LDAP integration + token issuance logic |
| POST | `/api/v1/auth/logout` | Invalidate refresh token | Server-side session management |
| GET | `/api/v1/auth/me` | Introspect token → current user | JWT decoding + DB lookup |
| POST | `/api/v1/auth/refresh` | Rotate refresh token + issue new access token | Token rotation logic |
| POST | `/api/v1/documents/upload` | Accept multipart file + write to disk + create DB record | File I/O + transactional DB insert |
| GET | `/api/v1/documents/{id}/status` | Live processing status from pipeline | Filesystem / subprocess state polling |
| POST | `/api/v1/documents/{id}/reprocess` | Trigger pipeline re-run | Subprocess orchestration |
| GET | `/api/v1/documents/{id}/artifacts` | Download artifact files | Filesystem access + access control checks |
| POST | `/api/v1/sections/{id}/approve` | Change status + conditionally trigger Stage 10 | Orchestration side-effect on approval |
| POST | `/api/v1/sections/{id}/reject` | Change status + record rejection reason | State machine with notification side-effects |
| POST | `/api/v1/chat/query` | RAG: embed query → Qdrant search → prompt build → LLM invoke | Multi-system orchestration |
| POST | `/api/v1/chat/stream` | As above but SSE streaming response | Streaming format requires FastAPI |
| POST | `/api/v1/pipeline/run` | Admin-triggered full pipeline run | Subprocess lifecycle management |

#### FastAPI WebSocket Channels (`/ws/` prefix)

| Path | Description |
|---|---|
| `/ws/pipeline/{documentId}` | Real-time pipeline stage/progress events |
| `/ws/chat/{conversationId}` | Token-level streaming of LLM responses |

### Overlap Resolution Log

| Original Spec Endpoint | Before | After (Decision) |
|---|---|---|
| `GET /api/v1/documents` | API spec listed in FastAPI | ➜ Moved to `GET /rest/documents` (pure data query) |
| `PATCH /api/v1/documents/{id}` | API spec listed in FastAPI | ➜ Moved to `PATCH /rest/documents?id=eq.{id}` (metadata only) |
| `DELETE /api/v1/documents/{id}` | API spec listed in FastAPI | ➜ Moved to `DELETE /rest/documents?id=eq.{id}` (admin RLS policy) |
| `GET /api/v1/documents/{id}` | API spec listed in FastAPI | ➜ Moved to `GET /rest/documents?id=eq.{id}` |
| `GET/PATCH /api/v1/sections/{id}` | API spec listed in FastAPI | ➜ Content edits: `PATCH /rest/document_sections?id=eq.{id}`. Approve/reject stays FastAPI. |
| `GET /api/v1/conversations` | API spec listed in FastAPI | ➜ Moved to `GET /rest/conversations` |
| `GET /api/v1/bookmarks` | API spec listed in FastAPI | ➜ Moved to `GET /rest/bookmarks` |

---

## JWT Claim Contract for PostgreSQL Role Mapping (T-002)

**Status:** ✅ Approved — 2026-03-09  
**Owner:** Architecture Planning  
**Consumed by:** T-004 (RLS policies), T-005 (FastAPI auth), T-006 (PostgREST config)

### Access Token Claim Schema

```json
{
  "sub":   "550e8400-e29b-41d4-a716-446655440000",
  "role":  "reviewer",
  "email": "jane.doe@covepointlng.local",
  "dept":  "operations",
  "scope": ["chat.read", "docs.review", "docs.upload"],
  "iss":   "plantig-auth",
  "aud":   "plantig",
  "iat":   1741478400,
  "exp":   1741479300
}
```

| Claim | Type | Required | Description |
|---|---|---|---|
| `sub` | UUID string | ✅ | PostgreSQL `users.id` — primary identity used by all RLS policies to scope rows |
| `role` | enum string | ✅ | One of `admin`, `reviewer`, `user`. Maps directly to a PostgreSQL DB role |
| `email` | string | ✅ | User email for display; not used by authorization logic |
| `dept` | string | optional | Department for future multi-tenant or department-level row filtering |
| `scope` | string[] | ✅ | Fine-grained capability flags for FastAPI middleware guards |
| `iss` | string | ✅ | Issuer identifier; PostgREST and FastAPI both validate this |
| `aud` | string | ✅ | Audience identifier; must match configured audience in PostgREST and FastAPI |
| `iat` | Unix int | ✅ | Issued-at timestamp |
| `exp` | Unix int | ✅ | Expiry — **15 minutes** from `iat` |

### Scope Definitions

| Scope | Granted To | Permitted Actions |
|---|---|---|
| `chat.read` | user, reviewer, admin | Submit RAG queries, read conversations |
| `docs.review` | reviewer, admin | Read sections, edit content, approve/reject sections |
| `docs.upload` | reviewer, admin | Upload documents, trigger pipeline |
| `admin.manage` | admin only | Manage users, delete documents, view metrics |

### PostgreSQL Role Mapping

| JWT `role` | PostgreSQL DB Role | Privilege Summary |
|---|---|---|
| `"admin"` | `plantig_admin` | Full access; bypasses RLS via `BYPASSRLS` or explicit permissive policies |
| `"reviewer"` | `plantig_reviewer` | SELECT + UPDATE on documents and sections; SELECT + INSERT on conversations |
| `"user"` | `plantig_user` | SELECT + INSERT on conversations and chat_messages; full CRUD on own bookmarks |

> PostgreSQL roles must be created before PostgREST is configured. Apply migrations before starting the PostgREST service.

### PostgREST JWT Configuration

```ini
# infra/compose/postgrest.env
PGRST_DB_URI         = "postgres://plantig_authenticator:${PG_PASS}@postgres:5432/plantig"
PGRST_DB_SCHEMA      = "public"
PGRST_DB_ANON_ROLE   = "plantig_anon"        # Role for unauthenticated requests (no access)
PGRST_JWT_SECRET     = "@/secrets/jwt-public.pem"  # RS256 public key file
PGRST_JWT_AUD        = "plantig"             # Must match 'aud' claim
PGRST_ROLE_CLAIM_KEY = ".role"               # Claim to use for role switching
```

> PostgREST uses the `role` claim to execute `SET ROLE plantig_<role>` before each request, activating the correct RLS policies.

### RLS Helper Function

Create this function in PostgreSQL **before** enabling RLS on any table. All policies reference it:

```sql
-- Returns the authenticated user's UUID from the JWT sub claim
CREATE OR REPLACE FUNCTION plantig_uid() RETURNS UUID AS $$
  SELECT COALESCE(
    current_setting('request.jwt.claims', true)::jsonb->>'sub',
    '00000000-0000-0000-0000-000000000000'
  )::UUID;
$$ LANGUAGE SQL STABLE SECURITY DEFINER;

-- Returns the authenticated user's role from the JWT role claim
CREATE OR REPLACE FUNCTION plantig_role() RETURNS TEXT AS $$
  SELECT COALESCE(
    current_setting('request.jwt.claims', true)::jsonb->>'role',
    'anon'
  );
$$ LANGUAGE SQL STABLE SECURITY DEFINER;
```

### Example RLS Policies (Reference for T-004)

```sql
-- Conversations: users see only their own  
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

CREATE POLICY conv_select_own ON conversations FOR SELECT
  TO plantig_user, plantig_reviewer
  USING (user_id = plantig_uid());

CREATE POLICY conv_insert_own ON conversations FOR INSERT
  TO plantig_user, plantig_reviewer
  WITH CHECK (user_id = plantig_uid());

-- Admin sees all
CREATE POLICY conv_admin_all ON conversations TO plantig_admin USING (true);

-- Documents: reviewer/admin can see all; user cannot
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY docs_reviewer_select ON documents FOR SELECT
  TO plantig_reviewer, plantig_admin USING (true);

CREATE POLICY docs_reviewer_update ON documents FOR UPDATE
  TO plantig_reviewer
  USING (true) WITH CHECK (status NOT IN ('approved'));  -- Only admin can approve

CREATE POLICY docs_admin_all ON documents TO plantig_admin USING (true);

-- Bookmarks: completely user-scoped
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;

CREATE POLICY bm_own ON bookmarks
  USING (user_id = plantig_uid())
  WITH CHECK (user_id = plantig_uid());
```

### Refresh Token Strategy

| Property | Value |
|---|---|
| Token format | Opaque UUID v4 (stored in `refresh_tokens` table) |
| Delivery | `HttpOnly; Secure; SameSite=Strict` cookie |
| Lifetime | **8 hours** from issuance |
| Rotation | Single-use — each `/api/v1/auth/refresh` call invalidates the old token and issues a new one |
| Revocation | FastAPI deletes row from `refresh_tokens` on logout or explicit revoke |

```sql
-- Refresh tokens table
CREATE TABLE refresh_tokens (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash   VARCHAR(64) NOT NULL UNIQUE,  -- SHA-256 of raw token
    expires_at   TIMESTAMP NOT NULL,
    revoked_at   TIMESTAMP,
    created_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
```

### Signing Algorithm

| Property | Value |
|---|---|
| Algorithm | RS256 (asymmetric — private key signs, public key verifies) |
| Key size | 2048-bit RSA minimum |
| Private key location | `/secrets/jwt-private.pem` (FastAPI only — never exposed) |
| Public key location | `/secrets/jwt-public.pem` (shared with PostgREST) |
| Key rotation | Rotate annually or on suspected compromise; use key ID (`kid`) in header for zero-downtime rotation |

---

## Pending Task Register (Agent-Owned, Flat List)

This replaces phase-based assignment with a single trackable backlog. Execute tasks by priority and dependency, not by phase labels.

### Tracking Rules
- Status values: `todo`, `in-progress`, `blocked`, `done`
- Each task has exactly one **Owner Agent**
- Every owner follows the **Agent Instruction** exactly and attaches evidence (PR, test output, or doc update)

| Task ID | Priority | Pending Task | Owner Agent | Agent Instruction | Depends On | Success Criteria | Status |
|---|---|---|---|---|---|---|---|
| T-001 | P0 | Finalize endpoint ownership map (PostgREST vs FastAPI) | Architecture Planning | Freeze endpoint boundaries and publish a conflict-free ownership matrix; resolve overlaps before implementation starts. | None | No endpoint is dual-owned; approved matrix added to architecture doc. | **done** |
| T-002 | P0 | Define JWT claim contract for PostgreSQL role mapping | Architecture Planning | Specify claim schema (`sub`, `role`, `org`, `scope`) and mapping rules for RLS-compatible authorization. | T-001 | Claim contract documented and referenced by backend + DB policy tasks. | **done** |
| T-003 | P0 | Provision PostgREST service in local stack | DevOps/Infrastructure | Add PostgREST service/config to compose, network, healthcheck, secrets wiring, and startup order with PostgreSQL. | T-001 | PostgREST reachable in dev; healthcheck passing; service documented. | **done** |
| T-004 | P0 | Create PostgreSQL RLS baseline policies | Backend Development | Implement RLS policies for users, documents, sections, bookmarks, conversations/messages per role model. | T-002 | Policy tests pass for admin/reviewer/user access matrix. | **done** |
| T-005 | P0 | Implement FastAPI auth bootstrap (`/api/v1/auth/*`) | Backend Development | Keep LDAP/JWT in FastAPI, issue tokens with agreed claims, and provide session endpoints for frontend login flow. | T-002 | Login, refresh, logout, `/me` functional and tested. | **done** |
| T-006 | P1 | Expose users/documents/sections/bookmarks/messages via PostgREST | Backend Development | Model views/functions as needed, remove redundant custom CRUD paths, and standardize pagination/filtering conventions. | T-003, T-004 | CRUD resources operational through PostgREST with documented query patterns. | **done** |
| T-007 | P1 | Replace frontend mock sources with PostgREST resources | Frontend Development | Migrate admin/review/bookmark/conversation pages from `lib/mock` to HTTP data APIs; preserve existing UI behavior. | T-006 | Target pages load live data with no mock dependency in runtime path. | **done** |
| T-008 | P1 | Build orchestration endpoints in FastAPI | Backend Development | Implement pipeline trigger/reprocess/status, artifact retrieval, and RAG query orchestration while keeping data CRUD out of FastAPI. | T-001, T-005 | Orchestration endpoints functional and integrated with pipeline/Qdrant/vLLM. | **done** |
| T-009 | P1 | Implement real-time streaming channels | Backend Development | Implement `/ws/chat/*` and `/ws/pipeline/*` with reconnect-safe message contracts and error events. | T-008 | Streaming works end-to-end with deterministic event schema. | **done** |
| T-010 | P1 | Integrate frontend with FastAPI orchestration endpoints | Frontend Development | Wire upload/reprocess/chat streaming/artifact actions to FastAPI endpoints and handle loading/error states. | T-008, T-009 | Full user journeys work without manual API intervention. | **done** |
| T-011 | P1 | Add integration test suite for hybrid architecture | Testing & QA | Build tests across Frontend ↔ FastAPI ↔ PostgREST ↔ PostgreSQL ↔ Qdrant ↔ Pipeline for critical flows. | T-006, T-008, T-010 | Critical-path integration tests pass in CI/local. | **done** |
| T-012 | P1 | Perform security review (JWT + RLS + endpoint exposure) | Code Review | Conduct focused security review on claim handling, RLS enforcement, and accidental overexposure via PostgREST. | T-004, T-005, T-006 | Security findings triaged; blocking issues resolved or accepted with risk notes. | **done**  |
| T-013 | P2 | Add observability for PostgREST and orchestration APIs | DevOps/Infrastructure | Instrument logs/metrics/traces for PostgREST + FastAPI and publish operational dashboards/alerts. | T-003, T-008 | Dashboard and alerts available; SLO metrics visible. | **done** |
| T-014 | P2 | Run performance benchmark (CRUD + streaming + RAG) | Testing & QA | Benchmark key endpoints and websocket paths; report against latency/throughput targets and regressions. | T-011, T-013 | Benchmark report published with pass/fail against targets. | **done** |
| T-015 | P2 | Publish operator and developer runbooks | Documentation | Document setup, incident response, API usage patterns, and troubleshooting for hybrid architecture. | T-003, T-008, T-011 | Runbooks completed and linked from project docs index. | todo |
| T-016 | P0 | Program-level tracking and release readiness | Project Lead | Maintain dependency board, unblock owners, enforce gates, and run go/no-go checklist before release. | T-001..T-015 | All P0/P1 tasks done, risks reviewed, release decision recorded. | todo |

### Execution Order (Dependency-Driven)

Start queue: `T-001`, `T-002`, `T-003`, `T-016`  
Then: `T-004`, `T-005`  
Then: `T-006`, `T-007`, `T-008`, `T-009`, `T-010`  
Then: `T-011`, `T-012`  
Then: `T-013`, `T-014`, `T-015`

### Global Acceptance Gates

- **G1 Architecture:** ownership matrix finalized (`T-001`)
- **G2 Security:** JWT claim contract + RLS verified (`T-002`, `T-004`, `T-012`)
- **G3 Functionality:** no runtime mock data for target modules (`T-007`, `T-010`)
- **G4 Reliability:** integration tests and observability in place (`T-011`, `T-013`)
- **G5 Readiness:** performance + docs + release checklist complete (`T-014`, `T-015`, `T-016`)

---

## Technical Stack Summary

### Frontend
- **Framework**: Next.js 16 (React 19)
- **Language**: TypeScript 5
- **UI Library**: Shadcn UI (Radix UI primitives + Tailwind CSS 4)
- **State Management**: React Context API
- **HTTP Client**: Fetch API with custom hooks
- **WebSocket**: Native WebSocket API
- **Markdown**: react-markdown
- **Form Validation**: react-hook-form + Zod
- **Build Tool**: Turbopack

### Backend
- **Framework**: FastAPI 0.104+
- **Language**: Python 3.10+
- **Data API**: PostgREST (for CRUD/data modules)
- **ORM**: SQLAlchemy 2.0 (limited to orchestration-side persistence needs)
- **Validation**: Pydantic 2.0
- **Authentication**: python-jose (JWT), passlib (bcrypt)
- **LDAP**: ldap3
- **Database Migrations**: Alembic
- **Async Runtime**: uvicorn with uvloop
- **Task Queue**: Celery (optional) or asyncio
- **OpenAPI**: Built-in FastAPI

### Data & Infrastructure
- **Relational DB**: PostgreSQL 15
- **REST over PostgreSQL**: PostgREST v14+
- **Vector DB**: Qdrant
- **File Storage**: NFS/Ceph (shared storage)
- **LLM Inference**: vLLM
- **Embedding Model**: BGE-large via Ollama
- **Containerization**: Docker + Docker Compose
- **Reverse Proxy**: Nginx
- **Monitoring**: Prometheus + Grafana
- **Logging**: Loki or ELK Stack
- **Tracing**: Langfuse

### Development Tools
- **Code Quality**: Black, Flake8, MyPy (backend), ESLint, Prettier (frontend)
- **Testing**: pytest (backend), Vitest (frontend)
- **API Testing**: Postman/HTTPie
- **Load Testing**: Locust
- **CI/CD**: GitHub Actions (air-gapped: GitLab CI)

---

## Non-Functional Requirements

### Performance

| Metric | Target | Measurement |
|--------|--------|-------------|
| RAG query response time | < 2 seconds | 95th percentile |
| Document upload processing | < 5 minutes per 100 pages | Average |
| API endpoint response time | < 200ms | 95th percentile |
| WebSocket message latency | < 50ms | Average |
| Page load time | < 1 second | First contentful paint |
| Database query time | < 100ms | 95th percentile |

**Strategies:**
- Async operations for I/O-bound tasks
- Connection pooling for database and HTTP clients
- Caching frequently accessed data (Redis)
- Database indexing on frequently queried columns
- Vector search optimization (quantization, HNSW tuning)
- Frontend code splitting and lazy loading

---

### Scalability

| Dimension | Initial Capacity | Scale Strategy |
|-----------|------------------|----------------|
| Concurrent users | 100 | Horizontal scaling of frontend/backend |
| Documents processed | 1000/month | GPU worker queue auto-scaling |
| Vector DB size | 10 million chunks | Qdrant clustering |
| Storage | 1TB | Expand NFS/Ceph storage |
| API requests | 10,000/hour | Load balancer + multiple API instances |

**Strategies:**
- Stateless services for horizontal scaling
- Database read replicas for read-heavy workloads
- Asynchronous pipeline processing with job queue
- Vector DB sharding for large datasets
- CDN for static assets (if applicable)

---

### Reliability

| Requirement | Implementation |
|-------------|---------------|
| Uptime | 99.5% (target) |
| Data durability | 99.999% |
| Backup frequency | Daily (full), hourly (incremental) |
| Recovery Time Objective (RTO) | < 4 hours |
| Recovery Point Objective (RPO) | < 1 hour |

**Strategies:**
- Database replication (primary-replica)
- Automated backups with offsite storage
- Health checks and auto-restart for containers
- Circuit breakers for external service calls
- Graceful degradation (fallback to cached data)
- Disaster recovery runbook

---

### Security

| Category | Measures |
|----------|----------|
| Authentication | LDAP/AD integration, JWT with rotation, session timeout |
| Authorization | RBAC, route guards, database RLS |
| Data Protection | TLS 1.3, encrypted connections, bcrypt passwords |
| Input Validation | Pydantic models, SQL injection prevention, XSS prevention |
| API Security | Rate limiting, CORS policy, audit logging |
| Infrastructure | Network segmentation, firewall rules, secrets management |

**Compliance:**
- Air-gapped deployment (no external connectivity)
- Role-based access control (RBAC)
- Audit trail for all document changes
- Data retention policy (7 years for compliance)

---

### Maintainability

| Aspect | Implementation |
|--------|---------------|
| Code Quality | Linting, type checking, code reviews |
| Testing | >80% coverage, unit + integration + E2E tests |
| Documentation | API docs, architecture docs, runbooks |
| Monitoring | Metrics, logs, tracing, alerts |
| Versioning | Semantic versioning, API versioning |
| Deployments | Automated CI/CD, blue-green deployments |

**Strategies:**
- Clear separation of concerns (layered architecture)
- Dependency injection for testability
- Comprehensive logging with structured format
- OpenAPI specification for API contracts
- Infrastructure as code (Docker Compose/K8s)

---

## Migration Strategy: Mock Data → Real APIs

### Frontend Changes Required

**1. Create API Client Module**

```typescript
// frontend/lib/api/client.ts
import type { User, Document, Conversation, Bookmark, Section } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

class APIClient {
  private async request<T>(
    endpoint: string,
    options?: RequestInit
  ): Promise<T> {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      credentials: "include", // Include cookies for JWT
    });

    if (!response.ok) {
      throw new Error(`API error: ${response.status}`);
    }

    return response.json();
  }

  // Auth endpoints
  async login(username: string, password: string): Promise<{ user: User; token: string }> {
    return this.request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
  }

  async logout(): Promise<void> {
    await this.request("/api/v1/auth/logout", { method: "POST" });
  }

  async getCurrentUser(): Promise<User> {
    return this.request("/api/v1/auth/me");
  }

  // Document endpoints
  async getDocuments(): Promise<Document[]> {
    return this.request("/api/v1/documents");
  }

  async uploadDocument(file: File, metadata: any): Promise<Document> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("metadata", JSON.stringify(metadata));

    return this.request("/api/v1/documents/upload", {
      method: "POST",
      body: formData,
      headers: {}, // Let browser set Content-Type for multipart
    });
  }

  // ... other endpoints
}

export const apiClient = new APIClient();
```

**2. Create WebSocket Hook**

```typescript
// frontend/lib/hooks/useWebSocket.ts
import { useEffect, useRef, useState } from "react";

export function useWebSocket<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const ws = useRef<WebSocket | null>(null);

  useEffect(() => {
    ws.current = new WebSocket(url);

    ws.current.onopen = () => setIsConnected(true);
    ws.current.onclose = () => setIsConnected(false);
    ws.current.onmessage = (event) => {
      setData(JSON.parse(event.data));
    };

    return () => ws.current?.close();
  }, [url]);

  return { data, isConnected };
}
```

**3. Update Components to Use Real API**

```typescript
// Example: frontend/app/admin/documents/page.tsx
"use client";

import { useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { Document } from "@/types";

export default function DocumentsPage() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiClient.getDocuments()
      .then(setDocuments)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div>Loading...</div>;

  return (
    <div>
      {documents.map((doc) => (
        <DocumentCard key={doc.id} document={doc} />
      ))}
    </div>
  );
}
```

**4. Update AuthContext**

```typescript
// frontend/lib/auth/AuthContext.tsx
import { createContext, useContext, useEffect, useState } from "react";
import { apiClient } from "@/lib/api/client";
import type { User } from "@/types";

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType>(null!);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    // Check if user is already authenticated
    apiClient.getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null));
  }, []);

  const login = async (username: string, password: string) => {
    const { user } = await apiClient.login(username, password);
    setUser(user);
  };

  const logout = async () => {
    await apiClient.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ 
      user, 
      isAuthenticated: !!user, 
      login, 
      logout 
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
```

**Files to Modify:**
1. Create `frontend/lib/api/client.ts` - centralized API client
2. Create `frontend/lib/hooks/useWebSocket.ts` - WebSocket hook
3. Update `frontend/lib/auth/AuthContext.tsx` - use real auth API
4. Update all page components to use `apiClient` instead of mock data
5. Remove `frontend/lib/mock/*` files (keep temporarily for reference)
6. Update `.env.local` with `NEXT_PUBLIC_API_URL=http://localhost:8000`

---

## Risk Assessment & Mitigation

### Technical Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| **Pipeline subprocess failures** | High | Medium | Robust error handling, retry logic, status tracking, automatic recovery |
| **GPU memory exhaustion** | High | Medium | Memory monitoring, graceful degradation, job queue with limits |
| **WebSocket connection drops** | Medium | High | Reconnection logic, fallback to polling, keepalive heartbeat |
| **Database performance degradation** | High | Low | Query optimization, indexing, read replicas, connection pooling |
| **Vector DB scaling issues** | Medium | Low | Quantization, HNSW tuning, clustering for large datasets |
| **LLM hallucinations** | High | Medium | Citation validation, confidence scoring, human review workflow |
| **Authentication bypass** | Critical | Low | Security audit, JWT validation, rate limiting, audit logging |
| **Data loss** | Critical | Low | Automated backups, replication, disaster recovery plan |

### Operational Risks

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| **Air-gapped deployment complexity** | Medium | High | Comprehensive offline documentation, pre-built containers |
| **Limited external support** | Medium | High | Detailed runbooks, internal training, support contracts |
| **User adoption resistance** | Medium | Medium | User training, intuitive UI, feedback loops |
| **Reviewer workload bottleneck** | Medium | High | Sampling strategies, parallel review, automation |
| **Lack of monitoring in air-gapped env** | Medium | Medium | Local monitoring stack, regular health checks |

---

## Success Metrics

### System Performance Metrics

| Metric | Baseline | Target | Measurement Frequency |
|--------|----------|--------|----------------------|
| RAG query accuracy | TBD | >90% (user feedback) | Weekly |
| Document processing throughput | TBD | 50 pages/hour | Daily |
| API uptime | 99% | 99.5% | Real-time |
| Average response time | TBD | <2 seconds | Real-time |
| User satisfaction score | TBD | >4.0/5.0 | Monthly survey |

### Business Metrics

| Metric | Baseline | Target | Measurement Frequency |
|--------|----------|--------|----------------------|
| Documents indexed | 0 | 500+ | Monthly |
| Active users | 0 | 50+ | Daily |
| Queries per day | 0 | 200+ | Daily |
| Manual search time saved | 0 | 10+ hours/week | Monthly |
| Mean time to information (MTTI) | 30 min | <2 min | Monthly |

---

## Conclusion

This integration architecture provides a comprehensive roadmap for connecting the PlantIQ frontend (Next.js hi-fi prototype) with the backend systems (FastAPI middleware, HITL pipeline, Vector DB). The design follows clean architecture principles with clear separation of concerns, ensuring the system is:

- **Scalable**: Stateless services, horizontal scaling, job queues
- **Secure**: LDAP integration, JWT authentication, RBAC, audit logging
- **Reliable**: Health checks, error handling, automated backups
- **Maintainable**: Layered architecture, comprehensive testing, documentation
- **Performant**: Async operations, caching, optimized queries

The phased implementation plan breaks down the work into manageable sprints, allowing for iterative development and testing. Each phase delivers tangible value while building toward the complete system.

**Next Steps:**
1. Review and validate this architecture with stakeholders
2. Setup development environment (databases, infrastructure)
3. Begin Phase 1: Foundation & Authentication
4. Establish CI/CD pipeline for automated testing and deployment

---

## Appendix

### A. Environment Variables

```bash
# Backend (.env)
DATABASE_URL=postgresql://plantiq:password@postgres:5432/plantiq
VECTOR_DB_URL=http://vector-db:6333
VLLM_API_URL=http://vllm:8001
SECRET_KEY=<generate-secure-random-key>
JWT_ALGORITHM=RS256
JWT_PRIVATE_KEY_PATH=/secrets/jwt-private.pem
JWT_PUBLIC_KEY_PATH=/secrets/jwt-public.pem
JWT_EXPIRATION_MINUTES=15
JWT_REFRESH_EXPIRATION_DAYS=7
LDAP_SERVER=ldap://ad-server:389
LDAP_BASE_DN=DC=covepointlng,DC=local
LDAP_BIND_DN=CN=service-account,OU=Services,DC=covepointlng,DC=local
LDAP_BIND_PASSWORD=<secure-password>
LOG_LEVEL=INFO
CORS_ORIGINS=http://localhost:3000,http://frontend:3000
UPLOAD_MAX_SIZE_MB=100
PIPELINE_WORKSPACE=/app/data/artifacts/hitl_workspace
PIPELINE_TIMEOUT_SECONDS=14400

# Frontend (.env.local)
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
NEXT_PUBLIC_APP_NAME=PlantIQ
```

### B. API Response Examples

**Successful Document Upload:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "COMMON Module 3 Characteristics of LNG",
  "version": "Rev 2.1",
  "status": "uploading",
  "uploadedAt": "2026-03-09T10:30:00Z",
  "uploadedBy": "550e8400-e29b-41d4-a716-446655440001"
}
```

**RAG Query Response:**
```json
{
  "message": {
    "id": "msg-123",
    "role": "assistant",
    "content": "LNG has a density of approximately **450 kg/m³** at atmospheric pressure and -162°C...",
    "citations": [
      {
        "id": "cite-1",
        "documentId": "doc-1",
        "documentTitle": "COMMON Module 3 Characteristics of LNG",
        "sectionHeading": "3. Physical Properties of LNG",
        "pageNumber": 12,
        "excerpt": "LNG density at atmospheric pressure is approximately 450 kg/m³ at -162°C...",
        "relevanceScore": 0.94
      }
    ],
    "timestamp": "2026-03-09T10:35:00Z"
  },
  "conversationId": "conv-456"
}
```

**Pipeline Progress WebSocket Message:**
```json
{
  "type": "progress",
  "documentId": "doc-123",
  "stage": "vlm-validating",
  "progress": 45,
  "message": "Processing page 23 of 51",
  "timestamp": "2026-03-09T10:40:00Z"
}
```

### C. File Structure (Post-Implementation)

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app entry point
│   ├── api/
│   │   ├── __init__.py
│   │   ├── v1/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py            # Auth endpoints
│   │   │   ├── users.py           # User endpoints
│   │   │   ├── documents.py       # Document endpoints
│   │   │   ├── sections.py        # Section endpoints
│   │   │   ├── chat.py            # Chat endpoints
│   │   │   ├── bookmarks.py       # Bookmark endpoints
│   │   │   └── websocket.py       # WebSocket endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # Configuration
│   │   ├── security.py            # JWT, hashing
│   │   ├── database.py            # DB connection
│   │   └── middleware.py          # Custom middleware
│   ├── models/
│   │   ├── __init__.py
│   │   ├── user.py                # SQLAlchemy models
│   │   ├── document.py
│   │   ├── section.py
│   │   ├── conversation.py
│   │   └── bookmark.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── user.py                # Pydantic schemas
│   │   ├── document.py
│   │   ├── section.py
│   │   ├── chat.py
│   │   └── bookmark.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth_service.py        # Business logic
│   │   ├── document_service.py
│   │   ├── chat_service.py
│   │   ├── review_service.py
│   │   └── bookmark_service.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── user_repository.py     # Data access layer
│   │   ├── document_repository.py
│   │   ├── section_repository.py
│   │   ├── conversation_repository.py
│   │   └── bookmark_repository.py
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── pipeline_client.py     # HITL pipeline integration
│   │   ├── qdrant_client.py       # Vector DB client
│   │   ├── vllm_client.py         # LLM inference client
│   │   └── ldap_client.py         # LDAP integration
│   └── utils/
│       ├── __init__.py
│       ├── logging.py
│       └── exceptions.py
├── migrations/
│   └── versions/                  # Alembic migrations
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── pyproject.toml

frontend/
├── app/
│   ├── (auth)/
│   │   └── login/
│   │       └── page.tsx
│   ├── (dashboard)/
│   │   ├── chat/
│   │   │   └── page.tsx
│   │   ├── admin/
│   │   │   └── documents/
│   │   │       └── page.tsx
│   │   └── bookmarks/
│   │       └── page.tsx
│   ├── layout.tsx
│   └── page.tsx
├── components/
│   ├── shared/
│   └── ui/
├── lib/
│   ├── api/
│   │   ├── client.ts              # API client
│   │   └── types.ts
│   ├── hooks/
│   │   ├── useWebSocket.ts
│   │   ├── useDocuments.ts
│   │   └── useChat.ts
│   ├── auth/
│   │   └── AuthContext.tsx
│   └── utils.ts
├── types/
│   └── index.ts
└── package.json
```

---

**Document Version:** 1.2  
**Last Updated:** March 9, 2026  
**Author:** Architecture Planning Agent  
**Status:** Ready for Review
