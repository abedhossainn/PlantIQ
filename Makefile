# PlantIQ Development Makefile
# Air-Gapped RAG System for Industrial OT Environments

.PHONY: help install test lint format clean docker-up docker-down docker-build docker-logs venv activate ensure-compose verify-llm-gpu llm-supervisor-start llm-supervisor-stop llm-supervisor-status

# Path to Python interpreter
PYTHON := python3
VENV := .venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(abspath $(VENV_BIN))/python
VENV_PIP := $(abspath $(VENV_BIN))/pip
COMPOSE_V2 := $(shell if docker compose version >/dev/null 2>&1; then printf '%s' 'docker compose'; fi)
COMPOSE_V1 := $(shell if command -v docker-compose >/dev/null 2>&1; then printf '%s' 'docker-compose'; fi)
COMPOSE := $(if $(COMPOSE_V2),$(COMPOSE_V2),$(COMPOSE_V1))

help:
	@echo "PlantIQ Development Commands"
	@echo "=============================="
	@echo ""
	@echo "Environment Setup:"
	@echo "  make venv             Create Python virtual environment"
	@echo "  make activate         Print activation command"
	@echo ""
	@echo "Setup & Installation:"
	@echo "  make install          Install all dependencies (requires venv)"
	@echo "  make install-backend  Install backend dependencies only"
	@echo "  make install-frontend Install frontend dependencies only"
	@echo "  make install-pipeline Install pipeline dependencies only"
	@echo ""
	@echo "Testing:"
	@echo "  make test            Run all test suites"
	@echo "  make test-backend    Run backend tests"
	@echo "  make test-frontend   Run frontend tests"
	@echo "  make test-pipeline   Run pipeline tests"
	@echo "  make test-integration Run integration tests"
	@echo "  make validate-imports Validate Python import structure"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint            Lint all code"
	@echo "  make format          Format all code"
	@echo "  make validate        Run linting + testing"
	@echo ""
	@echo "Docker & Deployment:"
	@echo "  make docker-up       Start all services via Docker Compose v2"
	@echo "  make docker-down     Stop all services"
	@echo "  make docker-build    Build all Docker images"
	@echo "  make docker-logs     View logs from all containers"
	@echo "  make verify-llm-gpu  Fail fast if Ollama is not using NVIDIA runtime"
	@echo "  make llm-supervisor-start  Start host-side on-demand LLM lifecycle supervisor"
	@echo "  make llm-supervisor-stop   Stop host-side on-demand LLM lifecycle supervisor"
	@echo "  make llm-supervisor-status Show supervisor process status"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean           Remove build artifacts and caches"
	@echo "  make clean-data      Clean data artifacts (CAUTION: removes processed data)"
	@echo "  make clean-venv      Remove virtual environment"

# === Virtual Environment ===

venv:
	@if [ ! -d "$(VENV)" ]; then \
		echo "Creating virtual environment..."; \
		$(PYTHON) -m venv $(VENV); \
		$(VENV_PIP) install --upgrade pip; \
		echo "✅ Virtual environment created at $(VENV)"; \
		echo "   Activate with: source $(VENV_BIN)/activate"; \
	else \
		echo "Virtual environment already exists at $(VENV)"; \
	fi

activate:
	@echo "source $(VENV_BIN)/activate"

# === Installation ===

install: venv install-pipeline install-backend install-frontend
	@echo "✅ All dependencies installed"
	@echo "To activate the environment, run: source $(VENV_BIN)/activate"

install-backend: venv
	@echo "Installing backend dependencies..."
	@if [ -f apps/api/requirements.txt ]; then \
		cd apps/api && $(VENV_PIP) install -r requirements.txt; \
	elif [ -f apps/api/pyproject.toml ]; then \
		cd apps/api && $(VENV_PIP) install -e .; \
	else \
		echo "⚠️  No backend dependency manifest found (expected requirements.txt or pyproject.toml)"; \
	fi

install-frontend:
	@echo "Installing frontend dependencies..."
	@cd apps/web && npm install

install-pipeline: venv
	@echo "Installing pipeline dependencies..."
	@if [ -f apps/pipeline/requirements.txt ]; then \
		$(VENV_PIP) install -r apps/pipeline/requirements.txt; \
	else \
		echo "⚠️  Pipeline requirements.txt not yet created"; \
	fi

# === Testing ===

test: test-pipeline test-backend test-frontend test-integration
	@echo "✅ All tests passed"

test-backend:
	@echo "Running backend tests..."
	@if [ -d apps/api/tests ]; then \
		cd apps/api && $(VENV_PYTHON) -m pytest tests/ -v; \
	else \
		echo "⚠️  Backend tests not yet implemented"; \
	fi

test-frontend:
	@echo "Running frontend tests..."
	@if [ -f apps/web/package.json ] && grep -q '"test"' apps/web/package.json; then \
		cd apps/web && npm test; \
	else \
		echo "⚠️  Frontend tests not yet configured"; \
	fi

test-pipeline:
	@echo "Running pipeline tests..."
	@if [ -d apps/pipeline/tests ]; then \
		cd apps/pipeline && $(VENV_PYTHON) -m pytest tests/ -v; \
	else \
		echo "⚠️  Pipeline tests not yet implemented"; \
	fi

validate-imports:
	@echo "Validating Python import structure..."
	@$(VENV_PYTHON) apps/pipeline/tests/validate_imports.py

test-integration:
	@echo "Running integration tests..."
	@if [ -d tests/integration ]; then \
		$(VENV_PYTHON) -m pytest tests/integration/ -v; \
	else \
		echo "⚠️  Integration tests not yet implemented"; \
	fi

# === Code Quality ===

lint:
	@echo "Linting all code..."
	@if [ -d apps/pipeline/src ]; then \
		cd apps/pipeline && pylint src/ --disable=all --enable=syntax-error || true; \
	fi
	@if [ -d apps/api/app ]; then \
		cd apps/api && pylint app/ --disable=all --enable=syntax-error || true; \
	fi
	@if [ -f apps/web/package.json ]; then \
		cd apps/web && npm run lint || true; \
	fi

format:
	@echo "Formatting all code..."
	@if [ -d apps/pipeline/src ]; then \
		cd apps/pipeline && black src/ || echo "Install black: pip install black"; \
	fi
	@if [ -d apps/api/app ]; then \
		cd apps/api && black app/ || echo "Install black: pip install black"; \
	fi
	@if [ -f apps/web/package.json ]; then \
		cd apps/web && npm run format || true; \
	fi

validate: lint test
	@echo "✅ Validation complete"

# === Docker ===

ensure-compose:
	@if [ -n "$(COMPOSE_V2)" ]; then \
		echo "Using Compose command: $(COMPOSE_V2)"; \
	elif [ -n "$(COMPOSE_V1)" ]; then \
		echo "❌ Legacy docker-compose v1 is installed, but this stack now requires Docker Compose v2."; \
		echo "   Reason: the GPU-enabled Docling image is published as an OCI manifest that plain Docker can pull,"; \
		echo "   but docker-compose v1 fails to resolve from Quay and does not provide the supported GPU runtime path"; \
		echo "   needed for NVIDIA device reservations."; \
		echo "   Install the Docker Compose v2 plugin so 'docker compose' is available, then rerun this target."; \
		exit 1; \
	elif [ -z "$(COMPOSE)" ]; then \
		echo "❌ Docker Compose is not installed."; \
		echo "   Preferred: install the Docker Compose v2 plugin so 'docker compose' is available."; \
		echo "   Legacy 'docker-compose' v1 is not sufficient for this GPU-enabled local stack."; \
		exit 1; \
	fi

docker-up: ensure-compose
	@echo "Starting stable infrastructure services..."
	@docker ps -aq --format '{{.ID}} {{.Names}}' | awk '/docling-serve/ {print $$1}' | xargs -r docker rm -f >/dev/null 2>&1 || true
	@$(COMPOSE) up -d postgres vector-db docling-serve llm
	@echo "Applying database migrations to local PostgreSQL volume..."
	@POSTGRES_USER=$${POSTGRES_USER:-plantiq}; \
	POSTGRES_DB=$${POSTGRES_DB:-plantiq}; \
	POSTGRES_CONTAINER=$$($(COMPOSE) ps -q postgres); \
	if [ -z "$$POSTGRES_CONTAINER" ]; then \
		echo "❌ Could not resolve the postgres service container from Compose."; \
		exit 1; \
	fi; \
	docker exec "$$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" >/dev/null; \
	docker exec "$$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "INSERT INTO schema_migrations (filename) VALUES ('001_init_schema.sql'), ('002_postgrest_views.sql') ON CONFLICT (filename) DO NOTHING;" >/dev/null; \
	for migration in $$(find infra/docker/migrations -maxdepth 1 -type f -name '*.sql' | sort); do \
		filename=$$(basename "$$migration"); \
		case "$$filename" in \
			001_*|002_*) continue ;; \
		esac; \
		applied=$$(docker exec "$$POSTGRES_CONTAINER" psql -tA -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "SELECT 1 FROM schema_migrations WHERE filename = '$$filename' LIMIT 1;"); \
		if [ "$$applied" = "1" ]; then \
			continue; \
		fi; \
		echo "  - applying $$filename"; \
		docker exec -i "$$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" < "$$migration" >/dev/null; \
		docker exec "$$POSTGRES_CONTAINER" psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "INSERT INTO schema_migrations (filename) VALUES ('$$filename') ON CONFLICT (filename) DO NOTHING;" >/dev/null; \
	done
	@echo "Refreshing development app containers..."
	@$(COMPOSE) rm -fs backend frontend >/dev/null 2>&1 || true
	@docker ps -aq --format '{{.ID}} {{.Names}}' | awk '/plantiq-backend|plantiq-frontend/ {print $$1}' | xargs -r docker rm -f >/dev/null 2>&1 || true
	@$(COMPOSE) up -d --force-recreate --no-deps backend frontend
	@$(MAKE) verify-llm-gpu

verify-llm-gpu: ensure-compose
	@bash infra/scripts/verify_llm_gpu_runtime.sh llm

docker-down: ensure-compose
	@echo "Stopping all services..."
	@$(COMPOSE) down --remove-orphans

docker-build: ensure-compose
	@echo "Building development app images..."
	@$(COMPOSE) build backend frontend

docker-logs: ensure-compose
	@$(COMPOSE) logs -f

llm-supervisor-start: ensure-compose
	@mkdir -p data/artifacts/runtime
	@if [ -f data/artifacts/runtime/llm_supervisor.pid ]; then \
		PID=$$(cat data/artifacts/runtime/llm_supervisor.pid); \
		if kill -0 $$PID >/dev/null 2>&1 && ps -p $$PID -o args= | grep -q "llm_lifecycle_supervisor.py"; then \
			echo "LLM lifecycle supervisor is already running (PID $$PID)"; \
			exit 0; \
		fi; \
		rm -f data/artifacts/runtime/llm_supervisor.pid; \
	fi; \
	echo "Starting LLM lifecycle supervisor in background..."; \
	nohup $(PYTHON) infra/scripts/llm_lifecycle_supervisor.py \
		--project-root . \
		--heartbeat-file $${LLM_DEMAND_HEARTBEAT_FILE:-./data/artifacts/runtime/llm_last_used} \
		--service $${LLM_SERVICE_NAME:-llm} \
		--idle-timeout-seconds $${LLM_IDLE_TIMEOUT_SECONDS:-300} \
		--request-window-seconds $${LLM_REQUEST_WINDOW_SECONDS:-30} \
		> data/artifacts/runtime/llm_supervisor.log 2>&1 & \
	echo $$! > data/artifacts/runtime/llm_supervisor.pid; \
	echo "LLM lifecycle supervisor started (PID $$!)"

llm-supervisor-stop:
	@if [ -f data/artifacts/runtime/llm_supervisor.pid ]; then \
		PID=$$(cat data/artifacts/runtime/llm_supervisor.pid); \
		if kill -0 $$PID >/dev/null 2>&1 && ps -p $$PID -o args= | grep -q "llm_lifecycle_supervisor.py"; then \
			echo "Stopping LLM lifecycle supervisor (PID $$PID)..."; \
			kill $$PID; \
		fi; \
		rm -f data/artifacts/runtime/llm_supervisor.pid; \
	else \
		echo "No supervisor pid file found"; \
	fi
	@echo "LLM lifecycle supervisor stopped"

llm-supervisor-status:
	@if [ -f data/artifacts/runtime/llm_supervisor.pid ]; then \
		PID=$$(cat data/artifacts/runtime/llm_supervisor.pid); \
		if kill -0 $$PID >/dev/null 2>&1 && ps -p $$PID -o args= | grep -q "llm_lifecycle_supervisor.py"; then \
			echo "LLM lifecycle supervisor is running (PID $$PID)"; \
			exit 0; \
		fi; \
		rm -f data/artifacts/runtime/llm_supervisor.pid; \
	fi; \
	echo "LLM lifecycle supervisor is not running"

# === Cleanup ===

clean:
	@echo "Cleaning build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf apps/api/dist apps/pipeline/dist apps/web/.next apps/web/out 2>/dev/null || true
	@echo "✅ Build artifacts cleaned"

clean-data:
	@echo "⚠️  WARNING: This will delete processed data artifacts!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf data/processed/* data/artifacts/* data/indexes/*; \
		touch data/processed/.gitkeep data/artifacts/.gitkeep data/indexes/.gitkeep; \
		echo "✅ Data artifacts cleaned"; \
	else \
		echo "Cancelled."; \
	fi

clean-venv:
	@echo "Removing virtual environment..."
	@rm -rf $(VENV)
	@echo "✅ Virtual environment removed"
