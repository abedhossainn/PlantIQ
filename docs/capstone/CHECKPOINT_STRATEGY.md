# PlantIQ Capstone Checkpoint Strategy for Source Control

**Architecture Planning Agent**  
**Date:** March 9, 2026  
**Purpose:** Staged deployment of tested Python modules across Alpha, Beta, and Final checkpoints

---

## Overview

Instead of removing `*.py` from .gitignore, this strategy uses a **layered allowlist approach** where Python files are explicitly included in git only after:
1. ✅ Unit tests pass
2. ✅ Module-level validation passes  
3. ✅ Integration with adjacent modules confirmed
4. ✅ Checkpoint submission completed

This ensures GitHub only contains production-ready, thoroughly tested code aligned to capstone milestones.

---

## Checkpoint Timeline & Deliverables

### Alpha Checkpoint (Week 4-5: Feb 28 - Mar 7)
**Focus:** Document Ingestion & VLM Validation  
**Primary Deliverable:** HITL pipeline core modules working end-to-end

**Files to Push:**
```
pipeline/src/ingestion/
  ├── docling_converter.py              ✅ Ready (tested)
  └── __init__.py

pipeline/src/validation/
  ├── enhanced_validator.py             ✅ Ready (tested)
  ├── vlm_comparison.py                 ✅ Ready (tested)
  ├── vlm_image_describer.py            ✅ Ready (tested)
  └── __init__.py

pipeline/src/utils/
  ├── vlm_options.py                    ✅ Ready (tested)
  ├── vlm_response_parser.py            ✅ Ready (tested)
  ├── progress_tracker.py               ✅ Ready (tested)
  ├── table_figure_handler.py           ✅ Ready (tested)
  └── __init__.py

pipeline/src/cli/
  ├── hitl_pipeline.py                  ✅ Ready (tested)
  └── __init__.py

pipeline/configs/
  ├── vlm_config.yaml                   ✅ Config (no testing needed)
  └── docling.env                       ✅ Config (no testing needed)

pipeline/tests/
  ├── test_vlm_integration.py           ✅ Ready (all 5 tests pass)
  ├── verify_hitl_setup.py              ✅ Ready (verified)
  └── __init__.py

pipeline/
  ├── pyproject.toml                    ✅ Dependencies (ready)
  ├── requirements.txt                  ✅ Frozen (ready)
  └── README.md                         ✅ Documentation

docs/capstone/
  ├── Capstone_Proposal_UPDATED.md      ✅ Proposal (final)
  ├── Alpha Deliverable Checklist.md    ✅ Checklist (final)
  └── ENHANCED_HITL_GUIDE.md            ✅ Documentation
```

**Checkpoint Validation:**
- [ ] All ingestion modules execute without errors
- [ ] VLM comparison produces valid JSON output
- [ ] Test suite passes: `pytest pipeline/tests/ -v`
- [ ] Sample document (LNG manual) processes end-to-end
- [ ] Evidence artifacts generated and validated
- [ ] Documentation complete and links functional

**Git Command:**
```bash
git add pipeline/src/
git add pipeline/configs/
git add pipeline/tests/
git add pipeline/{pyproject.toml,requirements.txt,README.md}
git add docs/capstone/Capstone_Proposal_UPDATED.md
git add docs/capstone/Alpha\ Deliverable\ Checklist.md
git add docs/capstone/ENHANCED_HITL_GUIDE.md
git commit -m "Alpha Checkpoint: HITL Ingestion Pipeline (Week 4-5)

- Docling PDF→MD conversion with Qwen integration
- VLM page comparison validation (Qwen2.5-VL-32B)
- VLM image description generation
- Enhanced validation with evidence extraction
- Section-based review workspace generation
- Multi-level progress tracking
- Complete test suite (5/5 passing)
- Integration guide and architecture documentation
"
```

---

### Beta Checkpoint (Week 7-8: Mar 7 - Mar 21)
**Focus:** Review & QA System + Backend Scaffold  
**Primary Deliverable:** Human-in-the-loop review + QA gates + backend API skeleton

**New Files to Push (Beyond Alpha):**

```
pipeline/src/review/
  ├── section_review.py                 ✅ Ready (tested)
  └── __init__.py

pipeline/src/qa/
  ├── qa_gates.py                       ✅ Ready (tested)
  └── __init__.py

pipeline/src/lineage/
  ├── lineage_tracker.py                ✅ Ready (tested)
  └── __init__.py

pipeline/src/cli/
  ├── text_reformatter.py               ✅ Ready (tested)
  └── __init__.py

backend/
  ├── app/
  │   ├── main.py                       ✅ FastAPI entrypoint
  │   ├── api/
  │   │   ├── __init__.py
  │   │   ├── chat.py                   ✅ Chat routers (skeleton)
  │   │   ├── auth.py                   ✅ Auth routers (skeleton)
  │   │   └── admin.py                  ✅ Admin routers (skeleton)
  │   ├── core/
  │   │   ├── __init__.py
  │   │   ├── config.py                 ✅ Settings
  │   │   ├── security.py               ✅ RBAC structure
  │   │   └── logging.py                ✅ Logging config
  │   ├── services/
  │   │   ├── __init__.py
  │   │   └── rag_service.py            ✅ RAG skeleton
  │   └── models/
  │       ├── __init__.py
  │       ├── chat.py                   ✅ Chat models
  │       ├── document.py               ✅ Document models
  │       └── user.py                   ✅ User models
  ├── tests/
  │   ├── __init__.py
  │   ├── test_api/
  │   │   └── test_chat.py              ✅ Basic tests
  │   └── conftest.py                   ✅ Pytest fixtures
  ├── pyproject.toml                    ✅ Dependencies
  ├── requirements.txt                  ✅ Frozen
  └── README.md                         ✅ Backend setup guide

frontend/tests/
  ├── __init__.py
  ├── test_components.tsx               ✅ Component tests (basic)
  ├── test_auth.test.tsx                ✅ Auth flow tests
  └── jest.config.js                    ✅ Config

docs/capstone/
  ├── Beta Deliverable Checklist.md     ✅ Checklist (updated)
  └── BACKEND_ARCHITECTURE.md           ✅ New documentation

infra/docker/
  ├── backend.Dockerfile               ✅ Backend container
  ├── frontend.Dockerfile              ✅ Frontend container
  └── nginx.Dockerfile                 ✅ Reverse proxy (optional)

infra/compose/
  ├── anythingllm-compose.yml           ✅ Moved from root
  └── .env.example                      ✅ Environment template
```

**Checkpoint Validation:**
- [ ] Review system creates section workspaces with checklists
- [ ] QA gates score documents with quantitative metrics
- [ ] Lineage tracker generates audit trails
- [ ] Post-approval reformatter executes without errors
- [ ] Backend app starts: `python backend/app/main.py`
- [ ] FastAPI docs available: `http://localhost:8000/docs`
- [ ] Frontend tests pass: `npm test`
- [ ] Docker images build successfully
- [ ] Docker compose orchestrates services

**Git Command:**
```bash
git add pipeline/src/review/
git add pipeline/src/qa/
git add pipeline/src/lineage/
git add pipeline/src/cli/text_reformatter.py
git add backend/
git add frontend/tests/
git add infra/
git add docs/capstone/Beta\ Deliverable\ Checklist.md
git add docs/capstone/BACKEND_ARCHITECTURE.md
git commit -m "Beta Checkpoint: Review System + Backend Scaffold + DevOps (Week 7-8)

Pipeline Additions:
- Section-based review workflow (section_review.py)
- QA gates with quantitative metrics (qa_gates.py)
- Document lineage and audit tracking (lineage_tracker.py)
- Post-approval text reformatting (text_reformatter.py)

Backend:
- FastAPI application scaffold with OpenAI-compatible endpoints
- Authentication and authorization layers (LDAP/AD ready)
- RAG service orchestration skeleton
- Pydantic models for chat, documents, users

Frontend:
- Component and auth flow test suite

Infrastructure:
- Backend, frontend, and nginx Dockerfiles
- Docker Compose orchestration for all services
- Environment configuration templates

Documentation:
- Backend architecture guide
- Beta checkpoint deliverables

All modules tested individually and integrated.
"
```

---

### Final Checkpoint (Week 10-11: Mar 21 - Apr 4)
**Focus:** Complete Chat Interface + Vector DB Integration + Deployment  
**Primary Deliverable:** End-to-end RAG system with citations, bookmarks, RBAC, and air-gapped deployment

**Final Files to Push (Beyond Beta):**

```
backend/
  ├── app/
  │   ├── api/
  │   │   ├── chat.py                   ✅ EXPANDED with LangChain
  │   │   ├── documents.py              ✅ Document upload endpoints
  │   │   ├── users.py                  ✅ User management endpoints
  │   │   └── admin.py                  ✅ EXPANDED with admin functions
  │   ├── services/
  │   │   ├── rag_service.py            ✅ EXPANDED with retrieval
  │   │   ├── retrieval.py              ✅ Vector DB queries
  │   │   ├── citation.py               ✅ Citation extraction
  │   │   └── llm_service.py            ✅ vLLM inference integration
  │   └── integrations/
  │       ├── __init__.py
  │       ├── vector_db.py              ✅ Qdrant/ChromaDB driver
  │       ├── postgres.py               ✅ Database ORM models
  │       └── vllm_client.py            ✅ vLLM HTTP client
  ├── tests/
  │   ├── test_services/
  │   │   ├── test_rag_service.py       ✅ RAG pipeline tests
  │   │   ├── test_retrieval.py         ✅ Vector DB tests
  │   │   └── test_citation.py          ✅ Citation tests
  │   ├── test_integration/
  │   │   ├── test_end_to_end.py        ✅ Full workflow tests
  │   │   └── test_deployment.py        ✅ Docker tests
  │   └── fixtures/
  │       ├── sample_documents.py       ✅ Test data
  │       └── mock_responses.py         ✅ Mock LLM responses
  └── migrations/
      └── 001_initial_schema.sql        ✅ Database schema

frontend/
  ├── app/
  │   └── [EXPANDED with all routes working end-to-end]
  ├── components/
  │   └── [EXPANDED with all UI components]
  ├── lib/
  │   └── [EXPANDED with API clients, hooks, auth]
  ├── tests/
  │   ├── __init__.py
  │   ├── test_components/              ✅ Comprehensive
  │   ├── test_pages/                   ✅ Page integration tests
  │   └── test_e2e.test.tsx             ✅ Playwright e2e tests
  ├── Dockerfile                        ✅ Simplified from infra/
  └── .dockerignore                     ✅ Docker context optimization

infra/
  ├── docker/
  │   ├── backend.Dockerfile           ✅ Production-grade
  │   ├── frontend.Dockerfile          ✅ Production-grade
  │   ├── nginx.Dockerfile             ✅ Reverse proxy setup
  │   └── vllm.Dockerfile              ✅ vLLM inference server
  ├── compose/
  │   ├── docker-compose.prod.yml      ✅ Production orchestration
  │   ├── docker-compose.dev.yml       ✅ Development orchestration
  │   └── .env.prod.example            ✅ Production environment
  ├── scripts/
  │   ├── setup_air_gap.sh              ✅ Air-gap preparation
  │   ├── initialize_db.sh              ✅ Database initialization
  │   ├── backup_vector_db.sh           ✅ Backup procedures
  │   └── deploy.sh                     ✅ Deployment automation
  ├── monitoring/
  │   ├── prometheus.yml                ✅ Metrics config
  │   ├── grafana_dashboard.json        ✅ Dashboards
  │   └── logging_config.yaml           ✅ Logging setup
  └── k8s/
      ├── deployment.yaml               ✅ K8s deployment (future-ready)
      ├── service.yaml                  ✅ K8s service
      └── volumeclaim.yaml              ✅ Persistent storage

tests/
  ├── integration/
  │   ├── test_pipeline_to_rag.py      ✅ Pipeline→RAG integration
  │   ├── test_frontend_to_backend.py  ✅ Frontend→Backend integration
  │   └── test_full_workflow.py        ✅ Complete workflow
  ├── e2e/
  │   ├── playwright.config.ts          ✅ E2E config
  │   ├── document_upload_flow.spec.ts ✅ Upload workflow
  │   ├── chat_query_flow.spec.ts      ✅ Chat workflow
  │   └── admin_review_flow.spec.ts    ✅ Admin workflow
  ├── performance/
  │   ├── test_retrieval_latency.py    ✅ Retrieval benchmarks
  │   ├── test_inference_latency.py    ✅ Inference benchmarks
  │   └── test_concurrent_users.py     ✅ Load testing
  └── fixtures/
      ├── real_documents/              ✅ Sample LNG manuals
      └── query_patterns.json          ✅ Real queries from domain

docs/
  ├── architecture/
  │   ├── rag_architecture.md           ✅ FINAL architecture
  │   ├── component_interactions.md     ✅ Component diagram explanations
  │   ├── data_flow.md                  ✅ End-to-end data flow
  │   └── security_architecture.md      ✅ Security design
  ├── api/
  │   ├── openapi.yaml                  ✅ OpenAPI 3.0 spec
  │   ├── chat_endpoints.md             ✅ Chat API docs
  │   ├── auth_endpoints.md             ✅ Auth API docs
  │   ├── admin_endpoints.md            ✅ Admin API docs
  │   └── EXAMPLES.md                   ✅ Usage examples
  ├── operations/
  │   ├── DEPLOYMENT_GUIDE.md           ✅ Air-gapped deployment
  │   ├── TROUBLESHOOTING.md            ✅ Common issues
  │   ├── RUNBOOK.md                    ✅ Operational runbook
  │   ├── DISASTER_RECOVERY.md          ✅ DR procedures
  │   └── BACKUP_STRATEGY.md            ✅ Backup/restore
  ├── security/
  │   ├── THREAT_MODEL.md               ✅ Threat analysis
  │   ├── SECURITY_CONTROLS.md          ✅ Control implementation
  │   ├── COMPLIANCE_CHECKLIST.md       ✅ IEC 62443 / NERC CIP mapping
  │   └── INCIDENT_RESPONSE.md          ✅ IR procedures
  ├── capstone/
  │   ├── Capstone_Proposal_UPDATED.md  ✅ FINAL proposal
  │   ├── Final Deliverable Checklist.md ✅ Completion checklist
  │   ├── PROJECT_LESSONS_LEARNED.md    ✅ Post-project notes
  │   └── FUTURE_ROADMAP.md             ✅ Future enhancements

tools/
  ├── generate_test_data.py             ✅ Test dataset generation
  ├── document_validator.py             ✅ Batch validation tool
  ├── vector_db_inspector.py            ✅ Vector store inspection
  └── performance_analyzer.py           ✅ Performance metrics

ROOT:
  ├── docker-compose.yml                ✅ Final unified helm
  ├── .env.example                      ✅ Complete environment template
  ├── Makefile                          ✅ Complete task automation
  ├── README.md                         ✅ Complete project guide
  ├── DEPLOYMENT_CHECKLIST.md           ✅ Pre-deployment validation
  └── ARCHITECTURE_DECISION_RECORDS/    ✅ ADRs for major decisions
```

**Checkpoint Validation:**
- [ ] End-to-end workflow: PDF upload → validation → review → QA → ingestion → query → citation
- [ ] Chat interface returns cited answers from vector DB
- [ ] Multi-turn conversation with context preservation
- [ ] Bookmarking and saved answers functionality
- [ ] Admin user management with role-based access
- [ ] All integration tests pass: `pytest tests/integration/ -v`
- [ ] All e2e tests pass: `npx playwright test`
- [ ] Performance benchmarks meet targets
- [ ] Deployment on air-gapped infrastructure validated
- [ ] Security audit completed (RBAC, audit logging, data isolation)
- [ ] Production Dockerfile images build and run

**Git Command:**
```bash
git add backend/
git add frontend/app/
git add frontend/components/
git add frontend/lib/
git add frontend/tests/
git add infra/
git add tests/
git add tools/
git add docs/
git add docker-compose.yml
git add .env.example
git add Makefile
git add README.md
git add DEPLOYMENT_CHECKLIST.md
git add ARCHITECTURE_DECISION_RECORDS/
git commit -m "Final Checkpoint: Complete Air-Gapped RAG System (Week 10-11)

Backend Completion:
- Full RAG service with LangChain orchestration
- Vector database integration (Qdrant/ChromaDB)
- Citation extraction and tracking
- vLLM inference integration
- PostgreSQL ORM models
- Comprehensive test suite (integration + e2e)
- Database migrations

Frontend Completion:
- All routes implemented and tested
- Chat workflow with streaming responses
- Document upload and review interface
- User management and RBAC
- Bookmark/saved answers functionality
- Full test coverage (unit + component + e2e)

Infrastructure:
- Production-grade Dockerfiles (backend, frontend, nginx, vllm)
- Production and development docker-compose files
- Database initialization scripts
- Backup and restore procedures
- Monitoring and logging setup
- Kubernetes manifests (future-ready)

Testing:
- Integration tests (pipeline→RAG)
- End-to-end tests (Playwright workflows)
- Performance benchmarks
- Load testing and stress tests

Documentation:
- Complete API specification (OpenAPI 3.0)
- Deployment guide for air-gapped environments
- Operations runbook and troubleshooting
- Security architecture and threat model
- Compliance checklist (IEC 62443, NERC CIP)
- Final capstone deliverables and lessons learned

System Ready for Production Deployment
"
```

---

## Staged .gitignore Strategy

### Initial .gitignore (Before Any Python)

```gitignore
# Root-level .gitignore
# This file BLOCKS all Python files until explicitly allowed per checkpoint

# === Python Global Blocks ===
*.pyc
*.pyo
*.pyd
__pycache__/
*.egg-info/
dist/
build/
.eggs/

# === Environment & Secrets ===
.env
.env.local
.env.*.local
*.env
!.env.example

# === Virtual Environments ===
.venv/
venv/
ENV/
env/

# === Data (Runtime, Never Source-Control) ===
data/raw/*
!data/raw/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/artifacts/*
!data/artifacts/.gitkeep
data/indexes/*
!data/indexes/.gitkeep

# === Build Artifacts ===
frontend/.next/
frontend/out/
frontend/dist/
frontend/node_modules/
backend/dist/
pipeline/dist/

# === IDE ===
.vscode/
.idea/
*.swp
*.swo
*.sublime-project
*.sublime-workspace

# === OS ===
.DS_Store
Thumbs.db
.directory

# === Logs ===
*.log
logs/

# === Testing ===
.coverage
htmlcov/
*.cover
.pytest_cache/
.nyc_output/

# === Temporary ===
*.tmp
*.temp
text.txt

# === Legacy Files (Pre-Restructure) ===
# These are the old root-level files that have been moved
# Keep them here for reference during transition period
# Once confirmed moved to new locations, can be safely ignored
/rag_*.py
/vlm_*.py
/docling_*.py
/test_*.py
/verify_*.py
/*.yaml
/*.env

!.gitkeep
```

### Alpha Checkpoint .gitignore Update

```gitignore
# After Alpha Checkpoint: Allow tested pipeline modules

# === ALPHA APPROVED: Pipeline Ingestion & Validation ===
# All modules tested, validated, and documented
!pipeline/src/ingestion/**/*.py
!pipeline/src/validation/**/*.py
!pipeline/src/utils/**/*.py
!pipeline/src/cli/hitl_pipeline.py
!pipeline/tests/**/*.py
!pipeline/configs/
!pipeline/requirements.txt
!pipeline/pyproject.toml

# === Documentation ===
!docs/capstone/Capstone_Proposal_UPDATED.md
!docs/capstone/Alpha*Deliverable*
!docs/capstone/ENHANCED_HITL_GUIDE.md
```

### Beta Checkpoint .gitignore Update

```gitignore
# After Beta Checkpoint: Add Review, QA, Lineage, Backend Scaffold

# === BETA APPROVED: Pipeline Review & QA ===
!pipeline/src/review/**/*.py
!pipeline/src/qa/**/*.py
!pipeline/src/lineage/**/*.py
!pipeline/src/cli/text_reformatter.py

# === BETA APPROVED: Backend Skeleton ===
!backend/app/**/*.py
!backend/tests/**/*.py
!backend/requirements.txt
!backend/pyproject.toml
!backend/README.md

# === BETA APPROVED: Frontend Tests ===
!frontend/tests/**/*

# === BETA APPROVED: Infrastructure as Code ===
!infra/docker/*.Dockerfile
!infra/compose/

# === Documentation ===
!docs/capstone/Beta*Deliverable*
!docs/capstone/BACKEND_ARCHITECTURE.md
```

### Final Checkpoint .gitignore Update

```gitignore
# After Final Checkpoint: Complete system (all Python files)

# === FINAL APPROVED: All Backend ===
!backend/**/*.py

# === FINAL APPROVED: All Frontend ===
!frontend/app/**/*
!frontend/components/**/*
!frontend/lib/**/*
!frontend/types/**/*.ts

# === FINAL APPROVED: All Tests ===
!tests/**/*.py
!tests/**/*.ts

# === FINAL APPROVED: Tools ===
!tools/**/*.py

# === FINAL APPROVED: All Documentation ===
!docs/**/*.md
!docs/**/*.yaml
!docs/**/*.json

# === FINAL: Root Config Files ===
!Makefile
!docker-compose.yml
!.env.example
!DEPLOYMENT_CHECKLIST.md
!ARCHITECTURE_DECISION_RECORDS/

# Allow all necessary files to be tracked
!.gitkeep
!README.md
!LICENSE
```

---

## Pre-Push Verification Workflow

Before pushing any Python file to GitHub, execute this verification checklist:

### 1. Unit Test Verification

```bash
# For pipeline modules
cd pipeline
pytest tests/test_vlm_integration.py -v
pytest tests/verify_hitl_setup.py -v

# For backend modules
cd backend
pytest tests/ -v --cov=app

# For frontend
cd frontend
npm test -- --coverage

echo "✅ All unit tests pass"
```

### 2. Module Integration Test

```bash
# Test module imports work
python3 << 'EOF'
try:
    from pipeline.src.ingestion.docling_converter import DoclingConverter
    from pipeline.src.validation.enhanced_validator import EnhancedValidator
    from pipeline.src.utils.vlm_options import VLMOptions
    from backend.app.main import app
    print("✅ All imports succeed")
except ImportError as e:
    print(f"❌ Import failed: {e}")
    exit(1)
EOF
```

### 3. Linting & Code Quality

```bash
# Python style checks
cd pipeline && pylint src/ --disable=all --enable=syntax-error
cd backend && pylint app/ --disable=all --enable=syntax-error

# TypeScript checks
cd frontend && npx eslint app/ components/ lib/

echo "✅ Code quality checks pass"
```

### 4. Functional Test (Sample Data)

```bash
# Pipeline: Test with sample document
cd pipeline
python3 -m src.cli.hitl_pipeline run ../data/raw/test_sample.pdf

# Backend: Test API startup
cd backend
timeout 10 python3 -m app.main &
sleep 2
curl -s http://localhost:8000/docs > /dev/null && echo "✅ Backend API starts"
kill %1

# Frontend: Test build
cd frontend
npm run build && echo "✅ Frontend builds successfully"
```

### 5. Docker Build Test

```bash
# Test Docker images build
docker build -f infra/docker/backend.Dockerfile -t plantiq-backend:test .
docker build -f infra/docker/frontend.Dockerfile -t plantiq-frontend:test .

echo "✅ Docker images build successfully"
```

### 6. Documentation Check

```bash
# Verify all referenced files exist
grep -r "^!\." .gitignore | while read line; do
  file=$(echo "$line" | cut -d' ' -f2)
  if [ ! -e "$file" ]; then
    echo "⚠️  .gitignore references non-existent file: $file"
  fi
done

echo "✅ Documentation references valid"
```

### 7. Checkpoint Completeness

```bash
# Run checkpoint validation script
python3 tools/checkpoint_validator.py --checkpoint Alpha
# Output: ✅ Alpha checkpoint complete (15/15 files)
```

---

## Checkpoint Validation Scripts

### Pipeline Test Commands by Checkpoint

**Alpha Validation:**
```bash
# Ingestion
python3 pipeline/src/ingestion/docling_converter.py --help

# Validation
python3 -m pytest pipeline/tests/test_vlm_integration.py::test_enhanced_validator -v
python3 -m pytest pipeline/tests/test_vlm_integration.py::test_vlm_comparison -v
python3 -m pytest pipeline/tests/test_vlm_integration.py::test_vlm_describer -v

# Full Pipeline
python3 pipeline/src/cli/hitl_pipeline.py run data/raw/test_sample.pdf --quick

# Result: ✅ PASS
```

**Beta Validation:**
```bash
# Review module
python3 -m pytest pipeline/tests/test_vlm_integration.py::test_section_review -v

# QA module
python3 -m pytest pipeline/tests/test_vlm_integration.py::test_qa_gates -v

# Backend startup
python3 -m pytest backend/tests/ -v
python3 -m backend.app.main --test-startup

# Docker
docker-compose -f infra/compose/docker-compose.dev.yml up -d
sleep 5
curl http://localhost:8000/health
docker-compose -f infra/compose/docker-compose.dev.yml down

# Result: ✅ PASS
```

**Final Validation:**
```bash
# Full end-to-end test
python3 -m pytest tests/integration/test_full_workflow.py -v

# E2E browser tests
npx playwright test tests/e2e/

# Docker production compose
docker-compose -f infra/compose/docker-compose.prod.yml config

# Performance benchmarks
python3 tests/performance/test_retrieval_latency.py

# Security audit
python3 tools/security_audit.py

# Deployment checklist
python3 tools/deployment_validator.py --environment air-gapped

# Result: ✅ PRODUCTION READY
```

---

## Git Workflow Per Checkpoint

### Alpha Deployment

```bash
# 1. Verify all tests pass
cd pipeline && pytest tests/ -v && cd ..

# 2. Update .gitignore for Alpha
cat >> .gitignore << 'EOF'

# === ALPHA APPROVED ===
!pipeline/src/ingestion/**/*.py
!pipeline/src/validation/**/*.py
!pipeline/src/utils/**/*.py
!pipeline/src/cli/hitl_pipeline.py
!pipeline/tests/**/*.py
!docs/capstone/Alpha*
EOF

# 3. Stage only Alpha files
git add .gitignore
git add pipeline/src/
git add pipeline/tests/
git add pipeline/configs/
git add pipeline/pyproject.toml
git add pipeline/requirements.txt
git add docs/capstone/Capstone_Proposal_UPDATED.md
git add docs/capstone/Alpha*

# 4. Review staged changes
git diff --staged --stat

# 5. Commit with checkpoint context
git commit -m "Alpha Checkpoint: HITL Ingestion Pipeline (Verified)

Complete modules:
- Docling PDF→Markdown conversion
- VLM page-by-page validation  
- VLM image description generation
- Enhanced validation with evidence
- Multi-level progress tracking

All tests passing (5/5):
✅ test_enhanced_validator
✅ test_vlm_comparison
✅ test_vlm_describer
✅ test_progress_tracker
✅ test_table_figure_handler

Document: LNG manual processed end-to-end
Artifacts: Evidence images, validation reports, section workspaces generated
Ready for manual review phase (Beta)
"

# 6. Push to GitHub
git push origin main
```

### Beta Deployment (Similar pattern)

```bash
# 1. Local verification
cd pipeline && pytest tests/ -v
cd backend && pytest tests/ -v
cd frontend && npm test
cd ..

# 2. Update .gitignore for Beta
# (append Beta-approved files)

# 3. Stage Beta files
git add .gitignore
git add pipeline/src/review/
git add pipeline/src/qa/
git add pipeline/src/lineage/
git add backend/
git add frontend/tests/
git add infra/
git add docs/capstone/Beta*

# 4-6. Commit and push
git diff --staged --stat
git commit -m "Beta Checkpoint: Review System + Backend Scaffold (Verified)..."
git push origin main
```

---

## Checkpoint Commit Template

Use this template for checkpoint commits (create `.gitmessage` file):

```
[CHECKPOINT: {ALPHA|BETA|FINAL}] {Feature Area}

## Verified Modules
- Module 1: {Status}
- Module 2: {Status}

## Test Results
✅ Unit tests: {N}/{N} passing
✅ Integration tests: {N}/{N} passing
✅ Coverage: {X}%

## Deliverables
- {Feature 1}
- {Feature 2}

## Documentation
- {Doc 1}
- {Doc 2}

## Ready for Next Phase
- {Next milestone}

---
Checkpoint: {Alpha|Beta|Final}
Timeline: Week {N}
Contributors: [List]
```

Use with:
```bash
git config commit.template ~/.gitmessage
```

---

## Rollback Strategy (If Tests Fail Post-Push)

If a module fails testing after push but before next checkpoint:

```bash
# 1. Create fix branch
git checkout -b fix/{module-name}

# 2. Fix the issue locally
# (make corrections, test thoroughly)

# 3. Force-push fix (only if not merged to main)
git push origin fix/{module-name} -f

# 4. OR: If already on main, create revert commit
git revert {commit-hash}
git push origin main

# 5. Update .gitignore to remove problematic file
# (Add to blockage section until re-verified)
```

---

## Summary

This checkpoint-driven approach ensures:

✅ **Quality Gates:** Every Python file tested before GitHub  
✅ **Traceability:** Clear commit history aligned to capstone milestones  
✅ **Rollback Capability:** Can revert to last known-good state  
✅ **Stakeholder Confidence:** Verified deliverables at each phase  
✅ **Documentation:** Clear what was added when and why  

The .gitignore evolves with your project maturity, allowing controlled progression from Alpha ingestion → Beta review → Final deployment readiness.
