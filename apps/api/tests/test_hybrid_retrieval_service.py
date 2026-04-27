#!/usr/bin/env python3
"""Unit tests for Candidate 4 hybrid retrieval branching/fusion/fallback behavior."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.chat import RAGContext  # noqa: E402
from app.services.hybrid_retrieval_service import (  # noqa: E402
    BranchHit,
    BranchResult,
    DenseRetriever,
    DeterministicFusionService,
    HybridRetrievalService,
    RetrievalScope,
)


class _StaticRetriever:
    def __init__(self, result: BranchResult):
        self._result = result

    async def retrieve(self, **_kwargs) -> BranchResult:
        return self._result


def _ctx(chunk_id: str, score: float, title: str = "Ops") -> RAGContext:
    return RAGContext(
        chunk_id=chunk_id,
        content=f"Content for {chunk_id}",
        document_id=uuid.uuid4(),
        document_title=title,
        metadata={"page_number": 1},
        score=score,
    )


def _hit(branch: str, rank: int, chunk_id: str, score_raw: float, score_norm: float = 1.0) -> BranchHit:
    context = _ctx(chunk_id=chunk_id, score=score_raw)
    return BranchHit(
        branch=branch,
        rank=rank,
        chunk_id=chunk_id,
        document_id=str(context.document_id),
        score_raw=score_raw,
        score_norm=score_norm,
        context=context,
    )


def test_weighted_rrf_fusion_is_deterministic_with_stable_tie_breaks():
    fusion = DeterministicFusionService()

    lexical = BranchResult(
        branch="lexical",
        hits=[
            _hit("lexical", 1, "chunk-a", 0.8),
            _hit("lexical", 2, "chunk-b", 0.7),
        ],
        timing_ms=3,
        engine_info={"engine": "qdrant"},
    )
    dense = BranchResult(
        branch="dense",
        hits=[
            _hit("dense", 1, "chunk-b", 0.9),
            _hit("dense", 2, "chunk-a", 0.85),
        ],
        timing_ms=4,
        engine_info={"engine": "qdrant"},
    )

    contexts, diagnostics = fusion.fuse(lexical_result=lexical, dense_result=dense, top_n=2)

    # Both chunks have equal RRF score; tie-break falls back to max normalized score
    # and then chunk_id. With equal normalized scores, chunk-a sorts before chunk-b.
    assert [ctx.chunk_id for ctx in contexts] == ["chunk-a", "chunk-b"]
    assert diagnostics["policy_id"] == "weighted_rrf_v1"
    assert diagnostics["hits"][0]["contribution"].keys() == {"lexical", "dense"}


@pytest.mark.asyncio
async def test_hybrid_retrieval_falls_back_to_dense_only_when_lexical_fails():
    lexical_failed = BranchResult(
        branch="lexical",
        hits=[],
        timing_ms=1,
        engine_info={"engine": "qdrant"},
        status="failed",
        error_code="lexical_unavailable",
        error_message="lexical timeout",
    )
    dense_ok = BranchResult(
        branch="dense",
        hits=[_hit("dense", 1, "chunk-dense", 0.77)],
        timing_ms=2,
        engine_info={"engine": "qdrant"},
    )

    service = HybridRetrievalService(
        lexical_retriever=_StaticRetriever(lexical_failed),
        dense_retriever=_StaticRetriever(dense_ok),
    )

    result = await service.retrieve(
        query_text="startup",
        query_vector=[0.1, 0.2, 0.3],
        scope=RetrievalScope(system_filters=["Liquefaction"], workspace="Liquefaction", include_shared_documents=True),
        top_k=3,
    )

    assert [ctx.chunk_id for ctx in result.contexts] == ["chunk-dense"]
    assert result.diagnostics.fallback_applied is True
    assert result.diagnostics.fallback_reason == "lexical_unavailable"
    assert result.diagnostics.fusion["hits"][0]["contribution"] == {"lexical": 0.0, "dense": 1.0}


@pytest.mark.asyncio
async def test_hybrid_retrieval_falls_back_to_lexical_only_when_dense_fails():
    lexical_ok = BranchResult(
        branch="lexical",
        hits=[_hit("lexical", 1, "chunk-lex", 0.66)],
        timing_ms=2,
        engine_info={"engine": "qdrant"},
    )
    dense_failed = BranchResult(
        branch="dense",
        hits=[],
        timing_ms=1,
        engine_info={"engine": "qdrant"},
        status="failed",
        error_code="dense_unavailable",
        error_message="dense timeout",
    )

    service = HybridRetrievalService(
        lexical_retriever=_StaticRetriever(lexical_ok),
        dense_retriever=_StaticRetriever(dense_failed),
    )

    result = await service.retrieve(
        query_text="startup",
        query_vector=[0.1, 0.2, 0.3],
        scope=RetrievalScope(system_filters=["Liquefaction"], workspace="Liquefaction", include_shared_documents=False),
        top_k=3,
    )

    assert [ctx.chunk_id for ctx in result.contexts] == ["chunk-lex"]
    assert result.diagnostics.fallback_applied is True
    assert result.diagnostics.fallback_reason == "dense_unavailable"
    assert result.diagnostics.fusion["hits"][0]["contribution"] == {"lexical": 1.0, "dense": 0.0}


@pytest.mark.asyncio
async def test_hybrid_retrieval_returns_no_context_when_both_branches_fail():
    lexical_failed = BranchResult(
        branch="lexical",
        hits=[],
        timing_ms=1,
        engine_info={"engine": "qdrant"},
        status="failed",
    )
    dense_failed = BranchResult(
        branch="dense",
        hits=[],
        timing_ms=1,
        engine_info={"engine": "qdrant"},
        status="failed",
    )

    service = HybridRetrievalService(
        lexical_retriever=_StaticRetriever(lexical_failed),
        dense_retriever=_StaticRetriever(dense_failed),
    )

    result = await service.retrieve(
        query_text="startup",
        query_vector=[0.1, 0.2, 0.3],
        scope=RetrievalScope(system_filters=None, workspace=None, include_shared_documents=True),
        top_k=5,
    )

    assert result.contexts == []
    assert result.diagnostics.fallback_applied is True
    assert result.diagnostics.fallback_reason == "both_unavailable"
    assert result.diagnostics.fusion["hits"] == []


@pytest.mark.asyncio
async def test_dense_retriever_reports_branch_metadata(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    async def fake_search_with_scope_resilience(**kwargs):
        captured.update(kwargs)
        return [_ctx("chunk-1", 0.92)]

    monkeypatch.setattr(
        "app.services.hybrid_retrieval_service.search_with_scope_resilience",
        fake_search_with_scope_resilience,
    )

    retriever = DenseRetriever()
    scope = RetrievalScope(system_filters=["Liquefaction"], workspace="Liquefaction", include_shared_documents=True)
    result = await retriever.retrieve(query_text="startup", query_vector=[0.1, 0.2, 0.3], scope=scope, top_k=4)

    assert result.branch == "dense"
    assert result.status == "ok"
    assert len(result.hits) == 1
    assert result.hits[0].rank == 1
    assert captured["normalized_workspace"] == "Liquefaction"
    assert captured["document_type_filters"] is None
