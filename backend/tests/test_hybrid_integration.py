#!/usr/bin/env python3
"""Hybrid integration tests for FastAPI orchestration, SSE, and websocket contracts."""

from __future__ import annotations

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


class FakeResult:
    def __init__(self, row: Any = None):
        self._row = row

    def fetchone(self):
        return self._row

    def first(self):
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
                document["status"] = params.get("status") or params.get("new_status")
                if "notes" in params:
                    document["notes"] = params["notes"]
            document["updated_at"] = datetime.now(timezone.utc)
            return FakeResult(None)

        if "select status from documents where id = :doc_id" in sql:
            document = self.documents.get(str(params["doc_id"]))
            if not document:
                return FakeResult(None)
            return FakeResult((document["status"],))

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

    with client.stream("POST", "/api/v1/chat/stream", json={"request": {"query": "Stream answer"}}) as response:
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


def test_artifact_download_returns_file_response(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    artifact_path = tmp_path / "validation.json"
    artifact_path.write_text('{"status":"ok"}', encoding="utf-8")

    async def fake_get_artifact(**_kwargs):
        return artifact_path

    monkeypatch.setattr(PipelineService, "get_artifact", fake_get_artifact)

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/artifacts/validation")

    assert response.status_code == 200
    assert response.content == b'{"status":"ok"}'


def test_qa_rescore_endpoint_recomputes_and_overwrites_existing_report(
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
    qa_report_path = work_dir / "sample_document_qa_pre_review.json"
    _write_json(qa_report_path, {"decision": "rejected", "metrics": {"overall_confidence_score": 15}})

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
                    "validation_issues": [],
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

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] in {"approved", "conditional_approval"}
    assert payload["metrics"]["overall_confidence_score"] == 96.0
    updated_report = json.loads(qa_report_path.read_text(encoding="utf-8"))
    assert updated_report["decision"] == payload["decision"]
    assert updated_report["metrics"]["overall_confidence_score"] == 96.0


def test_qa_rescore_endpoint_rejects_finalized_documents(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "approved",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
    }

    response = client.post(f"/api/v1/documents/{document_id}/qa-rescore")

    assert response.status_code == 409
    assert "Cannot rescore document in approved status" == response.json()["detail"]


def test_qa_decision_accept_is_blocked_when_current_report_is_rejected(
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
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    _write_json(
        work_dir / "sample_document_qa_pre_review.json",
        {"decision": "rejected", "metrics": {"overall_confidence_score": 42}},
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 422
    assert "QA criteria currently fail" in response.json()["detail"]


def test_qa_decision_accept_allows_missing_report(
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
    }

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.post(
        f"/api/v1/documents/{document_id}/qa-decision",
        json={"decision": "accept"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "in-review"}


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