#!/usr/bin/env python3
"""Split from former monolithic hybrid integration suite."""

from __future__ import annotations

from tests._hybrid_support import *  # noqa: F401,F403

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
        CHAT_QUERY_ENDPOINT,
        json={"query": COMMON_QUERY_LNG_DENSITY},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content"] == "LNG density is approximately 450 kg/m³ at atmospheric pressure."
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["document_title"] == "LNG Manual"
    assert len(fake_db.conversations) == 1
    assert [message["role"] for message in fake_db.chat_messages] == ["user", "assistant"]


def test_chat_query_applies_workspace_scope_and_ignores_document_type_filters(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Candidate 5: document_type_filters sent in request are accepted but ignored.
    Retrieval uses workspace (system/area) scope only; document_type_filter is None.
    """
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
        CHAT_QUERY_ENDPOINT,
        json={
            "query": "How do I start up liquefaction after pre-treatment checks?",
            "workspace": "Liquefaction",
            "document_type_filters": ["Procedure"],  # accepted but ignored (Candidate 5)
            "preferred_document_types": ["Procedure"],  # accepted but ignored (Candidate 5)
            "include_shared_documents": True,
        },
    )

    assert response.status_code == 200
    assert captured["workspace_filter"] == "Liquefaction"
    # Candidate 5: document_type_filter is always None regardless of request value
    assert captured["document_type_filter"] is None
    assert captured["include_shared_documents"] is True


def test_chat_query_document_type_preference_no_longer_reorders_contexts(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    """Candidate 5: preferred_document_types sent in request is accepted but ignored.
    Context order is determined by raw similarity score only (no doc-type boost).
    """
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
            "preferred_document_types": ["Procedure"],  # accepted but ignored (Candidate 5)
        },
    )

    assert response.status_code == 200
    payload = response.json()
    # Candidate 5 remains true (document_type preference ignored), but Candidate 4
    # hybrid lexical+dense fusion can reorder by query-term lexical relevance.
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
    # Candidate 5: document_type removed from active scope; persisted as None
    assert saved_conversation["document_type_filters"] is None
    assert saved_conversation["preferred_document_types"] is None
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
    # Candidate 5: document_type removed from active scope; persisted as None
    assert updated_conversation["document_type_filters"] is None
    assert updated_conversation["preferred_document_types"] is None
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
    # Candidate 5: persisted document_type scope is not restored; filter is None
    assert captured["document_type_filter"] is None
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


def test_chat_query_denies_workspace_outside_authorized_scope(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    async def override_get_jwt_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": ["chat.read"]}

    fake_db.user_scope_policies[str(TEST_USER_ID)] = [
        {"system_scope": "liquefaction", "area_scope": "liquefaction"}
    ]
    app.dependency_overrides[get_jwt_payload] = override_get_jwt_payload

    try:
        response = client.post(
            CHAT_QUERY_ENDPOINT,
            json={
                "query": "Show me electrical distribution interlock rules",
                "workspace": "Electrical",
            },
        )
    finally:
        app.dependency_overrides.pop(get_jwt_payload, None)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "SCOPE_ACCESS_DENIED"
    assert detail["reason_code"] == "AREA_SCOPE_DENIED"
    assert fake_db.access_audit_logs
    assert fake_db.access_audit_logs[-1]["action"] == "chat.retrieve"


def test_chat_query_filters_out_of_scope_contexts_from_citations(
    client: TestClient,
    fake_db: FakeAsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    async def override_get_jwt_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": ["chat.read"]}

    fake_db.user_scope_policies[str(TEST_USER_ID)] = [
        {"system_scope": "liquefaction", "area_scope": "liquefaction"}
    ]

    async def fake_embed_query(_query: str):
        return [0.1, 0.2, 0.3]

    async def fake_search_similar(**_kwargs):
        return [
            RAGContext(
                chunk_id="chunk-in-scope",
                content="Liquefaction startup checklists require valve alignment verification.",
                document_id=uuid.uuid4(),
                document_title="Liquefaction SOP",
                metadata={"page_number": 4, "system": "Liquefaction", "workspace": "Liquefaction"},
                score=0.95,
            ),
            RAGContext(
                chunk_id="chunk-out-of-scope",
                content="Electrical breaker sequencing applies to high-voltage panels.",
                document_id=uuid.uuid4(),
                document_title="Electrical Distribution Guide",
                metadata={"page_number": 9, "system": "Electrical", "workspace": "Electrical"},
                score=0.99,
            ),
        ]

    async def fake_generate(**_kwargs):
        return "Liquefaction startup requires valve alignment verification."

    monkeypatch.setattr(chat_service_module.EmbeddingService, "embed_query", fake_embed_query)
    monkeypatch.setattr(chat_service_module.QdrantService, "search_similar", fake_search_similar)
    monkeypatch.setattr(chat_service_module.VLLMService, "generate", fake_generate)

    app.dependency_overrides[get_jwt_payload] = override_get_jwt_payload
    try:
        response = client.post(
            CHAT_QUERY_ENDPOINT,
            json={
                "query": "What should I verify before liquefaction startup?",
                "workspace": "Liquefaction",
            },
        )
    finally:
        app.dependency_overrides.pop(get_jwt_payload, None)

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["citations"]) == 1
    assert payload["citations"][0]["document_title"] == "Liquefaction SOP"


def test_upload_document_denies_system_outside_authorized_scope(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    async def override_get_jwt_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": ["chat.read"]}

    fake_db.user_scope_policies[str(TEST_USER_ID)] = [
        {"system_scope": "liquefaction", "area_scope": "liquefaction"}
    ]
    app.dependency_overrides[get_jwt_payload] = override_get_jwt_payload

    try:
        response = client.post(
            "/api/v1/documents/upload",
            data={
                "title": "Electrical Procedure",
                "system": "Electrical",
                "document_type": "procedure",
            },
            files={"file": ("manual.pdf", io.BytesIO(b"%PDF-1.4 test"), "application/pdf")},
        )
    finally:
        app.dependency_overrides.pop(get_jwt_payload, None)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "SCOPE_ACCESS_DENIED"
    assert detail["reason_code"] == "SYSTEM_SCOPE_DENIED"
    assert fake_db.access_audit_logs
    assert fake_db.access_audit_logs[-1]["action"] == "ingestion.upload"


def test_chat_stream_denies_workspace_outside_authorized_scope(
    client: TestClient,
    fake_db: FakeAsyncSession,
):
    async def override_get_jwt_payload():
        return {"sub": str(TEST_USER_ID), "role": "plantig_user", "scope": ["chat.read"]}

    fake_db.user_scope_policies[str(TEST_USER_ID)] = [
        {"system_scope": "liquefaction", "area_scope": "liquefaction"}
    ]
    app.dependency_overrides[get_jwt_payload] = override_get_jwt_payload

    try:
        response = client.post(
            CHAT_STREAM_ENDPOINT,
            json={
                "query": "Stream electrical troubleshooting guidance",
                "workspace": "Electrical",
            },
        )
    finally:
        app.dependency_overrides.pop(get_jwt_payload, None)

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["code"] == "SCOPE_ACCESS_DENIED"
    assert detail["reason_code"] == "AREA_SCOPE_DENIED"


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
    # Candidate 4 hybrid retrieval executes both dense and lexical branches:
    # dense branch performs primary + relaxed-threshold retry, lexical branch runs once.
    assert len(search_calls) == 3
    assert search_calls[0]["score_threshold"] == pytest.approx(0.7)
    assert search_calls[1]["score_threshold"] == pytest.approx(0.45)
    assert search_calls[2]["score_threshold"] == pytest.approx(0.7)
    assert search_calls[0]["workspace_filter"] == "Power Block"
    assert search_calls[1]["workspace_filter"] == "Power Block"
    assert search_calls[2]["workspace_filter"] == "Power Block"
    assert search_calls[0]["include_shared_documents"] is False
    assert search_calls[1]["include_shared_documents"] is False
    assert search_calls[2]["include_shared_documents"] is False

