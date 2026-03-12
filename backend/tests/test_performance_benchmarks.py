#!/usr/bin/env python3
"""Performance benchmark tests for T-014 (CRUD + streaming + RAG + WebSocket)."""

from __future__ import annotations

import io
import json
import statistics
import sys
import time
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
import app.api.pipeline as pipeline_api  # noqa: E402
import app.api.websocket as websocket_api  # noqa: E402
import app.services.chat_service as chat_service_module  # noqa: E402
from app.services.pipeline_service import PipelineService  # noqa: E402


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

        raise AssertionError(f"Unexpected SQL in benchmark test double: {statement}")

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


def _stats(samples_ms: list[float]) -> dict[str, float]:
    sorted_samples = sorted(samples_ms)
    p95_index = max(0, min(len(sorted_samples) - 1, int(round(0.95 * len(sorted_samples))) - 1))
    return {
        "count": float(len(samples_ms)),
        "avg_ms": round(statistics.fmean(samples_ms), 3),
        "p50_ms": round(statistics.median(samples_ms), 3),
        "p95_ms": round(sorted_samples[p95_index], 3),
        "max_ms": round(max(samples_ms), 3),
    }


def _run_http_benchmark(name: str, iterations: int, request_func) -> dict[str, float | str]:
    samples: list[float] = []
    start_total = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()
        request_func()
        samples.append((time.perf_counter() - t0) * 1000)
    total_s = time.perf_counter() - start_total

    data = _stats(samples)
    data["name"] = name
    data["throughput_rps"] = round(iterations / total_s, 2)
    return data


def test_t014_performance_benchmark(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    """Run local benchmark for CRUD + streaming + RAG + WebSocket.

    Notes:
    - This is an in-process benchmark using TestClient and test doubles.
    - It is intended for trend/regression tracking, not production capacity planning.
    """

    # --- Arrange test doubles for orchestration dependencies ---
    def fake_get_upload_path(filename: str) -> Path:
        return tmp_path / f"{uuid.uuid4()}_{filename}"

    async def fake_trigger_pipeline(**_kwargs):
        return "job-bench"

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

    async def fake_generate_stream(**_kwargs):
        for token in ["Hello", " ", "operator"]:
            yield token

    async def fake_verify_ws_token(token: str | None):
        return (str(TEST_USER_ID), "reviewer") if token == "valid-token" else None

    async def fake_check_document_access(_document_id: str, _user_id, _user_role: str) -> bool:
        return True

    monkeypatch.setattr(pipeline_api, "get_upload_path", fake_get_upload_path)
    monkeypatch.setattr(PipelineService, "trigger_pipeline", fake_trigger_pipeline)
    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate_stream", fake_generate_stream)
    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_document_access", fake_check_document_access)

    # Seed one status doc
    status_doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake_db.documents[status_doc_id] = {
        "id": status_doc_id,
        "status": "vlm-validating",
        "created_at": now,
        "updated_at": now,
        "notes": None,
    }

    # --- Benchmarks ---
    upload_stats = _run_http_benchmark(
        name="crud_upload_document",
        iterations=30,
        request_func=lambda: (
            lambda r: (
                r.status_code == 200 or (_ for _ in ()).throw(AssertionError(f"upload status={r.status_code}"))
            )
        )(
            client.post(
                "/api/v1/documents/upload",
                data={"title": "Plant Manual", "version": "1.0", "system": "LNG", "document_type": "procedure"},
                files={"file": ("manual.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
            )
        ),
    )

    status_stats = _run_http_benchmark(
        name="crud_get_document_status",
        iterations=200,
        request_func=lambda: (
            lambda r: (
                r.status_code == 200 or (_ for _ in ()).throw(AssertionError(f"status status={r.status_code}"))
            )
        )(
            client.get(f"/api/v1/documents/{status_doc_id}/status")
        ),
    )

    rag_stats = _run_http_benchmark(
        name="rag_chat_query",
        iterations=120,
        request_func=lambda: (
            lambda r: (
                r.status_code == 200 or (_ for _ in ()).throw(AssertionError(f"rag status={r.status_code}"))
            )
        )(
            client.post("/api/v1/chat/query", json={"request": {"query": "What is LNG density?"}})
        ),
    )

    def _stream_request() -> None:
        with client.stream("POST", "/api/v1/chat/stream", json={"request": {"query": "Stream answer"}}) as response:
            body = "".join(response.iter_text())
            if response.status_code != 200 or "data: [DONE]" not in body:
                raise AssertionError("stream status/body invalid")

    stream_stats = _run_http_benchmark(
        name="stream_chat_sse",
        iterations=100,
        request_func=_stream_request,
    )

    ws_samples_ms: list[float] = []
    with TestClient(app) as ws_client:
        with ws_client.websocket_connect("/ws/pipeline/doc-123?token=valid-token") as websocket:
            connected = websocket.receive_json()
            assert connected["type"] == "connected"
            ws_start_total = time.perf_counter()
            for _ in range(300):
                t0 = time.perf_counter()
                websocket.send_json({"type": "ping"})
                pong = websocket.receive_json()
                assert pong == {"type": "pong"}
                ws_samples_ms.append((time.perf_counter() - t0) * 1000)
            ws_total = time.perf_counter() - ws_start_total

    websocket_stats = _stats(ws_samples_ms)
    websocket_stats["name"] = "websocket_ping_pong"
    websocket_stats["throughput_rps"] = round(300 / ws_total, 2)

    results = {
        "benchmarks": [upload_stats, status_stats, rag_stats, stream_stats, websocket_stats],
        "targets": {
            "api_p95_ms_lt": 200,
            "rag_p95_ms_lt": 2000,
            "websocket_avg_ms_lt": 50,
        },
        "pass_fail": {
            "crud_upload_document": upload_stats["p95_ms"] < 200,
            "crud_get_document_status": status_stats["p95_ms"] < 200,
            "rag_chat_query": rag_stats["p95_ms"] < 2000,
            "stream_chat_sse": stream_stats["p95_ms"] < 2000,
            "websocket_ping_pong": websocket_stats["avg_ms"] < 50,
        },
    }

    # Emit machine-readable evidence in test output
    print("T014_BENCHMARK_RESULTS=" + json.dumps(results, sort_keys=True))

    # Keep benchmark test informative (non-gating) and ensure benchmark executed.
    assert len(results["benchmarks"]) == 5
