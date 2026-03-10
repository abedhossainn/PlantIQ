"""
Pydantic models for pipeline orchestration endpoints.
"""
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, UUID4, Field
from enum import Enum


class PipelineStatus(str, Enum):
    """Pipeline processing status."""
    PENDING = "pending"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    VLM_VALIDATING = "vlm-validating"
    VALIDATION_COMPLETE = "validation-complete"
    IN_REVIEW = "in-review"
    REVIEW_COMPLETE = "review-complete"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


class PipelineStage(str, Enum):
    """Pipeline stage identifiers."""
    MANIFEST = "manifest"
    VALIDATION = "validation"
    IMAGE_DESCRIPTIONS = "image_descriptions"
    TABLE_FIGURE = "table_figure"
    REVIEW_WORKSPACE = "review_workspace"
    VERSIONING = "versioning"
    QA_METRICS = "qa_metrics"
    GATE_EVALUATION = "gate_evaluation"
    AUDIT = "audit"


class DocumentUploadRequest(BaseModel):
    """Request body for document upload."""
    title: str = Field(..., min_length=1, max_length=500)
    version: Optional[str] = Field(None, max_length=50)
    system: Optional[str] = Field(None, max_length=255)
    document_type: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    """Response for document upload."""
    document_id: UUID4
    status: PipelineStatus
    file_path: str
    message: str


class PipelineStatusResponse(BaseModel):
    """Response for pipeline status check."""
    document_id: UUID4
    status: PipelineStatus
    current_stage: Optional[str] = None
    progress: int = Field(default=0, ge=0, le=100)
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class PipelineProgressUpdate(BaseModel):
    """Progress update message for WebSocket."""
    type: Literal["progress"] = "progress"
    document_id: str
    stage: str
    progress: int = Field(ge=0, le=100)
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PipelineStageComplete(BaseModel):
    """Stage completion message for WebSocket."""
    type: Literal["stage-complete"] = "stage-complete"
    document_id: str
    stage: str
    duration: int  # seconds
    output: Optional[Dict[str, Any]] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PipelineError(BaseModel):
    """Error message for WebSocket."""
    type: Literal["error"] = "error"
    document_id: str
    stage: str
    error: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PipelineComplete(BaseModel):
    """Completion message for WebSocket."""
    type: Literal["complete"] = "complete"
    document_id: str
    status: PipelineStatus
    artifacts: List[str]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ReprocessRequest(BaseModel):
    """Request to reprocess a document."""
    force: bool = Field(default=False)
    stages: Optional[List[str]] = None  # Specific stages to rerun


class ReprocessResponse(BaseModel):
    """Response for reprocess request."""
    document_id: UUID4
    job_id: str
    status: PipelineStatus
    message: str


class ArtifactType(str, Enum):
    """Available artifact types."""
    VALIDATION = "validation"
    MANIFEST = "manifest"
    QA_REPORT = "qa_report"
    REVIEW_WORKSPACE = "review"
    TABLE_FIGURE = "table_figure"
