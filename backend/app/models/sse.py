"""Typed SSE event contracts for ingestion and chat streaming."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .chat import Citation


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SSEEventModel(BaseModel):
    """Base model for SSE payloads."""

    model_config = ConfigDict(extra="forbid")

    event: str
    timestamp: datetime = Field(default_factory=utc_now)


class IngestionJobAcceptedEvent(SSEEventModel):
    """Initial acknowledgement emitted when an ingestion job is accepted."""

    event: str = "job.accepted"
    document_id: str
    job_id: str
    stage: str = "queued"
    progress: int = Field(default=0, ge=0, le=100)
    message: str


class IngestionProgressEvent(SSEEventModel):
    """Progress update emitted while ingestion is in flight."""

    event: str = "progress"
    document_id: str
    job_id: Optional[str] = None
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str


class IngestionStageCompleteEvent(SSEEventModel):
    """Stage completion emitted when a pipeline stage is known to be complete."""

    event: str = "stage.complete"
    document_id: str
    job_id: Optional[str] = None
    stage: str
    progress: int = Field(default=100, ge=0, le=100)
    message: str
    artifact_type: Optional[str] = None
    artifact_path: Optional[str] = None


class IngestionCompleteEvent(SSEEventModel):
    """Final successful completion event for ingestion."""

    event: str = "complete"
    document_id: str
    job_id: Optional[str] = None
    stage: str = "completed"
    progress: int = Field(default=100, ge=0, le=100)
    message: str
    artifact_type: Optional[str] = None
    artifact_path: Optional[str] = None


class IngestionErrorEvent(SSEEventModel):
    """Terminal error event for ingestion."""

    event: str = "error"
    document_id: str
    job_id: Optional[str] = None
    stage: str
    progress: int = Field(default=0, ge=0, le=100)
    message: str
    error: str


class ChatTokenEvent(SSEEventModel):
    """Token chunk emitted during chat generation."""

    event: str = "token"
    conversation_id: str
    message_id: str
    token: str
    content: str
    done: bool = False


class ChatCitationEvent(SSEEventModel):
    """Citation emitted after token generation has enough context."""

    event: str = "citation"
    conversation_id: str
    message_id: str
    citation: Citation
    done: bool = False


class ChatCompleteEvent(SSEEventModel):
    """Terminal completion event for chat streaming."""

    event: str = "complete"
    conversation_id: str
    message_id: str
    done: bool = True


class ChatErrorEvent(SSEEventModel):
    """Terminal error event for chat streaming."""

    event: str = "error"
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    error: str
    done: bool = True