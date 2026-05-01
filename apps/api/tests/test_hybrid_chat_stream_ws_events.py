#!/usr/bin/env python3
"""Split from former monolithic hybrid integration suite."""

from __future__ import annotations

from tests._hybrid_support import *  # noqa: F401,F403

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
    assert "no-cache" in response.headers["cache-control"]
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
                content=COMMON_TEXT_LNG_CRYOGENIC,
                document_id=uuid.uuid4(),
                document_title=COMMON_TITLE_OPERATIONS_GUIDE,
                metadata={"page_number": 3},
                score=0.91,
            )
        ]

    async def fake_generate_stream(**_kwargs):
        if _kwargs.get("emit_tokens"):
            yield "unused"
        return

    async def fake_generate(**_kwargs):
        return COMMON_TEXT_METHANE_BOILING_POINT

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
    assert token_events[-1]["token"] == COMMON_TEXT_METHANE_BOILING_POINT
    assert fake_db.chat_messages[-1]["content"] == COMMON_TEXT_METHANE_BOILING_POINT
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


def test_chat_websocket_query_returns_explicit_unsupported_operation_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_verify_ws_token(_token: str | None):
        return TEST_USER_ID, "user"

    async def fake_check_conversation_access(_conversation_id: str, _user_id: uuid.UUID):
        return True

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_conversation_access", fake_check_conversation_access)

    conversation_id = str(uuid.uuid4())
    with client.websocket_connect(f"/ws/chat/{conversation_id}?token=test-token") as websocket:
        connected_event = websocket.receive_json()
        assert connected_event["type"] == "connected"

        websocket.send_json({"type": "query", "content": "What is LNG density?"})
        error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "error": "Query processing via WebSocket is not yet implemented. Use POST /api/v1/chat/stream instead.",
        "operation": "query",
    }


def test_chat_websocket_cancel_returns_explicit_unsupported_operation_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_verify_ws_token(_token: str | None):
        return TEST_USER_ID, "user"

    async def fake_check_conversation_access(_conversation_id: str, _user_id: uuid.UUID):
        return True

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_conversation_access", fake_check_conversation_access)

    conversation_id = str(uuid.uuid4())
    with client.websocket_connect(f"/ws/chat/{conversation_id}?token=test-token") as websocket:
        connected_event = websocket.receive_json()
        assert connected_event["type"] == "connected"

        websocket.send_json({"type": "cancel"})
        error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "error": "Generation cancellation via WebSocket is not supported for this endpoint.",
        "operation": "cancel",
    }


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
    assert "no-cache" in response.headers["cache-control"]
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

