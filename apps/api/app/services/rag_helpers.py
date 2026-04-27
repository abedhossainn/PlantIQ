"""RAG helpers - standalone functions for retrieval, prompt building, and citation creation."""
import logging
from typing import List, Optional

from ..core.config import settings
from ..models.chat import Citation, ChatQueryRequest, RAGContext
from .qdrant_service import QdrantService

logger = logging.getLogger(__name__)

# System prompt used for all RAG queries. Instructs the LLM to:
# (1) Ground answers in provided context only (no hallucination)
# (2) Emit structured citations for traceability
# (3) Explicitly communicate when no relevant context exists
RAG_SYSTEM_PROMPT = """You are an expert assistant for LNG plant documentation. 
Your role is to answer questions accurately based on the provided context from technical manuals and procedures.

Guidelines:
- Only use information from the provided context
- Cite sources using [Document Title, Page X] format
- If the context doesn't contain the answer, say so explicitly
- Be concise but thorough
- Use technical terminology appropriately
"""

_WORKSPACE_ALIASES = {
    "power block": "Power Block",
    "pre treatment": "Pre Treatment",
    "pretreatment": "Pre Treatment",
    "liquefaction": "Liquefaction",
    "osbl": "OSBL (Outside Battery Limits)",
    "outside battery limits": "OSBL (Outside Battery Limits)",
    "maintenance": "Maintenance",
    "instrumentation": "Instrumentation",
    "dcs": "DCS (Distributed Control System)",
    "distributed control system": "DCS (Distributed Control System)",
    "electrical": "Electrical",
    "mechanical": "Mechanical",
}

# Boost factor applied when preferred document types are found during retrieval.
# Amplifies relevance scores from 0.08 (8%) to push contextually relevant docs higher.
_DOCUMENT_TYPE_WEIGHT_BOOST = 0.08

# Retrieval pool size multiplier: retrieve 4x the final context count, then re-rank.
# Allows flexible re-ranking and filtering without discarding early candidates.
_WEIGHTING_RETRIEVAL_POOL_MULTIPLIER = 4

# RELAXED THRESHOLD STRATEGY: If initial retrieval is too strict (high threshold),
# lower the bar incrementally to find usable context. Floor at 0.45 similarity score;
# allows up to 0.25 delta reduction from original threshold before giving up.
_RELAXED_SCORE_THRESHOLD_FLOOR = 0.45
_RELAXED_SCORE_THRESHOLD_DELTA = 0.25

# Fallback response when retrieval yields no relevant context (below threshold).
_NO_CONTEXT_RESPONSE = (
    "I couldn't find relevant information in the documentation to answer your question."
)


def get_retrieval_top_k(preferred_document_types: Optional[List[str]]) -> int:
    """Return retrieval pool size, expanding it when doc-type weighting is active."""
    if preferred_document_types:
        return settings.RAG_TOP_K * _WEIGHTING_RETRIEVAL_POOL_MULTIPLIER
    return settings.RAG_TOP_K


def build_rag_prompt(query: str, contexts: List[RAGContext]) -> str:
    """Build prompt with retrieved context."""
    # Truncate context if too long
    total_length = 0
    selected_contexts = []

    for ctx in contexts:
        ctx_length = len(ctx.content)
        if total_length + ctx_length > settings.RAG_MAX_CONTEXT_LENGTH:
            break
        selected_contexts.append(ctx)
        total_length += ctx_length

    # Build context section
    context_text = "\n\n".join([
        f"[Source: {ctx.document_title}]\n{ctx.content}"
        for ctx in selected_contexts
    ])

    # Build full prompt
    prompt = f"""{RAG_SYSTEM_PROMPT}

Context:
{context_text}

User Question: {query}

Answer:"""

    return prompt


def create_citations(contexts: List[RAGContext]) -> List[Citation]:
    """Create citation objects from contexts."""
    citations = []

    for idx, ctx in enumerate(contexts):
        # Extract page number from metadata if available
        page_number = ctx.metadata.get("page_number")
        section_heading = ctx.metadata.get("section_heading")

        # Truncate excerpt to 500 chars (max_length constraint on Citation.excerpt)
        excerpt = ctx.content[:497] + "..." if len(ctx.content) > 500 else ctx.content

        citation = Citation(
            id=f"cite-{idx+1}",
            document_id=ctx.document_id,
            document_title=ctx.document_title,
            section_heading=section_heading,
            page_number=page_number,
            workspace=ctx.metadata.get("workspace"),
            system=ctx.metadata.get("system"),
            document_type=ctx.metadata.get("document_type"),
            excerpt=excerpt,
            relevance_score=ctx.score,
        )
        citations.append(citation)

    return citations


def apply_document_type_weighting(
    contexts: List[RAGContext],
    preferred_document_types: Optional[List[str]],
    top_k: int,
) -> List[RAGContext]:
    """Apply lightweight relevance weighting using preferred document types."""
    if not contexts:
        return contexts

    if not preferred_document_types:
        return contexts[:top_k]

    preferred_set = {
        doc_type.strip().lower()
        for doc_type in preferred_document_types
        if doc_type and doc_type.strip()
    }
    if not preferred_set:
        return contexts[:top_k]

    def _adjusted_score(context: RAGContext) -> float:
        base_score = float(context.score or 0.0)
        context_document_type = str(context.metadata.get("document_type") or "").strip().lower()
        if context_document_type and context_document_type in preferred_set:
            return min(1.0, base_score + _DOCUMENT_TYPE_WEIGHT_BOOST)
        return base_score

    ranked_contexts = sorted(contexts, key=_adjusted_score, reverse=True)
    return ranked_contexts[:top_k]


async def search_with_scope_resilience(
    *,
    query_vector: List[float],
    retrieval_top_k: int,
    system_filters: Optional[List[str]],
    document_type_filters: Optional[List[str]],
    normalized_workspace: Optional[str],
    include_shared_documents: bool,
) -> List[RAGContext]:
    """Search with same-scope resilience before returning no-context result.

    Strategy:
    1) primary search with configured threshold
    2) optional workspace->shared retry (existing behavior)
    3) same-scope relaxed-threshold retry for semantically sparse phrasings
    """
    contexts = await QdrantService.search_similar(
        query_vector=query_vector,
        top_k=retrieval_top_k,
        score_threshold=settings.RAG_SCORE_THRESHOLD,
        system_filter=system_filters,
        document_type_filter=document_type_filters,
        workspace_filter=normalized_workspace,
        include_shared_documents=include_shared_documents,
    )

    if (
        not contexts
        and normalized_workspace
        and settings.CHAT_ALLOW_WORKSPACE_FALLBACK_TO_SHARED
        and not include_shared_documents
    ):
        logger.info(
            "No contexts found for workspace '%s' without shared docs; retrying with shared docs enabled",
            normalized_workspace,
        )
        contexts = await QdrantService.search_similar(
            query_vector=query_vector,
            top_k=retrieval_top_k,
            score_threshold=settings.RAG_SCORE_THRESHOLD,
            system_filter=system_filters,
            document_type_filter=document_type_filters,
            workspace_filter=normalized_workspace,
            include_shared_documents=True,
        )

    if not contexts:
        relaxed_threshold = max(
            _RELAXED_SCORE_THRESHOLD_FLOOR,
            settings.RAG_SCORE_THRESHOLD - _RELAXED_SCORE_THRESHOLD_DELTA,
        )
        if relaxed_threshold < settings.RAG_SCORE_THRESHOLD:
            logger.info(
                "No contexts at threshold %.2f; retrying same scope with relaxed threshold %.2f",
                settings.RAG_SCORE_THRESHOLD,
                relaxed_threshold,
            )
            contexts = await QdrantService.search_similar(
                query_vector=query_vector,
                top_k=retrieval_top_k,
                score_threshold=relaxed_threshold,
                system_filter=system_filters,
                document_type_filter=document_type_filters,
                workspace_filter=normalized_workspace,
                include_shared_documents=include_shared_documents,
            )

    return contexts


def normalize_workspace(workspace: Optional[str]) -> Optional[str]:
    """Normalize free-text workspace input into a canonical workspace label."""
    if not workspace:
        return None

    cleaned = workspace.strip()
    if not cleaned:
        return None

    lowered = cleaned.lower()
    if lowered in _WORKSPACE_ALIASES:
        return _WORKSPACE_ALIASES[lowered]

    # Canonicalize title-cased free text when it doesn't match an alias.
    return " ".join(segment.capitalize() for segment in cleaned.split())


def resolve_include_shared_documents(request_value: Optional[bool]) -> bool:
    """Resolve include-shared behavior from request override or settings default."""
    if request_value is None:
        return settings.CHAT_INCLUDE_SHARED_DEFAULT
    return bool(request_value)


def resolve_query_scope(
    request: ChatQueryRequest,
    persisted_scope: Optional[dict],
) -> dict:
    """Resolve effective workspace and shared scope.

    Candidate 5 (scope simplification): document_type is no longer an active scope
    axis. Values sent in request fields or stored in persisted scope are accepted
    for backward-compat deserialization but treated as 'any' — no filter predicate
    or relevance-weighting is built from them. Scope is now system + area only.
    """
    persisted_scope = persisted_scope or {}

    workspace_value = request.workspace
    if workspace_value is None:
        workspace_value = persisted_scope.get("workspace")
    workspace = normalize_workspace(workspace_value)

    include_shared_documents_value = request.include_shared_documents
    if include_shared_documents_value is None:
        include_shared_documents_value = persisted_scope.get("include_shared_documents")
    include_shared_documents = resolve_include_shared_documents(include_shared_documents_value)

    return {
        "workspace": workspace,
        "document_type_filters": None,  # Candidate 5: removed from active scope
        "preferred_document_types": None,  # Candidate 5: removed from active scope
        "include_shared_documents": include_shared_documents,
    }
