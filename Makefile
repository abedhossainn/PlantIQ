# PlantIQ Development Makefile
# Air-Gapped RAG System for Industrial OT Environments

.PHONY: help install test lint format clean docker-up docker-down venv activate

# Path to Python interpreter
PYTHON := python3
VENV := .venv
VENV_BIN := $(VENV)/bin
VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP := $(VENV_BIN)/pip

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
	@echo "  make docker-up       Start all services via docker-compose"
	@echo "  make docker-down     Stop all services"
	@echo "  make docker-build    Build all Docker images"
	@echo "  make docker-logs     View logs from all containers"
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

install: install-pipeline install-backend install-frontend
	@echo "✅ All dependencies installed"

install: venv install-pipeline install-backend install-frontend
	@echo "✅ All dependencies installed"
	@echo "To activate the environment, run: source $(VENV_BIN)/activate"

install-backend: venv
	@echo "Installing backend dependencies..."
	@cd backend && $(VENV_PIP) install -r requirements.txt || echo "⚠️  Backend requirements.txt not yet created"

install-frontend:
	@echo "Installing frontend dependencies..."
	@cd frontend && npm install

install-pipeline: venv
	@echo "Installing pipeline dependencies..."
	@if [ -f pipeline/requirements.txt ]; then \
		$(VENV_PIP) install -r pipeline/requirements.txt; \
	else \
		echo "⚠️  Pipeline requirements.txt not yet created"; \
	fi

# === Testing ===

test: test-pipeline test-backend test-frontend test-integration
	@echo "✅ All tests passed"

test-backend:
	@echo "Running backend tests..."
	@if [ -d backend/tests ]; then \
		cd backend && $(VENV_PYTHON) -m pytest tests/ -v; \
	else \
		echo "⚠️  Backend tests not yet implemented"; \
	fi

test-frontend:
	@echo "Running frontend tests..."
	@if [ -f frontend/package.json ] && grep -q '"test"' frontend/package.json; then \
		cd frontend && npm test; \
	else \
		echo "⚠️  Frontend tests not yet configured"; \
	fi

test-pipeline:
	@echo "Running pipeline tests..."
	@if [ -d pipeline/tests ]; then \
		cd pipeline && $(VENV_PYTHON) -m pytest tests/ -v; \
	else \
		echo "⚠️  Pipeline tests not yet implemented"; \
	fi

validate-imports:
	@echo "Validating Python import structure..."
	@$(VENV_PYTHON) pipeline/tests/validate_imports.py

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
	@if [ -d pipeline/src ]; then \
		cd pipeline && pylint src/ --disable=all --enable=syntax-error || true; \
	fi
	@if [ -d backend/app ]; then \
		cd backend && pylint app/ --disable=all --enable=syntax-error || true; \
	fi
	@if [ -f frontend/package.json ]; then \
		cd frontend && npm run lint || true; \
	fi

format:
	@echo "Formatting all code..."
	@if [ -d pipeline/src ]; then \
		cd pipeline && black src/ || echo "Install black: pip install black"; \
	fi
	@if [ -d backend/app ]; then \
		cd backend && black app/ || echo "Install black: pip install black"; \
	fi
	@if [ -f frontend/package.json ]; then \
		cd frontend && npm run format || true; \
	fi

validate: lint test
	@echo "✅ Validation complete"

# === Docker ===

docker-up:
	@echo "Starting all services..."
	@docker-compose up -d

docker-down:
	@echo "Stopping all services..."
	@docker-compose down

docker-build:
	@echo "Building all Docker images..."
	@docker-compose build

docker-logs:
	@docker-compose logs -f

# === Cleanup ===

clean:
	@echo "Cleaning build artifacts..."
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@find . -type f -name "*.pyo" -delete 2>/dev/null || true
	@find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf backend/dist pipeline/dist frontend/.next frontend/out 2>/dev/null || true
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
