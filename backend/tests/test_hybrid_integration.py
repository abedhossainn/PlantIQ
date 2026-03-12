#!/usr/bin/env python3
"""Hybrid integration tests for FastAPI orchestration and websocket contracts."""

from __future__ import annotations

import io
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest

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


class FakeResult:
    def __init__(self, row: Any = None):
        self._row = row

    def fetchone(self):
        return self._row


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

        if "insert into conversations" in sql:
            self.conversations[str(params["id"])] = {
                "id": str(params["id"]),
                "user_id": str(params["user_id"]),
                "title": params["title"],
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
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
                "created_at": now,
                "updated_at": now,
            }
            return FakeResult(None)

        if "update documents" in sql:
            document_id = str(params.get("doc_id") or params.get("id"))
            document = self.documents[document_id]

            if "status = 'extracting'" in sql:
                document["status"] = "extracting"
            else:
                document["status"] = params["status"]
                if "notes" in params:
                    document["notes"] = params["notes"]
            document["updated_at"] = datetime.now(timezone.utc)
            return FakeResult(None)

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
        json={"request": {"query": "What is LNG density?"}},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "LNG density is approximately 450 kg/m³ at atmospheric pressure."
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["document_title"] == "LNG Manual"
    assert len(fake_db.conversations) == 1
    assert [message["role"] for message in fake_db.chat_messages] == ["user", "assistant"]


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

    with client.stream("POST", "/api/v1/chat/stream", json={"request": {"query": "Stream answer"}}) as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "data: Hello" in body
    assert "data:  " in body
    assert "data: operator" in body
    assert "data: [DONE]" in body
    assert fake_db.chat_messages[-1]["content"] == "Hello operator"


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
    assert payload["current_stage"] == "vlm-validation"


def test_artifact_download_returns_file_response(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    artifact_path = tmp_path / "validation.json"
    artifact_path.write_text('{"status":"ok"}', encoding="utf-8")

    async def fake_get_artifact(**_kwargs):
        return artifact_path

    monkeypatch.setattr(PipelineService, "get_artifact", fake_get_artifact)

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/artifacts/validation")

    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'


def test_pipeline_websocket_authenticates_and_replies_to_ping(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "reviewer") if token == "valid-token" else None

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


def test_chat_websocket_returns_not_implemented_for_query(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "reviewer") if token == "valid-token" else None

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