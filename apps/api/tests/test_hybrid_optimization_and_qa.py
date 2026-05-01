#!/usr/bin/env python3
"""Split from former monolithic hybrid integration suite."""

from __future__ import annotations

from tests._hybrid_support import *  # noqa: F401,F403

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


def test_optimization_logs_replay_failed_terminal_status(client: TestClient, fake_db: FakeAsyncSession):
    document_id = str(uuid.uuid4())
    fake_db.documents[document_id] = {
        "id": document_id,
        "status": "failed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "notes": None,
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
        "publication_status": None,
        "published_at": None,
        "publication_error": None,
        "indexed_chunk_count": None,
        "qdrant_collection": None,
    }
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


def test_optimization_logs_emit_structured_progress_events_for_segment_generation(
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
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
        "publication_status": None,
        "published_at": None,
        "publication_error": None,
        "indexed_chunk_count": None,
        "qdrant_collection": None,
    }

    pipeline_api.OptimizationLogManager.start(document_id)
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-04-11T01:00:00Z",
            "level": "INFO",
            "message": "Prepare generation request (chars=17452, segment=segment 2/5 chars)",
        },
    )
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-04-11T01:00:05Z",
            "level": "INFO",
            "message": "Generate output: 58% (4717/8000 tokens, 01:21 elapsed)",
        },
    )
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-04-11T01:00:11Z",
            "level": "INFO",
            "message": "Generation complete for segment 2/5 (8000 tokens in 86.7s)",
        },
    )
    pipeline_api.OptimizationLogManager.close(document_id, "optimization-complete")

    response = client.get(f"/api/v1/documents/{document_id}/optimization/logs")

    assert response.status_code == 200
    parsed_events = _parse_sse_events(response.text)
    progress_events = [payload for event_name, payload in parsed_events if event_name == "progress"]
    assert len(progress_events) >= 1

    first_progress = progress_events[0]
    assert first_progress["event"] == "progress"
    assert first_progress["document_id"] == document_id
    assert first_progress["phase"] == "segment-generation"
    assert first_progress["current_segment"] == 2
    assert first_progress["total_segments"] == 5
    assert first_progress["segment_progress_percent"] == 100
    assert first_progress["overall_progress_percent"] == 40
    assert first_progress["tokens_generated"] == 8000
    assert first_progress["tokens_target"] == 8000
    assert first_progress["elapsed_seconds"] == 87
    assert first_progress["label"] == "Segment 2/5"

    done_events = [payload for event_name, payload in parsed_events if event_name == "done"]
    assert done_events == [{"event": "done", "status": "optimization-complete"}]


def test_optimization_progress_fields_are_clamped_and_replayed_to_new_subscribers(
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
        "optimization_started_at": None,
        "optimization_completed_at": None,
        "optimization_error": None,
        "publication_status": None,
        "published_at": None,
        "publication_error": None,
        "indexed_chunk_count": None,
        "qdrant_collection": None,
    }

    pipeline_api.OptimizationLogManager.start(document_id)
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-04-11T02:10:00Z",
            "level": "INFO",
            "message": "Prepare generation request (chars=1000, segment=segment 12/8 chars)",
        },
    )
    pipeline_api.OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": "2026-04-11T02:10:03Z",
            "level": "INFO",
            "message": "Generate output: 140% (9000/8000 tokens, 10:70 elapsed)",
        },
    )
    pipeline_api.OptimizationLogManager.close(document_id, "optimization-complete")

    response = client.get(f"/api/v1/documents/{document_id}/optimization/logs")
    assert response.status_code == 200

    parsed_events = _parse_sse_events(response.text)
    progress_events = [payload for event_name, payload in parsed_events if event_name == "progress"]
    assert progress_events

    snapshot = progress_events[0]
    assert snapshot["current_segment"] == 12
    assert snapshot["total_segments"] == 8
    assert snapshot["segment_progress_percent"] == 100
    assert snapshot["overall_progress_percent"] == 100
    assert snapshot["tokens_generated"] == 9000
    assert snapshot["tokens_target"] == 8000
    assert snapshot["elapsed_seconds"] == 670
    assert snapshot["label"] == "Segment 12/8"

    done_events = [payload for event_name, payload in parsed_events if event_name == "done"]
    assert done_events == [{"event": "done", "status": "optimization-complete"}]


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


