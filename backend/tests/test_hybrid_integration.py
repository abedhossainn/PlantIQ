#!/usr/bin/env python3
"""Hybrid integration tests for FastAPI orchestration, SSE, and websocket contracts."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.security import get_current_user_id  # noqa: E402
from app.main import app  # noqa: E402
from app.models.chat import RAGContext  # noqa: E402
from app.models.database import get_db  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from app.services.pipeline_service import PipelineService  # noqa: E402
import app.api.websocket as websocket_api  # noqa: E402
import app.services.chat_service as chat_service_module  # noqa: E402
import app.api.pipeline as pipeline_api  # noqa: E402


TEST_USER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02"
    b"\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeMappings:
    def __init__(self, rows: Any = None):
        if rows is None:
            self._rows: list[Any] = []
        elif isinstance(rows, list):
            self._rows = rows
        else:
            self._rows = [rows]

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class FakeResult:
    def __init__(self, row: Any = None):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
        return self._row

    def mappings(self):
        return FakeMappings(self._row)


class FakeAsyncSession:
    def __init__(self):
        self.conversations: dict[str, dict[str, Any]] = {}
        self.chat_messages: list[dict[str, Any]] = []
        self.documents: dict[str, dict[str, Any]] = {}

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        params = params or {}

        if "select id from conversations" in sql:
            conversation = self.conversations.get(str(params["conv_id"]))
            if conversation and conversation["user_id"] == str(params["user_id"]):
                return FakeResult((conversation["id"],))
            return FakeResult(None)

        if "select workspace, document_type_filters, preferred_document_types, include_shared_documents" in sql:
            conversation = self.conversations.get(str(params["conv_id"]))
            if not conversation or conversation["user_id"] != str(params["user_id"]):
                return FakeResult(None)
            return FakeResult(
                {
                    "workspace": conversation.get("workspace"),
                    "document_type_filters": conversation.get("document_type_filters"),
                    "preferred_document_types": conversation.get("preferred_document_types"),
                    "include_shared_documents": conversation.get("include_shared_documents"),
                }
            )

        if "insert into conversations" in sql:
            self.conversations[str(params["id"])] = {
                "id": str(params["id"]),
                "user_id": str(params["user_id"]),
                "title": params["title"],
                "workspace": params.get("workspace"),
                "document_type_filters": params.get("document_type_filters"),
                "preferred_document_types": params.get("preferred_document_types"),
                "include_shared_documents": params.get("include_shared_documents"),
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
            return FakeResult(None)

        if "update conversations" in sql:
            conversation = self.conversations.get(str(params["conv_id"]))
            if not conversation or conversation["user_id"] != str(params["user_id"]):
                return FakeResult(None)

            conversation["workspace"] = params.get("workspace")
            conversation["document_type_filters"] = params.get("document_type_filters")
            conversation["preferred_document_types"] = params.get("preferred_document_types")
            conversation["include_shared_documents"] = params.get("include_shared_documents")
            conversation["updated_at"] = datetime.now(timezone.utc)
            return FakeResult(None)

        if "insert into chat_messages" in sql:
            self.chat_messages.append(
                {
                    "id": str(params["id"]),
                    "conversation_id": str(params["conv_id"]),
                    "role": params["role"],
                    "content": params["content"],
                    "citations": params.get("citations"),
                }
            )
            return FakeResult(None)

        if "insert into documents" in sql:
            now = datetime.now(timezone.utc)
            self.documents[str(params["id"])] = {
                "id": str(params["id"]),
                "title": params["title"],
                "version": params.get("version"),
                "system": params.get("system"),
                "document_type": params.get("doc_type"),
                "file_path": params["file_path"],
                "status": params["status"],
                "uploaded_by": str(params["user_id"]),
                "notes": params.get("notes"),
                "qa_score": None,
                "optimization_started_at": None,
                "optimization_completed_at": None,
                "optimization_error": None,
                "publication_status": None,
                "published_at": None,
                "publication_error": None,
                "indexed_chunk_count": None,
                "qdrant_collection": None,
                "created_at": now,
                "updated_at": now,
            }
            return FakeResult(None)

        if "update documents" in sql:
            document_id = str(params.get("doc_id") or params.get("id"))
            document = self.documents[document_id]

            if "status = 'extracting'" in sql:
                document["status"] = "extracting"
            elif "status = 'failed'" in sql:
                document["status"] = "failed"
                if "notes" in params:
                    document["notes"] = params["notes"]
            else:
                document["status"] = (
                    params.get("status")
                    or params.get("new_status")
                    or params.get("failed_status")
                    or document.get("status")
                )
                if "notes" in params:
                    document["notes"] = params["notes"]
                if "qa_score" in params:
                    document["qa_score"] = params["qa_score"]
                if "optimization_error" in params:
                    document["optimization_error"] = params["optimization_error"]
                if "publication_status" in params:
                    document["publication_status"] = params["publication_status"]
                if "published_at" in params:
                    document["published_at"] = params["published_at"]
                if "publication_error" in params:
                    document["publication_error"] = params["publication_error"]
                if "indexed_chunk_count" in params:
                    document["indexed_chunk_count"] = params["indexed_chunk_count"]
                if "qdrant_collection" in params:
                    document["qdrant_collection"] = params["qdrant_collection"]
                if "optimization_started_at" in params:
                    document["optimization_started_at"] = params["optimization_started_at"]
                if "optimization_completed_at" in params:
                    document["optimization_completed_at"] = params["optimization_completed_at"]
                if "optimization_started_at = now()" in sql:
                    document["optimization_started_at"] = datetime.now(timezone.utc)
                if "optimization_started_at = null" in sql:
                    document["optimization_started_at"] = None
                if "optimization_completed_at = now()" in sql:
                    document["optimization_completed_at"] = datetime.now(timezone.utc)
                if "optimization_completed_at = null" in sql:
                    document["optimization_completed_at"] = None
                if "published_at = now()" in sql:
                    document["published_at"] = datetime.now(timezone.utc)
                if "publication_status = null" in sql:
                    document["publication_status"] = None
                if "published_at = null" in sql:
                    document["published_at"] = None
                if "qa_score = null" in sql:
                    document["qa_score"] = None
                if "optimization_error = null" in sql:
                    document["optimization_error"] = None
                if "publication_error = null" in sql:
                    document["publication_error"] = None
                if "indexed_chunk_count = null" in sql:
                    document["indexed_chunk_count"] = None
                if "qdrant_collection = null" in sql:
                    document["qdrant_collection"] = None
            document["updated_at"] = datetime.now(timezone.utc)
            return FakeResult(None)

        if "delete from documents where id = :doc_id" in sql:
            self.documents.pop(str(params["doc_id"]), None)
            return FakeResult(None)

        if "select title, system, document_type, status, publication_status" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult(
                {
                    "title": document.get("title"),
                    "system": document.get("system"),
                    "document_type": document.get("document_type"),
                    "status": document["status"],
                    "publication_status": document.get("publication_status"),
                }
            )

        if "select title, file_path, status" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult(
                {
                    "title": document.get("title"),
                    "file_path": document.get("file_path"),
                    "status": document.get("status"),
                }
            )

        if "select published_at, publication_error, indexed_chunk_count, qdrant_collection" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult(
                {
                    "published_at": document.get("published_at"),
                    "publication_error": document.get("publication_error"),
                    "indexed_chunk_count": document.get("indexed_chunk_count"),
                    "qdrant_collection": document.get("qdrant_collection"),
                }
            )

        if "select status, file_path from documents where id = :doc_id" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult({"status": document["status"], "file_path": document.get("file_path")})

        if "select status from documents where id = :doc_id" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult((document["status"],))

        if "select" in sql and "from documents" in sql and "optimization_started_at" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)

            return FakeResult(
                (
                    document["status"],
                    document["created_at"],
                    document["updated_at"],
                    document.get("notes"),
                    document.get("optimization_started_at"),
                    document.get("optimization_completed_at"),
                    document.get("optimization_error"),
                    document.get("publication_status"),
                    document.get("published_at"),
                    document.get("publication_error"),
                    document.get("indexed_chunk_count"),
                    document.get("qdrant_collection"),
                )
            )

        if "from documents" in sql and "order by uploaded_at desc" in sql:
            rows = []
            for document in self.documents.values():
                rows.append(
                    {
                        "id": document["id"],
                        "title": document.get("title"),
                        "version": document.get("version"),
                        "system": document.get("system"),
                        "document_type": document.get("document_type"),
                        "status": document.get("status"),
                        "file_path": document.get("file_path"),
                        "uploaded_by": document.get("uploaded_by"),
                        "notes": document.get("notes"),
                        "uploaded_at": document.get("uploaded_at"),
                        "updated_at": document.get("updated_at"),
                        "total_pages": document.get("total_pages"),
                        "total_sections": document.get("total_sections"),
                        "review_progress": document.get("review_progress"),
                        "qa_score": document.get("qa_score"),
                        "approved_by": document.get("approved_by"),
                        "approved_at": document.get("approved_at"),
                        "publication_status": document.get("publication_status"),
                        "published_at": document.get("published_at"),
                        "publication_error": document.get("publication_error"),
                        "indexed_chunk_count": document.get("indexed_chunk_count"),
                        "qdrant_collection": document.get("qdrant_collection"),
                    }
                )
            rows.sort(key=lambda row: row.get("uploaded_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
            return FakeResult(rows)

        if "select status, created_at, updated_at, notes from documents" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)

            return FakeResult(
                (
                    document["status"],
                    document["created_at"],
                    document["updated_at"],
                    document.get("notes"),
                )
            )

        raise AssertionError(f"Unexpected SQL in test double: {statement}")

    async def commit(self):
        return None


class _AsyncSessionContext:
    def __init__(self, session: FakeAsyncSession):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_db() -> FakeAsyncSession:
    return FakeAsyncSession()


@pytest.fixture
def client(fake_db: FakeAsyncSession):
    async def override_get_db():
        yield fake_db

    async def override_get_current_user_id():
        return TEST_USER_ID

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user_id] = override_get_current_user_id

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_complete_checklist(path: Path) -> None:
    checklist = {
        "question_headings": {"item": "Headings are questions", "checked": True, "notes": None},
        "table_facts_extracted": {"item": "Table facts extracted to bullets", "checked": True, "notes": None},
        "figure_descriptions": {"item": "Figures have text descriptions", "checked": True, "notes": None},
        "citations_present": {"item": "Source citations included", "checked": True, "notes": None},
        "no_hallucinations": {"item": "No AI-generated content", "checked": True, "notes": None},
        "rag_optimized": {"item": "Follows RAG guidelines", "checked": True, "notes": None},
    }
    _write_json(path, checklist)


def _write_empty_checklist(path: Path) -> None:
    checklist = {
        "question_headings": {"item": "Headings are questions", "checked": False, "notes": None},
        "table_facts_extracted": {"item": "Table facts extracted to bullets", "checked": False, "notes": None},
        "figure_descriptions": {"item": "Figures have text descriptions", "checked": False, "notes": None},
        "citations_present": {"item": "Source citations included", "checked": False, "notes": None},
        "no_hallucinations": {"item": "No AI-generated content", "checked": False, "notes": None},
        "rag_optimized": {"item": "Follows RAG guidelines", "checked": False, "notes": None},
    }
    _write_json(path, checklist)


def test_chat_query_returns_citations_and_persists_messages(client: TestClient, fake_db: FakeAsyncSession, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="LNG density is approximately 450 kg/m³ at atmospheric pressure.",
                document_id=uuid.uuid4(),
                document_title="LNG Manual",
                metadata={"page_number": 12, "section_heading": "Physical Properties"},
                score=0.95,
            )
        ]

    async def fake_generate(**_kwargs):
        return "LNG density is approximately 450 kg/m³ at atmospheric pressure."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={"query": "What is LNG density?"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "LNG density is approximately 450 kg/m³ at atmospheric pressure."
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["document_title"] == "LNG Manual"
    assert len(fake_db.conversations) == 1
    assert [message["role"] for message in fake_db.chat_messages] == ["user", "assistant"]


def test_chat_query_applies_workspace_and_document_type_filters(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Liquefaction startup checklist.",
                document_id=uuid.uuid4(),
                document_title="Liquefaction SOP",
                metadata={"page_number": 4, "document_type": "Procedure"},
                score=0.9,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Use the liquefaction startup checklist and verify pre-treatment readiness."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "How do I start up liquefaction after pre-treatment checks?",
            "workspace": "Liquefaction",
            "document_type_filters": ["Procedure"],
            "preferred_document_types": ["Procedure"],
            "include_shared_documents": True,
        },
    )

    assert response.status_code == 200
    assert captured["workspace_filter"] == "Liquefaction"
    assert captured["document_type_filter"] == ["Procedure"]
    assert captured["include_shared_documents"] is True


def test_chat_query_document_type_preference_reorders_contexts(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed_query(_query: str):
        return [0.4, 0.5, 0.6]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="General operating note from manual.",
                document_id=uuid.uuid4(),
                document_title="Operations Manual",
                metadata={"page_number": 10, "document_type": "Operating Manual"},
                score=0.90,
            ),
            RAGContext(
                chunk_id="chunk-2",
                content="Procedure-specific startup sequence.",
                document_id=uuid.uuid4(),
                document_title="Startup Procedure",
                metadata={"page_number": 11, "document_type": "Procedure"},
                score=0.86,
            ),
        ]

    async def fake_generate(**_kwargs):
        return "Follow the startup procedure for deterministic sequencing."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "Give me startup sequencing guidance",
            "preferred_document_types": ["Procedure"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["citations"][0]["document_title"] == "Startup Procedure"


def test_chat_query_normalizes_workspace_alias_before_search(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="DCS alarm response playbook.",
                document_id=uuid.uuid4(),
                document_title="DCS Playbook",
                metadata={"page_number": 2, "document_type": "Procedure"},
                score=0.93,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Follow the DCS playbook alarm response checklist."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "How should I handle this DCS alarm?",
            "workspace": "dcs",
        },
    )

    assert response.status_code == 200
    assert captured["workspace_filter"] == "DCS (Distributed Control System)"


def test_chat_query_persists_conversation_scope_metadata_on_create(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Liquefaction startup checklist.",
                document_id=uuid.uuid4(),
                document_title="Liquefaction SOP",
                metadata={"page_number": 4, "document_type": "Procedure"},
                score=0.9,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Use the liquefaction startup checklist."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "How do I start liquefaction?",
            "workspace": "Liquefaction",
            "document_type_filters": ["Procedure"],
            "preferred_document_types": ["Procedure"],
            "include_shared_documents": False,
        },
    )

    assert response.status_code == 200
    assert len(fake_db.conversations) == 1
    saved_conversation = next(iter(fake_db.conversations.values()))
    assert saved_conversation["workspace"] == "Liquefaction"
    assert saved_conversation["document_type_filters"] == ["Procedure"]
    assert saved_conversation["preferred_document_types"] == ["Procedure"]
    assert saved_conversation["include_shared_documents"] is False
    assert saved_conversation["title"] == "How do I start liquefaction?"


def test_chat_query_truncates_generated_conversation_title_on_create(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Long-query guidance.",
                document_id=uuid.uuid4(),
                document_title="Long Query Guide",
                metadata={"page_number": 1, "document_type": "Procedure"},
                score=0.92,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Use the long-query guidance."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    long_query = (
        "What is the detailed liquefaction startup sequence after pre-treatment is complete "
        "and before refrigerant circulation begins under cold weather conditions?"
    )

    response = client.post(
        "/api/v1/chat/query",
        json={"query": long_query},
    )

    assert response.status_code == 200
    saved_conversation = next(iter(fake_db.conversations.values()))
    assert len(saved_conversation["title"]) <= 80
    assert saved_conversation["title"].endswith("...")


def test_chat_query_updates_existing_conversation_scope_metadata(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    conversation_id = str(uuid.uuid4())
    original_updated_at = datetime.now(timezone.utc)
    fake_db.conversations[conversation_id] = {
        "id": conversation_id,
        "user_id": str(TEST_USER_ID),
        "title": "Existing Conversation",
        "workspace": "Power Block",
        "document_type_filters": ["Operating Manual"],
        "preferred_document_types": ["Operating Manual"],
        "include_shared_documents": True,
        "created_at": original_updated_at,
        "updated_at": original_updated_at,
    }

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Mechanical maintenance checklist.",
                document_id=uuid.uuid4(),
                document_title="Mechanical Maintenance Guide",
                metadata={"page_number": 8, "document_type": "Maintenance Manual"},
                score=0.91,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Use the mechanical maintenance checklist."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "conversation_id": conversation_id,
            "query": "What maintenance checklist applies?",
            "workspace": "Mechanical",
            "document_type_filters": ["Maintenance Manual"],
            "preferred_document_types": ["Maintenance Manual"],
            "include_shared_documents": False,
        },
    )

    assert response.status_code == 200
    updated_conversation = fake_db.conversations[conversation_id]
    assert updated_conversation["workspace"] == "Mechanical"
    assert updated_conversation["document_type_filters"] == ["Maintenance Manual"]
    assert updated_conversation["preferred_document_types"] == ["Maintenance Manual"]
    assert updated_conversation["include_shared_documents"] is False
    assert updated_conversation["updated_at"] >= original_updated_at


def test_chat_query_uses_persisted_scope_when_request_scope_fields_omitted(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    conversation_id = str(uuid.uuid4())
    fake_db.conversations[conversation_id] = {
        "id": conversation_id,
        "user_id": str(TEST_USER_ID),
        "title": "Persisted Scope Conversation",
        "workspace": "Liquefaction",
        "document_type_filters": ["Procedure"],
        "preferred_document_types": ["Procedure"],
        "include_shared_documents": False,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }

    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Persisted scope retrieval result.",
                document_id=uuid.uuid4(),
                document_title="Scope Guide",
                metadata={"page_number": 5, "document_type": "Procedure"},
                score=0.9,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Using persisted scope defaults for this conversation."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "conversation_id": conversation_id,
            "query": "Continue this scoped conversation",
        },
    )

    assert response.status_code == 200
    assert captured["workspace_filter"] == "Liquefaction"
    assert captured["document_type_filter"] == ["Procedure"]
    assert captured["include_shared_documents"] is False


def test_chat_query_uses_config_default_for_include_shared_when_omitted(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, Any] = {}

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**kwargs):
        captured.update(kwargs)
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Shared safety bulletin for startup checks.",
                document_id=uuid.uuid4(),
                document_title="Shared Safety Bulletin",
                metadata={"page_number": 1, "document_type": "Procedure", "workspace": "shared"},
                score=0.88,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Use the shared safety bulletin checklist."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)
    monkeypatch.setattr(chat_service_module.settings, "CHAT_INCLUDE_SHARED_DEFAULT", False)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "What shared safety checks apply?",
            "workspace": "Liquefaction",
        },
    )

    assert response.status_code == 200
    assert captured["include_shared_documents"] is False


def test_chat_query_returns_503_when_llm_generation_unavailable(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="Procedure excerpt",
                document_id=uuid.uuid4(),
                document_title="Startup Procedure",
                metadata={"page_number": 1, "document_type": "Procedure"},
                score=0.91,
            )
        ]

    async def fake_generate(**_kwargs):
        raise chat_service_module.LLMConfigurationError(
            "Configured Ollama model is not installed. Configured: 'Qwen/Qwen3-4B'."
        )

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.LLMService, "generate", fake_generate)

    response = client.post(
        "/api/v1/chat/query",
        json={"query": "How do I start the train?"},
    )

    assert response.status_code == 503
    assert "Chat generation unavailable" in response.json()["detail"]


def test_chat_query_retries_same_scope_with_relaxed_threshold_when_initial_search_is_empty(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    search_calls: list[dict[str, Any]] = []

    async def fake_embed_query(_query: str):
        return [0.11, 0.22, 0.33]

    async def fake_search_similar(**kwargs):
        search_calls.append(dict(kwargs))
        if len(search_calls) == 1:
            return []
        return [
            RAGContext(
                chunk_id="chunk-figure-1",
                content="Figure 1 shows the process flow for the startup sequence.",
                document_id=uuid.uuid4(),
                document_title="Power Block Technical Standard",
                metadata={"page_number": 3, "document_type": "Technical Standard"},
                score=0.57,
            )
        ]

    async def fake_generate(**_kwargs):
        return "Figure 1 shows the process flow for startup sequencing and control boundaries."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)
    monkeypatch.setattr(chat_service_module.settings, "RAG_SCORE_THRESHOLD", 0.7)
    monkeypatch.setattr(chat_service_module.settings, "CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED", False)

    response = client.post(
        "/api/v1/chat/query",
        json={
            "query": "can you explain figure 1?",
            "workspace": "Power Block",
            "document_type_filters": ["Technical Standard"],
            "include_shared_documents": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "Figure 1" in payload["content"]
    assert payload["citations"][0]["document_title"] == "Power Block Technical Standard"
    assert len(search_calls) == 2
    assert search_calls[0]["score_threshold"] == pytest.approx(0.7)
    assert search_calls[1]["score_threshold"] == pytest.approx(0.45)
    assert search_calls[0]["workspace_filter"] == "Power Block"
    assert search_calls[1]["workspace_filter"] == "Power Block"
    assert search_calls[0]["include_shared_documents"] is False
    assert search_calls[1]["include_shared_documents"] is False


def test_chat_stream_emits_sse_tokens_and_done_marker(client: TestClient, fake_db: FakeAsyncSession, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="LNG is cryogenic.",
                document_id=uuid.uuid4(),
                document_title="Operations Guide",
                metadata={"page_number": 3},
                score=0.91,
            )
        ]

    async def fake_generate_stream(**_kwargs):
        for token in ["Hello", " ", "operator"]:
            yield token

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate_stream", fake_generate_stream)

    with client.stream("POST", "/api/v1/chat/stream", json={"query": "Stream answer"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"

    raw_events = [chunk for chunk in body.split("\n\n") if chunk.strip()]
    parsed_events = []
    for raw_event in raw_events:
        event_name = None
        payload = None
        for line in raw_event.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if event_name and payload:
            parsed_events.append((event_name, payload))

    token_events = [payload for event_name, payload in parsed_events if event_name == "token"]
    citation_events = [payload for event_name, payload in parsed_events if event_name == "citation"]
    complete_events = [payload for event_name, payload in parsed_events if event_name == "complete"]

    assert [payload["token"] for payload in token_events] == ["Hello", " ", "operator"]
    assert all(payload["content"] == payload["token"] for payload in token_events)
    assert len({payload["message_id"] for payload in token_events}) == 1
    assert len({payload["conversation_id"] for payload in token_events}) == 1
    assert len(citation_events) == 1
    assert citation_events[0]["citation"]["document_title"] == "Operations Guide"
    assert complete_events == [{
        "event": "complete",
        "conversation_id": token_events[0]["conversation_id"],
        "message_id": token_events[0]["message_id"],
        "timestamp": complete_events[0]["timestamp"],
        "done": True,
    }]
    assert fake_db.chat_messages[-1]["content"] == "Hello operator"


def test_chat_stream_falls_back_to_non_stream_generation_when_stream_is_empty(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="LNG is cryogenic.",
                document_id=uuid.uuid4(),
                document_title="Operations Guide",
                metadata={"page_number": 3},
                score=0.91,
            )
        ]

    async def fake_generate_stream(**_kwargs):
        if False:  # pragma: no cover
            yield ""

    async def fake_generate(**_kwargs):
        return "The boiling point of methane is -259.6°F."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.LLMService, "generate_stream", fake_generate_stream)
    monkeypatch.setattr(chat_service_module.LLMService, "generate", fake_generate)

    with client.stream("POST", "/api/v1/chat/stream", json={"query": "What is methane boiling point?"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200

    raw_events = [chunk for chunk in body.split("\n\n") if chunk.strip()]
    parsed_events = []
    for raw_event in raw_events:
        event_name = None
        payload = None
        for line in raw_event.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if event_name and payload:
            parsed_events.append((event_name, payload))

    token_events = [payload for event_name, payload in parsed_events if event_name == "token"]
    assert token_events
    assert token_events[-1]["token"] == "The boiling point of methane is -259.6°F."
    assert fake_db.chat_messages[-1]["content"] == "The boiling point of methane is -259.6°F."
    assert parsed_events[-1][0] == "complete"


def test_chat_stream_emits_structured_error_event_on_generation_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    async def fake_embed_query(_query: str):
        return [0.1, 0.2]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-1",
                content="LNG is cryogenic.",
                document_id=uuid.uuid4(),
                document_title="Operations Guide",
                metadata={"page_number": 3},
                score=0.91,
            )
        ]

    async def fake_generate_stream(**_kwargs):
        raise RuntimeError("LLM inference failed")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate_stream", fake_generate_stream)

    with client.stream("POST", "/api/v1/chat/stream", json={"query": "Stream answer"}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    raw_events = [chunk for chunk in body.split("\n\n") if chunk.strip()]

    parsed_events = []
    for raw_event in raw_events:
        event_name = None
        payload = None
        for line in raw_event.splitlines():
            if line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
        if event_name and payload:
            parsed_events.append((event_name, payload))

    assert parsed_events[-1][0] == "error"
    assert parsed_events[-1][1]["error"] == "LLM inference failed"
    assert parsed_events[-1][1]["done"] is True


def test_pipeline_events_stream_replays_accept_progress_and_complete(client: TestClient, fake_db: FakeAsyncSession):
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "extracting",
        "created_at": now,
        "updated_at": now,
        "notes": None,
    }

    PipelineService._event_history[document_id] = [
        {
            "event": "job.accepted",
            "document_id": document_id,
            "job_id": "job-123",
            "stage": "queued",
            "progress": 0,
            "message": "Document upload accepted. Pipeline job queued.",
            "timestamp": now.isoformat(),
        },
        {
            "event": "progress",
            "document_id": document_id,
            "job_id": "job-123",
            "stage": "extraction",
            "progress": 30,
            "message": "Pipeline started and extraction is in progress.",
            "timestamp": now.isoformat(),
        },
        {
            "event": "stage.complete",
            "document_id": document_id,
            "job_id": "job-123",
            "stage": "validation",
            "progress": 100,
            "message": "Pipeline validation stage completed.",
            "artifact_type": "workspace",
            "artifact_path": f"/tmp/{document_id}",
            "timestamp": now.isoformat(),
        },
        {
            "event": "complete",
            "document_id": document_id,
            "job_id": "job-123",
            "stage": "completed",
            "progress": 100,
            "message": "Document ingestion completed successfully.",
            "artifact_type": "workspace",
            "artifact_path": f"/tmp/{document_id}",
            "timestamp": now.isoformat(),
        },
    ]

    with client.stream("GET", f"/api/v1/documents/{document_id}/events") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: job.accepted" in body
    assert "event: progress" in body
    assert "event: stage.complete" in body
    assert "event: complete" in body
    assert f'"document_id": "{document_id}"' in body


def test_pipeline_events_stream_builds_terminal_error_event_from_failed_status(client: TestClient, fake_db: FakeAsyncSession):
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "failed",
        "created_at": now,
        "updated_at": now,
        "notes": "Pipeline execution timed out",
    }

    PipelineService._event_history.pop(document_id, None)

    with client.stream("GET", f"/api/v1/documents/{document_id}/events") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: error" in body
    assert '"stage": "failed"' in body
    assert '"error": "Pipeline execution timed out"' in body


def test_upload_document_saves_pdf_and_triggers_pipeline(client: TestClient, fake_db: FakeAsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    saved_paths: list[Path] = []

    def fake_get_upload_path(filename: str) -> Path:
        path = tmp_path / filename
        saved_paths.append(path)
        return path

    async def fake_trigger_pipeline(**_kwargs):
        return "job-123"

    monkeypatch.setattr(pipeline_api, "get_upload_path", fake_get_upload_path)
    monkeypatch.setattr(PipelineService, "trigger_pipeline", fake_trigger_pipeline)

    response = client.post(
        "/api/v1/documents/upload",
        data={
            "title": "Plant Manual",
            "version": "1.0",
            "system": "LNG",
            "document_type": "procedure",
            "notes": "integration test",
        },
        files={"file": ("manual.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "extracting"
    assert payload["message"].endswith("job-123 started.")
    assert saved_paths[0].exists()
    assert len(fake_db.documents) == 1


def test_upload_document_rejects_non_pdf(client: TestClient):
    response = client.post(
        "/api/v1/documents/upload",
        data={"title": "Not a PDF"},
        files={"file": ("notes.txt", io.BytesIO(b"plain text"), "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only PDF files are allowed"


def test_reprocess_document_accepts_flat_request_body_and_triggers_pipeline(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    pdf_path = tmp_path / "reprocess.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 reprocess test")
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "failed",
        "file_path": str(pdf_path),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": "previous failure",
    }

    captured: dict[str, Any] = {}

    async def fake_trigger_pipeline(**kwargs):
        captured.update(kwargs)
        return "job-456"

    monkeypatch.setattr(PipelineService, "trigger_pipeline", fake_trigger_pipeline)

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess",
        json={"force": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["job_id"] == "job-456"
    assert payload["status"] == "extracting"
    assert captured["document_id"] == document_id
    assert captured["pdf_path"] == str(pdf_path)
    assert captured["reviewer"] == str(TEST_USER_ID)


def test_get_document_status_maps_progress_and_stage(client: TestClient, fake_db: FakeAsyncSession):
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "vlm-validating",
        "created_at": now,
        "updated_at": now,
        "notes": None,
    }

    response = client.get(f"/api/v1/documents/{document_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"] == 60
    assert payload["current_stage"] == "validation"


def test_get_document_status_marks_stale_ingestion_without_live_process_as_failed(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale_updated_at = now.replace(year=max(2000, now.year - 1))
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "extracting",
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
        "notes": None,
    }

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_STALLED_GRACE_SECONDS", 1)
    monkeypatch.setattr(PipelineService, "_job_ids_by_document", {})
    monkeypatch.setattr(PipelineService, "_active_processes", {})

    response = client.get(f"/api/v1/documents/{document_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert "stopped unexpectedly" in payload["error"]
    assert fake_db.documents[document_id]["status"] == "failed"
    assert "stopped unexpectedly" in str(fake_db.documents[document_id]["notes"])


def test_list_documents_marks_stale_ingestion_without_live_process_as_failed(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    stale_document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale_updated_at = now.replace(year=max(2000, now.year - 1))
    fake_db.documents[stale_document_id] = {
        "id": stale_document_id,
        "title": "Stale Upload",
        "version": "1.0",
        "system": "Power Block",
        "document_type": "Technical Standard",
        "status": "extracting",
        "file_path": "/tmp/stale.pdf",
        "uploaded_by": str(TEST_USER_ID),
        "notes": None,
        "uploaded_at": stale_updated_at,
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
    }

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_STALLED_GRACE_SECONDS", 1)
    monkeypatch.setattr(PipelineService, "_job_ids_by_document", {})
    monkeypatch.setattr(PipelineService, "_active_processes", {})

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    stale_row = next(item for item in payload if item["id"] == stale_document_id)
    assert stale_row["status"] == "failed"
    assert "stopped unexpectedly" in stale_row["notes"]
    assert fake_db.documents[stale_document_id]["status"] == "failed"


def test_document_pages_endpoint_generates_page_review_units_from_validation(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    thumbnail_dir = work_dir / "validation_evidence"
    thumbnail_dir.mkdir(parents=True)
    (thumbnail_dir / "page_1_thumbnail.png").write_bytes(PNG_1X1)

    validation_payload = {
        "document_name": "sample_document",
        "page_validations": [
            {
                "page_number": 1,
                "markdown_section": "# Page 1\n\nHydrocarbons are organic compounds.",
                "evidence": {
                    "page_number": 1,
                    "text_preview": "Hydrocarbons are organic compounds.",
                    "image_count": 1,
                    "table_count": 0,
                    "has_figures": True,
                    "thumbnail_path": "validation_evidence/page_1_thumbnail.png",
                },
                "issues": [
                    {
                        "issue_type": "image_loss",
                        "severity": "critical",
                        "page_number": 1,
                        "description": "Image missing from markdown",
                        "evidence": "Images detected in PDF page 1",
                        "suggested_fix": "Add figure description",
                    }
                ],
            }
        ],
        "metadata": {"total_pages": 1, "total_issues": 1, "critical_issues": 1},
    }
    _write_json(work_dir / "sample_document_validation.json", validation_payload)

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/pages")

    assert response.status_code == 200
    payload = response.json()
    assert payload["review_unit"] == "page"
    assert payload["document_name"] == "sample_document"
    assert payload["progress"]["total_pages"] == 1
    assert payload["progress"]["completion_percentage"] == 0
    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["page_number"] == 1
    assert payload["pages"][0]["markdown_content"].startswith("# Page 1")
    assert payload["pages"][0]["text_preview"] == "Hydrocarbons are organic compounds."
    assert payload["pages"][0]["evidence"]["thumbnail_url"].endswith(f"/api/v1/documents/{document_id}/pages/1/thumbnail")
    assert (review_dir / "page_review_manifest.json").exists()

    thumbnail_response = client.get(f"/api/v1/documents/{document_id}/pages/1/thumbnail")
    assert thumbnail_response.status_code == 200
    assert thumbnail_response.headers["content-type"] == "image/png"
    assert thumbnail_response.content.startswith(b"\x89PNG")


def test_document_pages_endpoint_reports_progress_from_page_checklists(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    _write_json(
        review_dir / "page_review_manifest.json",
        {
            "document_name": "sample_document",
            "review_unit": "page",
            "total_pages": 2,
            "pages": [
                {
                    "page_id": "page_001",
                    "page_number": 1,
                    "file": "page_001.md",
                    "checklist": "page_001_checklist.json",
                    "text_preview": "Reviewed page",
                    "markdown_content": "# Page 1",
                    "validation_issues": [],
                    "evidence": {"page_number": 1, "text_preview": "Reviewed page", "image_count": 0, "table_count": 0, "has_figures": False},
                    "evidence_images": [],
                },
                {
                    "page_id": "page_002",
                    "page_number": 2,
                    "file": "page_002.md",
                    "checklist": "page_002_checklist.json",
                    "text_preview": "Pending page",
                    "markdown_content": "# Page 2",
                    "validation_issues": [],
                    "evidence": {"page_number": 2, "text_preview": "Pending page", "image_count": 0, "table_count": 0, "has_figures": False},
                    "evidence_images": [],
                },
            ],
        },
    )
    _write_complete_checklist(review_dir / "page_001_checklist.json")
    _write_empty_checklist(review_dir / "page_002_checklist.json")

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/pages")

    assert response.status_code == 200
    payload = response.json()
    assert payload["progress"] == {
        "total_pages": 2,
        "reviewed_pages": 1,
        "pending_pages": 1,
        "completion_percentage": 50.0,
        "by_status": {"reviewed": 1, "pending": 1},
    }


def test_page_content_patch_persists_markdown_and_pages_endpoint_returns_updated_content(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    _write_json(
        review_dir / "page_review_manifest.json",
        {
            "document_name": "sample_document",
            "review_unit": "page",
            "total_pages": 1,
            "pages": [
                {
                    "page_id": "page_001",
                    "page_number": 1,
                    "file": "page_001.md",
                    "checklist": "page_001_checklist.json",
                    "text_preview": "Original page",
                    "markdown_content": "# Original\n\nOld text",
                    "validation_issues": [],
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "Original page",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "evidence_images": [],
                }
            ],
        },
    )
    (review_dir / "page_001.md").write_text("# Original\n\nOld text", encoding="utf-8")

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    patch_response = client.patch(
        f"/api/v1/documents/{document_id}/pages/page_001/content",
        json={"markdown_content": "# Updated\n\nPersisted text"},
    )

    assert patch_response.status_code == 200
    assert patch_response.json() == {"page_id": "page_001", "status": "saved"}
    assert (review_dir / "page_001.md").read_text(encoding="utf-8") == "# Updated\n\nPersisted text"

    pages_response = client.get(f"/api/v1/documents/{document_id}/pages")

    assert pages_response.status_code == 200
    payload = pages_response.json()
    assert payload["pages"][0]["markdown_content"] == "# Updated\n\nPersisted text"


def test_optimized_chunks_endpoint_returns_editable_chunk_payload(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "qa_score": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.",
                    "source_pages": [1],
                    "table_facts": ["LNG is a cryogenic fuel."],
                    "ambiguity_flags": ["Verify temperature range against source table"],
                }
            ],
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/optimized-chunks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_name"] == "sample_document"
    assert payload["review_unit"] == "optimized_chunk"
    assert len(payload["chunks"]) == 1
    assert payload["chunks"][0]["heading"] == "What is LNG?"
    assert payload["chunks"][0]["source_pages"] == [1]
    assert payload["chunks"][0]["table_facts"] == ["LNG is a cryogenic fuel."]


def test_optimized_chunk_patch_updates_artifacts_and_invalidates_qa_report(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-review",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "qa_score": 77.5,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    optimized_json_path = work_dir / "sample_document_rag_optimized.json"
    optimized_markdown_path = work_dir / "sample_document_rag_optimized.md"
    qa_report_path = work_dir / "sample_document_qa_report.json"
    _write_json(
        optimized_json_path,
        {
            "document_name": "sample_document",
            "input_contract": {"primary_source": "optimization_prep", "document_name": "sample_document"},
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.",
                    "source_pages": [1],
                    "table_facts": [],
                    "ambiguity_flags": [],
                }
            ],
            "markdown": "# sample_document\n\n## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.\n",
        },
    )
    optimized_markdown_path.write_text(
        "# sample_document\n\n## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.\n",
        encoding="utf-8",
    )
    _write_json(
        work_dir / "sample_document_validation.json",
        {"document_name": "sample_document", "overall_confidence": 0.96, "page_validations": []},
    )
    _write_json(
        qa_report_path,
        {"decision": "rejected", "metrics": {"overall_confidence_score": 77.5}},
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.patch(
        f"/api/v1/documents/{document_id}/optimized-chunks/chunk_001",
        json={
            "heading": "What are the key LNG properties?",
            "markdown_content": "## What are the key LNG properties?\n\n[Source: sample_document, Page 1]\n\n- LNG is cryogenic.\n- LNG expands rapidly when vaporized.",
            "table_facts": ["LNG is cryogenic.", "LNG expands rapidly when vaporized."],
            "ambiguity_flags": ["Confirm expansion ratio against source figure"],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"chunk_id": "chunk_001", "status": "saved"}

    updated_payload = json.loads(optimized_json_path.read_text(encoding="utf-8"))
    assert updated_payload["chunks"][0]["heading"] == "What are the key LNG properties?"
    assert updated_payload["chunks"][0]["table_facts"] == [
        "LNG is cryogenic.",
        "LNG expands rapidly when vaporized.",
    ]
    assert updated_payload["markdown"].startswith("# sample_document")
    assert "What are the key LNG properties?" in optimized_markdown_path.read_text(encoding="utf-8")
    assert qa_report_path.exists() is False
    assert fake_db.documents[document_id]["status"] == "optimization-complete"
    assert fake_db.documents[document_id]["qa_score"] is None


def test_optimized_chunk_patch_is_blocked_after_qa_passes(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-passed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "qa_score": 96.0,
    }

    response = client.patch(
        f"/api/v1/documents/{document_id}/optimized-chunks/chunk_001",
        json={"heading": "Updated heading", "markdown_content": "Updated content"},
    )

    assert response.status_code == 409
    assert "before QA has passed" in response.json()["detail"]


def test_document_pages_endpoint_prefers_matching_document_workspace_over_unrelated_root_review_dir(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    configured_root = tmp_path / "data" / "artifacts" / "hitl_workspace"
    configured_root.mkdir(parents=True)

    unrelated_review_dir = configured_root / "unrelated_review"
    unrelated_review_dir.mkdir()
    _write_json(
        unrelated_review_dir / "page_review_manifest.json",
        {
            "document_name": "wrong_document",
            "review_unit": "page",
            "total_pages": 30,
            "pages": [
                {
                    "page_id": f"page_{page_number:03d}",
                    "page_number": page_number,
                    "file": f"page_{page_number:03d}.md",
                    "checklist": f"page_{page_number:03d}_checklist.json",
                    "text_preview": f"Wrong page {page_number}",
                    "markdown_content": f"# Wrong Page {page_number}",
                    "validation_issues": [],
                    "evidence": {
                        "page_number": page_number,
                        "text_preview": f"Wrong page {page_number}",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "evidence_images": [],
                }
                for page_number in range(1, 31)
            ],
        },
    )

    backend_root = tmp_path / "backend" / "data" / "artifacts" / "hitl_workspace"
    work_dir = backend_root / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_validation.json",
        {
            "document_name": "sample_document",
            "page_validations": [
                {
                    "page_number": 1,
                    "markdown_section": "# Page 1\n\nCorrect workspace content.",
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "Correct workspace content.",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "issues": [],
                }
            ],
            "metadata": {"total_pages": 1},
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(configured_root))

    response = client.get(f"/api/v1/documents/{document_id}/pages")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_name"] == "sample_document"
    assert payload["progress"]["total_pages"] == 1
    assert [page["page_number"] for page in payload["pages"]] == [1]
    assert payload["pages"][0]["text_preview"] == "Correct workspace content."


def test_sections_endpoint_derives_page_numbers_from_page_review_data(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    section_content = "## Hydrocarbons\n\nHydrocarbons are organic compounds used in LNG processing."
    (review_dir / "section_001.md").write_text(section_content, encoding="utf-8")
    _write_json(review_dir / "section_001_checklist.json", {})
    _write_json(
        review_dir / "review_manifest.json",
        {
            "document_name": "sample_document",
            "sections": [
                {
                    "section_id": "section_001",
                    "heading": "Hydrocarbons",
                    "file": "section_001.md",
                    "checklist": "section_001_checklist.json",
                    "status": "PENDING",
                }
            ],
        },
    )
    _write_json(
        work_dir / "sample_document_validation.json",
        {
            "document_name": "sample_document",
            "page_validations": [
                {
                    "page_number": 1,
                    "markdown_section": "Hydrocarbons are organic compounds used in LNG processing.",
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "Hydrocarbons are organic compounds used in LNG processing.",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "issues": [],
                },
                {
                    "page_number": 2,
                    "markdown_section": "Other unrelated appendix material.",
                    "evidence": {
                        "page_number": 2,
                        "text_preview": "Other unrelated appendix material.",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "issues": [],
                },
            ],
            "metadata": {"total_pages": 2},
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/sections")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sections"][0]["pageRange"] == {"start": 1, "end": 1}
    assert payload["sections"][0]["pageNumbers"] == [1]


def test_artifact_download_returns_file_response(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "validation-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }
    artifact_path = tmp_path / "validation.json"
    artifact_path.write_text('{"status":"ok"}', encoding="utf-8")

    async def fake_get_artifact(**_kwargs):
        return artifact_path

    monkeypatch.setattr(PipelineService, "get_artifact", fake_get_artifact)

    response = client.get(f"/api/v1/documents/{document_id}/artifacts/validation")

    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'


def test_approve_for_optimization_generates_prep_and_triggers_optimization(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "review-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    validation_payload = {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [
                    {
                        "issue_type": "semantic_mismatch",
                        "severity": "major",
                        "page_number": 1,
                        "description": "Reviewer flagged an ambiguity",
                        "evidence": "Ambiguous equipment label",
                        "suggested_fix": "Clarify before optimization",
                    }
                ],
                "evidence": {
                    "page_number": 1,
                    "text_preview": "What is LNG?",
                    "image_count": 0,
                    "table_count": 0,
                    "has_figures": False,
                },
            }
        ],
    }
    _write_json(work_dir / "sample_document_validation.json", validation_payload)
    _write_json(
        work_dir / "sample_document_tables_figures.json",
        {
            "tables": [
                {
                    "table_id": "table_p1_1",
                    "page_number": 1,
                    "key_facts": ["LNG: Density = 450 kg/m3"],
                }
            ],
            "figures": [
                {
                    "figure_id": "figure_001",
                    "page_number": 1,
                    "description": "Tank layout diagram",
                }
            ],
        },
    )
    _write_json(
        review_dir / "page_review_manifest.json",
        {
            "document_name": "sample_document",
            "review_unit": "page",
            "total_pages": 1,
            "pages": [
                {
                    "page_id": "page_001",
                    "page_number": 1,
                    "file": "page_001.md",
                    "checklist": "page_001_checklist.json",
                    "text_preview": "What is LNG?",
                    "markdown_content": "# Stale\n\nOld content",
                    "validation_issues": validation_payload["page_validations"][0]["issues"],
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "What is LNG?",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "evidence_images": [],
                }
            ],
        },
    )
    (review_dir / "page_001.md").write_text(
        "<!-- Page ID: page_001 -->\n# What is LNG?\n\n[Source: sample_document, Page 1]\n\n- Fact one\n- Fact two\n",
        encoding="utf-8",
    )
    _write_json(
        review_dir / "page_001_checklist.json",
        {
            "question_headings": {"item": "Headings are questions", "checked": True, "notes": None},
            "table_facts_extracted": {"item": "Table facts extracted to bullets", "checked": True, "notes": None},
            "figure_descriptions": {"item": "Figures have text descriptions", "checked": False, "notes": "Diagram caption still ambiguous"},
            "citations_present": {"item": "Source citations included", "checked": True, "notes": None},
            "no_hallucinations": {"item": "No AI-generated content", "checked": True, "notes": None},
            "rag_optimized": {"item": "Follows RAG guidelines", "checked": False, "notes": "Leave to Stage 10"},
        },
    )

    triggered: dict[str, Any] = {}

    async def fake_execute_optimization_stage(**kwargs):
        triggered.update(kwargs)

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api, "_execute_optimization_stage", fake_execute_optimization_stage)

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["status"] == "approved-for-optimization"
    assert payload["optimization_triggered"] is True
    prep_path = Path(payload["optimization_prep_path"])
    assert prep_path.exists()

    prep_payload = json.loads(prep_path.read_text(encoding="utf-8"))
    assert prep_payload["document_name"] == "sample_document"
    assert prep_payload["pages"][0]["authoritative_markdown"].startswith("<!-- Page ID: page_001 -->")
    assert prep_payload["pages"][0]["table_facts"] == ["LNG: Density = 450 kg/m3"]
    assert prep_payload["pages"][0]["figure_records"][0]["description"] == "Tank layout diagram"
    assert prep_payload["unresolved_ambiguities"][0]["page_number"] == 1
    assert fake_db.documents[document_id]["status"] == "approved-for-optimization"
    assert triggered["document_id"] == document_id
    assert triggered["optimization_prep_path"] == str(prep_path)


def test_approve_for_optimization_rejects_invalid_state_with_422(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "pending",  # too early in the pipeline — not yet ready for review
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 422
    assert "Approve for optimization is only available" in response.json()["detail"]


def test_approve_for_optimization_returns_conflict_for_active_or_finished_optimization(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimizing",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": datetime.now(timezone.utc),
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot approve document in optimizing status"


def test_approve_for_optimization_allows_retry_from_failed(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "failed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": "old failure",
        "optimization_started_at": datetime.now(timezone.utc),
        "optimization_completed_at": datetime.now(timezone.utc),
        "optimization_error": "old failure",
    }

    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_validation.json",
        {
            "document_name": "sample_document",
            "page_validations": [
                {
                    "page_number": 1,
                    "issues": [],
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "Retry content",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                }
            ],
        },
    )
    _write_json(
        review_dir / "page_review_manifest.json",
        {
            "document_name": "sample_document",
            "review_unit": "page",
            "total_pages": 1,
            "pages": [
                {
                    "page_id": "page_001",
                    "page_number": 1,
                    "file": "page_001.md",
                    "checklist": "page_001_checklist.json",
                    "text_preview": "Retry content",
                    "markdown_content": "# Retry content",
                    "validation_issues": [],
                    "evidence": {
                        "page_number": 1,
                        "text_preview": "Retry content",
                        "image_count": 0,
                        "table_count": 0,
                        "has_figures": False,
                    },
                    "evidence_images": [],
                }
            ],
        },
    )
    (review_dir / "page_001.md").write_text("# Retry content", encoding="utf-8")
    _write_complete_checklist(review_dir / "page_001_checklist.json")

    async def fake_execute_optimization_stage(**_kwargs):
        return None

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api, "_execute_optimization_stage", fake_execute_optimization_stage)

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 200
    assert fake_db.documents[document_id]["status"] == "approved-for-optimization"
    assert fake_db.documents[document_id]["optimization_started_at"] is None
    assert fake_db.documents[document_id]["optimization_completed_at"] is None
    assert fake_db.documents[document_id]["optimization_error"] is None


def test_optimization_logs_replay_failed_terminal_status(client: TestClient):
    document_id = str(uuid.uuid4())
    pipeline_api.OptimizationLogManager.start(document_id)
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-03-25T08:10:05Z",
            "level": "INFO",
            "message": "▶️ Text Reformatting (model=mistral-7b-instruct)",
        },
    )
    pipeline_api.OptimizationLogManager.close(document_id, "failed")

    response = client.get(f"/api/v1/documents/{document_id}/optimization/logs")

    assert response.status_code == 200
    body = response.text
    assert 'event: log' in body
    assert '"message": "▶️ Text Reformatting (model=mistral-7b-instruct)"' in body
    assert 'event: done' in body
    assert '"status": "failed"' in body


def test_status_endpoint_returns_optimization_timing_fields(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": started_at,
        "optimization_completed_at": completed_at,
        "optimization_error": None,
    }

    response = client.get(f"/api/v1/documents/{document_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "optimization-complete"
    assert payload["current_stage"] == "optimization"
    assert payload["started_at"].startswith(started_at.isoformat().replace("+00:00", ""))
    assert payload["completed_at"].startswith(completed_at.isoformat().replace("+00:00", ""))


def test_status_endpoint_reconciles_stale_approved_optimization_state_from_artifacts(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "approved-for-optimization",
        "created_at": created_at,
        "updated_at": created_at,
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_optimization_prep.json",
        {"document_name": "sample_document"},
    )
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\nLNG is a cryogenic fuel.",
                }
            ],
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(PipelineService, "_event_history", {})

    response = client.get(f"/api/v1/documents/{document_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "optimization-complete"
    assert payload["completed_at"] is not None
    assert fake_db.documents[document_id]["status"] == "optimization-complete"
    assert fake_db.documents[document_id]["optimization_completed_at"] is not None


def test_status_endpoint_does_not_reconcile_old_artifacts_over_new_optimization_run(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    fresh_started_at = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimizing",
        "created_at": created_at,
        "updated_at": created_at,
        "notes": None,
        "optimization_started_at": fresh_started_at,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    prep_path = work_dir / "sample_document_optimization_prep.json"
    optimized_path = work_dir / "sample_document_rag_optimized.json"
    _write_json(prep_path, {"document_name": "sample_document"})
    _write_json(
        optimized_path,
        {
            "document_name": "sample_document",
            "chunks": [{"heading": "What is LNG?", "content": "## What is LNG?\n\nLNG is a cryogenic fuel."}],
        },
    )

    stale_timestamp = created_at.timestamp() - 120
    import os
    os.utime(prep_path, (stale_timestamp, stale_timestamp))
    os.utime(optimized_path, (stale_timestamp, stale_timestamp))

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "optimizing"
    assert fake_db.documents[document_id]["status"] == "optimizing"
    assert fake_db.documents[document_id]["optimization_completed_at"] is None


def test_optimization_logs_return_done_when_artifacts_show_completed_but_status_is_stale(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "approved-for-optimization",
        "created_at": created_at,
        "updated_at": created_at,
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\nLNG is a cryogenic fuel.",
                }
            ],
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/optimization/logs")

    assert response.status_code == 200
    assert 'event: done' in response.text
    assert '"status": "optimization-complete"' in response.text


def test_qa_rescore_endpoint_reads_optimized_output_and_overwrites_report(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    validation_payload = {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [],
                "evidence": {
                    "page_number": 1,
                    "text_preview": "What is LNG?",
                    "image_count": 0,
                    "table_count": 0,
                    "has_figures": False,
                },
            }
        ],
    }
    _write_json(work_dir / "sample_document_validation.json", validation_payload)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\n[Source: sample_document, Page 1]\n\n- LNG is a cryogenic fuel.",
                    "table_facts": ["LNG is a cryogenic fuel."],
                }
            ],
        },
    )
    qa_report_path = work_dir / "sample_document_qa_report.json"
    _write_json(qa_report_path, {"decision": "rejected", "metrics": {"overall_confidence_score": 15}})

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"approved", "conditional_approval"}
    assert payload["metrics"]["overall_confidence_score"] == 100.0
    updated_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    assert updated_report["decision"] == payload["decision"]
    assert updated_report["metrics"]["overall_confidence_score"] == 100.0
    assert fake_db.documents[document_id]["status"] == "qa-review"


def test_qa_rescore_uses_structured_table_facts_and_ignores_toc_style_tables(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    validation_payload = {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [],
                "evidence": {
                    "page_number": 1,
                    "text_preview": "What is LNG?",
                    "image_count": 0,
                    "table_count": 1,
                    "has_figures": False,
                },
            }
        ],
    }
    _write_json(work_dir / "sample_document_validation.json", validation_payload)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What does this section explain about CONTENTS?",
                    "content": (
                        "## CONTENTS\n\n"
                        "| Chapter | Page |\n"
                        "| --- | --- |\n"
                        "| Overview | 1 |\n\n"
                        "[Source: sample_document, Page 1]"
                    ),
                    "table_facts": [],
                },
                {
                    "heading": "What does this section explain about LIST OF FIGURES?",
                    "content": (
                        "## LIST OF FIGURES\n\n"
                        "| Figure | Page |\n"
                        "| --- | --- |\n"
                        "| Figure 1 | 5 |\n"
                        "| Table 1 | 7 |\n\n"
                        "[Source: sample_document, Page 2]"
                    ),
                    "table_facts": [],
                },
                {
                    "heading": "What does the table show about LNG properties?",
                    "content": (
                        "## LNG Properties\n\n"
                        "| Parameter | Methane | Ethane |\n"
                        "| --- | --- | --- |\n"
                        "| Molecular Weight | 16 | 30 |\n"
                        "| Specific Gravity | 0.3 | 0.36 |\n\n"
                        "[Source: sample_document, Page 8]"
                    ),
                    "table_facts": [
                        "Molecular Weight: Methane = 16",
                        "Specific Gravity: Methane = 0.3",
                    ],
                },
            ],
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"approved", "conditional_approval"}
    assert payload["metrics"]["table_to_bullets_ratio"] == 100.0
    assert "Table facts extraction: 100.0%" in payload["passed_criteria"]


def test_qa_rescore_clears_stale_critical_image_loss_when_figures_are_described(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    validation_payload = {
        "document_name": "sample_document",
        "overall_confidence": 0.25,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [
                    {
                        "issue_type": "image_loss",
                        "severity": "critical",
                        "description": "Image missing from markdown",
                    }
                ],
                "evidence": {
                    "page_number": 1,
                    "text_preview": "LNG figure.",
                    "image_count": 1,
                    "table_count": 0,
                    "has_figures": True,
                },
            }
        ],
    }
    _write_json(work_dir / "sample_document_validation.json", validation_payload)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What does the figure show?",
                    "content": (
                        "## What does the figure show?\n\n"
                        "**[Figure 1: LNG storage tank schematic with inlet and outlet flow paths.]**\n\n"
                        "[Source: sample_document, Page 1]"
                    ),
                    "table_facts": [],
                }
            ],
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"approved", "conditional_approval"}
    assert payload["metrics"]["critical_issues_count"] == 0
    assert payload["metrics"]["total_issues_count"] == 0
    assert "Critical issues: 0" in payload["passed_criteria"]


def test_qa_rescore_endpoint_rejects_finalized_documents(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "final-approved",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 409
    assert "Cannot rescore document in final-approved status" == response.json()["detail"]


def test_qa_decision_accept_is_blocked_when_current_report_is_rejected(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-review",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_qa_report.json",
        {"decision": "rejected", "metrics": {"overall_confidence_score": 42}},
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 422
    assert "QA criteria currently fail" in response.json()["detail"]


def test_qa_decision_accept_requires_existing_report(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-review",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 422
    assert "QA report not found" in response.json()["detail"]


def test_qa_decision_accept_sets_status_to_qa_passed(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-review",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_qa_report.json",
        {"decision": "approved", "metrics": {"overall_confidence_score": 96}},
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "qa-passed"}


def test_final_approve_is_blocked_until_qa_passes(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(
        f"/api/v1/documents/{document_id}/final-approve",
        json={"decision": "approve"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Final approval requires a QA-passed document"


def test_final_approve_sets_final_approved_after_qa_passes(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-passed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(
        f"/api/v1/documents/{document_id}/final-approve",
        json={"decision": "approve", "notes": "QA complete"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "final-approved"}
    assert fake_db.documents[document_id]["publication_status"] == "pending"
    assert fake_db.documents[document_id]["published_at"] is None


def test_publish_endpoint_blocks_documents_that_are_not_final_approved(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Sample Document",
        "system": "LNG",
        "status": "qa-passed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "uploaded_at": datetime.now(timezone.utc),
        "notes": None,
        "publication_status": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/publish")

    assert response.status_code == 409
    assert response.json()["detail"] == "Only final-approved documents can be published to RAG"


def test_publish_endpoint_indexes_optimized_chunks_and_updates_publication_metadata(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Sample Document",
        "system": "LNG",
        "status": "final-approved",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "uploaded_at": datetime.now(timezone.utc),
        "notes": None,
        "publication_status": "pending",
        "published_at": None,
        "publication_error": None,
        "indexed_chunk_count": None,
        "qdrant_collection": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [
                {
                    "heading": "What is LNG?",
                    "content": "## What is LNG?\n\n[Source: sample_document, Page 7]\n\nLNG is a cryogenic fuel.",
                    "source_pages": [7],
                    "table_facts": ["LNG is a cryogenic fuel."],
                    "ambiguity_flags": ["Verify temperature range against source table"],
                }
            ],
        },
    )

    embedded_texts: list[list[str]] = []
    deleted_documents: list[str] = []
    upsert_calls: list[list[dict[str, Any]]] = []

    async def fake_ensure_collection():
        return True

    async def fake_embed_batch(texts: list[str]):
        embedded_texts.append(texts)
        return [[0.1, 0.2, 0.3]]

    async def fake_delete_document_chunks(doc_id: str):
        deleted_documents.append(doc_id)
        return True

    async def fake_upsert_chunks(chunks: list[dict[str, Any]]):
        upsert_calls.append(chunks)
        return True

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api.QdrantService, "ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(pipeline_api.EmbeddingService, "embed_batch", fake_embed_batch)
    monkeypatch.setattr(pipeline_api.QdrantService, "delete_document_chunks", fake_delete_document_chunks)
    monkeypatch.setattr(pipeline_api.QdrantService, "upsert_chunks", fake_upsert_chunks)

    response = client.post(f"/api/v1/documents/{document_id}/publish")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "final-approved"
    assert payload["publication_status"] == "published"
    assert payload["indexed_chunk_count"] == 1
    assert payload["qdrant_collection"] == pipeline_api.settings.QDRANT_COLLECTION
    assert embedded_texts == [["## What is LNG?\n\n[Source: sample_document, Page 7]\n\nLNG is a cryogenic fuel."]]
    assert deleted_documents == [document_id]
    assert len(upsert_calls) == 1
    stored_chunk = upsert_calls[0][0]
    assert uuid.UUID(str(stored_chunk["id"]))
    assert stored_chunk["payload"]["document_id"] == document_id
    assert stored_chunk["payload"]["document_title"] == "Sample Document"
    assert stored_chunk["payload"]["system"] == "LNG"
    assert stored_chunk["payload"]["chunk_id"] == "chunk_001"
    assert stored_chunk["payload"]["section_heading"] == "What is LNG?"
    assert stored_chunk["payload"]["page_number"] == 7
    assert stored_chunk["payload"]["source_pages"] == [7]
    assert stored_chunk["payload"]["table_facts"] == ["LNG is a cryogenic fuel."]
    assert fake_db.documents[document_id]["publication_status"] == "published"
    assert fake_db.documents[document_id]["indexed_chunk_count"] == 1
    assert fake_db.documents[document_id]["qdrant_collection"] == pipeline_api.settings.QDRANT_COLLECTION
    assert fake_db.documents[document_id]["published_at"] is not None


def test_publish_endpoint_persists_failure_state_when_publication_raises(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Sample Document",
        "system": "LNG",
        "status": "final-approved",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "uploaded_at": datetime.now(timezone.utc),
        "notes": None,
        "publication_status": "pending",
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_rag_optimized.json",
        {
            "document_name": "sample_document",
            "chunks": [{"heading": "What is LNG?", "content": "LNG is a cryogenic fuel."}],
        },
    )

    async def fake_ensure_collection():
        return True

    async def fake_embed_batch(_texts: list[str]):
        raise RuntimeError("embedding service offline")

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api.QdrantService, "ensure_collection", fake_ensure_collection)
    monkeypatch.setattr(pipeline_api.EmbeddingService, "embed_batch", fake_embed_batch)

    response = client.post(f"/api/v1/documents/{document_id}/publish")

    assert response.status_code == 500
    assert "embedding service offline" in response.json()["detail"]
    assert fake_db.documents[document_id]["publication_status"] == "failed"
    assert fake_db.documents[document_id]["publication_error"] == "embedding service offline"
    assert fake_db.documents[document_id]["published_at"] is None
    assert fake_db.documents[document_id]["indexed_chunk_count"] is None


def test_status_and_list_documents_include_publication_fields(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    published_at = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Published Doc",
        "version": "1.0",
        "system": "LNG",
        "document_type": "manual",
        "file_path": "/tmp/published.pdf",
        "status": "final-approved",
        "uploaded_by": str(TEST_USER_ID),
        "notes": None,
        "uploaded_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "total_pages": 30,
        "total_sections": 28,
        "review_progress": 100,
        "qa_score": 100.0,
        "approved_by": str(TEST_USER_ID),
        "approved_at": datetime.now(timezone.utc),
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
        "publication_status": "published",
        "published_at": published_at,
        "publication_error": None,
        "indexed_chunk_count": 28,
        "qdrant_collection": "plantig_documents",
    }

    status_response = client.get(f"/api/v1/documents/{document_id}/status")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["publication_status"] == "published"
    assert status_payload["indexed_chunk_count"] == 28
    assert status_payload["qdrant_collection"] == "plantig_documents"
    assert status_payload["published_at"].startswith(published_at.isoformat().replace("+00:00", ""))

    list_response = client.get("/api/v1/documents")
    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload[0]["publicationStatus"] == "published"
    assert list_payload[0]["indexedChunkCount"] == 28
    assert list_payload[0]["qdrantCollection"] == "plantig_documents"


def test_delete_document_removes_db_vector_and_storage_artifacts(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    pdf_path = tmp_path / f"{document_id}_manual.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 delete test")

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    (work_dir / "sample_document_validation.json").write_text("{}", encoding="utf-8")

    flat_manifest = tmp_path / "sample_document_manifest.json"
    flat_manifest.write_text(
        json.dumps({"document_name": "sample_document", "pdf_path": str(pdf_path)}),
        encoding="utf-8",
    )
    flat_validation = tmp_path / "sample_document_validation.json"
    flat_validation.write_text("{}", encoding="utf-8")
    flat_review_dir = tmp_path / "sample_document_review"
    flat_review_dir.mkdir()

    legacy_dir = tmp_path / "legacy_artifacts" / document_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "qa_report.json").write_text("{}", encoding="utf-8")

    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Cleanup Doc",
        "status": "final-approved",
        "file_path": str(pdf_path),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    deleted_document_ids: list[str] = []

    async def fake_delete_document_chunks(doc_id: str):
        deleted_document_ids.append(doc_id)
        return True

    PipelineService._event_history[document_id] = [{"event": "complete"}]
    PipelineService._job_ids_by_document[document_id] = "job-delete-1"
    pipeline_api.OptimizationLogManager.start(document_id)
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {"timestamp": "2026-03-27T00:00:00Z", "level": "INFO", "message": "cleanup"},
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api.settings, "ARTIFACTS_DIR", str(tmp_path / "legacy_artifacts"))
    monkeypatch.setattr(pipeline_api.QdrantService, "delete_document_chunks", fake_delete_document_chunks)

    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == document_id
    assert payload["qdrant_chunks_deleted"] is True
    assert deleted_document_ids == [document_id]
    assert document_id not in fake_db.documents
    assert pdf_path.exists() is False
    assert work_dir.exists() is False
    assert flat_manifest.exists() is False
    assert flat_validation.exists() is False
    assert flat_review_dir.exists() is False
    assert legacy_dir.exists() is False
    assert document_id not in PipelineService._event_history
    assert document_id not in PipelineService._job_ids_by_document
    assert document_id not in pipeline_api.OptimizationLogManager._buffers


@pytest.mark.parametrize("active_status", ["uploading", "extracting", "vlm-validating", "approved-for-optimization", "optimizing"])
def test_delete_document_blocks_active_pipeline_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    active_status: str,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Active Doc",
        "status": active_status,
        "file_path": "/tmp/active.pdf",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 409
    assert "still running" in response.json()["detail"]


def test_pipeline_websocket_authenticates_and_replies_to_ping(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "admin") if token == "valid-token" else None

    async def fake_check_document_access(_document_id: str, _user_id, _user_role: str) -> bool:
        return True

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_document_access", fake_check_document_access)

    with TestClient(app) as test_client:
        with test_client.websocket_connect("/ws/pipeline/doc-123?token=valid-token") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"
            websocket.send_json({"type": "ping"})
            assert websocket.receive_json() == {"type": "pong"}


def test_pipeline_websocket_rejects_non_admin_users(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "user") if token == "valid-token" else None

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)

    with TestClient(app) as test_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect("/ws/pipeline/doc-123?token=valid-token"):
                pass

        assert exc_info.value.code == 403


def test_chat_websocket_returns_not_implemented_for_query(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "user") if token == "valid-token" else None

    async def fake_check_conversation_access(_conversation_id: str, _user_id) -> bool:
        return True

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_conversation_access", fake_check_conversation_access)

    with TestClient(app) as test_client:
        with test_client.websocket_connect("/ws/chat/conv-123?token=valid-token") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"
            websocket.send_json({"type": "query", "content": "What is LNG density?"})
            error_message = websocket.receive_json()
            assert error_message["type"] == "error"
            assert "not yet implemented" in error_message["error"]


# ---------------------------------------------------------------------------
# State machine: approve-for-optimization — valid entry statuses
# ---------------------------------------------------------------------------

def _setup_optimization_workspace(
    tmp_path: Path,
    document_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Create the minimum workspace artifacts needed for approve-for-optimization."""
    work_dir = tmp_path / document_id
    review_dir = work_dir / "sample_review"
    review_dir.mkdir(parents=True)

    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [],
                "evidence": {"page_number": 1, "text_preview": "LNG.", "image_count": 0, "table_count": 0, "has_figures": False},
            }
        ],
    })
    _write_json(review_dir / "page_review_manifest.json", {
        "document_name": "sample_document",
        "review_unit": "page",
        "total_pages": 1,
        "pages": [{
            "page_id": "page_001",
            "page_number": 1,
            "file": "page_001.md",
            "checklist": "page_001_checklist.json",
            "text_preview": "LNG.",
            "markdown_content": "# What is LNG?",
            "validation_issues": [],
            "evidence": {"page_number": 1, "text_preview": "LNG.", "image_count": 0, "table_count": 0, "has_figures": False},
            "evidence_images": [],
        }],
    })
    (review_dir / "page_001.md").write_text("# What is LNG?\n\n[Source: sample_document, Page 1]", encoding="utf-8")
    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))


@pytest.mark.parametrize("valid_status", ["in-review", "review-complete"])
def test_approve_for_optimization_succeeds_from_valid_pre_optimization_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    valid_status: str,
):
    """Documents in in-review or review-complete may be approved for optimization."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": valid_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }
    _setup_optimization_workspace(tmp_path, document_id, monkeypatch)

    async def fake_execute_optimization_stage(**_kwargs):
        pass

    monkeypatch.setattr(pipeline_api, "_execute_optimization_stage", fake_execute_optimization_stage)

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 200
    assert response.json()["status"] == "approved-for-optimization"
    assert fake_db.documents[document_id]["status"] == "approved-for-optimization"


def test_review_complete_alias_delegates_to_approve_for_optimization(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """POST /review-complete is a compatibility alias and behaves identically."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "review-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }
    _setup_optimization_workspace(tmp_path, document_id, monkeypatch)

    async def fake_execute_optimization_stage(**_kwargs):
        pass

    monkeypatch.setattr(pipeline_api, "_execute_optimization_stage", fake_execute_optimization_stage)

    response = client.post(f"/api/v1/documents/{document_id}/review-complete")

    assert response.status_code == 200
    assert response.json()["status"] == "approved-for-optimization"


# ---------------------------------------------------------------------------
# State machine: approve-for-optimization — blocked from all invalid statuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("blocked_status", [
    "approved-for-optimization",
    "optimizing",
    "optimization-complete",
    "qa-review",
    "qa-passed",
    "final-approved",
    "rejected",
])
def test_approve_for_optimization_blocked_from_invalid_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    blocked_status: str,
):
    """Only validation-complete / in-review / review-complete allow approve-for-optimization."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": blocked_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/approve-for-optimization")

    assert response.status_code == 409, f"Expected 409 from {blocked_status}, got {response.status_code}"


# ---------------------------------------------------------------------------
# QA rescore — artifact fallback and guard scenarios
# ---------------------------------------------------------------------------

def test_qa_rescore_blocked_from_pre_optimization_status(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    """QA rescore is unavailable for documents that have not passed optimization yet."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimizing",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 409
    assert "after optimization" in response.json()["detail"]


def test_qa_rescore_falls_back_to_optimized_markdown_when_json_has_no_chunks(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """qa-rescore reads *_rag_optimized.md when the JSON artifact has no chunks."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [],
                "evidence": {"page_number": 1, "text_preview": "LNG.", "image_count": 0, "table_count": 0, "has_figures": False},
            }
        ],
    })
    # JSON artifact exists but has no chunks — should fall back to markdown
    _write_json(work_dir / "sample_document_rag_optimized.json", {
        "document_name": "sample_document",
        "chunks": None,
    })
    (work_dir / "sample_document_rag_optimized.md").write_text(
        "## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.",
        encoding="utf-8",
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    assert response.json()["metrics"]["overall_confidence_score"] == 100.0


def test_qa_rescore_returns_409_when_no_optimized_output_exists(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """qa-rescore must return 409 when neither *_rag_optimized.json nor .md exist."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [],
    })
    # Intentionally omit any *_rag_optimized.* files

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 409
    assert "Optimization output is incomplete" in response.json()["detail"]


def test_qa_rescore_returns_409_when_optimized_output_is_incomplete(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """qa-rescore must reject skeletal optimized artifacts with no chunks or markdown."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [],
    })
    _write_json(work_dir / "sample_document_rag_optimized.json", {
        "document_name": "sample_document",
        "input_contract": {"primary_source": "optimization_prep"},
    })

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 409
    assert "Optimization output is incomplete" in response.json()["detail"]


def test_qa_rescore_writes_new_qa_report_without_overwriting_legacy_pre_review(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """qa-rescore must create *_qa_report.json instead of mutating legacy pre-review QA."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [{"page_number": 1, "issues": []}],
    })
    _write_json(work_dir / "sample_document_qa_pre_review.json", {
        "decision": "rejected",
        "metrics": {"overall_confidence_score": 15},
    })
    _write_json(work_dir / "sample_document_rag_optimized.json", {
        "document_name": "sample_document",
        "chunks": [
            {
                "heading": "What is LNG?",
                "content": "## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.",
            }
        ],
    })

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    assert json.loads((work_dir / "sample_document_qa_pre_review.json").read_text(encoding="utf-8"))["decision"] == "rejected"
    assert (work_dir / "sample_document_qa_report.json").exists() is True


def test_qa_report_artifact_route_blocks_legacy_pre_review_fallback_after_optimization(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Artifact download must not expose legacy pre-review QA as post-optimization qa_report."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_qa_pre_review.json", {
        "decision": "rejected",
        "metrics": {"overall_confidence_score": 15},
    })

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/artifacts/qa_report")

    assert response.status_code == 409
    assert "Post-optimization QA report not found" in response.json()["detail"]


def test_qa_report_artifact_route_auto_generates_report_when_missing_and_optimized_output_exists(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Artifact download should lazily generate *_qa_report.json for post-optimization docs."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "optimization-complete",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_validation.json", {
        "document_name": "sample_document",
        "overall_confidence": 0.96,
        "page_validations": [{"page_number": 1, "issues": []}],
    })
    _write_json(work_dir / "sample_document_rag_optimized.json", {
        "document_name": "sample_document",
        "chunks": [
            {
                "heading": "What is LNG?",
                "content": "## What is LNG?\n\n[Source: sample_document, Page 1]\n\nLNG is a cryogenic fuel.",
            }
        ],
    })

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get(f"/api/v1/documents/{document_id}/artifacts/qa_report")

    assert response.status_code == 200
    report_payload = json.loads(response.content.decode("utf-8"))
    assert report_payload["document_name"] == "sample_document"
    assert "overall_confidence_score" in report_payload["metrics"]
    assert fake_db.documents[document_id]["status"] == "qa-review"
    assert (work_dir / "sample_document_qa_report.json").exists() is True


def test_execute_optimization_stage_marks_document_failed_when_completed_artifacts_are_incomplete(
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Backend must not persist optimization-complete when Stage 10 writes a skeletal artifact."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "approved-for-optimization",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _write_json(work_dir / "sample_document_validation.json", {"document_name": "sample_document"})
    _write_json(work_dir / "sample_document_manifest.json", {"document_name": "sample_document", "pdf_path": str(pdf_path)})
    (work_dir / "sample_document_optimization_prep.json").write_text("{}", encoding="utf-8")

    class FakeRunner:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_post_approval_reformatting(self, **_kwargs):
            _write_json(work_dir / "sample_document_rag_optimized.json", {
                "document_name": "sample_document",
                "input_contract": {"primary_source": "optimization_prep"},
            })
            return {"status": "complete"}

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr("pipeline.src.cli.hitl_pipeline.HITLPipeline", FakeRunner)
    monkeypatch.setattr(pipeline_api, "AsyncSessionLocal", lambda: _AsyncSessionContext(fake_db))

    asyncio.run(
        pipeline_api._execute_optimization_stage(
            document_id=document_id,
            reviewer=str(TEST_USER_ID),
            work_dir=str(work_dir),
            optimization_prep_path=str(work_dir / "sample_document_optimization_prep.json"),
        )
    )

    assert fake_db.documents[document_id]["status"] == "failed"
    assert "incomplete" in fake_db.documents[document_id]["optimization_error"].lower()


def test_execute_optimization_stage_persists_optimization_complete_for_valid_artifacts(
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Valid optimized artifacts should preserve the optimization-complete lifecycle."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "approved-for-optimization",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    _write_json(work_dir / "sample_document_validation.json", {"document_name": "sample_document"})
    _write_json(work_dir / "sample_document_manifest.json", {"document_name": "sample_document", "pdf_path": str(pdf_path)})
    (work_dir / "sample_document_optimization_prep.json").write_text("{}", encoding="utf-8")

    class FakeRunner:
        def __init__(self, *_args, **_kwargs):
            pass

        def run_post_approval_reformatting(self, **_kwargs):
            _write_json(work_dir / "sample_document_rag_optimized.json", {
                "document_name": "sample_document",
                "chunks": [{"heading": "What is LNG?", "content": "## What is LNG?\n\nLNG is a cryogenic fuel."}],
            })
            return {"status": "complete"}

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr("pipeline.src.cli.hitl_pipeline.HITLPipeline", FakeRunner)
    monkeypatch.setattr("pipeline.src.lineage.lineage_tracker.load_manifest", lambda _path: {"versions": {}})
    monkeypatch.setattr("pipeline.src.lineage.lineage_tracker.update_manifest_timestamp", lambda manifest, *_args: manifest)
    monkeypatch.setattr("pipeline.src.lineage.lineage_tracker.save_manifest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline_api, "AsyncSessionLocal", lambda: _AsyncSessionContext(fake_db))

    asyncio.run(
        pipeline_api._execute_optimization_stage(
            document_id=document_id,
            reviewer=str(TEST_USER_ID),
            work_dir=str(work_dir),
            optimization_prep_path=str(work_dir / "sample_document_optimization_prep.json"),
        )
    )

    assert fake_db.documents[document_id]["status"] == "optimization-complete"
    assert fake_db.documents[document_id]["optimization_error"] is None


# ---------------------------------------------------------------------------
# Artifact priority bug: *_qa_report.json must be preferred over *_qa_pre_review.json
# ---------------------------------------------------------------------------

def test_qa_decision_accept_prefers_qa_report_over_legacy_pre_review_when_both_exist(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """
    Bug regression: *_qa_report.json (current optimisation QA) must take priority
    over *_qa_pre_review.json (legacy pre-optimisation QA) when both are present.

    If the legacy file has decision=approved but the current optimisation QA has
    decision=rejected, the accept guard must block the transition.
    """
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "qa-review",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)

    # Legacy pre-review file: stale "approved" result from pre-optimisation QA
    _write_json(work_dir / "sample_document_qa_pre_review.json", {
        "decision": "approved",
        "metrics": {"overall_confidence_score": 96},
    })
    # Current optimisation QA: says "rejected"
    _write_json(work_dir / "sample_document_qa_report.json", {
        "decision": "rejected",
        "metrics": {"overall_confidence_score": 42},
    })

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    # Must be blocked: current qa_report says rejected
    assert response.status_code == 422, (
        "qa-decision accept must be blocked when *_qa_report.json says rejected, "
        "even if *_qa_pre_review.json says approved"
    )
    assert "QA criteria currently fail" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Status guard: qa-decision must not mutate terminal statuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("terminal_status", ["final-approved", "approved", "rejected"])
def test_qa_decision_reject_blocked_from_terminal_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    terminal_status: str,
):
    """
    qa-decision reject must not be able to overwrite a terminal status.
    final-approved is a locked state and must not transition to rejected.
    """
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": terminal_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "reject"},
    )

    assert response.status_code == 409, (
        f"qa-decision reject must be blocked from {terminal_status} status"
    )
    # Status must remain unchanged
    assert fake_db.documents[document_id]["status"] == terminal_status


@pytest.mark.parametrize("terminal_status", ["final-approved", "approved"])
def test_qa_decision_accept_blocked_from_terminal_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    terminal_status: str,
):
    """qa-decision accept must be blocked for already-finalised documents."""
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": terminal_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(work_dir / "sample_document_qa_report.json", {
        "decision": "approved",
        "metrics": {"overall_confidence_score": 96},
    })
    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 409
    assert fake_db.documents[document_id]["status"] == terminal_status


# ---------------------------------------------------------------------------
# Status guard: final-approve reject must not mutate terminal statuses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("terminal_status", ["final-approved", "approved", "rejected"])
def test_final_approve_reject_blocked_from_terminal_statuses(
    client: TestClient,
    fake_db: FakeAsyncSession,
    terminal_status: str,
):
    """
    final-approve with decision=reject must not overwrite a terminal status.
    Calling reject on an already-final-approved document must return 409.
    """
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": terminal_status,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(
        f"/api/v1/documents/{document_id}/final-approve",
        json={"decision": "reject"},
    )

    assert response.status_code == 409, (
        f"final-approve reject must be blocked from {terminal_status} status"
    )
    assert fake_db.documents[document_id]["status"] == terminal_status


# ---------------------------------------------------------------------------
# Reprocess guard: final-approved is locked without force
# ---------------------------------------------------------------------------

def test_reprocess_blocked_from_final_approved_without_force(
    client: TestClient,
    fake_db: FakeAsyncSession,
    tmp_path: Path,
):
    """Reprocessing a final-approved document without force=True must return 409."""
    document_id = str(uuid.uuid4())
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "final-approved",
        "file_path": str(pdf_path),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess",
        json={"force": False},
    )

    assert response.status_code == 409
    assert "final-approved" in response.json()["detail"]


def test_reprocess_allowed_with_force_from_final_approved(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Reprocessing a final-approved document with force=True must succeed."""
    document_id = str(uuid.uuid4())
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "final-approved",
        "file_path": str(pdf_path),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    async def fake_trigger_pipeline(**_kwargs):
        return "job-reprocess-123"

    monkeypatch.setattr(PipelineService, "trigger_pipeline", fake_trigger_pipeline)

    response = client.post(
        f"/api/v1/documents/{document_id}/reprocess",
        json={"force": True},
    )

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-reprocess-123"