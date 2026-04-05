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
from ...core.config import get_upload_path  # exposed here so tests can monkeypatch pipeline_api.get_upload_path

__all__ = ["router", "get_upload_path"]
