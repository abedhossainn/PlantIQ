"""Chat API Endpoints."""
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.sse import create_sse_response, encode_sse_event
from ..core.security import get_current_user_id, get_jwt_payload
from ..models.database import get_db
from ..models.chat import (
    ChatFeedbackSubmitRequest,
    ChatFeedbackSubmitResponse,
    ChatQualityMetricsResponse,
    ChatQueryRequest,
    ChatQueryResponse,
)
from ..services.answer_feedback_service import AnswerFeedbackService, FeedbackServiceError
from ..services.access_governance_service import ScopeAccessDenied
from ..services.chat_service import ChatService
from ..services.llm_service import LLMConfigurationError, LLMUnavailableError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/chat", tags=["Chat"])


def _error_detail(code: str, message: str, extra: dict | None = None) -> dict:
    detail = {"code": code, "message": message}
    if extra:
        detail.update(extra)
    return detail


@router.post("/query", response_model=ChatQueryResponse)
async def chat_query(
    request: ChatQueryRequest,
    current_user_id: str = Depends(get_current_user_id),
    jwt_payload: dict = Depends(get_jwt_payload),
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
            user_claims=jwt_payload,
            db=db,
        )
        return response

    except ScopeAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.detail,
        )

    except (LLMConfigurationError, LLMUnavailableError) as exc:
        logger.error("Chat generation unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Chat generation unavailable: {str(exc)}",
        )
        
    except Exception as exc:
        logger.error("Query processing failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process query: {str(exc)}"
        )


@router.post("/stream")
async def chat_query_stream(
    request: ChatQueryRequest,
    current_user_id: str = Depends(get_current_user_id),
    jwt_payload: dict = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a RAG chat query with streaming response.
    
    Returns Server-Sent Events (SSE) stream with:
    - Token chunks as they're generated
    - Final citations after completion
    
    Client should use EventSource or fetch with stream handling.
    """
    try:
        await ChatService.preflight_scope_check(
            request=request,
            user_id=current_user_id,
            user_claims=jwt_payload,
            db=db,
        )
    except ScopeAccessDenied as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.detail,
        )

    async def event_generator():
        """Generate explicit chat SSE events."""
        async for event in ChatService.process_query_stream(
            request=request,
            user_id=current_user_id,
            user_claims=jwt_payload,
            db=db,
        ):
            yield encode_sse_event(event)

    return create_sse_response(event_generator())


@router.post("/feedback", response_model=ChatFeedbackSubmitResponse)
async def submit_chat_feedback(
    request: ChatFeedbackSubmitRequest,
    current_user_id: str = Depends(get_current_user_id),
    jwt_payload: dict = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
):
    """Submit append-only answer feedback and refresh lightweight quality snapshot."""
    try:
        return await AnswerFeedbackService.submit_feedback(
            request=request,
            user_id=str(current_user_id),
            user_claims=jwt_payload,
            db=db,
        )
    except FeedbackServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=_error_detail(exc.code, exc.message),
        )
    except Exception as exc:
        logger.error("Feedback submission failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_error_detail("FEEDBACK_SUBMISSION_FAILED", "Failed to submit feedback."),
        )


@router.get("/feedback/metrics", response_model=ChatQualityMetricsResponse)
async def get_chat_feedback_metrics(
    window_days: int = Query(default=30, ge=1, le=365),
    system_scope: str | None = Query(default=None),
    area_scope: str | None = Query(default=None),
    jwt_payload: dict = Depends(get_jwt_payload),
    db: AsyncSession = Depends(get_db),
):
    """Return lightweight feedback quality metrics for admin/QA monitoring."""
    role = str(jwt_payload.get("role") or "")
    if role not in {"admin", "reviewer", "plantig_admin", "plantig_reviewer"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_error_detail(
                "METRICS_ACCESS_DENIED",
                "Only admin/reviewer roles can access feedback metrics.",
            ),
        )

    try:
        return await AnswerFeedbackService.get_metrics_summary(
            window_days=window_days,
            system_scope=system_scope,
            area_scope=area_scope,
            db=db,
        )
    except Exception as exc:
        logger.error("Feedback metrics query failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=_error_detail("METRICS_QUERY_FAILED", "Failed to retrieve feedback metrics."),
        )
