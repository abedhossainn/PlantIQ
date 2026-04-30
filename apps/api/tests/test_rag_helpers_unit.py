"""Unit tests for app/services/rag_helpers.py."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.models.chat import ChatQueryRequest, RAGContext
from app.services import rag_helpers


def _ctx(
    *,
    content: str,
    score: float,
    document_type: str | None = None,
    title: str = "Doc",
) -> RAGContext:
    metadata = {"page_number": 3, "section_heading": "Section A", "workspace": "Liquefaction"}
    if document_type is not None:
        metadata["document_type"] = document_type
    return RAGContext(
        chunk_id=str(uuid.uuid4()),
        content=content,
        document_id=uuid.uuid4(),
        document_title=title,
        metadata=metadata,
        score=score,
    )


def test_get_retrieval_top_k_uses_multiplier_when_preferred_types_present():
    with patch.object(rag_helpers.settings, "RAG_TOP_K", 3):
        assert rag_helpers.get_retrieval_top_k(["manual"]) == 12
        assert rag_helpers.get_retrieval_top_k(None) == 3


def test_build_rag_prompt_respects_max_context_length():
    contexts = [
        _ctx(content="A" * 80, score=0.9, title="Doc A"),
        _ctx(content="B" * 80, score=0.8, title="Doc B"),
    ]
    with patch.object(rag_helpers.settings, "RAG_MAX_CONTEXT_LENGTH", 100):
        prompt = rag_helpers.build_rag_prompt("What is the startup step?", contexts)

    assert "[Source: Doc A]" in prompt
    assert "[Source: Doc B]" not in prompt
    assert "User Question: What is the startup step?" in prompt


def test_create_citations_truncates_excerpt_and_maps_metadata():
    long_text = "x" * 600
    citations = rag_helpers.create_citations([_ctx(content=long_text, score=0.7, title="Manual")])

    assert len(citations) == 1
    citation = citations[0]
    assert citation.id == "cite-1"
    assert citation.document_title == "Manual"
    assert citation.page_number == 3
    assert len(citation.excerpt) == 500
    assert citation.excerpt.endswith("...")


def test_apply_document_type_weighting_returns_top_k_without_preference():
    contexts = [_ctx(content="a", score=0.3), _ctx(content="b", score=0.2), _ctx(content="c", score=0.1)]
    ranked = rag_helpers.apply_document_type_weighting(contexts, None, top_k=2)
    assert len(ranked) == 2
    assert ranked[0].score == 0.3


def test_apply_document_type_weighting_returns_empty_when_no_contexts():
    assert rag_helpers.apply_document_type_weighting([], ["manual"], top_k=3) == []


def test_apply_document_type_weighting_boosts_preferred_document_type():
    low_manual = _ctx(content="manual", score=0.70, document_type="manual", title="Manual")
    high_other = _ctx(content="other", score=0.75, document_type="other", title="Other")

    ranked = rag_helpers.apply_document_type_weighting(
        [high_other, low_manual],
        preferred_document_types=["  MANUAL  "],
        top_k=2,
    )

    assert ranked[0].document_title == "Manual"


def test_apply_document_type_weighting_ignores_blank_preferred_values():
    contexts = [_ctx(content="a", score=0.5), _ctx(content="b", score=0.4)]
    ranked = rag_helpers.apply_document_type_weighting(
        contexts,
        preferred_document_types=["", "   ", None],
        top_k=1,
    )
    assert len(ranked) == 1
    assert ranked[0].score == 0.5


def test_apply_document_type_weighting_keeps_base_score_for_non_match():
    contexts = [
        _ctx(content="manual", score=0.6, document_type="manual", title="Manual"),
        _ctx(content="procedure", score=0.7, document_type="procedure", title="Procedure"),
    ]
    ranked = rag_helpers.apply_document_type_weighting(
        contexts,
        preferred_document_types=["spec"],
        top_k=2,
    )
    assert ranked[0].document_title == "Procedure"


def test_normalize_workspace_alias_blank_and_title_case():
    assert rag_helpers.normalize_workspace(None) is None
    assert rag_helpers.normalize_workspace("pretreatment") == "Pre Treatment"
    assert rag_helpers.normalize_workspace("  ") is None
    assert rag_helpers.normalize_workspace("power system area") == "Power System Area"


def test_resolve_include_shared_documents_uses_settings_default_and_override():
    with patch.object(rag_helpers.settings, "CHAT_INCLUDE_SHARED_DEFAULT", True):
        assert rag_helpers.resolve_include_shared_documents(None) is True
    assert rag_helpers.resolve_include_shared_documents(False) is False


def test_resolve_query_scope_uses_persisted_workspace_and_ignores_document_type_axis():
    request = ChatQueryRequest(query="q", workspace=None, include_shared_documents=None)
    resolved = rag_helpers.resolve_query_scope(
        request=request,
        persisted_scope={
            "workspace": "dcs",
            "document_type_filters": ["Procedure"],
            "preferred_document_types": ["Procedure"],
            "include_shared_documents": True,
        },
    )

    assert resolved["workspace"] == "DCS (Distributed Control System)"
    assert resolved["include_shared_documents"] is True
    assert resolved["document_type_filters"] is None
    assert resolved["preferred_document_types"] is None


def test_resolve_query_scope_prefers_request_values_over_persisted_scope():
    request = ChatQueryRequest(query="q", workspace="  power block  ", include_shared_documents=False)
    resolved = rag_helpers.resolve_query_scope(
        request=request,
        persisted_scope={"workspace": "Liquefaction", "include_shared_documents": True},
    )
    assert resolved["workspace"] == "Power Block"
    assert resolved["include_shared_documents"] is False


@pytest.mark.asyncio
async def test_search_with_scope_resilience_returns_primary_result_without_retry():
    fake_search = AsyncMock(return_value=[_ctx(content="result", score=0.9)])

    with patch.object(rag_helpers.QdrantService, "search_similar", fake_search):
        contexts = await rag_helpers.search_with_scope_resilience(
            query_vector=[0.1, 0.2],
            retrieval_top_k=5,
            system_filters=["liquefaction"],
            document_type_filters=None,
            normalized_workspace="Pre Treatment",
            include_shared_documents=False,
        )

    assert len(contexts) == 1
    assert fake_search.await_count == 1


@pytest.mark.asyncio
async def test_search_with_scope_resilience_retries_with_shared_docs_when_enabled():
    fake_search = AsyncMock(side_effect=[[], [_ctx(content="fallback", score=0.81)]])

    with patch.object(rag_helpers.settings, "CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED", True), patch.object(
        rag_helpers.QdrantService,
        "search_similar",
        fake_search,
    ):
        contexts = await rag_helpers.search_with_scope_resilience(
            query_vector=[0.1],
            retrieval_top_k=4,
            system_filters=None,
            document_type_filters=None,
            normalized_workspace="Liquefaction",
            include_shared_documents=False,
        )

    assert len(contexts) == 1
    assert fake_search.await_count == 2
    second_call = fake_search.await_args_list[1].kwargs
    assert second_call["include_shared_documents"] is True


@pytest.mark.asyncio
async def test_search_with_scope_resilience_uses_relaxed_threshold_when_needed():
    fake_search = AsyncMock(side_effect=[[], [], [_ctx(content="relaxed", score=0.6)]])

    with patch.object(rag_helpers.settings, "CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED", True), patch.object(
        rag_helpers.settings,
        "RAG_SCORE_THRESHOLD",
        0.7,
    ), patch.object(rag_helpers.QdrantService, "search_similar", fake_search):
        contexts = await rag_helpers.search_with_scope_resilience(
            query_vector=[0.1],
            retrieval_top_k=4,
            system_filters=None,
            document_type_filters=None,
            normalized_workspace="Liquefaction",
            include_shared_documents=False,
        )

    assert len(contexts) == 1
    assert fake_search.await_count == 3
    relaxed_call = fake_search.await_args_list[2].kwargs
    assert relaxed_call["score_threshold"] == pytest.approx(0.45)
