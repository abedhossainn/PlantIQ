"""
Pipeline API Endpoints.

Endpoints for document upload, pipeline control, and artifact retrieval.
"""
import logging
import shutil
from pathlib import Path
from typing import Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
    UploadFile,
    File,
    Form,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import UUID4
from uuid import UUID

from ..core.config import settings, get_upload_path
from ..core.security import get_current_user_id
from ..models.database import get_db
from ..models.pipeline import (
    DocumentUploadResponse,
    PipelineStatusResponse,
    ReprocessRequest,
    ReprocessResponse,
    ArtifactType,
    PipelineStatus,
)
from ..services.pipeline_service import PipelineService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Pipeline"])


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    version: Optional[str] = Form(None),
    system: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a new PDF document and trigger processing pipeline.
    
    - Validates file type and size
    - Saves file to storage
    - Creates database record
    - Triggers HITL pipeline subprocess
    - Returns document ID and initial status
    """
    # Validate file extension
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )
    
    # Validate file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to start
    
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )
    
    logger.info(f"Uploading document: {file.filename} ({file_size} bytes)")
    
    try:
        # Generate unique document ID
        import uuid
        document_id = str(uuid.uuid4())
        
        # Save file to upload directory
        safe_filename = f"{document_id}_{file.filename}"
        file_path = get_upload_path(safe_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"File saved to: {file_path}")
        
        # Create document record in database
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO documents (
                    id, title, version, system, document_type, 
                    file_path, status, uploaded_by, notes,
                    uploaded_at, created_at, updated_at
                )
                VALUES (
                    :id, :title, :version, :system, :doc_type,
                    :file_path, :status, :user_id, :notes,
                    NOW(), NOW(), NOW()
                )
            """),
            {
                "id": document_id,
                "title": title,
                "version": version,
                "system": system,
                "doc_type": document_type,
                "file_path": str(file_path),
                "status": PipelineStatus.UPLOADING.value,
                "user_id": current_user_id,
                "notes": notes,
            }
        )
        await db.commit()
        
        logger.info(f"Document record created: {document_id}")
        
        # Trigger pipeline asynchronously
        job_id = await PipelineService.trigger_pipeline(
            document_id=document_id,
            pdf_path=str(file_path),
            reviewer=str(current_user_id),
            db=db,
        )
        
        return DocumentUploadResponse(
            document_id=UUID(document_id),
            status=PipelineStatus.EXTRACTING,
            file_path=str(file_path),
            message=f"Document uploaded successfully. Pipeline job {job_id} started.",
        )
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("/documents/{document_id}/status", response_model=PipelineStatusResponse)
async def get_document_status(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current processing status for a document.
    
    Returns:
        - Current status (pending, extracting, validating, complete, etc.)
        - Progress percentage
        - Current stage
        - Start/completion timestamps
        - Error message if failed
    """
    try:
        status_info = await PipelineService.get_pipeline_status(
            document_id=str(document_id),
            db=db,
        )
        return status_info
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get document status"
        )


@router.post("/documents/{document_id}/reprocess", response_model=ReprocessResponse)
async def reprocess_document(
    document_id: UUID4,
    request: ReprocessRequest,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger reprocessing of a document.
    
    - Can reprocess entire pipeline or specific stages
    - Requires document to be in validation-complete or failed state
    - force=True allows reprocessing approved documents
    """
    # TODO: Implement reprocessing logic
    # For now, return not implemented
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Reprocessing not yet implemented"
    )


@router.get("/documents/{document_id}/artifacts/{artifact_type}")
async def get_document_artifact(
    document_id: UUID4,
    artifact_type: ArtifactType,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Download document processing artifacts.
    
    Available artifact types:
    - validation: Validation report (JSON)
    - manifest: Document manifest (JSON)
    - qa_report: QA metrics report (JSON)
    - review: Review workspace (ZIP)
    - table_figure: Table/figure report (JSON)
    """
    try:
        artifact_path = await PipelineService.get_artifact(
            document_id=str(document_id),
            artifact_type=artifact_type.value,
        )
        
        if not artifact_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact {artifact_type} not found"
            )
        
        # Return file for download
        return FileResponse(
            path=str(artifact_path),
            filename=artifact_path.name,
            media_type="application/json" if artifact_path.suffix == ".json" else "application/octet-stream"
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting artifact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve artifact"
        )
