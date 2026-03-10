"""
Chat API Endpoints.

Endpoints for RAG chat queries, both streaming and non-streaming.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import get_current_user_id
from ..models.database import get_db
from ..models.chat import (
    ChatQueryRequest,
    ChatQueryResponse,
)
from ..services.chat_service import ChatService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


@router.post("/query", response_model=ChatQueryResponse)
async def chat_query(
    request: ChatQueryRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a RAG chat query (non-streaming).
    
    Process flow:
    1. Generate query embedding
    2. Search Qdrant for relevant document chunks
    3. Build RAG prompt with retrieved context
    4. Generate LLM response
    5. Save conversation and messages to database
    6. Return complete response with citations
    
    Returns:
        Complete response with message ID, content, and source citations
    """
    try:
        response = await ChatService.process_query(
            request=request,
            user_id=current_user_id,
            db=db,
        )
        return response
        
    except Exception as e:
        logger.error(f"Query processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process query: {str(e)}"
        )


@router.post("/stream")
async def chat_query_stream(
    request: ChatQueryRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a RAG chat query with streaming response.
    
    Returns Server-Sent Events (SSE) stream with:
    - Token chunks as they're generated
    - Final citations after completion
    
    Client should use EventSource or fetch with stream handling.
    """
    async def event_generator():
        """Generate SSE events."""
        try:
            # Stream tokens from LLM
            async for token in ChatService.process_query_stream(
                request=request,
                user_id=current_user_id,
                db=db,
            ):
                # Format as SSE
                yield f"data: {token}\n\n"
            
            # Signal completion
            yield "data: [DONE]\n\n"
            
        except Exception as e:
            logger.error(f"Streaming failed: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
