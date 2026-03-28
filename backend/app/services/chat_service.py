"""Chat Service - RAG query orchestration."""
import logging
import uuid
from typing import List, Optional, AsyncIterator
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

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
from .qdrant_service import QdrantService
from .llm_service import LLMService, LLMConfigurationError, LLMUnavailableError

# Backward-compatibility alias for tests and older call sites.
VLLMService = LLMService

logger = logging.getLogger(__name__)


class _ConversationScope(dict):
    """Internal helper payload for persisted conversation scope."""


class ChatService:
    """Service for processing RAG chat queries."""

    _DOCUMENT_TYPE_WEIGHT_BOOST = 0.08
    _WEIGHTING_RETRIEVAL_POOL_MULTIPLIER = 4
    _CONVERSATION_TITLE_MAX_LENGTH = 80
    _RELAXED_SCORE_THRESHOLD_FLOOR = 0.45
    _RELAXED_SCORE_THRESHOLD_DELTA = 0.25

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
    
    RAG_SYSTEM_PROMPT = """You are an expert assistant for LNG plant documentation. 
Your role is to answer questions accurately based on the provided context from technical manuals and procedures.

Guidelines:
- Only use information from the provided context
- Cite sources using [Document Title, Page X] format
- If the context doesn't contain the answer, say so explicitly
- Be concise but thorough
- Use technical terminology appropriately
"""
    
    @classmethod
    async def process_query(
        cls,
        request: ChatQueryRequest,
        user_id: str,
        db: AsyncSession,
    ) -> ChatQueryResponse:
        """
        Process RAG query (non-streaming).
        
        Args:
            request: Chat query request
            user_id: Current user ID
            db: Database session
            
        Returns:
            Chat response with citations
        """
        logger.info(f"Processing query from user {user_id}: {request.query[:50]}...")

        persisted_scope = await cls._get_persisted_conversation_scope(
            conversation_id=str(request.conversation_id) if request.conversation_id else None,
            user_id=user_id,
            db=db,
        )
        scope_resolution = cls._resolve_query_scope(
            request=request,
            persisted_scope=persisted_scope,
        )
        preferred_document_types = scope_resolution["preferred_document_types"]
        normalized_workspace = scope_resolution["workspace"]
        document_type_filters = scope_resolution["document_type_filters"]
        include_shared_documents = scope_resolution["include_shared_documents"]
        conversation_scope = cls._build_conversation_scope(
            workspace=normalized_workspace,
            document_type_filters=document_type_filters,
            preferred_document_types=preferred_document_types,
            include_shared_documents=include_shared_documents,
        )
        
        # Step 1: Create or get conversation
        conversation_id = await cls._get_or_create_conversation(
            str(request.conversation_id) if request.conversation_id else None,
            user_id,
            db,
            conversation_scope,
            cls._generate_conversation_title(request.query),
        )
        
        # Step 2: Save user message
        user_message_id = await cls._save_message(
            conversation_id,
            "user",
            request.query,
            None,
            db
        )
        
        # Step 3: Generate query embedding
        logger.info("Generating query embedding...")
        query_vector = await EmbeddingService.embed_query(request.query)
        
        # Step 4: Retrieve relevant context from Qdrant
        logger.info("Searching for relevant documents...")
        retrieval_top_k = settings.RAG_TOP_K
        if preferred_document_types:
            retrieval_top_k = settings.RAG_TOP_K * cls._WEIGHTING_RETRIEVAL_POOL_MULTIPLIER

        contexts = await cls._search_with_scope_resilience(
            query_vector=query_vector,
            request=request,
            retrieval_top_k=retrieval_top_k,
            document_type_filters=document_type_filters,
            normalized_workspace=normalized_workspace,
            include_shared_documents=include_shared_documents,
        )

        contexts = cls._apply_document_type_weighting(
            contexts,
            preferred_document_types,
            settings.RAG_TOP_K,
        )
        
        if not contexts:
            logger.warning("No relevant contexts found")
            response_text = "I couldn't find relevant information in the documentation to answer your question."
            citations = []
        else:
            # Step 5: Build RAG prompt
            prompt = cls._build_rag_prompt(request.query, contexts)
            
            # Step 6: Generate LLM response
            logger.info("Generating LLM response...")
            citations = cls._create_citations(contexts)
            response_text = await LLMService.generate(
                prompt=prompt,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
            )
        
        # Step 8: Save assistant message
        assistant_message_id = await cls._save_message(
            conversation_id,
            "assistant",
            response_text,
            citations,
            db
        )
        
        logger.info(f"Query processed successfully, message_id={assistant_message_id}")
        
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
        logger.info(f"Processing streaming query from user {user_id}")

        conversation_id: Optional[str] = None
        assistant_message_id: Optional[str] = None

        try:
            persisted_scope = await cls._get_persisted_conversation_scope(
                conversation_id=str(request.conversation_id) if request.conversation_id else None,
                user_id=user_id,
                db=db,
            )
            scope_resolution = cls._resolve_query_scope(
                request=request,
                persisted_scope=persisted_scope,
            )
            preferred_document_types = scope_resolution["preferred_document_types"]
            normalized_workspace = scope_resolution["workspace"]
            document_type_filters = scope_resolution["document_type_filters"]
            include_shared_documents = scope_resolution["include_shared_documents"]
            conversation_scope = cls._build_conversation_scope(
                workspace=normalized_workspace,
                document_type_filters=document_type_filters,
                preferred_document_types=preferred_document_types,
                include_shared_documents=include_shared_documents,
            )

            # Step 1: Create or get conversation
            conversation_id = await cls._get_or_create_conversation(
                str(request.conversation_id) if request.conversation_id else None,
                user_id,
                db,
                conversation_scope,
                cls._generate_conversation_title(request.query),
            )

            # Step 2: Save user message
            await cls._save_message(
                conversation_id,
                "user",
                request.query,
                None,
                db,
            )

            # Step 3: Generate query embedding
            query_vector = await EmbeddingService.embed_query(request.query)

            # Step 4: Retrieve relevant context
            retrieval_top_k = settings.RAG_TOP_K
            if preferred_document_types:
                retrieval_top_k = settings.RAG_TOP_K * cls._WEIGHTING_RETRIEVAL_POOL_MULTIPLIER

            contexts = await cls._search_with_scope_resilience(
                query_vector=query_vector,
                request=request,
                retrieval_top_k=retrieval_top_k,
                document_type_filters=document_type_filters,
                normalized_workspace=normalized_workspace,
                include_shared_documents=include_shared_documents,
            )

            contexts = cls._apply_document_type_weighting(
                contexts,
                preferred_document_types,
                settings.RAG_TOP_K,
            )

            assistant_message_id = str(uuid.uuid4())

            if not contexts:
                fallback_message = (
                    "I couldn't find relevant information in the documentation to answer your question."
                )
                yield ChatTokenEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    token=fallback_message,
                    content=fallback_message,
                )
                await cls._save_message(
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
            prompt = cls._build_rag_prompt(request.query, contexts)

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

            citations = cls._create_citations(contexts)
            await cls._save_message(
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
            logger.error(f"Streaming query failed: {exc}")
            yield ChatErrorEvent(
                conversation_id=conversation_id,
                message_id=assistant_message_id,
                error=str(exc),
            )
    
    @classmethod
    def _build_rag_prompt(cls, query: str, contexts: List[RAGContext]) -> str:
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
        prompt = f"""{cls.RAG_SYSTEM_PROMPT}

Context:
{context_text}

User Question: {query}

Answer:"""
        
        return prompt
    
    @classmethod
    def _create_citations(cls, contexts: List[RAGContext]) -> List[Citation]:
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

    @classmethod
    def _apply_document_type_weighting(
        cls,
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
                return min(1.0, base_score + cls._DOCUMENT_TYPE_WEIGHT_BOOST)
            return base_score

        ranked_contexts = sorted(contexts, key=_adjusted_score, reverse=True)
        return ranked_contexts[:top_k]

    @classmethod
    async def _search_with_scope_resilience(
        cls,
        *,
        query_vector: List[float],
        request: ChatQueryRequest,
        retrieval_top_k: int,
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
        document_filter = [str(doc_id) for doc_id in request.document_filters] if request.document_filters else None

        contexts = await QdrantService.search_similar(
            query_vector=query_vector,
            top_k=retrieval_top_k,
            score_threshold=settings.RAG_SCORE_THRESHOLD,
            document_filter=document_filter,
            system_filter=request.system_filters,
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
                document_filter=document_filter,
                system_filter=request.system_filters,
                document_type_filter=document_type_filters,
                workspace_filter=normalized_workspace,
                include_shared_documents=True,
            )

        if not contexts:
            relaxed_threshold = max(
                cls._RELAXED_SCORE_THRESHOLD_FLOOR,
                settings.RAG_SCORE_THRESHOLD - cls._RELAXED_SCORE_THRESHOLD_DELTA,
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
                    document_filter=document_filter,
                    system_filter=request.system_filters,
                    document_type_filter=document_type_filters,
                    workspace_filter=normalized_workspace,
                    include_shared_documents=include_shared_documents,
                )

        return contexts

    @classmethod
    def _normalize_workspace(cls, workspace: Optional[str]) -> Optional[str]:
        """Normalize free-text workspace input into a canonical workspace label."""
        if not workspace:
            return None

        cleaned = workspace.strip()
        if not cleaned:
            return None

        lowered = cleaned.lower()
        if lowered in cls._WORKSPACE_ALIASES:
            return cls._WORKSPACE_ALIASES[lowered]

        # Canonicalize title-cased free text when it doesn't match an alias.
        return " ".join(segment.capitalize() for segment in cleaned.split())

    @classmethod
    def _resolve_include_shared_documents(cls, request_value: Optional[bool]) -> bool:
        """Resolve include-shared behavior from request override or settings default."""
        if request_value is None:
            return settings.CHAT_INCLUDE_SHARED_DEFAULT
        return bool(request_value)

    @classmethod
    def _resolve_query_scope(
        cls,
        request: ChatQueryRequest,
        persisted_scope: Optional[dict],
    ) -> dict:
        """Resolve effective workspace/doc-type/shared scope using request values with persisted fallback."""
        persisted_scope = persisted_scope or {}

        workspace_value = request.workspace
        if workspace_value is None:
            workspace_value = persisted_scope.get("workspace")
        workspace = cls._normalize_workspace(workspace_value)

        document_type_filters = request.document_type_filters
        if document_type_filters is None:
            document_type_filters = persisted_scope.get("document_type_filters")
        document_type_filters = list(document_type_filters) if document_type_filters else None

        preferred_document_types = request.preferred_document_types
        if preferred_document_types is None:
            preferred_document_types = persisted_scope.get("preferred_document_types")
        preferred_document_types = list(preferred_document_types) if preferred_document_types else document_type_filters

        include_shared_documents_value = request.include_shared_documents
        if include_shared_documents_value is None:
            include_shared_documents_value = persisted_scope.get("include_shared_documents")
        include_shared_documents = cls._resolve_include_shared_documents(include_shared_documents_value)

        return {
            "workspace": workspace,
            "document_type_filters": document_type_filters,
            "preferred_document_types": preferred_document_types,
            "include_shared_documents": include_shared_documents,
        }

    @classmethod
    def _build_conversation_scope(
        cls,
        workspace: Optional[str],
        document_type_filters: Optional[List[str]],
        preferred_document_types: Optional[List[str]],
        include_shared_documents: bool,
    ) -> _ConversationScope:
        """Create a normalized conversation-scope payload for persistence."""
        return _ConversationScope(
            workspace=workspace,
            document_type_filters=list(document_type_filters) if document_type_filters else None,
            preferred_document_types=list(preferred_document_types) if preferred_document_types else None,
            include_shared_documents=include_shared_documents,
        )

    @classmethod
    def _generate_conversation_title(cls, query: str) -> str:
        """Generate a stable conversation title from the first user query."""
        cleaned = " ".join((query or "").split())
        if not cleaned:
            return "New Conversation"

        if len(cleaned) <= cls._CONVERSATION_TITLE_MAX_LENGTH:
            return cleaned

        return cleaned[: cls._CONVERSATION_TITLE_MAX_LENGTH - 3].rstrip() + "..."
    
    @classmethod
    async def _get_or_create_conversation(
        cls,
        conversation_id: Optional[str],
        user_id: str,
        db: AsyncSession,
        conversation_scope: Optional[_ConversationScope] = None,
        initial_title: Optional[str] = None,
    ) -> str:
        """Get existing conversation or create new one."""
        if conversation_id:
            # Verify conversation exists and belongs to user
            result = await db.execute(
                text("SELECT id FROM conversations WHERE id = :conv_id AND user_id = :user_id"),
                {"conv_id": conversation_id, "user_id": user_id}
            )
            if result.fetchone():
                await cls._persist_conversation_scope(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    db=db,
                    conversation_scope=conversation_scope,
                )
                return conversation_id
        
        # Create new conversation
        new_id = str(uuid.uuid4())
        conversation_scope = conversation_scope or cls._build_conversation_scope(
            workspace=None,
            document_type_filters=None,
            preferred_document_types=None,
            include_shared_documents=settings.CHAT_INCLUDE_SHARED_DEFAULT,
        )
        await db.execute(
            text(
                """
                INSERT INTO conversations (
                    id,
                    user_id,
                    title,
                    workspace,
                    document_type_filters,
                    preferred_document_types,
                    include_shared_documents,
                    created_at,
                    updated_at
                ) VALUES (
                    :id,
                    :user_id,
                    :title,
                    :workspace,
                    :document_type_filters,
                    :preferred_document_types,
                    :include_shared_documents,
                    NOW(),
                    NOW()
                )
                """
            ),
            {
                "id": new_id,
                "user_id": user_id,
                "title": initial_title or "New Conversation",
                "workspace": conversation_scope.get("workspace"),
                "document_type_filters": conversation_scope.get("document_type_filters"),
                "preferred_document_types": conversation_scope.get("preferred_document_types"),
                "include_shared_documents": conversation_scope.get("include_shared_documents"),
            }
        )
        await db.commit()
        
        logger.info(f"Created new conversation {new_id}")
        return new_id

    @classmethod
    async def _persist_conversation_scope(
        cls,
        conversation_id: str,
        user_id: str,
        db: AsyncSession,
        conversation_scope: Optional[_ConversationScope],
    ) -> None:
        """Persist the current chat scope onto the conversation record."""
        if not conversation_scope:
            return

        await db.execute(
            text(
                """
                UPDATE conversations
                SET
                    workspace = :workspace,
                    document_type_filters = :document_type_filters,
                    preferred_document_types = :preferred_document_types,
                    include_shared_documents = :include_shared_documents,
                    updated_at = NOW()
                WHERE id = :conv_id AND user_id = :user_id
                """
            ),
            {
                "conv_id": conversation_id,
                "user_id": user_id,
                "workspace": conversation_scope.get("workspace"),
                "document_type_filters": conversation_scope.get("document_type_filters"),
                "preferred_document_types": conversation_scope.get("preferred_document_types"),
                "include_shared_documents": conversation_scope.get("include_shared_documents"),
            },
        )
        await db.commit()

    @classmethod
    async def _get_persisted_conversation_scope(
        cls,
        conversation_id: Optional[str],
        user_id: str,
        db: AsyncSession,
    ) -> Optional[dict]:
        """Load persisted scope for an existing conversation owned by the current user."""
        if not conversation_id:
            return None

        result = await db.execute(
            text(
                """
                SELECT workspace, document_type_filters, preferred_document_types, include_shared_documents
                FROM conversations
                WHERE id = :conv_id AND user_id = :user_id
                """
            ),
            {"conv_id": conversation_id, "user_id": user_id},
        )
        row = result.first()
        if not row:
            return None

        if hasattr(row, "_mapping"):
            mapping = row._mapping
            return {
                "workspace": mapping.get("workspace"),
                "document_type_filters": mapping.get("document_type_filters"),
                "preferred_document_types": mapping.get("preferred_document_types"),
                "include_shared_documents": mapping.get("include_shared_documents"),
            }

        if isinstance(row, dict):
            return {
                "workspace": row.get("workspace"),
                "document_type_filters": row.get("document_type_filters"),
                "preferred_document_types": row.get("preferred_document_types"),
                "include_shared_documents": row.get("include_shared_documents"),
            }

        return None
    
    @classmethod
    async def _save_message(
        cls,
        conversation_id: str,
        role: str,
        content: str,
        citations: Optional[List[Citation]],
        db: AsyncSession,
        message_id: Optional[str] = None,
    ) -> str:
        """Save message to database."""
        message_id = message_id or str(uuid.uuid4())
        
        # Serialize citations to JSON string (asyncpg requires a JSON string for JSONB columns)
        citations_json: Optional[str] = None
        if citations:
            import json
            citations_json = json.dumps([c.model_dump(mode="json") for c in citations])
        
        await db.execute(
            text("""
                INSERT INTO chat_messages (id, conversation_id, role, content, citations, timestamp)
                VALUES (:id, :conv_id, :role, :content, CAST(:citations AS jsonb), NOW())
            """),
            {
                "id": message_id,
                "conv_id": conversation_id,
                "role": role,
                "content": content,
                "citations": citations_json,
            }
        )
        await db.commit()
        
        return message_id