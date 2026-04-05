# PlantIQ Production-Grade Repository Restructure Plan

**Architecture Planning Agent**  
**Date:** March 9, 2026  
**Status:** Blueprint - Ready for Implementation

---

## Executive Summary

This plan reorganizes the PlantIQ project from a flat root-level structure into a production-grade monorepo with clear separation of concerns across frontend, backend, pipeline, infrastructure, documentation, data, and testing layers. The restructure aligns with the capstone proposal's recommended structure and enables maintainable, scalable, and secure air-gapped deployment.

**Key Benefits:**
- Clear separation between application layers (frontend/backend/pipeline)
- Improved maintainability through logical grouping
- Better version control and .gitignore management
- Simplified onboarding for new developers
- Production-ready deployment structure
- Audit-friendly documentation organization

---

## Current Structure Analysis

### Root-Level Files (15 Python modules + configs)

**Pipeline HITL Modules (Production Code):**
```
rag_hitl_pipeline.py              # Pipeline orchestrator (Stage 1-10 coordinator)
rag_validation_enhanced.py        # Enhanced validation with evidence extraction
rag_section_review.py             # Section-based review workspace generator
rag_qa_gates.py                   # QA metrics and acceptance criteria
rag_lineage.py                    # Document manifest and audit trail
rag_table_figure_handler.py       # Table/figure extraction and serialization
rag_vlm_comparison.py             # VLM page-by-page validation (Stage 2a)
rag_vlm_image_describer.py        # VLM image description generation (Stage 2b)
rag_text_reformatter.py           # Post-approval RAG reformatting (Stage 10)
vlm_options.py                    # VLM configuration and presets
vlm_response_parser.py            # Pydantic-based JSON response parser
progress_tracker.py               # Multi-level progress tracking infrastructure
docling_convert_with_qwen.py      # Docling PDF→MD conversion with Qwen integration
```

**Test & Utility Scripts:**
```
test_vlm_integration.py           # VLM infrastructure test suite
verify_hitl_setup.py              # HITL pipeline setup verification
```

**Configuration Files:**
```
docker-compose.yml                # Container orchestration (AnythingLLM setup)
docling.env                       # Docling-specific environment variables
vlm_config_project.yaml           # VLM pipeline configuration
```

**Documentation (Root):**
```
README.md                         # Top-level project overview
PROJECT_STATUS.md                 # Progress tracking and change log
instructions.md                   # Original project requirements/notes
INTEGRATED_ARCHITECTURE.md        # Architecture documentation (legacy)
RAG_Chatbot_Architecture.md       # HITL architecture plan
```

### Existing Directories

**Frontend (Complete Next.js app):**
```
frontend/
├── app/                          # Next.js routes (chat, admin, login)
├── components/                   # React components (shared, ui feature)
├── lib/                          # Client utilities, auth, API clients
├── public/                       # Static assets (logos, images)
├── types/                        # TypeScript type definitions
├── .next/                        # Build artifacts (ignored)
├── out/                          # Static export output (deployed to GitHub Pages)
├── node_modules/                 # Dependencies (ignored)
└── Config files (package.json, tsconfig.json, next.config.ts, etc.)
```

**Capstone Documents:**
```
Documents/
├── Capstone_Proposal_UPDATED.md  # Primary proposal with monorepo structure
├── Capstone_Proposal.md           # Original proposal
├── Alpha/Beta/Final Deliverable Checklists
├── Appendix 2a/2b/3/4 (Consent agreements, templates)
├── Project Bacground.md
└── User Story Template.md
```

**Data & Artifacts:**
```
InjestDocs/                       # Source PDF manuals (3 PDFs + sample pages)
  ├── COMMON Module 3 Characteristics of LNG.pdf
  ├── COMMON Module 4 Electrical Distribution System.pdf
  ├── COMMON Module 8 Integrated Control and Safety System.pdf
  ├── Characteristics of LNG.md   # Extracted markdown
  └── test_pages_13_14.pdf        # Test subset

hitl_workspace/                   # HITL review workspace (generated artifacts)
  ├── *_audit.txt                 # Audit trail reports
  ├── *_manifest.json             # Document manifests
  ├── *_pipeline_results.json     # Pipeline execution results
  ├── *_qa_pre_review.json        # QA gate metrics
  ├── *_tables_figures.json       # Table/figure extraction results
  ├── *_validation.json           # VLM validation reports
  ├── *_review/                   # Section-by-section review workspace
  └── *_versions/                 # Version history

validation_evidence/              # VLM validation evidence artifacts

anythingllm-storage/              # AnythingLLM data (if used for RAG backend)
  ├── comkey/
  ├── models/
  └── push-notifications/
```

**.github/ (CI/CD & Agents):**
```
.github/
├── workflows/                    # GitHub Actions CI/CD
│   ├── ci.yml                    # Backend CI pipeline
│   └── frontend-deploy.yml       # Frontend deployment to GitHub Pages
├── agents/                       # Copilot agent definitions
│   ├── lead.agent.md
│   ├── architecture.agent.md
│   ├── backend.agent.md
│   ├── frontend.agent.md
│   ├── devops.agent.md
│   ├── documentation.agent.md
│   ├── code-review.agent.md
│   └── testing.agent.md
└── copilot-instructions.md       # Project-level Copilot instructions
```

**Ignored Directories:**
```
.venv/                           # Python virtual environment
venv/                            # Alternative venv location
__pycache__/                     # Python bytecode cache
.vscode/                         # VS Code workspace settings
```

---

## Target Structure (Monorepo)

Based on the capstone proposal's recommended structure:

```
PlantIQ/
├── .github/                     # CI/CD & agent configs (KEEP, update paths)
│   ├── workflows/
│   ├── agents/
│   └── copilot-instructions.md
│
├── frontend/                    # Next.js UI (KEEP, already well-structured)
│   ├── app/
│   ├── components/
│   ├── lib/
│   ├── public/
│   ├── types/
│   ├── tests/                   # NEW: Frontend test suite
│   ├── package.json
│   └── tsconfig.json
│
├── backend/                     # NEW: FastAPI middleware + RAG API
│   ├── app/
│   │   ├── api/                 # routers: chat, auth, admin, docs
│   │   ├── core/                # config, settings, security, logging
│   │   ├── services/            # RAG, retrieval, citation services
│   │   ├── models/              # Pydantic models
│   │   └── main.py              # FastAPI entrypoint
│   ├── tests/                   # Backend unit/integration tests
│   ├── pyproject.toml           # NEW: Backend dependencies
│   └── requirements.txt
│
├── pipeline/                    # NEW: HITL ingestion + validation
│   ├── src/
│   │   ├── ingestion/           # MOVE: docling_convert_with_qwen.py
│   │   ├── validation/          # MOVE: rag_validation_enhanced.py, rag_vlm_*.py
│   │   ├── review/              # MOVE: rag_section_review.py
│   │   ├── qa/                  # MOVE: rag_qa_gates.py
│   │   ├── lineage/             # MOVE: rag_lineage.py
│   │   ├── utils/               # MOVE: vlm_options.py, vlm_response_parser.py, progress_tracker.py
│   │   └── cli/                 # MOVE: rag_hitl_pipeline.py, rag_text_reformatter.py
│   ├── configs/                 # MOVE: vlm_config_project.yaml, docling.env
│   ├── tests/                   # MOVE: test_vlm_integration.py, verify_hitl_setup.py
│   └── pyproject.toml           # NEW: Pipeline dependencies
│
├── infra/                       # NEW: Deployment infrastructure
│   ├── docker/                  # NEW: Service Dockerfiles
│   ├── compose/                 # MOVE: docker-compose.yml
│   ├── k8s/                     # NEW: Kubernetes manifests (future)
│   ├── scripts/                 # NEW: Provisioning, backup scripts
│   └── monitoring/              # NEW: Logging/metrics configs
│
├── data/                        # NEW: Runtime data (git-ignored)
│   ├── raw/                     # MOVE: InjestDocs/ → data/raw/
│   ├── processed/               # NEW: Intermediate outputs
│   ├── artifacts/               # MOVE: validation_evidence/, hitl_workspace/
│   └── indexes/                 # NEW: Vector DB persistence
│
├── docs/                        # NEW: Technical documentation
│   ├── architecture/            # MOVE: RAG_Chatbot_Architecture.md, INTEGRATED_ARCHITECTURE.md
│   ├── api/                     # NEW: API specs, examples
│   ├── operations/              # NEW: Runbooks, DR procedures
│   ├── security/                # NEW: Threat model, controls
│   └── capstone/                # MOVE: Documents/ contents
│
├── tests/                       # NEW: Cross-system tests
│   ├── integration/
│   ├── e2e/
│   ├── performance/
│   └── fixtures/
│
├── tools/                       # NEW: Developer utilities
│
├── .env.example                 # NEW: Environment template
├── .gitignore                   # UPDATE: Clean up, layer-specific ignores
├── docker-compose.yml           # NEW: Root-level unified deployment
├── Makefile                     # NEW: Standardized task shortcuts
├── README.md                    # UPDATE: New structure navigation
└── PROJECT_STATUS.md            # KEEP: Progress tracking
```

---

## Detailed File Migration Map

### Phase 1: Create New Directory Structure

**New Directories to Create:**
```bash
mkdir -p backend/app/{api,core,services,models}
mkdir -p backend/tests
mkdir -p pipeline/src/{ingestion,validation,review,qa,lineage,utils,cli}
mkdir -p pipeline/configs
mkdir -p pipeline/tests
mkdir -p infra/{docker,compose,k8s,scripts,monitoring}
mkdir -p data/{raw,processed,artifacts,indexes}
mkdir -p docs/{architecture,api,operations,security,capstone}
mkdir -p tests/{integration,e2e,performance,fixtures}
mkdir -p tools
mkdir -p frontend/tests
```

### Phase 2: Move Pipeline Modules

| Current Path | Target Path | Category |
|--------------|-------------|----------|
| `docling_convert_with_qwen.py` | `pipeline/src/ingestion/docling_converter.py` | Ingestion |
| `rag_validation_enhanced.py` | `pipeline/src/validation/enhanced_validator.py` | Validation |
| `rag_vlm_comparison.py` | `pipeline/src/validation/vlm_comparison.py` | Validation (Stage 2a) |
| `rag_vlm_image_describer.py` | `pipeline/src/validation/vlm_image_describer.py` | Validation (Stage 2b) |
| `rag_section_review.py` | `pipeline/src/review/section_review.py` | Review |
| `rag_qa_gates.py` | `pipeline/src/qa/qa_gates.py` | QA |
| `rag_lineage.py` | `pipeline/src/lineage/lineage_tracker.py` | Lineage |
| `rag_table_figure_handler.py` | `pipeline/src/utils/table_figure_handler.py` | Utils |
| `vlm_options.py` | `pipeline/src/utils/vlm_options.py` | Utils |
| `vlm_response_parser.py` | `pipeline/src/utils/vlm_response_parser.py` | Utils |
| `progress_tracker.py` | `pipeline/src/utils/progress_tracker.py` | Utils |
| `rag_hitl_pipeline.py` | `pipeline/src/cli/hitl_pipeline.py` | CLI orchestrator |
| `rag_text_reformatter.py` | `pipeline/src/cli/text_reformatter.py` | CLI (Stage 10) |

### Phase 3: Move Test & Config Files

| Current Path | Target Path |
|--------------|-------------|
| `test_vlm_integration.py` | `pipeline/tests/test_vlm_integration.py` |
| `verify_hitl_setup.py` | `pipeline/tests/verify_hitl_setup.py` |
| `vlm_config_project.yaml` | `pipeline/configs/vlm_config.yaml` |
| `docling.env` | `pipeline/configs/docling.env` |

### Phase 4: Move Data & Artifacts

| Current Path | Target Path |
|--------------|-------------|
| `InjestDocs/` | `data/raw/` |
| `hitl_workspace/` | `data/artifacts/hitl_workspace/` |
| `validation_evidence/` | `data/artifacts/validation_evidence/` |

### Phase 5: Move Documentation

| Current Path | Target Path |
|--------------|-------------|
| `RAG_Chatbot_Architecture.md` | `docs/architecture/rag_architecture.md` |
| `INTEGRATED_ARCHITECTURE.md` | `docs/architecture/integrated_architecture.md` |
| `instructions.md` | `docs/capstone/original_requirements.md` |
| `Documents/` (entire directory) | `docs/capstone/` |

### Phase 6: Move Infrastructure

| Current Path | Target Path |
|--------------|-------------|
| `docker-compose.yml` (AnythingLLM) | `infra/compose/anythingllm-compose.yml` |

### Phase 7: Frontend (No Move, Add Tests)

Frontend remains at `frontend/` but add:
- `frontend/tests/` for test suites
- Update imports if backend API client paths change

### Phase 8: Backend (Create New)

Backend directory is currently empty. Create structure:
```bash
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI app entrypoint
│   ├── api/
│   │   ├── __init__.py
│   │   ├── chat.py              # Chat endpoint routers
│   │   ├── auth.py              # Authentication routers
│   │   ├── admin.py             # Admin/document management routers
│   │   └── docs.py              # API documentation routers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py            # Settings, environment variables
│   │   ├── security.py          # Auth, RBAC, token handling
│   │   └── logging.py           # Structured logging setup
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rag_service.py       # RAG orchestration logic
│   │   ├── retrieval.py         # Vector DB retrieval
│   │   ├── citation.py          # Citation extraction
│   │   └── llm_service.py       # LLM inference integration
│   └── models/
│       ├── __init__.py
│       ├── chat.py              # Chat request/response models
│       ├── document.py          # Document metadata models
│       └── user.py              # User/auth models
├── tests/
│   ├── __init__.py
│   ├── test_api/
│   ├── test_services/
│   └── test_models/
├── pyproject.toml               # Poetry/pip-tools config
├── requirements.txt             # Pinned dependencies
└── README.md                    # Backend-specific setup
```

---

## Impact Analysis: What Needs Updates

### 1. Python Import Paths

**Pipeline Modules:**
All internal imports between pipeline modules need updating.

**Before:**
```python
from rag_validation_enhanced import EnhancedValidator
from vlm_options import VLMOptions
```

**After:**
```python
from pipeline.src.validation.enhanced_validator import EnhancedValidator
from pipeline.src.utils.vlm_options import VLMOptions
```

**Action:** Update all import statements in pipeline modules after relocation.

### 2. Configuration File Paths

**Pipeline Orchestrator:**
```python
# Before
config_path = "vlm_config_project.yaml"

# After
config_path = "pipeline/configs/vlm_config.yaml"
```

**Docker Compose:**
```yaml
# Before
env_file: ./docling.env

# After
env_file: ./pipeline/configs/docling.env
```

### 3. Data Paths

**Pipeline Scripts:**
```python
# Before
pdf_path = "InjestDocs/COMMON Module 3.pdf"
workspace = "hitl_workspace/"

# After
pdf_path = "data/raw/COMMON Module 3.pdf"
workspace = "data/artifacts/hitl_workspace/"
```

### 4. Documentation Links

**README.md** references need updating:
- Architecture doc paths → `docs/architecture/`
- Proposal links → `docs/capstone/`

### 5. CI/CD Workflows

**.github/workflows/ci.yml:**
```yaml
# Before
- name: Test Pipeline
  run: python test_vlm_integration.py

# After
- name: Test Pipeline
  run: python -m pytest pipeline/tests/
```

### 6. .gitignore Updates

**Current .gitignore is overly aggressive** (ignoring all `.py` files). Need to create layer-specific ignores:

```gitignore
# Root .gitignore
*.pyc
__pycache__/
.venv/
venv/
.env
.env.local

# Data (runtime, not source controlled)
data/raw/*
!data/raw/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/artifacts/*
!data/artifacts/.gitkeep
data/indexes/*
!data/indexes/.gitkeep

# Build artifacts
frontend/.next/
frontend/out/
frontend/node_modules/
backend/dist/
pipeline/dist/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Logs
*.log
logs/

# OS
.DS_Store
Thumbs.db

# Temporary
text.txt
*.tmp
```

**Important:** Remove `*.py` from .gitignore to allow Python files to be tracked!

### 7. Docker Compose Root File

Create new unified `docker-compose.yml` at root for orchestrating all services:

```yaml
# docker-compose.yml (root)
version: '3.8'

services:
  backend:
    build:
      context: ./backend
      dockerfile: ../infra/docker/backend.Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://...
      - VECTOR_DB_URL=...
    volumes:
      - ./data:/app/data
    depends_on:
      - vector-db
      - postgres

  frontend:
    build:
      context: ./frontend
      dockerfile: ../infra/docker/frontend.Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://backend:8000
    depends_on:
      - backend

  vector-db:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
    volumes:
      - ./data/indexes/qdrant:/qdrant/storage

  postgres:
    image: postgres:15-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=plantiq
      - POSTGRES_USER=plantiq
      - POSTGRES_PASSWORD=changeme
    volumes:
      - postgres_data:/var/lib/postgresql/data

  # Optional: AnythingLLM (if still used)
  anythingllm:
    extends:
      file: ./infra/compose/anythingllm-compose.yml
      service: anythingllm

volumes:
  postgres_data:
```

### 8. Makefile for Developer Convenience

Create `Makefile` at root:

```makefile
# Makefile

.PHONY: help install test lint format clean docker-up docker-down

help:
	@echo "PlantIQ Development Commands"
	@echo "----------------------------"
	@echo "install        Install all dependencies (backend, frontend, pipeline)"
	@echo "test           Run all test suites"
	@echo "lint           Lint all code"
	@echo "format         Format all code"
	@echo "docker-up      Start all services via docker-compose"
	@echo "docker-down    Stop all services"
	@echo "clean          Remove build artifacts and caches"

install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install
	@echo "Installing pipeline dependencies..."
	cd pipeline && pip install -r requirements.txt

test:
	@echo "Running backend tests..."
	cd backend && pytest tests/
	@echo "Running pipeline tests..."
	cd pipeline && pytest tests/
	@echo "Running frontend tests..."
	cd frontend && npm test

lint:
	cd backend && pylint app/
	cd pipeline && pylint src/
	cd frontend && npm run lint

format:
	cd backend && black app/
	cd pipeline && black src/
	cd frontend && npm run format

docker-up:
	docker-compose up -d

docker-down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf backend/dist pipeline/dist frontend/.next frontend/out
```

---

## Migration Phases

### Phase 1: Preparation (No Code Changes)
**Duration:** 1 hour  
**Risk:** Low

1. Create new directory structure
2. Create `.gitkeep` files in empty directories
3. Update .gitignore (remove `*.py` exclusion!)
4. Commit empty structure

### Phase 2: Move Pipeline Code
**Duration:** 2 hours  
**Risk:** Medium

1. Move pipeline Python modules to `pipeline/src/`
2. Update internal imports within pipeline
3. Move config files to `pipeline/configs/`
4. Move test files to `pipeline/tests/`
5. Test pipeline scripts individually

### Phase 3: Move Data & Artifacts
**Duration:** 30 minutes  
**Risk:** Low

1. Move `InjestDocs/` → `data/raw/`
2. Move `hitl_workspace/` → `data/artifacts/hitl_workspace/`
3. Move `validation_evidence/` → `data/artifacts/validation_evidence/`
4. Update data paths in pipeline scripts

### Phase 4: Move Documentation
**Duration:** 30 minutes  
**Risk:** Low

1. Move architecture docs → `docs/architecture/`
2. Move capstone docs → `docs/capstone/`
3. Update README.md links

### Phase 5: Move Infrastructure
**Duration:** 1 hour  
**Risk:** Low

1. Move docker-compose.yml → `infra/compose/`
2. Create new root docker-compose.yml
3. Create Dockerfiles in `infra/docker/`

### Phase 6: Update CI/CD
**Duration:** 1 hour  
**Risk:** Medium

1. Update .github/workflows/ paths
2. Test GitHub Actions locally with `act`
3. Update deployment scripts

### Phase 7: Create Backend Scaffold
**Duration:** 2 hours  
**Risk:** Low (new code, no migration)

1. Create backend directory structure
2. Create placeholder files
3. Add pyproject.toml / requirements.txt
4. Document backend architecture

### Phase 8: Update Frontend
**Duration:** 1 hour  
**Risk:** Low

1. Create `frontend/tests/` directory
2. Update API client imports (if backend paths change)
3. Test frontend build

### Phase 9: Testing & Validation
**Duration:** 2 hours  
**Risk:** High

1. Run pipeline tests: `pytest pipeline/tests/`
2. Run frontend build: `cd frontend && npm run build`
3. Test docker-compose: `docker-compose up`
4. Validate all documentation links
5. Check CI/CD workflows

### Phase 10: Documentation & Cleanup
**Duration:** 1 hour  
**Risk:** Low

1. Update README.md with new structure
2. Update PROJECT_STATUS.md
3. Create migration notes
4. Remove old root-level files
5. Final commit

---

## Implementation Commands

### Step 1: Create New Structure

```bash
# From project root
cd /home/cpdcs/Projects/llm-rag-chatbot

# Create main directories
mkdir -p backend/app/{api,core,services,models}
mkdir -p backend/tests
mkdir -p pipeline/src/{ingestion,validation,review,qa,lineage,utils,cli}
mkdir -p pipeline/configs
mkdir -p pipeline/tests
mkdir -p infra/{docker,compose,k8s,scripts,monitoring}
mkdir -p data/{raw,processed,artifacts,indexes}
mkdir -p docs/{architecture,api,operations,security,capstone}
mkdir -p tests/{integration,e2e,performance,fixtures}
mkdir -p tools
mkdir -p frontend/tests

# Create .gitkeep files for empty directories
touch backend/app/{api,core,services,models}/.gitkeep
touch backend/tests/.gitkeep
touch pipeline/src/{ingestion,validation,review,qa,lineage,utils,cli}/.gitkeep
touch infra/{docker,k8s,scripts,monitoring}/.gitkeep
touch data/{processed,indexes}/.gitkeep
touch docs/{api,operations,security}/.gitkeep
touch tests/{integration,e2e,performance,fixtures}/.gitkeep
touch tools/.gitkeep
touch frontend/tests/.gitkeep
```

### Step 2: Move Pipeline Modules

```bash
# Ingestion
mv docling_convert_with_qwen.py pipeline/src/ingestion/docling_converter.py

# Validation
mv rag_validation_enhanced.py pipeline/src/validation/enhanced_validator.py
mv rag_vlm_comparison.py pipeline/src/validation/vlm_comparison.py
mv rag_vlm_image_describer.py pipeline/src/validation/vlm_image_describer.py

# Review
mv rag_section_review.py pipeline/src/review/section_review.py

# QA
mv rag_qa_gates.py pipeline/src/qa/qa_gates.py

# Lineage
mv rag_lineage.py pipeline/src/lineage/lineage_tracker.py

# Utils
mv rag_table_figure_handler.py pipeline/src/utils/table_figure_handler.py
mv vlm_options.py pipeline/src/utils/vlm_options.py
mv vlm_response_parser.py pipeline/src/utils/vlm_response_parser.py
mv progress_tracker.py pipeline/src/utils/progress_tracker.py

# CLI
mv rag_hitl_pipeline.py pipeline/src/cli/hitl_pipeline.py
mv rag_text_reformatter.py pipeline/src/cli/text_reformatter.py

# Create __init__.py files
touch pipeline/src/__init__.py
touch pipeline/src/{ingestion,validation,review,qa,lineage,utils,cli}/__init__.py
```

### Step 3: Move Config & Test Files

```bash
# Configs
mv vlm_config_project.yaml pipeline/configs/vlm_config.yaml
mv docling.env pipeline/configs/docling.env

# Tests
mv test_vlm_integration.py pipeline/tests/test_vlm_integration.py
mv verify_hitl_setup.py pipeline/tests/verify_hitl_setup.py
touch pipeline/tests/__init__.py
```

### Step 4: Move Data

```bash
# Move data directories
mv InjestDocs data/raw
mv hitl_workspace data/artifacts/
mv validation_evidence data/artifacts/
touch data/raw/.gitkeep
```

### Step 5: Move Documentation

```bash
# Architecture docs
mv RAG_Chatbot_Architecture.md docs/architecture/rag_architecture.md
mv INTEGRATED_ARCHITECTURE.md docs/architecture/integrated_architecture.md
mv instructions.md docs/capstone/original_requirements.md

# Capstone deliverables
mv Documents/* docs/capstone/
rmdir Documents
```

### Step 6: Move Infrastructure

```bash
# Move docker-compose
mv docker-compose.yml infra/compose/anythingllm-compose.yml
```

### Step 7: Update .gitignore

```bash
# Backup old .gitignore
cp .gitignore .gitignore.old

# Create new .gitignore (see content in "Impact Analysis" section)
cat > .gitignore << 'EOF'
# Python
*.pyc
__pycache__/
*.pyo
*.pyd
.Python
*.so
*.egg
*.egg-info/
dist/
build/

# Virtual environments
.venv/
venv/
ENV/
env/

# Environment variables
.env
.env.local
.env.*.local

# Data (runtime, not source controlled)
data/raw/*
!data/raw/.gitkeep
data/processed/*
!data/processed/.gitkeep
data/artifacts/*
!data/artifacts/.gitkeep
data/indexes/*
!data/indexes/.gitkeep

# AnythingLLM storage
anythingllm-storage/

# Build artifacts
frontend/.next/
frontend/out/
frontend/dist/
frontend/node_modules/
backend/dist/
pipeline/dist/

# IDE
.vscode/
.idea/
*.swp
*.swo
*.sublime-project
*.sublime-workspace

# Logs
*.log
logs/

# OS
.DS_Store
Thumbs.db
.directory

# Temporary files
text.txt
*.tmp
*.temp

# Test coverage
.coverage
htmlcov/
*.cover
.pytest_cache/

# Compiled assets
*.pyc
*.pyo
EOF
```

---

## Post-Migration Validation Checklist

### Pipeline Validation
- [ ] `python pipeline/src/cli/hitl_pipeline.py --help` works
- [ ] Import test: `python -c "from pipeline.src.utils.vlm_options import VLMOptions"`
- [ ] Config file loads: Check `pipeline/configs/vlm_config.yaml`
- [ ] Test suite passes: `pytest pipeline/tests/`

### Frontend Validation
- [ ] `cd frontend && npm install` succeeds
- [ ] `npm run build` completes without errors
- [ ] Static export works: `npm run export`
- [ ] Deployed site loads: Check GitHub Pages URL

### Backend Validation
- [ ] Backend structure created with placeholder files
- [ ] `backend/requirements.txt` exists
- [ ] Documentation describes backend architecture

### Infrastructure Validation
- [ ] `docker-compose.yml` at root exists
- [ ] `docker-compose config` validates syntax
- [ ] Dockerfiles in `infra/docker/` are placeholders (to be implemented)

### Documentation Validation
- [ ] `README.md` reflects new structure
- [ ] `docs/architecture/` contains architecture files
- [ ] `docs/capstone/` contains all capstone deliverables
- [ ] All internal links work

### CI/CD Validation
- [ ] `.github/workflows/ci.yml` updated with new paths
- [ ] `.github/workflows/frontend-deploy.yml` still works
- [ ] GitHub Actions pass on next push

---

## Risk Mitigation Strategies

### 1. Import Path Breakage
**Risk:** Python imports break after moving modules

**Mitigation:**
- Create comprehensive test suite before migration
- Use IDE refactoring tools to update imports automatically
- Update imports in phases (one layer at a time)
- Keep root-level symlinks temporarily during transition

### 2. Data Path Breakage
**Risk:** Scripts can't find data files after reorganization

**Mitigation:**
- Create path constants in a central config file
- Use relative paths from project root
- Update all hardcoded paths before moving data
- Test with sample data before moving production artifacts

### 3. Git History Loss
**Risk:** Moving files may make git history harder to follow

**Mitigation:**
- Use `git mv` instead of `mv` to preserve history
- Document all moves in commit messages
- Create a migration map file for reference

### 4. CI/CD Pipeline Breakage
**Risk:** GitHub Actions fail after path changes

**Mitigation:**
- Test workflows locally using `act` tool
- Update workflows in separate commit before moving files
- Keep backup branch before restructure
- Monitor first few CI runs closely

### 5. Development Workflow Disruption
**Risk:** Team members confused by new structure

**Mitigation:**
- Update README.md first with navigation guide
- Create architectural decision record (ADR)
- Hold team walkthrough of new structure
- Provide clear "before/after" documentation

---

## Success Criteria

### Technical Success
- [ ] All pipeline scripts execute without errors
- [ ] Frontend builds and deploys successfully
- [ ] CI/CD pipelines pass
- [ ] No broken imports or missing files
- [ ] Git history preserved for moved files

### Organizational Success
- [ ] Clear separation between frontend/backend/pipeline
- [ ] Intuitive directory navigation
- [ ] Improved .gitignore hygiene (Python files tracked!)
- [ ] Documentation reflects new structure
- [ ] Ready for backend development to begin

### Operational Success
- [ ] Development workflow documented
- [ ] Docker compose orchestration works
- [ ] Testing infrastructure in place
- [ ] Deployment process simplified

---

## Next Steps After Restructure

### 1. Backend Development (Week 1-2)
- Implement FastAPI app structure
- Create authentication endpoints
- Build RAG service layer
- Integrate with vector database

### 2. API Documentation (Week 2)
- OpenAPI/Swagger spec
- API usage examples
- Authentication guide

### 3. Integration Testing (Week 3)
- End-to-end tests in `tests/integration/`
- Frontend-to-backend integration
- Pipeline-to-backend integration

### 4. Deployment Automation (Week 4)
- Complete Dockerfiles
- Kubernetes manifests (optional)
- Air-gapped deployment guide

---

## References

- **Capstone Proposal:** `docs/capstone/Capstone_Proposal_UPDATED.md`  
  (Section: "Proposed Production Repository Structure")
- **Architecture Plan:** `docs/architecture/rag_architecture.md`
- **Project Status:** `PROJECT_STATUS.md`

---

## Approval & Implementation

**Prepared By:** Architecture Planning Agent  
**Review Required:** Project Lead, Backend Development, DevOps  
**Estimated Implementation Time:** 8-10 hours  
**Recommended Start:** Immediate (MVP timeline: 11 weeks)

**Approval Checklist:**
- [ ] Project Lead reviews and approves structure
- [ ] Backend Development agent confirms backend layout
- [ ] DevOps agent confirms infrastructure layout
- [ ] Team consensus on migration timeline

**Implementation Handoff:**
Once approved, hand off to:
1. **DevOps/Infrastructure Agent** for directory creation and file moves
2. **Backend Development Agent** for import path updates
3. **Testing & QA Agent** for validation testing
4. **Documentation Agent** for README and guide updates
