# PlantIQ Backend Dockerfile
# FastAPI + LangChain RAG Middleware

FROM python:3.10-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    curl \
    libglib2.0-0 \
    libgl1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# Copy backend + pipeline metadata first for dependency install caching
COPY backend/pyproject.toml /workspace/backend/pyproject.toml
COPY backend/README.md /workspace/backend/README.md
COPY pipeline/pyproject.toml /workspace/pipeline/pyproject.toml
COPY pipeline/requirements.txt /workspace/pipeline/requirements.txt

# Copy source required for editable installs
COPY backend/app /workspace/backend/app
COPY pipeline /workspace/pipeline

# Install Python dependencies for both backend and pipeline
# Include backend dev extras so pytest and related tooling are available
# in the development container used for local test execution.
RUN pip install --no-cache-dir -e '/workspace/backend[dev]' \
    && pip install --no-cache-dir -e /workspace/pipeline

WORKDIR /workspace/backend

# Default command (can be overridden by docker-compose)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
