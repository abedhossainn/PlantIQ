"""
Pydantic models for chat and RAG endpoints.
"""
from typing import Optional, List, Literal
from datetime import datetime
from pydantic import BaseModel, UUID4, Field


class Citation(BaseModel):
    """Citation metadata for RAG responses."""
    id: str
    document_id: UUID4
    document_title: str
    section_heading: Optional[str] = None
    page_number: Optional[int] = None
    workspace: Optional[str] = None
    system: Optional[str] = None
    document_type: Optional[str] = None
    excerpt: str = Field(..., max_length=500)
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class ChatQueryRequest(BaseModel):
    """Request body for chat query."""
    query: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[UUID4] = None
    workspace: Optional[str] = Field(default=None, max_length=120)
    document_filters: Optional[List[UUID4]] = None  # Filter by specific documents
    system_filters: Optional[List[str]] = None  # Filter by system type
    # Candidate 5 (scope simplification): document_type is no longer an active scope axis.
    # These fields are accepted for backward compatibility but are ignored in filter predicates.
    document_type_filters: Optional[List[str]] = Field(
        default=None,
        description="Deprecated (Candidate 5): document_type is no longer an active scope axis. "
                    "Accepted for backward compatibility; value is ignored in retrieval filters.",
    )
    preferred_document_types: Optional[List[str]] = Field(
        default=None,
        description="Deprecated (Candidate 5): document_type weighting is no longer applied. "
                    "Accepted for backward compatibility; value is ignored.",
    )
    include_shared_documents: Optional[bool] = None
    stream: bool = Field(default=False)


class ChatQueryResponse(BaseModel):
    """Response for chat query (non-streaming)."""
    message_id: UUID4
    conversation_id: UUID4
    content: str
    citations: List[Citation]
    timestamp: datetime


class ChatFeedbackSubmitRequest(BaseModel):
    """Request body for answer/message feedback submission."""

    answer_message_id: UUID4
    conversation_id: Optional[UUID4] = None
    source_message_id: Optional[UUID4] = None
    sentiment: Literal["up", "down"]
    reason_code: Optional[str] = Field(default=None, max_length=80)
    comment: Optional[str] = Field(default=None, max_length=1000)
    system_scope: Optional[str] = Field(default=None, max_length=255)
    area_scope: Optional[str] = Field(default=None, max_length=255)


class ChatQualitySnapshot(BaseModel):
    """Lightweight answer-quality snapshot updated by feedback events."""

    answer_message_id: UUID4
    conversation_id: UUID4
    feedback_count: int
    positive_count: int
    negative_count: int
    negative_streak: int
    quality_score: float
    is_flagged: bool
    last_feedback_at: datetime


class ChatFeedbackSubmitResponse(BaseModel):
    """Feedback submission result with updated quality snapshot."""

    event_id: UUID4
    answer_message_id: UUID4
    conversation_id: UUID4
    timestamp: datetime
    snapshot: ChatQualitySnapshot


class ChatFeedbackReasonMetric(BaseModel):
    """Aggregate count for a reason code."""

    reason_code: str
    count: int


class ChatQualityMetricsResponse(BaseModel):
    """Admin/QA-oriented aggregate metrics for feedback quality signals."""

    window_days: int
    total_feedback_events: int
    positive_feedback_events: int
    negative_feedback_events: int
    flagged_answers: int
    reason_breakdown: List[ChatFeedbackReasonMetric]


class ChatTokenMessage(BaseModel):
    """Token message for streaming WebSocket."""
    type: Literal["token"] = "token"
    content: str
    conversation_id: str
    message_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatCitationMessage(BaseModel):
    """Citation message for streaming WebSocket."""
    type: Literal["citation"] = "citation"
    citation: Citation
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatCompleteMessage(BaseModel):
    """Completion message for streaming WebSocket."""
    type: Literal["complete"] = "complete"
    message_id: str
    citations: List[Citation]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ChatErrorMessage(BaseModel):
    """Error message for streaming WebSocket."""
    type: Literal["error"] = "error"
    error: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RAGContext(BaseModel):
    """Retrieved context for RAG query."""
    chunk_id: str
    content: str
    document_id: UUID4
    document_title: str
    metadata: dict
    score: float
