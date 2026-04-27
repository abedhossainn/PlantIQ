"""Chat Service - RAG query orchestration."""
import json
import logging
import uuid
from typing import List, Optional, AsyncIterator
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.chat import (
    Citation,
    ChatQueryRequest,
    ChatQueryResponse,
    RAGContext,
)
from ..models.sse import (
    ChatCitationEvent,
    ChatCompleteEvent,
    ChatErrorEvent,
    ChatTokenEvent,
)
from .embedding_service import EmbeddingService
from .qdrant_service import QdrantService  # re-exported for test monkeypatching compatibility
from .llm_service import LLMService, LLMConfigurationError, LLMUnavailableError
from .access_governance_service import (
    ScopePolicy,
    enforce_chat_scope,
    filter_contexts_to_scope,
)
from .hybrid_retrieval_service import HybridRetrievalService, RetrievalScope
from .rag_helpers import (
    build_rag_prompt,
    create_citations,
    resolve_query_scope,
    _NO_CONTEXT_RESPONSE,
)
from .conversation_service import (
    _ConversationScope,
    _PreparedChatTurn,
    build_conversation_scope,
    generate_conversation_title,
    get_or_create_conversation,
    persist_conversation_scope,
    get_persisted_conversation_scope,
    save_message,
)

# Backward-compatibility alias for tests and older call sites.
VLLMService = LLMService

logger = logging.getLogger(__name__)


class ChatService:
    """Service for processing RAG chat queries.
    
    Core Responsibility:
    - Orchestrate document retrieval, context assembly, and LLM-based response generation
    - Manage conversation lifecycle, scope constraints, and multi-turn context preservation
    - Emit structured citation events for grounded answer accountability
    
    Retrieval Strategy:
    - Executes externalized hybrid retrieval with independent lexical and dense branches
    - Applies deterministic weighted-RRF fusion with stable tie-breaks in the app layer
    - Preserves scope filtering and emits internal branch attribution diagnostics
    """

    @classmethod
    async def process_query(
        cls,
        request: ChatQueryRequest,
        user_id: str,
        user_claims: dict,
        db: AsyncSession,
    ) -> ChatQueryResponse:
        """
        Process RAG query (non-streaming synchronous path).
        
        Execution flow:
        1. Prepare turn: resolve conversation scope, perform scoped retrieval
        2. Build RAG prompt: assemble context + user query with system instructions
        3. Generate response: call LLM service with streaming disabled
        4. Extract citations: harvest source references from retrieved context
        5. Persist conversation: save both user message and assistant response
        
        Args:
            request: Chat query request (query text, conversation ID, scope controls)
            user_id: Current user ID (for scope and conversation access)
            db: Database session (for persistence and scope lookup)
            
        Returns:
            Chat response with structured citations for source traceability
        """
        logger.info("Processing query from user %s: %s...", user_id, request.query[:50])
        prepared_turn = await cls._prepare_chat_turn(
            request=request,
            user_id=user_id,
            user_claims=user_claims,
            db=db,
        )
        conversation_id = prepared_turn.conversation_id
        contexts = prepared_turn.contexts
        if prepared_turn.retrieval_diagnostics:
            logger.info(
                "Hybrid retrieval diagnostics (query): %s",
                json.dumps(prepared_turn.retrieval_diagnostics, sort_keys=True),
            )
        
        if not contexts:
            logger.warning("No relevant contexts found")
            response_text = _NO_CONTEXT_RESPONSE
            citations = []
        else:
            # Step 5: Build RAG prompt
            prompt = build_rag_prompt(request.query, contexts)
            
            # Step 6: Generate LLM response
            logger.info("Generating LLM response...")
            citations = create_citations(contexts)
            response_text = await LLMService.generate(
                prompt=prompt,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
            )
        
        # Step 8: Save assistant message
        assistant_message_id = await save_message(
            conversation_id,
            "assistant",
            response_text,
            citations,
            db
        )
        
        logger.info("Query processed successfully, message_id=%s", assistant_message_id)
        
        return ChatQueryResponse(
            message_id=UUID(assistant_message_id),
            conversation_id=UUID(conversation_id),
            content=response_text,
            citations=citations,
            timestamp=datetime.now(timezone.utc),
        )
    
    @classmethod
    async def process_query_stream(
        cls,
        request: ChatQueryRequest,
        user_id: str,
        user_claims: dict,
        db: AsyncSession,
    ) -> AsyncIterator[ChatTokenEvent | ChatCitationEvent | ChatCompleteEvent | ChatErrorEvent]:
        """
        Process RAG query with streaming.
        
        Args:
            request: Chat query request
            user_id: Current user ID
            db: Database session
            
        Yields:
            Structured chat SSE payloads.
        """
        logger.info("Processing streaming query from user %s", user_id)

        conversation_id: Optional[str] = None
        assistant_message_id: Optional[str] = None

        try:
            prepared_turn = await cls._prepare_chat_turn(
                request=request,
                user_id=user_id,
                user_claims=user_claims,
                db=db,
            )
            conversation_id = prepared_turn.conversation_id
            contexts = prepared_turn.contexts
            if prepared_turn.retrieval_diagnostics:
                logger.info(
                    "Hybrid retrieval diagnostics (stream): %s",
                    json.dumps(prepared_turn.retrieval_diagnostics, sort_keys=True),
                )

            assistant_message_id = str(uuid.uuid4())

            if not contexts:
                fallback_message = _NO_CONTEXT_RESPONSE
                yield ChatTokenEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    token=fallback_message,
                    content=fallback_message,
                )
                await save_message(
                    conversation_id,
                    "assistant",
                    fallback_message,
                    [],
                    db,
                    message_id=assistant_message_id,
                )
                yield ChatCompleteEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                )
                return

            # Step 5: Build RAG prompt
            prompt = build_rag_prompt(request.query, contexts)

            # Step 6: Stream LLM response
            full_response = ""
            async for token in LLMService.generate_stream(
                prompt=prompt,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
            ):
                full_response += token
                yield ChatTokenEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    token=token,
                    content=token,
                )

            # Ollama's OpenAI-compatible streaming can emit empty text chunks for
            # /v1/completions even when non-stream generation succeeds. Prevent
            # citations-only responses by falling back to non-stream generation.
            if not full_response.strip():
                logger.warning(
                    "LLM stream produced no token text; falling back to non-stream generation"
                )
                full_response = await LLMService.generate(
                    prompt=prompt,
                    max_tokens=settings.LLM_MAX_TOKENS,
                    temperature=settings.LLM_TEMPERATURE,
                )
                if full_response:
                    yield ChatTokenEvent(
                        conversation_id=conversation_id,
                        message_id=assistant_message_id,
                        token=full_response,
                        content=full_response,
                    )

            citations = create_citations(contexts)
            await save_message(
                conversation_id,
                "assistant",
                full_response,
                citations,
                db,
                message_id=assistant_message_id,
            )

            for citation in citations:
                yield ChatCitationEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    citation=citation,
                )

            yield ChatCompleteEvent(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
            )

        except Exception as exc:
            logger.exception("Streaming query failed: %s", exc)
            yield ChatErrorEvent(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                error=str(exc),
            )

    @classmethod
    async def _prepare_chat_turn(
        cls,
        *,
        request: ChatQueryRequest,
        user_id: str,
        user_claims: dict,
        db: AsyncSession,
    ) -> _PreparedChatTurn:
        """Prepare the shared conversation, scope, and retrieval state for one chat turn."""
        persisted_scope = await get_persisted_conversation_scope(
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
            user_id=user_id,
            db=db,
        )
        scope_resolution = resolve_query_scope(
            request=request,
            persisted_scope=persisted_scope,
        )

        effective_scope = await enforce_chat_scope(
            db=db,
            user_id=user_id,
            claims=user_claims,
            workspace=scope_resolution["workspace"],
            system_filters=request.system_filters,
            endpoint="/api/v1/chat/query",
        )

        document_type_filters = scope_resolution["document_type_filters"]
        include_shared_documents = (
            scope_resolution["include_shared_documents"] and effective_scope.allow_shared_documents
        )
        conversation_scope = build_conversation_scope(
            workspace=scope_resolution["workspace"],
            document_type_filters=document_type_filters,
            preferred_document_types=scope_resolution["preferred_document_types"],
            include_shared_documents=include_shared_documents,
        )

        conversation_id = await get_or_create_conversation(
            str(request.conversation_id) if request.conversation_id else None,
            user_id,
            db,
            conversation_scope,
            generate_conversation_title(request.query),
        )

        await save_message(
            conversation_id,
            "user",
            request.query,
            None,
            db,
        )

        logger.info("Generating query embedding...")
        query_vector = await EmbeddingService.embed_query(request.query)

        logger.info("Searching for relevant documents...")
        retrieval_top_k = settings.RAG_TOP_K
        hybrid_result = await HybridRetrievalService().retrieve(
            query_text=request.query,
            query_vector=query_vector,
            scope=RetrievalScope(
                system_filters=effective_scope.system_filters,
                workspace=effective_scope.workspace,
                include_shared_documents=include_shared_documents,
            ),
            top_k=retrieval_top_k,
        )
        contexts = hybrid_result.contexts
        contexts = cls._filter_contexts_for_scope(
            contexts=contexts,
            policy=effective_scope.policy,
            allow_shared_documents=include_shared_documents,
        )

        retrieval_diagnostics = hybrid_result.diagnostics.as_log_dict()
        retrieval_diagnostics["scope"] = {
            "system_filters": effective_scope.system_filters,
            "workspace": effective_scope.workspace,
            "include_shared_documents": include_shared_documents,
        }

        return _PreparedChatTurn(
            conversation_id=conversation_id,
            contexts=contexts,
            retrieval_diagnostics=retrieval_diagnostics,
        )

    @classmethod
    async def preflight_scope_check(
        cls,
        *,
        request: ChatQueryRequest,
        user_id: str,
        user_claims: dict,
        db: AsyncSession,
    ) -> None:
        """Run chat scope authorization checks before streaming starts."""
        persisted_scope = await get_persisted_conversation_scope(
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
            user_id=user_id,
            db=db,
        )
        scope_resolution = resolve_query_scope(request=request, persisted_scope=persisted_scope)
        await enforce_chat_scope(
            db=db,
            user_id=user_id,
            claims=user_claims,
            workspace=scope_resolution["workspace"],
            system_filters=request.system_filters,
            endpoint="/api/v1/chat/stream",
        )

    @classmethod
    def _filter_contexts_for_scope(
        cls,
        *,
        contexts: list[RAGContext],
        policy: ScopePolicy,
        allow_shared_documents: bool,
    ) -> list[RAGContext]:
        return filter_contexts_to_scope(
            contexts,
            policy=policy,
            allow_shared_documents=allow_shared_documents,
        )