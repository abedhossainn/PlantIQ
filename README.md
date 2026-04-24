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
| User-story completion | **12 / 13 fully implemented**, **1 / 13 partial** |
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
   - Workspace/document-type/shared scope filters
   - Retrieved context assembly
   - Local generation
   - Source citations in responses

3. **Operational controls and traceability**
   - Lifecycle status tracking
   - Artifacts for validation/review/optimization/QA
   - Conversation persistence and bookmarks

### Quality-gated workflow at a glance

`upload → extract/validate → review → optimize → QA → publish`

### Chat runtime at a glance

`query → scoped retrieval → context assembly → local generation → citations`

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

1. **Production AD integration** is not fully closed for enterprise rollout.
2. **Final enterprise hardening** remains in progress (auth/governance/runtime hardening tasks).
3. **Code-quality hardening** is active via remediation waves across backend/pipeline/frontend.

---

## Immediate next priorities

1. Complete production-grade AD/LDAP integration validation.
2. Close remaining hardening tasks on ingestion/chat critical paths.
3. Finish outstanding code-quality remediation waves and re-verify regressions.
4. Finalize Beta evidence packaging and readiness for final checkpoint signoff.

---

## Notes for contributors

- Current priority is **core path reliability** (ingestion + chat), not new feature breadth.
- Keep changes aligned to the quality-gated workflow and citation trust model.
- Treat `PROJECT_STATUS.md` as the current operational source of truth for progress and validation evidence.

For full checkpoint evidence and detailed architecture/test tables, see:
`docs/capstone/Beta_Checkpoint_Report.md`
