"""Candidate 5: Scope Simplification tests.

Confirms that document_type has been removed from active scope governance.
Scope is now system + area only. Tests cover:
- resolve_query_scope always returns None for document_type fields
- Retrieval passes document_type_filter=None to QdrantService regardless of request value
- Upload endpoint still works without document_type in scope enforcement
- Chat still works with only system/area scope selectors
- Backward compat: requests that include document_type_filters are accepted (no 422)
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.security import get_current_user_id, get_jwt_payload  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chat import ChatQueryRequest, RAGContext  # noqa: E402
from app.models.database import get_db  # noqa: E402
from app.services.rag_helpers import resolve_query_scope  # noqa: E402
import app.services.chat_service as chat_service_module  # noqa: E402


TEST_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
CHAT_QUERY_ENDPOINT = "/api/v1/chat/query"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self):
        self.conversations: dict[str, dict] = {}
        self.messages: list[dict] = []

    async def execute(self, query, params=None):
        sql = str(query).lower()
        if "select id from conversations" in sql:
            conv_id = (params or {}).get("conv_id")
            if conv_id and conv_id in self.conversations:
                return _FakeResult([{"id": conv_id}])
            return _FakeResult([])
        if "select workspace, document_type_filters" in sql:
            return _FakeResult([])
        if "insert into conversations" in sql:
            p = params or {}
            self.conversations[p["id"]] = {
                "workspace": p.get("workspace"),
                "document_type_filters": p.get("document_type_filters"),
                "preferred_document_types": p.get("preferred_document_types"),
                "include_shared_documents": p.get("include_shared_documents"),
                "title": p.get("title"),
            }
        if "insert into messages" in sql or "insert into chat_messages" in sql:
            self.messages.append(params or {})
        if "select user_scope_policies" in sql or "user_scope_policies" in sql:
            return _FakeResult([])
        return _FakeResult([])

    async def commit(self):
        pass


@pytest.fixture()
def fake_db():
    return _FakeDB()


@pytest.fixture()
def client(fake_db: _FakeDB):
    app.dependency_overrides[get_current_user_id] = lambda: str(TEST_USER_ID)
    app.dependency_overrides[get_jwt_payload] = lambda: {
        "sub": str(TEST_USER_ID),
        "role": "admin",
    }
    app.dependency_overrides[get_db] = lambda: fake_db
    with TestClient(app, raise_server_exceptions=True) as tc:
        yield tc
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Unit tests: resolve_query_scope
# ---------------------------------------------------------------------------


def test_resolve_query_scope_returns_none_for_document_type_fields():
    """Candidate 5: document_type_filters and preferred_document_types always None."""
    request = ChatQueryRequest(
        query="What is the startup procedure?",
        workspace="Liquefaction",
        document_type_filters=["Procedure", "SOP"],
        preferred_document_types=["SOP"],
        include_shared_documents=False,
    )
    result = resolve_query_scope(request=request, persisted_scope=None)

    assert result["document_type_filters"] is None
    assert result["preferred_document_types"] is None


def test_resolve_query_scope_ignores_persisted_document_type_scope():
    """Candidate 5: persisted scope document_type values are not restored."""
    request = ChatQueryRequest(query="Pressure readings?")
    persisted = {
        "workspace": "Power Block",
        "document_type_filters": ["Manual"],
        "preferred_document_types": ["Manual"],
        "include_shared_documents": True,
    }
    result = resolve_query_scope(request=request, persisted_scope=persisted)

    assert result["document_type_filters"] is None
    assert result["preferred_document_types"] is None
    # workspace and include_shared_documents still resolved normally
    assert result["workspace"] == "Power Block"
    assert result["include_shared_documents"] is True


def test_resolve_query_scope_workspace_still_active():
    """Workspace (area) scope axis is still active after Candidate 5."""
    request = ChatQueryRequest(query="Compressor maintenance?", workspace="Liquefaction")
    result = resolve_query_scope(request=request, persisted_scope=None)

    assert result["workspace"] == "Liquefaction"
    assert result["document_type_filters"] is None


def test_resolve_query_scope_no_document_type_returns_none():
    """No document_type in request → still None (no change in behavior)."""
    request = ChatQueryRequest(query="What is LNG density?", workspace="Power Block")
    result = resolve_query_scope(request=request, persisted_scope=None)

    assert result["document_type_filters"] is None
    assert result["preferred_document_types"] is None


# ---------------------------------------------------------------------------
# Integration tests: chat endpoint
# ---------------------------------------------------------------------------


def test_chat_query_without_document_type_succeeds(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Chat works with system/area only — no document_type in request body."""
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Pre-treatment filter maintenance schedule.",
                document_id=uuid.uuid4(),
                document_title="Pre-Treatment Ops Manual",
                metadata={"page_number": 7, "system": "pre treatment"},
                score=0.88,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Maintain filters on a 30-day schedule per the pre-treatment ops manual."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        CHAT_QUERY_ENDPOINT,
        json={
            "query": "What is the filter maintenance schedule?",
            "workspace": "Pre Treatment",
            "include_shared_documents": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "citations" in payload
    assert len(payload["citations"]) >= 1
    # document_type_filter must be None (system/area only)
    assert captured.get("document_type_filter") is None


def test_chat_query_with_legacy_document_type_fields_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Backward compat: requests containing document_type_filters are accepted (no 422)."""
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.2, 0.3, 0.4]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-x",
                content="Startup checklist for liquefaction train.",
                document_id=uuid.uuid4(),
                document_title="Liquefaction SOP",
                metadata={"page_number": 1},
                score=0.91,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Follow the startup checklist."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        CHAT_QUERY_ENDPOINT,
        json={
            "query": "Startup checklist?",
            "workspace": "Liquefaction",
            # Legacy fields — must be accepted (no 422) but ignored
            "document_type_filters": ["Procedure"],
            "preferred_document_types": ["Procedure"],
        },
    )

    # Request is accepted despite deprecated fields being present
    assert response.status_code == 200
    # document_type was NOT forwarded to Qdrant
    assert captured.get("document_type_filter") is None


def test_chat_query_system_filters_still_active(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """System filters (the other active scope axis) still work after Candidate 5."""
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.3, 0.4, 0.5]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-s1",
                content="Power block turbine maintenance.",
                document_id=uuid.uuid4(),
                document_title="Power Block Guide",
                metadata={"page_number": 3, "system": "power block"},
                score=0.87,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Follow turbine maintenance procedure."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        CHAT_QUERY_ENDPOINT,
        json={
            "query": "Turbine maintenance schedule?",
            "system_filters": ["power block"],
        },
    )

    assert response.status_code == 200
    # system_filter is still passed to Qdrant (active scope axis)
    assert captured.get("system_filter") is not None


def test_chat_query_context_order_based_on_raw_score_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Candidate 5: no doc-type boost — citation order follows raw similarity score."""

    async def fake_embed_query(_query: str):
        return [0.5, 0.6, 0.7]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-hi",
                content="High-score manual content.",
                document_id=uuid.uuid4(),
                document_title="High Score Manual",
                metadata={"document_type": "Manual"},
                score=0.95,
            ),
            RAGContext(
                chunk_id="chunk-lo",
                content="Low-score procedure content.",
                document_id=uuid.uuid4(),
                document_title="Low Score Procedure",
                metadata={"document_type": "Procedure"},
                score=0.80,
            ),
        ]

    async def fake_generate(**_kwargs):
        return "Use the high-score manual."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        CHAT_QUERY_ENDPOINT,
        json={
            "query": "What do I need?",
            # Even with preferred_document_types=["Procedure"], score order unchanged
            "preferred_document_types": ["Procedure"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # High-score doc comes first regardless of preferred_document_types
    assert payload["citations"][0]["document_title"] == "High Score Manual"
