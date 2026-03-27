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
    def __init__(self, row: Any = None):
        self._row = row

    def first(self):
        return self._row

    def all(self):
        if self._row is None:
            return []
        return [self._row]


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
                "qa_score": None,
                "optimization_started_at": None,
                "optimization_completed_at": None,
                "optimization_error": None,
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
                document["status"] = params.get("status") or params.get("new_status")
                if "notes" in params:
                    document["notes"] = params["notes"]
                if "qa_score" in params:
                    document["qa_score"] = params["qa_score"]
                if "optimization_error" in params:
                    document["optimization_error"] = params["optimization_error"]
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
                if "qa_score = null" in sql:
                    document["qa_score"] = None
                if "optimization_error = null" in sql:
                    document["optimization_error"] = None
            document["updated_at"] = datetime.now(timezone.utc)
            return FakeResult(None)

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
                )
            )

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