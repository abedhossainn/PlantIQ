# PlantIQ — Repository Restructure Migration Plan

**Status:** Ready to execute (post-Beta stabilization)  
**Author:** Architecture Agent  
**Date:** April 2026  
**Branch convention:** Execute each phase on a dedicated branch, merge with PR after verification.

---

## Executive Summary

This plan converts the current flat monorepo layout into the professional `apps/`-based structure
recommended in the project feedback. Git LFS is **not required** — no binary dependencies are tracked in Git history.

The migration is decomposed into three phases ordered by risk:

| Phase | Scope | Risk | When |
|---|---|---|---|
| 1 — Documents cleanup | Move `Documents/` → `docs/` | 🟢 Zero | Now |
| 2 — Directory renames | `backend/` → `apps/api/`, `frontend/` → `apps/web/`, `pipeline/` → `apps/pipeline/` | 🔴 High | Pre-Beta (current) |
| 3 — `src/` layout (optional) | Add `src/` build-isolation layer inside `apps/api/` | 🟠 Medium | After Phase 2 is stable |

`packages/shared-utils/` is **deferred indefinitely** — backend and pipeline communicate via subprocess,
not Python imports. There is nothing shared to extract yet.

---

## Phase 0 — Pre-flight Checklist

Run before starting any phase.

```bash
# 1. Confirm secrets are excluded from git history
git ls-files backend/secrets/ backend/test_keys/
# Expected: no output (both already in .gitignore ✓)

# 2. Confirm current test suite is green (baseline)
make test-backend
npm --prefix frontend test -- --run tests/api.integration.test.ts

# 3. Confirm containers run cleanly
make docker-up
docker ps --format "table {{.Names}}\t{{.Status}}"

# 4. Create a dedicated migration branch
git checkout -b chore/phase-1-docs-cleanup   # or chore/phase-2-dir-rename
```

---

## Phase 1 — Documents Cleanup

**Risk:** Zero. No code, no Docker, no imports affected.  
**Estimated time:** 10 minutes.

### What changes

`Documents/` files are moved into the existing `docs/` hierarchy.
The `Documents/` folder is then removed entirely.

| Source | Destination |
|---|---|
| `Documents/Alpha Checkpoint Guideline.md` | `docs/capstone/` |
| `Documents/Alpha_Checkpoint_Report.md` | `docs/capstone/` |
| `Documents/Alpha_Checkpoint_Report_v2.md` | `docs/capstone/` |
| `Documents/Capstone_Proposal_UPDATED.md` | `docs/capstone/` |
| `Documents/CHECKPOINT_STRATEGY.md` | `docs/capstone/` |
| `Documents/COMMON Module 3 Characteristics of LNG.pdf` | `docs/capstone/` |
| `Documents/COMMON Module 3 Characteristics of LNG 12 Page.pdf` | `docs/capstone/` |
| `Documents/diagrams/` | `docs/capstone/diagrams/` |
| `Documents/COMPLETION_SUMMARY_T004_T005.md` | `docs/operations/` |
| `Documents/COMPLETION_SUMMARY_T006.md` | `docs/operations/` |
| `Documents/T007_COMPLETION_SUMMARY.md` | `docs/operations/` |
| `Documents/T008_T009_COMPLETION_SUMMARY.md` | `docs/operations/` |
| `Documents/T010_COMPLETION_SUMMARY.md` | `docs/operations/` |
| `Documents/RESTRUCTURE_COMPLETE.md` | `docs/operations/` |
| `Documents/RESTRUCTURE_PLAN.md` | `docs/operations/` |
| `Documents/PlantIQ_Integration_Architecture.md` | `docs/architecture/` |
| `Documents/How to write clean code.md` | `docs/` |
| `Documents/PROJECT_STATUS.md` | Delete — duplicate of root `PROJECT_STATUS.md` |
| `Documents/text.txt` | Delete — scratch file with no value |

### Commands

```bash
# Create destination directories (already exist but ensure completeness)
mkdir -p docs/capstone/diagrams docs/operations docs/architecture

# Move capstone docs
git mv "Documents/Alpha Checkpoint Guideline.md"       docs/capstone/
git mv Documents/Alpha_Checkpoint_Report.md             docs/capstone/
git mv Documents/Alpha_Checkpoint_Report_v2.md          docs/capstone/
git mv Documents/Capstone_Proposal_UPDATED.md           docs/capstone/
git mv Documents/CHECKPOINT_STRATEGY.md                 docs/capstone/
git mv "Documents/COMMON Module 3 Characteristics of LNG.pdf"          docs/capstone/
git mv "Documents/COMMON Module 3 Characteristics of LNG 12 Page.pdf"  docs/capstone/
git mv Documents/diagrams                               docs/capstone/diagrams

# Move operation summaries
git mv Documents/COMPLETION_SUMMARY_T004_T005.md  docs/operations/
git mv Documents/COMPLETION_SUMMARY_T006.md       docs/operations/
git mv Documents/T007_COMPLETION_SUMMARY.md       docs/operations/
git mv Documents/T008_T009_COMPLETION_SUMMARY.md  docs/operations/
git mv Documents/T010_COMPLETION_SUMMARY.md       docs/operations/
git mv Documents/RESTRUCTURE_COMPLETE.md          docs/operations/
git mv Documents/RESTRUCTURE_PLAN.md              docs/operations/

# Move architecture doc
git mv Documents/PlantIQ_Integration_Architecture.md  docs/architecture/

# Move coding guidelines
git mv "Documents/How to write clean code.md"  docs/

# Delete duplicates / scratch
git rm Documents/PROJECT_STATUS.md
git rm Documents/text.txt

# Verify nothing left before removing the directory
ls Documents/
# Expected: empty — then remove it
rmdir Documents/

git add -A
git commit -m "chore: consolidate Documents/ into docs/ hierarchy"
```

### Verification

```bash
# No broken references to Documents/ in active code
grep -r "Documents/" backend/ pipeline/ frontend/ --include="*.py" --include="*.ts" --include="*.tsx"
# Expected: no output
```

---

## Phase 2 — Directory Renames

**Risk:** High. All Docker, Makefile, and pytest paths break simultaneously if any step is missed.  
**Estimated time:** 2–3 hours including container rebuild and smoke test.  
**Pre-condition:** Phase 1 must be merged and all containers must pass smoke test before starting.

### 2.1 — Target Structure

```
llm-rag-chatbot/
├── apps/
│   ├── api/          ← formerly backend/
│   │   ├── app/      (Python package, unchanged)
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── README.md
│   ├── web/          ← formerly frontend/
│   │   ├── app/
│   │   ├── components/
│   │   ├── lib/
│   │   ├── package.json
│   │   └── ... (all current frontend/ contents)
│   └── pipeline/     ← formerly pipeline/
│       ├── src/
│       ├── tests/
│       ├── pyproject.toml
│       ├── setup.py
│       └── requirements.txt
├── data/             (unchanged)
├── docs/             (expanded in Phase 1)
├── infra/            (unchanged)
├── models/           (unchanged)
├── tests/            (unchanged)
├── tools/            (unchanged)
└── ... (root config files unchanged)
```

### 2.2 — Step-by-step execution

**Step 1: Move directories**

```bash
git checkout -b chore/phase-2-dir-rename

mkdir -p apps
git mv backend  apps/api
git mv frontend apps/web
git mv pipeline apps/pipeline
```

**Step 2: Update `docker-compose.yml`** — 18 changes

In the `backend` service:

| Location | Old value | New value |
|---|---|---|
| `PYTHONPATH` env | `/workspace` | `/workspace/apps:/workspace` |
| `PIPELINE_SCRIPT_PATH` env | `/workspace/pipeline/src/cli/hitl_pipeline.py` | `/workspace/apps/pipeline/src/cli/hitl_pipeline.py` |
| `command` — working dir | `cd /workspace/backend` | `cd /workspace/apps/api` |
| `command` — reload-dir 1 | `--reload-dir /workspace/backend/app` | `--reload-dir /workspace/apps/api/app` |
| `command` — reload-dir 2 | `--reload-dir /workspace/pipeline/src` | `--reload-dir /workspace/apps/pipeline/src` |

In the `frontend` service:

| Location | Old value | New value |
|---|---|---|
| `build.context` | `./frontend` | `./apps/web` |
| `build.dockerfile` | `../infra/docker/frontend.Dockerfile` | `../../infra/docker/frontend.Dockerfile` |
| volume `app` | `./frontend/app:/app/app` | `./apps/web/app:/app/app` |
| volume `components` | `./frontend/components:/app/components` | `./apps/web/components:/app/components` |
| volume `lib` | `./frontend/lib:/app/lib` | `./apps/web/lib:/app/lib` |
| volume `pages` | `./frontend/pages:/app/pages` | `./apps/web/pages:/app/pages` |
| volume `public` | `./frontend/public:/app/public` | `./apps/web/public:/app/public` |
| volume `types` | `./frontend/types:/app/types` | `./apps/web/types:/app/types` |
| volume `package.json` | `./frontend/package.json:/app/package.json` | `./apps/web/package.json:/app/package.json` |
| volume `package-lock.json` | `./frontend/package-lock.json:/app/package-lock.json` | `./apps/web/package-lock.json:/app/package-lock.json` |
| volume `next.config.ts` | `./frontend/next.config.ts:/app/next.config.ts` | `./apps/web/next.config.ts:/app/next.config.ts` |
| volume `postcss.config.mjs` | `./frontend/postcss.config.mjs:/app/postcss.config.mjs` | `./apps/web/postcss.config.mjs:/app/postcss.config.mjs` |
| volume `tsconfig.json` | `./frontend/tsconfig.json:/app/tsconfig.json` | `./apps/web/tsconfig.json:/app/tsconfig.json` |
| volume `next-env.d.ts` | `./frontend/next-env.d.ts:/app/next-env.d.ts` | `./apps/web/next-env.d.ts:/app/next-env.d.ts` |
| volume `components.json` | `./frontend/components.json:/app/components.json` | `./apps/web/components.json:/app/components.json` |

> **Why `PYTHONPATH=/workspace/apps:/workspace`?**
> The backend subprocess runs `python -m pipeline.src.cli.hitl_pipeline`.
> Python resolves `pipeline` as a top-level package by scanning `PYTHONPATH`.
> After rename, `pipeline/__init__.py` lives at `/workspace/apps/pipeline/`, so
> `/workspace/apps` must be on the path. `/workspace` is kept so any other
> workspace-root resolution continues to work.

**Step 3: Update `infra/docker/backend.Dockerfile`** — 9 changes

```dockerfile
# OLD
COPY backend/pyproject.toml      /workspace/backend/pyproject.toml
COPY backend/README.md           /workspace/backend/README.md
COPY pipeline/pyproject.toml     /workspace/pipeline/pyproject.toml
COPY pipeline/requirements.txt   /workspace/pipeline/requirements.txt
COPY backend/app                 /workspace/backend/app
COPY pipeline                    /workspace/pipeline
RUN pip install --no-cache-dir -e '/workspace/backend[dev]' \
    && pip install --no-cache-dir "transformers>=5.0.0,<6.0.0" "huggingface_hub>=1.0.0" \
    && pip install --no-cache-dir -e /workspace/pipeline
WORKDIR /workspace/backend

# NEW
COPY apps/api/pyproject.toml         /workspace/apps/api/pyproject.toml
COPY apps/api/README.md              /workspace/apps/api/README.md
COPY apps/pipeline/pyproject.toml    /workspace/apps/pipeline/pyproject.toml
COPY apps/pipeline/requirements.txt  /workspace/apps/pipeline/requirements.txt
COPY apps/api/app                    /workspace/apps/api/app
COPY apps/pipeline                   /workspace/apps/pipeline
RUN pip install --no-cache-dir -e '/workspace/apps/api[dev]' \
    && pip install --no-cache-dir "transformers>=5.0.0,<6.0.0" "huggingface_hub>=1.0.0" \
    && pip install --no-cache-dir -e /workspace/apps/pipeline
WORKDIR /workspace/apps/api
```

**Step 4: Update `Makefile`** — 27 changes across 8 targets

| Line | Target | Old | New |
|---|---|---|---|
| 82 | `install-backend` | `backend/requirements.txt` | `apps/api/requirements.txt` |
| 83 | `install-backend` | `cd backend` | `cd apps/api` |
| 84 | `install-backend` | `backend/pyproject.toml` | `apps/api/pyproject.toml` |
| 85 | `install-backend` | `cd backend` | `cd apps/api` |
| 92 | `install-frontend` | `cd frontend` | `cd apps/web` |
| 96 | `install-pipeline` | `pipeline/requirements.txt` | `apps/pipeline/requirements.txt` |
| 97 | `install-pipeline` | `pipeline/requirements.txt` (2nd occurrence) | `apps/pipeline/requirements.txt` |
| 109 | `test-backend` | `backend/tests` | `apps/api/tests` |
| 110 | `test-backend` | `cd backend` | `cd apps/api` |
| 117 | `test-frontend` | `frontend/package.json` | `apps/web/package.json` |
| 118 | `test-frontend` | `cd frontend` | `cd apps/web` |
| 125 | `test-pipeline` | `pipeline/tests` | `apps/pipeline/tests` |
| 126 | `test-pipeline` | `cd pipeline` | `cd apps/pipeline` |
| 133 | `validate-imports` | `pipeline/tests/validate_imports.py` | `apps/pipeline/tests/validate_imports.py` |
| 147 | `lint` | `pipeline/src` | `apps/pipeline/src` |
| 148 | `lint` | `cd pipeline` | `cd apps/pipeline` |
| 150 | `lint` | `backend/app` | `apps/api/app` |
| 151 | `lint` | `cd backend` | `cd apps/api` |
| 153 | `lint` | `frontend/package.json` | `apps/web/package.json` |
| 154 | `lint` | `cd frontend` | `cd apps/web` |
| 159 | `format` | `pipeline/src` | `apps/pipeline/src` |
| 160 | `format` | `cd pipeline` | `cd apps/pipeline` |
| 162 | `format` | `backend/app` | `apps/api/app` |
| 163 | `format` | `cd backend` | `cd apps/api` |
| 165 | `format` | `frontend/package.json` | `apps/web/package.json` |
| 166 | `format` | `cd frontend` | `cd apps/web` |
| 291 | `clean` | `backend/dist pipeline/dist frontend/.next frontend/out` | `apps/api/dist apps/pipeline/dist apps/web/.next apps/web/out` |

> Line 220 (`awk '/plantiq-backend\|plantiq-frontend/'`) matches **container names**, not directory paths — no change needed.

**Step 5: Update `pytest.ini`** — 1 change

```ini
# OLD
testpaths =
    backend/tests

# NEW
testpaths =
    apps/api/tests
```

**Step 6: Update `apps/pipeline/setup.py`** — 1 change

The file moves from `pipeline/setup.py` to `apps/pipeline/setup.py` — one level deeper.
`Path(__file__).parent.parent` previously resolved to the repo root; it now resolves to `apps/`.

```python
# OLD
readme_path = Path(__file__).parent.parent / "README.md"

# NEW
readme_path = Path(__file__).parent.parent.parent / "README.md"
```

**Step 7: Update `apps/api/app/services/pipeline_service.py`** — 1 change

`repo_root = pipeline_script.parents[3]` walks up from the pipeline script path to compute the
subprocess `cwd`. The directory depth increases by one with the `apps/` prefix:

| | Path | `parents[3]` yields |
|---|---|---|
| Before | `/workspace/pipeline/src/cli/hitl_pipeline.py` | `/workspace` ✓ |
| After | `/workspace/apps/pipeline/src/cli/hitl_pipeline.py` | `/workspace/apps` ✗ |

```python
# OLD (line ~192)
repo_root = pipeline_script.parents[3]

# NEW
repo_root = pipeline_script.parents[4]
```

**Step 8: Update `apps/api/tests/test_postgrest_endpoints.sh`** — 2 changes

```bash
# OLD line 86
echo "  cd backend && uvicorn app.main:app --reload"
# NEW
echo "  cd apps/api && uvicorn app.main:app --reload"

# OLD line 187
echo "  2. Run Python test suite: python backend/tests/test_postgrest.py"
# NEW
echo "  2. Run Python test suite: python apps/api/tests/test_postgrest.py"
```

**Step 9: Update `README.md`** — 3 lines

```
# OLD (lines 298–300)
├── backend/          # FastAPI APIs, services, models
├── frontend/         # Next.js UI (admin + operator chat)
├── pipeline/         # HITL ingestion, QA, optimization

# NEW
├── apps/
│   ├── api/          # FastAPI APIs, services, models
│   ├── web/          # Next.js UI (admin + operator chat)
│   └── pipeline/     # HITL ingestion, QA, optimization
```

### 2.3 — Rebuild and smoke test

```bash
# Commit all changes
git add -A
git commit -m "chore: rename backend→apps/api, frontend→apps/web, pipeline→apps/pipeline

- docker-compose.yml: PYTHONPATH, PIPELINE_SCRIPT_PATH, command (3 paths),
  frontend build context + dockerfile, and all 13 volume mount host paths
- infra/docker/backend.Dockerfile: 6 COPY paths, 2 pip install paths, WORKDIR
- Makefile: 27 path references across install/test/lint/format/clean targets
- pytest.ini: testpaths
- apps/pipeline/setup.py: README path depth parent.parent → parent.parent.parent
- apps/api/app/services/pipeline_service.py: parents[3] → parents[4]
- apps/api/tests/test_postgrest_endpoints.sh: 2 developer hint strings
- README.md: directory tree"

# Rebuild images from scratch (cache invalidated by path changes)
docker compose build --no-cache backend frontend

# Bring up the full stack
make docker-up

# Verify all containers are healthy
docker ps --format "table {{.Names}}\t{{.Status}}"

# Confirm Python module resolution inside backend container
docker exec plantiq-backend python -c "
import app.main
import pipeline.src.cli.hitl_pipeline
print('imports OK')
"

# Run backend tests
make test-backend

# Run frontend tests
npm --prefix apps/web test -- --run tests/api.integration.test.ts

# Confirm API is responding
curl -s http://localhost:8001/health | python3 -m json.tool
```

### 2.4 — Rollback

```bash
git checkout beta-checkpoint
docker compose down
docker compose build --no-cache backend frontend
make docker-up
```

---

## Phase 3 — `src/` Layout for Backend (Optional)

**Risk:** Medium. Requires coordinated changes to pyproject.toml, PYTHONPATH, and Dockerfile.  
**Pre-condition:** Phase 2 must be merged and stable.  
**Value:** Build isolation — prevents accidental imports of test/dev files in production package.

### What changes

Move `apps/api/app/` into `apps/api/src/app/`. Import paths (`from app.X import Y`) remain
unchanged because the editable install remaps the namespace.

| File | Change |
|---|---|
| `apps/api/pyproject.toml` | Add `[tool.setuptools.packages.find] where = ["src"]` |
| `apps/api/pyproject.toml` | Add `package-dir = {"" = "src"}` |
| `infra/docker/backend.Dockerfile` | `COPY apps/api/app` → `COPY apps/api/src/app` |
| `docker-compose.yml` command | `--reload-dir /workspace/apps/api/app` → `--reload-dir /workspace/apps/api/src/app` |
| `Makefile` lint/format | `apps/api/app/` → `apps/api/src/app/` |

Do **not** apply `src/` layout to `apps/pipeline/` — `pipeline.src.cli.hitl_pipeline` is the
established module path; changing it would require updates to `pipeline_service.py`.

---

## Summary: Complete File Change Inventory

### Phase 1
- No file content changes — only `git mv` operations

### Phase 2 — 9 files, 58 discrete changes

| File | Changes |
|---|---|
| `docker-compose.yml` | 18 — PYTHONPATH (new), PIPELINE_SCRIPT_PATH, command (3), build context, dockerfile, 13 volume mounts |
| `infra/docker/backend.Dockerfile` | 9 — 6 COPY paths, 2 pip install paths, WORKDIR |
| `Makefile` | 27 — install (5), test (8), lint (6), format (6), clean (1) targets |
| `pytest.ini` | 1 — testpaths |
| `apps/pipeline/setup.py` | 1 — README path depth |
| `apps/api/app/services/pipeline_service.py` | 1 — `parents[3]` → `parents[4]` |
| `apps/api/tests/test_postgrest_endpoints.sh` | 2 — developer hint strings |
| `README.md` | 3 — directory tree lines |

### Phase 3 (optional)

| File | Changes |
|---|---|
| `apps/api/pyproject.toml` | 2 sections added |
| `infra/docker/backend.Dockerfile` | 1 COPY path |
| `docker-compose.yml` | 1 reload-dir |
| `Makefile` | 2 lint/format paths |
