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
from .vllm_service import VLLMService

logger = logging.getLogger(__name__)


class ChatService:
    """Service for processing RAG chat queries."""
    
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
        
        # Step 1: Create or get conversation
        conversation_id = await cls._get_or_create_conversation(
            str(request.conversation_id) if request.conversation_id else None,
            user_id,
            db
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
        contexts = await QdrantService.search_similar(
            query_vector=query_vector,
            top_k=settings.RAG_TOP_K,
            score_threshold=settings.RAG_SCORE_THRESHOLD,
            document_filter=[str(doc_id) for doc_id in request.document_filters] if request.document_filters else None,
            system_filter=request.system_filters,
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
            response_text = await VLLMService.generate(
                prompt=prompt,
                max_tokens=settings.VLLM_MAX_TOKENS,
                temperature=settings.VLLM_TEMPERATURE,
            )
            
            # Step 7: Create citations
            citations = cls._create_citations(contexts)
        
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
            # Step 1: Create or get conversation
            conversation_id = await cls._get_or_create_conversation(
                str(request.conversation_id) if request.conversation_id else None,
                user_id,
                db,
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
            contexts = await QdrantService.search_similar(
                query_vector=query_vector,
                top_k=settings.RAG_TOP_K,
                score_threshold=settings.RAG_SCORE_THRESHOLD,
                document_filter=[str(doc_id) for doc_id in request.document_filters] if request.document_filters else None,
                system_filter=request.system_filters,
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
            async for token in VLLMService.generate_stream(
                prompt=prompt,
                max_tokens=settings.VLLM_MAX_TOKENS,
                temperature=settings.VLLM_TEMPERATURE,
            ):
                full_response += token
                yield ChatTokenEvent(
                    conversation_id=conversation_id,
                    message_id=assistant_message_id,
                    token=token,
                    content=token,
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
            
            # Truncate excerpt to 500 chars
            excerpt = ctx.content[:500] + "..." if len(ctx.content) > 500 else ctx.content
            
            citation = Citation(
                id=f"cite-{idx+1}",
                document_id=ctx.document_id,
                document_title=ctx.document_title,
                section_heading=section_heading,
                page_number=page_number,
                excerpt=excerpt,
                relevance_score=ctx.score,
            )
            citations.append(citation)
        
        return citations
    
    @classmethod
    async def _get_or_create_conversation(
        cls,
        conversation_id: Optional[str],
        user_id: str,
        db: AsyncSession,
    ) -> str:
        """Get existing conversation or create new one."""
        if conversation_id:
            # Verify conversation exists and belongs to user
            result = await db.execute(
                text("SELECT id FROM conversations WHERE id = :conv_id AND user_id = :user_id"),
                {"conv_id": conversation_id, "user_id": user_id}
            )
            if result.fetchone():
                return conversation_id
        
        # Create new conversation
        new_id = str(uuid.uuid4())
        await db.execute(
            text("INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (:id, :user_id, :title, NOW(), NOW())"),
            {"id": new_id, "user_id": user_id, "title": "New Conversation"}
        )
        await db.commit()
        
        logger.info(f"Created new conversation {new_id}")
        return new_id
    
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
        
        # Serialize citations to JSON
        citations_json = None
        if citations:
            citations_json = [c.model_dump() for c in citations]
        
        await db.execute(
            text("""
                INSERT INTO chat_messages (id, conversation_id, role, content, citations, timestamp)
                VALUES (:id, :conv_id, :role, :content, :citations, NOW())
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