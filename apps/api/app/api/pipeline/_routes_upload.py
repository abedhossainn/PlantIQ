"""Pipeline routes — document upload, status, and event streaming."""
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import UUID4
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.optimization_log import OptimizationLogManager
from ...core.security import get_current_user_id
from ...core.sse import create_sse_response, encode_sse_event
from ...models.database import get_db
from ...models.pipeline import DocumentUploadResponse, PipelineStatus, PipelineStatusResponse
from ...services.pipeline_service import PipelineService
from ._constants import pipeline_timestamp

logger = logging.getLogger(__name__)

router = APIRouter()


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
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed",
        )

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)

    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    logger.info("Uploading document: %s (%s bytes)", file.filename, file_size)

    try:
        document_id = str(uuid4())
        # Restrict to the bare filename to prevent path traversal via user-supplied name
        safe_filename = f"{document_id}_{Path(file.filename).name}"
        # Lazy lookup through the package so tests can monkeypatch pipeline_api.get_upload_path
        import app.api.pipeline as _pipeline_pkg  # noqa: PLC0415 (circular import; must stay lazy)
        file_path = _pipeline_pkg.get_upload_path(safe_filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        logger.info("File saved to: %s", file_path)

        try:
            await db.execute(
                text(
                    """
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
                    """
                ),
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
                },
            )
            await db.commit()
        except Exception:
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not clean up orphaned upload file: %s", file_path)
            raise

        logger.info("Document record created: %s", document_id)

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

    except Exception as exc:
        logger.error("Upload failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload failed due to an internal error",
        )


@router.get("/documents/{document_id}/status", response_model=PipelineStatusResponse)
async def get_document_status(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Get current processing status for a document."""
    try:
        status_info = await PipelineService.get_pipeline_status(
            document_id=str(document_id),
            db=db,
        )
        return status_info
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("Error getting status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get document status",
        )


@router.get("/documents/{document_id}/events")
async def stream_document_events(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Stream normalized ingestion progress events as SSE."""
    try:
        status_info = await PipelineService.get_pipeline_status(
            document_id=str(document_id),
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("Error streaming document events: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stream document events",
        )

    async def event_generator():
        event_stream = PipelineService.stream_events(
            document_id=str(document_id),
            initial_status=status_info,
        )
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await anext(event_stream)
                except StopAsyncIteration:
                    return
                yield encode_sse_event(event)
        except asyncio.CancelledError:
            return
        finally:
            await event_stream.aclose()

    return create_sse_response(event_generator())


@router.get("/documents/{document_id}/optimization/logs")
async def stream_optimization_logs(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Stream Stage 10 optimization log lines as SSE.

    Events:
      - ``log``  — ``{"event": "log", "timestamp": "<iso>", "level": "INFO|WARNING|ERROR", "message": "<text>"}``
      - ``done`` — ``{"event": "done", "status": "optimization-complete"|"failed"}``
    """
    doc_id = str(document_id)

    try:
        await PipelineService.get_pipeline_status(document_id=doc_id, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        logger.error("Status check failed for optimization log stream %s: %s", doc_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start optimization log stream",
        )

    async def log_generator():
        buffer, queue = OptimizationLogManager.subscribe(doc_id)
        latest_progress = OptimizationLogManager.get_progress_snapshot(doc_id)

        for entry in buffer:
            yield encode_sse_event({"event": "log", **entry})

        if latest_progress is not None:
            yield encode_sse_event(latest_progress)

        if queue is None:
            yield encode_sse_event(
                {
                    "event": "done",
                    "status": OptimizationLogManager.get_final_status(doc_id) or "optimization-complete",
                }
            )
            return

        status_info = await PipelineService.get_pipeline_status(document_id=doc_id, db=db)
        current_status = status_info.status.value
        if not buffer and current_status in {
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.FAILED.value,
        }:
            yield encode_sse_event(
                {
                    "event": "done",
                    "status": (
                        "failed"
                        if current_status == PipelineStatus.FAILED.value
                        else "optimization-complete"
                    ),
                }
            )
            return

        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield encode_sse_event(
                        {
                            "event": "ping",
                            "document_id": doc_id,
                            "timestamp": pipeline_timestamp(),
                        }
                    )
                    continue

                if kind == "log":
                    yield encode_sse_event({"event": "log", **payload})
                elif kind == "progress":
                    yield encode_sse_event(payload)
                elif kind == "done":
                    yield encode_sse_event({"event": "done", **payload})
                    return
        except asyncio.CancelledError:
            return
        finally:
            OptimizationLogManager.unsubscribe(doc_id, queue)

    return create_sse_response(log_generator())
