# PlantIQ — Air-Gapped RAG for Industrial OT

PlantIQ is a local-first, citation-grounded Retrieval-Augmented Generation (RAG) system for industrial operations teams.
It is designed for environments where proprietary documents must remain on-prem and cloud AI is not allowed.

As of **April 2026 (Beta checkpoint)**, the project is focused on two core capabilities:

- **Document ingestion pipeline** (upload → extract/validate → review → optimize → QA → publish)
- **Citation-grounded chat** with scoped retrieval

---

## Beta checkpoint status (April 2026)

| Metric | Current value |
|---|---|
| User-story completion | **13 / 13 fully implemented** |
| Core path status | **Implemented end to end** (ingestion + chat) |
| Remaining major gap | **Production Active Directory integration + final enterprise hardening** |
| Concurrency evidence | 100% success through 23-user OT-paced load profiles; latency inflection at 25 users |
| Endurance evidence | 8-hour run: 3,127 requests, 100% success, 0 errors |
| Code-quality hardening | Ongoing remediation waves in progress (quality/security backlog being reduced) |

> This repository is currently in **Beta hardening mode**, with non-core feature expansion intentionally deprioritized.

---

## What is implemented now

### Core functionality

1. **Quality-gated ingestion workflow**
   - Upload + metadata capture
   - Extract + validate
   - Human review + correction
   - RAG optimization
   - QA gate
   - Publication to retrieval index

2. **Scoped, citation-grounded chat**
   - System + area scope filters (document-type axis removed — see [ADR](docs/architecture/adr_scope_simplification.md))
   - Retrieved context assembly
   - Local generation
   - Source citations in responses

3. **User scope governance**
   - Per-user system/area access policies stored and enforced server-side
   - Upload and chat endpoints return `403 SCOPE_ACCESS_DENIED` for out-of-policy requests
   - Full audit trail in `access_audit_logs`
   - Frontend surfaces denial reason with actionable guidance; retry locked until scope corrected

4. **Answer feedback loop**
   - Thumbs up/down controls on assistant messages
   - Optional reason code + comment capture
   - Append-only feedback events preserved in `answer_feedback_events`
   - Rolling quality snapshots and negative-pattern flagging in `answer_quality_snapshots`
   - Admin/reviewer metrics panel at `GET /api/v1/chat/feedback/metrics` (role-gated)

5. **LDAP-backed user management (identity source of truth)**
   - LDAP is the authoritative source for user identities; the PlantIQ UI cannot create or delete users
   - `GET /api/v1/auth/admin/users` returns paginated list of LDAP-backed users (admin only)
   - `PATCH /api/v1/auth/admin/users/{user_id}/role` allows role updates only (no self-update; non-admin cannot assign `plantiq_admin`)
   - `POST /api/v1/auth/admin/users` removed and returns **410 Gone** — user creation must go through LDAP/AD provisioning
   - Admin UI shows users sourced from LDAP; role-only editing is the only permitted mutation

6. **Hybrid retrieval with explainability (Candidate 4 — Option B)**
   - BM25 lexical and dense vector retrieval run as independent branches
   - Application-layer weighted-RRF fusion with one-branch-failure fallback
   - Per-result provenance attribution (lexical score, vector score, fusion weight) preserved in retrieval diagnostics
   - Existing `/api/v1/chat/query` and `/api/v1/chat/stream` contracts are unchanged; diagnostics are additive only

6. **Operational controls and traceability**
   - Lifecycle status tracking
   - Artifacts for validation/review/optimization/QA
   - Conversation persistence and bookmarks

### Quality-gated workflow at a glance

`upload → extract/validate → review → optimize → QA → publish`

### Chat runtime at a glance

`query → scoped retrieval → context assembly → local generation → citations`

---

## Key API endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | Issue JWT |
| POST | `/api/v1/documents/upload` | user+ | Upload document; enforces system/area scope policy |
| GET | `/api/v1/documents` | user+ | List documents visible to caller's scope |
| POST | `/api/v1/chat/query` | user+ | Scoped RAG query (SSE stream) |
| POST | `/api/v1/chat/feedback` | user+ | Submit thumbs up/down feedback on an answer |
| GET | `/api/v1/chat/feedback/metrics` | admin/reviewer | Aggregate feedback quality metrics |
| GET | `/api/v1/auth/admin/users` | admin | Paginated list of LDAP-backed users |
| PATCH | `/api/v1/auth/admin/users/{user_id}/role` | admin | Update a user's role (role updates only) |
| ~~POST~~ | ~~`/api/v1/auth/admin/users`~~ | — | **410 Gone** — user creation via UI removed; provision through LDAP/AD |

See [docs/api/chat_feedback.md](docs/api/chat_feedback.md) for full request/response contracts.

---

## Architecture summary

PlantIQ separates:

- **Transactional workflow state** in PostgreSQL (documents, statuses, approvals, conversations)
- **Semantic retrieval state** in Qdrant (published chunk vectors + metadata)

This keeps governance/auditability and retrieval performance decoupled while preserving citation traceability.

---

## Tech stack

| Layer | Technologies |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind, shadcn/ui |
| Backend | Python 3.10+, FastAPI, Pydantic, SQLAlchemy |
| Pipeline/AI | Docling, Qwen3-VL-4B, Qwen3-4B, BGE-Large-v1.5 |
| Data | PostgreSQL 15, Qdrant 1.x |
| Runtime | Docker, Docker Compose, SSE/WebSocket contracts |

---

## Repository structure

```text
llm-rag-chatbot/
├── apps/
│   ├── api/         # FastAPI backend APIs/services/tests
│   ├── pipeline/    # Ingestion, validation, optimization, QA pipeline
│   └── web/         # Next.js frontend (admin + chat)
├── docs/            # Architecture, capstone, ops, security docs
├── data/            # Raw/processed/artifact data
├── infra/           # Docker and infra scripts
├── logs/            # Load/endurance evidence outputs
├── docker-compose.yml
├── Makefile
└── PROJECT_STATUS.md
```

---

## Local setup and run

### Prerequisites

- Linux/macOS (Linux recommended for local parity)
- Python 3.10+
- Node.js 18+
- Docker with Compose v2
- NVIDIA GPU recommended for local model inference

### 1) Install dependencies

- `make install`

### 2) Configure environment

- Copy `.env.example` to `.env`
- Fill local values (ports, model references, auth settings)

### 3) Build and start local stack

- `make docker-build`
- `make docker-up`

### Local LDAP (dev)

The stack starts a local OpenLDAP container (`bitnami/openldap:2.6`, `dc=plantiq,dc=local`) seeded with demo users from [`infra/docker/ldap/seed.ldif`](infra/docker/ldap/seed.ldif).

**Verify LDAP is healthy after `make docker-up`:**

```bash
# List all users (anonymous read — confirms server is up and seed applied)
docker exec plantiq-ldap ldapsearch -x -H ldap://localhost:1389 \
  -b "ou=users,dc=plantiq,dc=local"

# Authenticated search (bind as admin)
docker exec plantiq-ldap ldapsearch -x -H ldap://localhost:1389 \
  -D "cn=admin,dc=plantiq,dc=local" \
  -w "PlantIQ_Dev_Admin_2026" \
  -b "ou=users,dc=plantiq,dc=local" uid mail
```

**Seed demo users:** `alice` / `bob` / `carol` — password `DemoPass@2026` for all.

**Toggle mock mode** (bypass real LDAP for unit tests): set `LDAP_MOCK=true` in `.env`.

**Production AD wiring:** Replace the `LDAP_*` vars in `.env` with real AD values (see commented production profile in `.env.example`). Remove the `ldap` service from compose or leave it stopped.

### 4) View runtime logs

- `make docker-logs`

### 5) Stop services

- `make docker-down`

---

## Testing commands

### Run all

- `make test`

### Run per area

- `make test-backend`
- `make test-pipeline`
- `make test-frontend`
- `make test-integration`

### Optional validation sweep

- `make validate`

---

## Demo accounts

| Username | Password | Role | Access |
|---|---|---|---|
| `demoadmin` | `demo@plantiq` | Admin | Document workflow + chat |
| `demouser` | `demo@plantiq` | User | Chat + conversation history |

> Demo credentials are for local/demo evaluation only.

---

## Evaluator links

- Prototype: https://plantiq.sahossain.com/PlantIQ/
- Backend API: https://plantiqapi.sahossain.com/
- Repository: https://github.com/abedhossainn/PlantIQ
- Source archive (Beta): https://drive.google.com/file/d/1cuf5pbR_7IyQsdDAL5FehS2SkBEVsh32/view?usp=drive_link

---

## Known gaps (Beta)

1. **Production AD/LDAP integration:** LDAP-backed user management is implemented for local/dev environments. Production binding to a real AD/LDAP server requires environment-specific `LDAP_SERVER_URL`, `LDAP_BIND_DN`, `LDAP_BIND_PASSWORD`, and `LDAP_USER_SEARCH_BASE` to be configured.
2. **User creation/deletion must go through LDAP/AD** — PlantIQ UI intentionally has no user-provisioning capability.
3. **Final enterprise hardening** remains in progress (governance/runtime hardening tasks).
4. **Code-quality hardening** is active via remediation waves across backend/pipeline/frontend.

---

## Immediate next priorities

1. Configure production LDAP/AD binding credentials and validate against real directory.
2. Close remaining hardening tasks on ingestion/chat critical paths.
3. Finish outstanding code-quality remediation waves (Sonar Waves 2–4) and re-verify regressions.
4. Finalize Beta evidence packaging and readiness for final checkpoint signoff.

