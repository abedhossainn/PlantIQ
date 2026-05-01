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
from app.core.security import get_jwt_payload  # noqa: E402
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

CHECKLIST_LABELS = {
    "question_headings": "Headings are questions",
    "table_facts_extracted": "Table facts extracted to bullets",
    "figure_descriptions": "Figures have text descriptions",
    "citations_present": "Source citations included",
    "no_hallucinations": "No AI-generated content",
    "rag_optimized": "Follows RAG guidelines",
}
SSE_EVENT_PREFIX = "event: "
SSE_DATA_PREFIX = "data: "
CHAT_QUERY_ENDPOINT = "/api/v1/chat/query"
CHAT_STREAM_ENDPOINT = "/api/v1/chat/stream"
DOCS_ENDPOINT = "/api/v1/documents"
COMMON_QUERY_LNG_DENSITY = "What is LNG density?"
COMMON_QUERY_WHAT_IS_LNG = "What is LNG?"
COMMON_TEXT_LNG_CRYOGENIC = "LNG is a cryogenic fuel."
COMMON_TITLE_OPERATIONS_GUIDE = "Operations Guide"
COMMON_TEXT_METHANE_BOILING_POINT = "The boiling point of methane is -259.6°F."
SAMPLE_DOC_TITLE = "Sample Document"
SAMPLE_OPTIMIZED_JSON = "sample_document_rag_optimized.json"
SAMPLE_VALIDATION_JSON = "sample_document_validation.json"
SAMPLE_QA_REPORT_JSON = "sample_document_qa_report.json"
SAMPLE_QA_PRE_REVIEW_JSON = "sample_document_qa_pre_review.json"
PAGE_REVIEW_MANIFEST_JSON = "page_review_manifest.json"
PAGE_001_MD = "page_001.md"
PAGE_001_CHECKLIST_JSON = "page_001_checklist.json"


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
        self.user_scope_policies: dict[str, list[dict[str, Any]]] = {}
        self.access_audit_logs: list[dict[str, Any]] = []

    async def execute(self, statement, params=None):
        sql = str(statement).lower()
        params = params or {}

        if "select id from conversations" in sql:
            conversation = self.conversations.get(str(params["conv_id"]))
            if conversation and conversation["user_id"] == str(params["user_id"]):
                return FakeResult((conversation["id"],))
            return FakeResult(None)

        if "from user_scope_policies" in sql:
            policies = self.user_scope_policies.get(str(params["user_id"]), [])
            return FakeResult(list(policies))

        if "insert into access_audit_logs" in sql:
            self.access_audit_logs.append(dict(params))
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
                if "tp" in params and document.get("total_pages") is None:
                    document["total_pages"] = params["tp"]
                if "ts" in params and document.get("total_sections") is None:
                    document["total_sections"] = params["ts"]
                if "qs" in params and document.get("qa_score") is None:
                    document["qa_score"] = params["qs"]
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
                    "updated_at": document.get("updated_at"),
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
        "question_headings": {"item": CHECKLIST_LABELS["question_headings"], "checked": True, "notes": None},
        "table_facts_extracted": {"item": CHECKLIST_LABELS["table_facts_extracted"], "checked": True, "notes": None},
        "figure_descriptions": {"item": CHECKLIST_LABELS["figure_descriptions"], "checked": True, "notes": None},
        "citations_present": {"item": CHECKLIST_LABELS["citations_present"], "checked": True, "notes": None},
        "no_hallucinations": {"item": CHECKLIST_LABELS["no_hallucinations"], "checked": True, "notes": None},
        "rag_optimized": {"item": CHECKLIST_LABELS["rag_optimized"], "checked": True, "notes": None},
    }
    _write_json(path, checklist)


def _write_empty_checklist(path: Path) -> None:
    checklist = {
        "question_headings": {"item": CHECKLIST_LABELS["question_headings"], "checked": False, "notes": None},
        "table_facts_extracted": {"item": CHECKLIST_LABELS["table_facts_extracted"], "checked": False, "notes": None},
        "figure_descriptions": {"item": CHECKLIST_LABELS["figure_descriptions"], "checked": False, "notes": None},
        "citations_present": {"item": CHECKLIST_LABELS["citations_present"], "checked": False, "notes": None},
        "no_hallucinations": {"item": CHECKLIST_LABELS["no_hallucinations"], "checked": False, "notes": None},
        "rag_optimized": {"item": CHECKLIST_LABELS["rag_optimized"], "checked": False, "notes": None},
    }
    _write_json(path, checklist)


def _parse_sse_events(body: str) -> list[tuple[str, dict[str, Any]]]:
    parsed_events: list[tuple[str, dict[str, Any]]] = []
    for raw_event in [chunk for chunk in body.split("\n\n") if chunk.strip()]:
        event_name: str | None = None
        payload: dict[str, Any] | None = None
        for line in raw_event.splitlines():
            if line.startswith(SSE_EVENT_PREFIX):
                event_name = line[7:]
            elif line.startswith(SSE_DATA_PREFIX):
                payload = json.loads(line[6:])
        if event_name is not None and payload is not None:
            parsed_events.append((event_name, payload))
    return parsed_events


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


# Export all shared symbols (including underscore-prefixed helpers) for split test modules.
__all__ = [name for name in globals() if not name.startswith("__")]


