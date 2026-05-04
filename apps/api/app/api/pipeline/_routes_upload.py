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
from ...core.security import get_current_user_id, get_jwt_payload
from ...core.sse import create_sse_response, encode_sse_event
from ...models.database import get_db
from ...models.pipeline import DocumentUploadResponse, PipelineStatus, PipelineStatusResponse
from ...services.access_governance_service import ScopeAccessDenied, enforce_upload_scope
from ...services.pipeline_service import PipelineService
from ._constants import pipeline_timestamp

logger = logging.getLogger(__name__)

router = APIRouter()


_UPLOAD_SOURCE_TYPES_BY_EXTENSION = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
}


def _resolve_upload_source_type(file: UploadFile) -> str | None:
    """Resolve supported upload source type from filename extension or MIME hint."""
    suffix = Path(file.filename or "").suffix.lower()
    source_type = _UPLOAD_SOURCE_TYPES_BY_EXTENSION.get(suffix)
    if source_type is not None:
        return source_type

    content_type = str(getattr(file, "content_type", "") or "").lower()
    if content_type == "application/pdf":
        return "pdf"
    if content_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    }:
        return "xlsx"
    return None


async def _resolve_missing_subscription_queue(
    *,
    doc_id: str,
    request: Request,
    db: AsyncSession,
    log_buffer: list[dict],
) -> tuple[list[dict], object, Optional[str], list[dict]]:
    queue = None
    final_status = OptimizationLogManager.get_final_status(doc_id)
    if final_status is not None:
        return log_buffer, queue, final_status, []

    status_info = await PipelineService.get_pipeline_status(document_id=doc_id, db=db)
    current_status = status_info.status.value

    if current_status in {
        PipelineStatus.OPTIMIZING.value,
        PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    }:
        deadline = asyncio.get_event_loop().time() + 30.0
        while asyncio.get_event_loop().time() < deadline:
            if await request.is_disconnected():
                return log_buffer, queue, "failed", []
            await asyncio.sleep(1.0)
            new_buffer, queue = OptimizationLogManager.subscribe(doc_id)
            if queue is None:
                continue

            already_seen = len(log_buffer)
            replay_entries = new_buffer[already_seen:]
            return new_buffer, queue, None, replay_entries

        logger.warning("Timed out waiting for OptimizationLogManager.start() for %s", doc_id)
        return log_buffer, queue, "failed", []

    terminal_status = (
        "failed"
        if current_status == PipelineStatus.FAILED.value
        else "optimization-complete"
    )
    return log_buffer, queue, OptimizationLogManager.get_final_status(doc_id) or terminal_status, []


async def _resolve_existing_subscription_queue(
    *,
    doc_id: str,
    db: AsyncSession,
    log_buffer: list[dict],
    queue,
) -> tuple[list[dict], object, Optional[str], list[dict]]:
    status_info = await PipelineService.get_pipeline_status(document_id=doc_id, db=db)
    current_status = status_info.status.value
    if not log_buffer and current_status in {
        PipelineStatus.OPTIMIZATION_COMPLETE.value,
        PipelineStatus.FAILED.value,
    }:
        OptimizationLogManager.unsubscribe(doc_id, queue)
        terminal_status = (
            "failed"
            if current_status == PipelineStatus.FAILED.value
            else "optimization-complete"
        )
        return log_buffer, queue, terminal_status, []

    return log_buffer, queue, None, []


async def _resolve_optimization_subscription_queue(
    *,
    doc_id: str,
    request: Request,
    db: AsyncSession,
    log_buffer: list[dict],
    queue,
) -> tuple[list[dict], object, Optional[str], list[dict]]:
    if queue is None:
        return await _resolve_missing_subscription_queue(
            doc_id=doc_id,
            request=request,
            db=db,
            log_buffer=log_buffer,
        )

    return await _resolve_existing_subscription_queue(
        doc_id=doc_id,
        db=db,
        log_buffer=log_buffer,
        queue=queue,
    )


async def _stream_optimization_queue_events(*, queue, request: Request, doc_id: str):
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
            continue
        if kind == "progress":
            yield encode_sse_event(payload)
            continue
        if kind == "done":
            yield encode_sse_event({"event": "done", **payload})
            return


async def _emit_optimization_initial_events(
    *,
    doc_id: str,
    log_buffer: list[dict],
    latest_progress: Optional[dict],
    queue,
):
    for entry in log_buffer:
        yield encode_sse_event({"event": "log", **entry})

    if latest_progress is not None:
        yield encode_sse_event(latest_progress)

    if queue is None:
        yield encode_sse_event(
            {"event": "ping", "document_id": doc_id, "timestamp": pipeline_timestamp()}
        )


async def _emit_optimization_live_events(
    *,
    doc_id: str,
    request: Request,
    queue,
    terminal_status: Optional[str],
    replay_entries: list[dict],
):
    if terminal_status is not None:
        yield encode_sse_event({"event": "done", "status": terminal_status})
        return

    for entry in replay_entries:
        yield encode_sse_event({"event": "log", **entry})

    if queue is None:
        yield encode_sse_event({"event": "done", "status": "failed"})
        return

    try:
        async for event_payload in _stream_optimization_queue_events(
            queue=queue,
            request=request,
            doc_id=doc_id,
        ):
            yield event_payload
    except asyncio.CancelledError:
        return
    finally:
        OptimizationLogManager.unsubscribe(doc_id, queue)


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    version: Optional[str] = Form(None),
    system: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user_id),
    jwt_payload: dict = Depends(get_jwt_payload),
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
    source_type = _resolve_upload_source_type(file)
    if source_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF, XLSX, and XLS files are allowed",
        )
    if source_type == "xlsx" and not settings.PIPELINE_XLSX_DISPATCH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Spreadsheet uploads are currently disabled by configuration",
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
        try:
            await enforce_upload_scope(
                db=db,
                user_id=current_user_id,
                claims=jwt_payload,
                system=system,
                endpoint="/api/v1/documents/upload",
            )
        except ScopeAccessDenied as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=exc.detail,
            )

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
            source_path=str(file_path),
            source_type=source_type,
        )

        return DocumentUploadResponse(
            document_id=UUID(document_id),
            status=PipelineStatus.EXTRACTING,
            file_path=str(file_path),
            message=f"Document uploaded successfully. Pipeline job {job_id} started.",
        )

    except HTTPException:
        raise
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
@router.get("/documents/{document_id}/events/")
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
@router.get("/documents/{document_id}/optimization/logs/")
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
        log_buffer, queue = OptimizationLogManager.subscribe(doc_id)
        latest_progress = OptimizationLogManager.get_progress_snapshot(doc_id)

        async for initial_event in _emit_optimization_initial_events(
            doc_id=doc_id,
            log_buffer=log_buffer,
            latest_progress=latest_progress,
            queue=queue,
        ):
            yield initial_event

        _, queue, terminal_status, replay_entries = await _resolve_optimization_subscription_queue(
            doc_id=doc_id,
            request=request,
            db=db,
            log_buffer=log_buffer,
            queue=queue,
        )

        async for live_event in _emit_optimization_live_events(
            doc_id=doc_id,
            request=request,
            queue=queue,
            terminal_status=terminal_status,
            replay_entries=replay_entries,
        ):
            yield live_event

    return create_sse_response(log_generator())
