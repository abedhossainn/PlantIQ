"""
Pipeline API package.

Exposes the `router` object which main.py mounts. All implementation
lives in the sub-modules below:

    _constants.py      — Status guard sets, sentinel values, SQL, artifact naming
    _filesystem.py     — Workspace discovery, JSON loading, storage cleanup
    _db_ops.py         — DB helpers, status updates, guards, HTTP error utilities
    _review.py         — Checklist, page manifest, section helpers, response builders
    _chunks.py         — Optimized chunk coercion, serialization, publishable assembly
    _qa.py             — QA report path resolution, section assembly, compute & persist
    _document_ops.py   — Optimization stage runner, RAG publishing, approval, enrichment
    routes.py          — Thin @router route handlers (no business logic)
"""
from .routes import router
from ...core.config import get_upload_path, settings  # exposed for test monkeypatching
from ...core.optimization_log import OptimizationLogManager  # exposed for test monkeypatching
from ._document_ops import _execute_optimization_stage  # exposed for test monkeypatching
from ...models.database import AsyncSessionLocal  # exposed for test monkeypatching
from ...services.qdrant_service import QdrantService  # exposed for test monkeypatching
from ...services.embedding_service import EmbeddingService  # exposed for test monkeypatching

__all__ = [
    "router", "get_upload_path", "settings", "OptimizationLogManager",
    "_execute_optimization_stage", "AsyncSessionLocal", "QdrantService", "EmbeddingService",
]
