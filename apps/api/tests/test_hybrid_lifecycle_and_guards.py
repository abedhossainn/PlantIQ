#!/usr/bin/env python3
"""Split from former monolithic hybrid integration suite."""

from __future__ import annotations

from tests._hybrid_support import *  # noqa: F401,F403

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


def test_delete_document_allows_stale_optimizing_status_without_active_optimization(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    stale_updated_at = datetime.now(timezone.utc).replace(year=max(2000, datetime.now(timezone.utc).year - 1))
    pdf_path = tmp_path / f"{document_id}_stale_optimization.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 stale optimization")

    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Stale Optimizing Doc",
        "status": "optimizing",
        "file_path": str(pdf_path),
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
        "uploaded_at": stale_updated_at,
        "notes": None,
    }

    async def fake_delete_document_chunks(_doc_id: str):
        return True

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline_api.settings, "ARTIFACTS_DIR", str(tmp_path / "legacy_artifacts"))
    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_STALLED_GRACE_SECONDS", 1)
    monkeypatch.setattr(pipeline_api.QdrantService, "delete_document_chunks", fake_delete_document_chunks)
    monkeypatch.setattr(PipelineService, "_job_ids_by_document", {})
    monkeypatch.setattr(PipelineService, "_active_processes", {})
    pipeline_api.OptimizationLogManager.clear_document(document_id)

    response = client.delete(f"/api/v1/documents/{document_id}")

    assert response.status_code == 200
    assert document_id not in fake_db.documents


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
            with test_client.websocket_connect("/ws/pipeline/doc-123?token=valid-token") as websocket:
                websocket.receive_json()

        assert exc_info.value.code == 403


def test_pipeline_websocket_allows_plantig_admin_role(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "plantig_admin") if token == "valid-token" else None

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


def test_chat_websocket_rejects_when_conversation_access_check_fails(monkeypatch: pytest.MonkeyPatch):
    async def fake_verify_ws_token(token: str | None):
        return (TEST_USER_ID, "plantig_user") if token == "valid-token" else None

    async def fake_check_conversation_access(_conversation_id: str, _user_id) -> bool:
        return False

    monkeypatch.setattr(websocket_api, "verify_ws_token", fake_verify_ws_token)
    monkeypatch.setattr(websocket_api, "check_conversation_access", fake_check_conversation_access)

    with TestClient(app) as test_client:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            with test_client.websocket_connect("/ws/chat/conv-123?token=valid-token") as websocket:
                websocket.receive_json()

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
        return None

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
        return None

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
            self._initialized = True

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
            self._initialized = True

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