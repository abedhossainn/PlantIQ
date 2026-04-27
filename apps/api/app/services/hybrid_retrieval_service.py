"""Hybrid retrieval orchestration with branch attribution and deterministic fusion."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Optional, Protocol

from ..core.config import settings
from ..models.chat import RAGContext
from .rag_helpers import search_with_scope_resilience

logger = logging.getLogger(__name__)


_DEFAULT_RRF_RANK_CONSTANT = 60
_DEFAULT_LEXICAL_WEIGHT = 0.5
_DEFAULT_DENSE_WEIGHT = 0.5
_LEXICAL_CANDIDATE_POOL_MULTIPLIER = 4
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(slots=True)
class RetrievalScope:
    """Resolved retrieval scope used by both retrieval branches."""

    system_filters: Optional[list[str]]
    workspace: Optional[str]
    include_shared_documents: bool


@dataclass(slots=True)
class BranchHit:
    """A branch-local retrieval hit with branch scoring metadata."""

    branch: str
    rank: int
    chunk_id: str
    document_id: str
    score_raw: float
    score_norm: float
    context: RAGContext


@dataclass(slots=True)
class BranchResult:
    """Result envelope for one retrieval branch execution."""

    branch: str
    hits: list[BranchHit]
    timing_ms: int
    engine_info: dict[str, str]
    status: str = "ok"
    error_code: Optional[str] = None
    error_message: Optional[str] = None


@dataclass(slots=True)
class HybridRetrievalDiagnostics:
    """Internal diagnostics and attribution for one retrieval run."""

    branches: dict
    fusion: dict
    fallback_applied: bool
    fallback_reason: Optional[str]
    trace_flags: dict

    def as_log_dict(self) -> dict:
        return {
            "branches": self.branches,
            "fusion": self.fusion,
            "fallback_applied": self.fallback_applied,
            "fallback_reason": self.fallback_reason,
            "trace_flags": self.trace_flags,
        }


@dataclass(slots=True)
class HybridRetrievalResult:
    """Final retrieval contexts and internal diagnostics."""

    contexts: list[RAGContext]
    diagnostics: HybridRetrievalDiagnostics


class RetrieverBranch(Protocol):
    """Branch contract for independent retrieval execution."""

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        scope: RetrievalScope,
        top_k: int,
    ) -> BranchResult:
        """Execute the branch and return ranked hits."""


class DenseRetriever:
    """Dense branch using embedding similarity search."""

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        scope: RetrievalScope,
        top_k: int,
    ) -> BranchResult:
        start = perf_counter()
        try:
            query_token_count = len(_tokenize(query_text))
            contexts = await search_with_scope_resilience(
                query_vector=query_vector,
                retrieval_top_k=top_k,
                system_filters=scope.system_filters,
                document_type_filters=None,
                normalized_workspace=scope.workspace,
                include_shared_documents=scope.include_shared_documents,
            )
            hits = _contexts_to_branch_hits("dense", contexts)
            return BranchResult(
                branch="dense",
                hits=hits,
                timing_ms=int((perf_counter() - start) * 1000),
                engine_info={
                    "engine": "qdrant",
                    "collection": settings.QDRANT_COLLECTION,
                    "strategy": "vector_similarity",
                    "query_token_count": str(query_token_count),
                },
            )
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.exception("Dense branch failed: %s", exc)
            return BranchResult(
                branch="dense",
                hits=[],
                timing_ms=int((perf_counter() - start) * 1000),
                engine_info={"engine": "qdrant", "collection": settings.QDRANT_COLLECTION},
                status="failed",
                error_code="dense_unavailable",
                error_message=str(exc),
            )


class LexicalRetriever:
    """Lexical BM25-like branch backed by token-overlap scoring."""

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        scope: RetrievalScope,
        top_k: int,
    ) -> BranchResult:
        start = perf_counter()
        try:
            query_terms = _tokenize(query_text)
            if not query_terms:
                return BranchResult(
                    branch="lexical",
                    hits=[],
                    timing_ms=int((perf_counter() - start) * 1000),
                    engine_info={
                        "engine": "qdrant",
                        "collection": settings.QDRANT_COLLECTION,
                        "strategy": "keyword_overlap",
                    },
                    status="partial",
                )

            candidate_pool = max(top_k * _LEXICAL_CANDIDATE_POOL_MULTIPLIER, top_k)
            candidate_contexts = await search_with_scope_resilience(
                query_vector=query_vector,
                retrieval_top_k=candidate_pool,
                system_filters=scope.system_filters,
                document_type_filters=None,
                normalized_workspace=scope.workspace,
                include_shared_documents=scope.include_shared_documents,
            )

            scored = []
            for context in candidate_contexts:
                text = " ".join(
                    [
                        str(context.document_title or ""),
                        str(context.metadata.get("section_heading") or ""),
                        str(context.content or ""),
                    ]
                )
                lexical_score = _keyword_overlap_score(query_terms, text)
                if lexical_score <= 0.0:
                    continue
                scored.append((context, lexical_score))

            scored.sort(
                key=lambda item: (
                    -item[1],
                    -float(item[0].score or 0.0),
                    str(item[0].chunk_id),
                )
            )
            contexts = [context for context, _score in scored[:top_k]]
            raw_scores = [score for _context, score in scored[:top_k]]
            hits = _contexts_to_branch_hits("lexical", contexts, raw_scores=raw_scores)

            return BranchResult(
                branch="lexical",
                hits=hits,
                timing_ms=int((perf_counter() - start) * 1000),
                engine_info={
                    "engine": "qdrant",
                    "collection": settings.QDRANT_COLLECTION,
                    "strategy": "keyword_overlap",
                },
            )
        except Exception as exc:  # pragma: no cover - defensive fallback path
            logger.exception("Lexical branch failed: %s", exc)
            return BranchResult(
                branch="lexical",
                hits=[],
                timing_ms=int((perf_counter() - start) * 1000),
                engine_info={"engine": "qdrant", "collection": settings.QDRANT_COLLECTION},
                status="failed",
                error_code="lexical_unavailable",
                error_message=str(exc),
            )


class DeterministicFusionService:
    """Deterministic weighted-RRF fusion with stable tie-break rules."""

    def __init__(
        self,
        *,
        lexical_weight: float = _DEFAULT_LEXICAL_WEIGHT,
        dense_weight: float = _DEFAULT_DENSE_WEIGHT,
        rank_constant: int = _DEFAULT_RRF_RANK_CONSTANT,
    ) -> None:
        self._weights = {
            "lexical": float(lexical_weight),
            "dense": float(dense_weight),
        }
        self._rank_constant = max(1, int(rank_constant))

    def fuse(
        self,
        *,
        lexical_result: Optional[BranchResult],
        dense_result: Optional[BranchResult],
        top_n: int,
    ) -> tuple[list[RAGContext], dict]:
        branch_results = [result for result in [lexical_result, dense_result] if result is not None]
        if not branch_results:
            return [], {
                "policy_id": "weighted_rrf_v1",
                "weights": dict(self._weights),
                "normalization": "branch_minmax",
                "top_n": top_n,
                "hits": [],
            }

        by_chunk: dict[str, dict] = {}
        for result in branch_results:
            weight = self._weights.get(result.branch, 0.0)
            for hit in result.hits:
                chunk_bucket = by_chunk.setdefault(
                    hit.chunk_id,
                    {
                        "context": hit.context,
                        "score_fused": 0.0,
                        "components": {},
                        "branch_ranks": {},
                        "branch_scores": {},
                        "max_branch_score_norm": 0.0,
                    },
                )
                component = weight / (self._rank_constant + hit.rank)
                chunk_bucket["score_fused"] += component
                chunk_bucket["components"][result.branch] = component
                chunk_bucket["branch_ranks"][result.branch] = hit.rank
                chunk_bucket["branch_scores"][result.branch] = hit.score_raw
                chunk_bucket["max_branch_score_norm"] = max(
                    float(chunk_bucket["max_branch_score_norm"]),
                    float(hit.score_norm),
                )

        fused_rows = list(by_chunk.items())
        fused_rows.sort(
            key=lambda item: (
                -float(item[1]["score_fused"]),
                -float(item[1]["max_branch_score_norm"]),
                str(item[0]),
            )
        )

        selected_rows = fused_rows[:top_n]
        contexts: list[RAGContext] = []
        hit_diagnostics: list[dict] = []

        for rank_index, (chunk_id, row) in enumerate(selected_rows, start=1):
            context = row["context"].model_copy(deep=True)
            context.score = min(1.0, max(0.0, float(row["score_fused"])))
            contexts.append(context)

            total_component = sum(float(value) for value in row["components"].values())
            contribution = {
                "lexical": 0.0,
                "dense": 0.0,
            }
            if total_component > 0:
                for branch_name, component in row["components"].items():
                    contribution[branch_name] = round(float(component) / total_component, 6)

            hit_diagnostics.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": str(context.document_id),
                    "rank_final": rank_index,
                    "score_fused": round(float(row["score_fused"]), 10),
                    "contribution": contribution,
                    "branch_ranks": {
                        "lexical": row["branch_ranks"].get("lexical"),
                        "dense": row["branch_ranks"].get("dense"),
                    },
                    "branch_scores": {
                        "lexical": row["branch_scores"].get("lexical"),
                        "dense": row["branch_scores"].get("dense"),
                    },
                }
            )

        diagnostics = {
            "policy_id": "weighted_rrf_v1",
            "weights": dict(self._weights),
            "normalization": "branch_minmax",
            "top_n": top_n,
            "hits": hit_diagnostics,
        }
        return contexts, diagnostics


class HybridRetrievalService:
    """Hybrid retrieval coordinator for lexical+dense branches and deterministic fusion."""

    def __init__(
        self,
        *,
        lexical_retriever: Optional[RetrieverBranch] = None,
        dense_retriever: Optional[RetrieverBranch] = None,
        fusion_service: Optional[DeterministicFusionService] = None,
    ) -> None:
        self._lexical_retriever = lexical_retriever or LexicalRetriever()
        self._dense_retriever = dense_retriever or DenseRetriever()
        self._fusion_service = fusion_service or DeterministicFusionService()

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        scope: RetrievalScope,
        top_k: int,
    ) -> HybridRetrievalResult:
        lexical_result = await self._lexical_retriever.retrieve(
            query_text=query_text,
            query_vector=query_vector,
            scope=scope,
            top_k=top_k,
        )
        dense_result = await self._dense_retriever.retrieve(
            query_text=query_text,
            query_vector=query_vector,
            scope=scope,
            top_k=top_k,
        )

        lexical_ok = lexical_result.status != "failed"
        dense_ok = dense_result.status != "failed"
        fallback_applied = False
        fallback_reason: Optional[str] = None

        if not lexical_ok and not dense_ok:
            fallback_applied = True
            fallback_reason = "both_unavailable"
            contexts = []
            fusion_diagnostics = {
                "policy_id": "weighted_rrf_v1",
                "weights": {"lexical": _DEFAULT_LEXICAL_WEIGHT, "dense": _DEFAULT_DENSE_WEIGHT},
                "normalization": "branch_minmax",
                "top_n": top_k,
                "hits": [],
            }
        elif not lexical_ok:
            fallback_applied = True
            fallback_reason = "lexical_unavailable"
            contexts, fusion_diagnostics = _single_branch_result_to_contexts(
                branch_result=dense_result,
                top_n=top_k,
            )
        elif not dense_ok:
            fallback_applied = True
            fallback_reason = "dense_unavailable"
            contexts, fusion_diagnostics = _single_branch_result_to_contexts(
                branch_result=lexical_result,
                top_n=top_k,
            )
        else:
            contexts, fusion_diagnostics = self._fusion_service.fuse(
                lexical_result=lexical_result,
                dense_result=dense_result,
                top_n=top_k,
            )

        diagnostics = HybridRetrievalDiagnostics(
            branches={
                "lexical": _branch_result_to_diagnostics(lexical_result, top_k),
                "dense": _branch_result_to_diagnostics(dense_result, top_k),
            },
            fusion=fusion_diagnostics,
            fallback_applied=fallback_applied,
            fallback_reason=fallback_reason,
            trace_flags={
                "scope_enforced": True,
                "document_type_axis_active": False,
            },
        )
        return HybridRetrievalResult(contexts=contexts, diagnostics=diagnostics)


def _tokenize(value: str) -> list[str]:
    return [token for token in _TOKEN_PATTERN.findall((value or "").lower()) if token]


def _keyword_overlap_score(query_terms: list[str], text: str) -> float:
    if not query_terms:
        return 0.0
    text_tokens = set(_tokenize(text))
    if not text_tokens:
        return 0.0
    matched = sum(1 for term in query_terms if term in text_tokens)
    return matched / len(query_terms)


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    minimum = min(scores)
    maximum = max(scores)
    if maximum <= minimum:
        return [1.0 for _ in scores]
    spread = maximum - minimum
    return [(score - minimum) / spread for score in scores]


def _contexts_to_branch_hits(
    branch: str,
    contexts: list[RAGContext],
    *,
    raw_scores: Optional[list[float]] = None,
) -> list[BranchHit]:
    resolved_scores = raw_scores or [float(context.score or 0.0) for context in contexts]
    normalized_scores = _normalize_scores(resolved_scores)

    hits: list[BranchHit] = []
    for rank, context in enumerate(contexts, start=1):
        raw_score = float(resolved_scores[rank - 1]) if rank - 1 < len(resolved_scores) else 0.0
        norm_score = float(normalized_scores[rank - 1]) if rank - 1 < len(normalized_scores) else 0.0
        hits.append(
            BranchHit(
                branch=branch,
                rank=rank,
                chunk_id=str(context.chunk_id),
                document_id=str(context.document_id),
                score_raw=raw_score,
                score_norm=norm_score,
                context=context,
            )
        )
    return hits


def _branch_result_to_diagnostics(result: BranchResult, requested_top_k: int) -> dict:
    return {
        "status": result.status,
        "timing_ms": result.timing_ms,
        "top_k_requested": requested_top_k,
        "top_k_returned": len(result.hits),
        "engine_info": result.engine_info,
        "error_code": result.error_code,
        "error_message": result.error_message,
    }


def _single_branch_result_to_contexts(
    *,
    branch_result: BranchResult,
    top_n: int,
) -> tuple[list[RAGContext], dict]:
    selected_hits = sorted(
        branch_result.hits,
        key=lambda hit: (hit.rank, str(hit.chunk_id)),
    )[:top_n]

    contexts: list[RAGContext] = []
    diagnostics_hits: list[dict] = []
    for rank_index, hit in enumerate(selected_hits, start=1):
        context = hit.context.model_copy(deep=True)
        contexts.append(context)
        diagnostics_hits.append(
            {
                "chunk_id": str(hit.chunk_id),
                "document_id": str(hit.document_id),
                "rank_final": rank_index,
                "score_fused": round(float(hit.score_raw), 10),
                "contribution": {
                    "lexical": 1.0 if hit.branch == "lexical" else 0.0,
                    "dense": 1.0 if hit.branch == "dense" else 0.0,
                },
                "branch_ranks": {
                    "lexical": hit.rank if hit.branch == "lexical" else None,
                    "dense": hit.rank if hit.branch == "dense" else None,
                },
                "branch_scores": {
                    "lexical": hit.score_raw if hit.branch == "lexical" else None,
                    "dense": hit.score_raw if hit.branch == "dense" else None,
                },
            }
        )

    diagnostics = {
        "policy_id": "single_branch_fallback_v1",
        "weights": {
            "lexical": 1.0 if branch_result.branch == "lexical" else 0.0,
            "dense": 1.0 if branch_result.branch == "dense" else 0.0,
        },
        "normalization": "branch_minmax",
        "top_n": top_n,
        "hits": diagnostics_hits,
    }
    return contexts, diagnostics
