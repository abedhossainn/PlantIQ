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
    excerpt: str = Field(..., max_length=500)
    relevance_score: float = Field(..., ge=0.0, le=1.0)


class ChatQueryRequest(BaseModel):
    """Request body for chat query."""
    query: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[UUID4] = None
    document_filters: Optional[List[UUID4]] = None  # Filter by specific documents
    system_filters: Optional[List[str]] = None  # Filter by system type
    stream: bool = Field(default=False)


class ChatQueryResponse(BaseModel):
    """Response for chat query (non-streaming)."""
    message_id: UUID4
    conversation_id: UUID4
    content: str
    citations: List[Citation]
    timestamp: datetime


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
