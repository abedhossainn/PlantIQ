#!/usr/bin/env python3
"""Split from former monolithic hybrid integration suite."""

from __future__ import annotations

from tests._hybrid_support import *  # noqa: F401,F403

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


def test_openapi_request_contract_does_not_expose_jwt_claims_in_request_body():
    """Regression guard: get_db JWT claims must never appear as a client body field."""
    schema = app.openapi()

    reprocess_operation = schema["paths"]["/api/v1/documents/{document_id}/reprocess"]["post"]
    reprocess_body_json = json.dumps(reprocess_operation.get("requestBody", {}))
    assert "jwt_claims" not in reprocess_body_json

    chat_query_operation = schema["paths"]["/api/v1/chat/query"]["post"]
    chat_query_body_json = json.dumps(chat_query_operation.get("requestBody", {}))
    assert "jwt_claims" not in chat_query_body_json


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


def test_list_documents_marks_stale_optimizing_without_active_optimization_as_failed(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    stale_document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale_updated_at = now.replace(year=max(2000, now.year - 1))
    fake_db.documents[stale_document_id] = {
        "id": stale_document_id,
        "title": "Stale Optimizing",
        "version": "1.0",
        "system": "Liquefaction",
        "document_type": "Technical Standard",
        "status": "optimizing",
        "file_path": "/tmp/stale-opt.pdf",
        "uploaded_by": str(TEST_USER_ID),
        "notes": None,
        "uploaded_at": stale_updated_at,
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
        "optimization_started_at": stale_updated_at,
        "optimization_completed_at": None,
        "optimization_error": None,
    }

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_STALLED_GRACE_SECONDS", 1)
    monkeypatch.setattr(PipelineService, "_job_ids_by_document", {})
    monkeypatch.setattr(PipelineService, "_active_processes", {})
    pipeline_api.OptimizationLogManager.clear_document(stale_document_id)

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    stale_row = next(item for item in payload if item["id"] == stale_document_id)
    assert stale_row["status"] == "failed"
    assert "optimization appears to have stopped unexpectedly" in stale_row["notes"].lower()
    assert fake_db.documents[stale_document_id]["status"] == "failed"


def test_list_documents_reconciles_stale_optimizing_to_optimization_complete_when_artifacts_exist(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    stale_updated_at = now.replace(year=max(2000, now.year - 1))
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": "Reconcilable Optimizing",
        "version": "1.0",
        "system": "Liquefaction",
        "document_type": "Technical Standard",
        "status": "optimizing",
        "file_path": "/tmp/recon-opt.pdf",
        "uploaded_by": str(TEST_USER_ID),
        "notes": None,
        "uploaded_at": stale_updated_at,
        "created_at": stale_updated_at,
        "updated_at": stale_updated_at,
        "optimization_started_at": stale_updated_at,
        "optimization_completed_at": None,
        "optimization_error": "previous timeout",
    }

    work_dir = tmp_path / document_id
    work_dir.mkdir(parents=True)
    optimized_path = work_dir / "sample_document_rag_optimized.json"
    _write_json(
        optimized_path,
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
    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_STALLED_GRACE_SECONDS", 1)
    monkeypatch.setattr(PipelineService, "_job_ids_by_document", {})
    monkeypatch.setattr(PipelineService, "_active_processes", {})
    pipeline_api.OptimizationLogManager.clear_document(document_id)

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    row = next(item for item in payload if item["id"] == document_id)
    assert row["status"] == "optimization-complete"
    assert fake_db.documents[document_id]["status"] == "optimization-complete"
    assert fake_db.documents[document_id]["optimization_error"] is None


def test_list_documents_enriches_metadata_from_nested_artifact_directories(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    document_id = str(uuid.uuid4())
    document_title = "COMMON Module 4 Electrical Distribution System"
    now = datetime.now(timezone.utc)
    fake_db.documents[document_id] = {
        "id": document_id,
        "title": document_title,
        "version": "1.0",
        "system": "Electrical",
        "document_type": "Technical Standard",
        "status": "final-approved",
        "file_path": "/tmp/common-module-4.pdf",
        "uploaded_by": str(TEST_USER_ID),
        "notes": None,
        "uploaded_at": now,
        "created_at": now,
        "updated_at": now,
        "total_pages": None,
        "total_sections": None,
        "review_progress": 100,
        "qa_score": None,
        "approved_by": TEST_USER_ID,
        "approved_at": now,
        "publication_status": "pending",
        "published_at": None,
        "publication_error": None,
        "indexed_chunk_count": None,
        "qdrant_collection": None,
    }

    nested_artifact_dir = tmp_path / document_id
    nested_artifact_dir.mkdir(parents=True)
    artifact_stem = f"{document_id}_{document_title}"
    _write_json(
        nested_artifact_dir / f"{artifact_stem}_manifest.json",
        {
            "document_name": document_title,
            "pdf_page_count": 124,
        },
    )
    _write_json(
        nested_artifact_dir / f"{artifact_stem}_pipeline_results.json",
        {
            "document": document_title,
            "stages": {
                "review_workspace": {
                    "total_sections": 51,
                }
            },
        },
    )
    _write_json(
        nested_artifact_dir / f"{artifact_stem}_qa_report.json",
        {
            "document_name": document_title,
            "metrics": {
                "overall_confidence_score": 96.5,
            },
        },
    )

    monkeypatch.setattr(pipeline_api.settings, "PIPELINE_WORK_DIR", str(tmp_path))

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    payload = response.json()
    document_row = next(item for item in payload if item["id"] == document_id)
    assert document_row["totalPages"] == 124
    assert document_row["totalSections"] == 51
    assert document_row["qaScore"] == 96.5
    assert fake_db.documents[document_id]["total_pages"] == 124
    assert fake_db.documents[document_id]["total_sections"] == 51
    assert fake_db.documents[document_id]["qa_score"] == 96.5


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

