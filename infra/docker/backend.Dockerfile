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
COPY apps/api/pyproject.toml /workspace/apps/api/pyproject.toml
COPY apps/api/README.md /workspace/apps/api/README.md
COPY apps/pipeline/pyproject.toml /workspace/apps/pipeline/pyproject.toml
COPY apps/pipeline/requirements.txt /workspace/apps/pipeline/requirements.txt

# Copy source required for editable installs
COPY apps/api/app /workspace/apps/api/app
COPY apps/pipeline /workspace/apps/pipeline

# Install Python dependencies for both backend and pipeline
# Include backend dev extras so pytest and related tooling are available
# in the development container used for local test execution.
# Install transformers 5.x + huggingface_hub>=1.0 explicitly first so that
# docling's stale metadata constraint (huggingface_hub<1) does not cause pip
# to downgrade huggingface_hub and break transformers. Docling 2.82.0 works
# with huggingface_hub 1.x at runtime despite the metadata mismatch.
RUN pip install --no-cache-dir -e '/workspace/apps/api[dev]' \
    && pip install --no-cache-dir "transformers>=5.0.0,<6.0.0" "huggingface_hub>=1.0.0" \
    && pip install --no-cache-dir -e /workspace/apps/pipeline

WORKDIR /workspace/apps/api

# Default command (can be overridden by docker-compose)
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
