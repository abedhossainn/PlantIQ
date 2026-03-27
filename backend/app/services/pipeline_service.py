"""Pipeline Service - Manages HITL pipeline subprocess execution."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from uuid import UUID
from pathlib import Path
from typing import Optional, Dict, Any, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings, get_artifacts_path
from ..models.pipeline import (
    PipelineStatus,
    PipelineStatusResponse,
    PublicationStatus,
)
from ..models.sse import (
    IngestionCompleteEvent,
    IngestionErrorEvent,
    IngestionJobAcceptedEvent,
    IngestionProgressEvent,
    IngestionStageCompleteEvent,
)

logger = logging.getLogger(__name__)


def _utc_iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _optimized_output_has_usable_content(payload: dict[str, Any]) -> bool:
    chunks = payload.get("chunks")
    if not isinstance(chunks, list):
        return False

    for chunk in chunks:
        if isinstance(chunk, str) and chunk.strip():
            return True
        if not isinstance(chunk, dict):
            continue
        for key in ("content", "markdown", "body", "text"):
            if str(chunk.get(key) or "").strip():
                return True

    return False


def _read_valid_optimized_artifact_metadata(document_id: str) -> dict[str, Optional[str]] | None:
    work_dir = Path(settings.PIPELINE_WORK_DIR).expanduser().resolve() / document_id
    if not work_dir.exists():
        return None

    optimized_json_candidates = sorted(work_dir.glob("*_rag_optimized.json"))
    optimized_markdown_candidates = sorted(work_dir.glob("*_rag_optimized.md"))
    optimization_prep_candidates = sorted(work_dir.glob("*_optimization_prep.json"))

    optimized_json_path = optimized_json_candidates[0] if optimized_json_candidates else None
    optimized_markdown_path = optimized_markdown_candidates[0] if optimized_markdown_candidates else None
    optimization_prep_path = optimization_prep_candidates[0] if optimization_prep_candidates else None

    markdown_content = ""
    if optimized_markdown_path and optimized_markdown_path.is_file():
        markdown_content = optimized_markdown_path.read_text(encoding="utf-8").strip()

    payload: dict[str, Any] = {}
    if optimized_json_path and optimized_json_path.is_file():
        try:
            payload = json.loads(optimized_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

        payload_markdown = payload.get("markdown")
        if isinstance(payload_markdown, str) and payload_markdown.strip():
            markdown_content = payload_markdown.strip()

    if not _optimized_output_has_usable_content(payload) and not markdown_content:
        return None

    completion_sources = [
        path.stat().st_mtime
        for path in (optimized_json_path, optimized_markdown_path)
        if path is not None and path.exists()
    ]
    started_sources = [
        path.stat().st_mtime
        for path in (optimization_prep_path, optimized_json_path, optimized_markdown_path)
        if path is not None and path.exists()
    ]
    if not completion_sources:
        return None

    return {
        "started_at": _utc_iso_from_timestamp(min(started_sources)) if started_sources else None,
        "completed_at": _utc_iso_from_timestamp(max(completion_sources)),
    }


class PipelineService:
    """Service for managing pipeline subprocess execution."""
    
    # Track active pipeline processes
    _active_processes: Dict[str, asyncio.subprocess.Process] = {}
    _status_cache: Dict[str, PipelineStatusResponse] = {}
    _job_ids_by_document: Dict[str, str] = {}
    _event_history: Dict[str, list[dict[str, Any]]] = {}
    _event_subscribers: Dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    _status_progress_map = {
        PipelineStatus.PENDING.value: 0,
        PipelineStatus.UPLOADING.value: 10,
        PipelineStatus.EXTRACTING.value: 30,
        PipelineStatus.VLM_VALIDATING.value: 60,
        PipelineStatus.VALIDATION_COMPLETE.value: 100,
        PipelineStatus.IN_REVIEW.value: 100,
        PipelineStatus.REVIEW_COMPLETE.value: 100,
        PipelineStatus.APPROVED_FOR_OPTIMIZATION.value: 0,
        PipelineStatus.OPTIMIZING.value: 0,
        PipelineStatus.OPTIMIZATION_COMPLETE.value: 100,
        PipelineStatus.QA_REVIEW.value: 100,
        PipelineStatus.QA_PASSED.value: 100,
        PipelineStatus.FINAL_APPROVED.value: 100,
        PipelineStatus.APPROVED.value: 100,
        PipelineStatus.REJECTED.value: 100,
        PipelineStatus.FAILED.value: 0,
    }

    _status_stage_map = {
        PipelineStatus.UPLOADING.value: "upload",
        PipelineStatus.EXTRACTING.value: "extraction",
        PipelineStatus.VLM_VALIDATING.value: "validation",
        PipelineStatus.VALIDATION_COMPLETE.value: "validation",
        PipelineStatus.IN_REVIEW.value: "review",
        PipelineStatus.REVIEW_COMPLETE.value: "review",
        PipelineStatus.APPROVED_FOR_OPTIMIZATION.value: "optimization",
        PipelineStatus.OPTIMIZING.value: "optimization",
        PipelineStatus.OPTIMIZATION_COMPLETE.value: "optimization",
        PipelineStatus.QA_REVIEW.value: "qa",
        PipelineStatus.QA_PASSED.value: "qa",
        PipelineStatus.FINAL_APPROVED.value: "approved",
        PipelineStatus.APPROVED.value: "approved",
        PipelineStatus.REJECTED.value: "rejected",
        PipelineStatus.FAILED.value: "failed",
    }
    
    @classmethod
    async def trigger_pipeline(
        cls,
        document_id: str,
        pdf_path: str,
        reviewer: str,
        db: AsyncSession,
    ) -> str:
        """
        Trigger HITL pipeline for a document.
        
        Args:
            document_id: Document UUID
            pdf_path: Path to uploaded PDF file
            reviewer: Reviewer username
            db: Database session
            
        Returns:
            Job ID for tracking
        """
        document_id = str(document_id)
        pdf_path = str(pdf_path)
        reviewer = str(reviewer)
        job_id = str(uuid.uuid4())
        logger.info(f"Starting pipeline for document {document_id}, job {job_id}")
        cls._job_ids_by_document[document_id] = job_id
        
        # Update document status to extracting
        from sqlalchemy import text
        await db.execute(
            text("""
                UPDATE documents 
                SET status = 'extracting'
                WHERE id = :doc_id
            """),
            {"doc_id": document_id}
        )
        await db.commit()

        cls._publish_event(
            document_id,
            IngestionJobAcceptedEvent(
                document_id=document_id,
                job_id=job_id,
                message="Document upload accepted. Pipeline job queued.",
            ),
        )
        
        # Prepare pipeline command
        pdf_path = str(Path(pdf_path).expanduser().resolve())
        work_dir = Path(settings.PIPELINE_WORK_DIR).expanduser().resolve() / document_id
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate markdown path (pipeline will create the real Docling output)
        markdown_path = work_dir / f"{Path(pdf_path).stem}.md"
        
        pipeline_script = Path(settings.PIPELINE_SCRIPT_PATH).resolve()
        repo_root = pipeline_script.parents[3]

        cmd = [
            settings.PIPELINE_PYTHON_PATH,
            "-m",
            "pipeline.src.cli.hitl_pipeline",
            "run",
            "--pdf", pdf_path,
            "--markdown", str(markdown_path),
            "--workspace", str(work_dir),
            "--reviewer", reviewer,
        ]
        
        # Start subprocess asynchronously
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_root),
            )
            
            cls._active_processes[job_id] = process

            cls._publish_event(
                document_id,
                IngestionProgressEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage="extraction",
                    progress=30,
                    message="Pipeline started and extraction is in progress.",
                ),
            )
            
            # Monitor process in background
            asyncio.create_task(cls._monitor_pipeline(job_id, document_id, process, work_dir))
            
            logger.info(f"Pipeline started for document {document_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to start pipeline: {e}")
            cls._publish_event(
                document_id,
                IngestionErrorEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage="startup",
                    progress=0,
                    message="Failed to start ingestion pipeline.",
                    error=str(e),
                ),
            )
            # Update document status to failed
            from sqlalchemy import text
            await db.execute(
                text("UPDATE documents SET status = 'failed' WHERE id = :doc_id"),
                {"doc_id": document_id}
            )
            await db.commit()
            raise
    
    @classmethod
    async def _monitor_pipeline(
        cls,
        job_id: str,
        document_id: str,
        process: asyncio.subprocess.Process,
        work_dir: Path,
    ):
        """Monitor pipeline subprocess and stream live SSE events from structured stdout."""
        import json as _json

        PIPELINE_EVENT_PREFIX = b"PIPELINE_EVENT:"

        async def _stream_stdout() -> None:
            """Parse PIPELINE_EVENT: lines from subprocess stdout and emit SSE events."""
            assert process.stdout is not None
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                if not line.startswith(PIPELINE_EVENT_PREFIX):
                    continue
                raw = line[len(PIPELINE_EVENT_PREFIX):].strip()
                try:
                    payload = _json.loads(raw)
                    event_type = str(payload.get("event", "progress"))
                    stage = str(payload.get("stage", "extraction"))
                    progress = min(100, max(0, int(payload.get("progress", 0))))
                    message = str(payload.get("message", ""))
                    # stage_start events carry an optional human-readable step label.
                    if event_type == "stage_start":
                        label = str(payload["step"]) if payload.get("step") else message
                        cls._publish_event(
                            document_id,
                            IngestionProgressEvent(
                                document_id=document_id,
                                job_id=job_id,
                                stage=stage,
                                progress=progress,
                                message=label,
                            ),
                        )
                    else:
                        cls._publish_event(
                            document_id,
                            IngestionProgressEvent(
                                document_id=document_id,
                                job_id=job_id,
                                stage=stage,
                                progress=progress,
                                message=message,
                            ),
                        )
                except Exception:
                    pass  # Ignore malformed lines

        async def _drain_stderr() -> bytes:
            assert process.stderr is not None
            chunks: list[bytes] = []
            while True:
                chunk = await process.stderr.read(4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)

        stdout_task = asyncio.create_task(_stream_stdout())
        stderr_task = asyncio.create_task(_drain_stderr())

        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=settings.PIPELINE_TIMEOUT_SECONDS,
            )
            exit_code = process.returncode

            # Drain remaining buffered output before inspecting results.
            gather_results = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

            if exit_code == 0:
                logger.info(f"Pipeline completed successfully for document {document_id}")
                await cls._update_document_status(
                    document_id,
                    PipelineStatus.VALIDATION_COMPLETE,
                    progress=100,
                )
                artifact_path = str(work_dir)
                cls._publish_event(
                    document_id,
                    IngestionStageCompleteEvent(
                        document_id=document_id,
                        job_id=job_id,
                        stage="validation",
                        progress=100,
                        message="Pipeline validation stage completed.",
                        artifact_type="workspace",
                        artifact_path=artifact_path,
                    ),
                )
                cls._publish_event(
                    document_id,
                    IngestionCompleteEvent(
                        document_id=document_id,
                        job_id=job_id,
                        stage="completed",
                        progress=100,
                        message="Document ingestion completed successfully.",
                        artifact_type="workspace",
                        artifact_path=artifact_path,
                    ),
                )
            else:
                stderr_raw = gather_results[1]
                error_message = (
                    stderr_raw.decode(errors="replace")[-500:]
                    if isinstance(stderr_raw, bytes)
                    else ""
                )
                logger.error(f"Pipeline failed for document {document_id}: {error_message}")
                await cls._update_document_status(
                    document_id,
                    PipelineStatus.FAILED,
                    error=error_message,
                )
                cls._publish_event(
                    document_id,
                    IngestionErrorEvent(
                        document_id=document_id,
                        job_id=job_id,
                        stage="validation",
                        progress=cls._status_progress_map[PipelineStatus.EXTRACTING.value],
                        message="Document ingestion failed.",
                        error=error_message,
                    ),
                )

        except asyncio.TimeoutError:
            stdout_task.cancel()
            stderr_task.cancel()
            logger.error(f"Pipeline timed out for document {document_id}")
            process.kill()
            await cls._update_document_status(
                document_id,
                PipelineStatus.FAILED,
                error="Pipeline execution timed out",
            )
            cls._publish_event(
                document_id,
                IngestionErrorEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage="validation",
                    progress=cls._status_progress_map[PipelineStatus.EXTRACTING.value],
                    message="Document ingestion timed out.",
                    error="Pipeline execution timed out",
                ),
            )
        except Exception as e:
            stdout_task.cancel()
            stderr_task.cancel()
            logger.error(f"Pipeline monitoring error for document {document_id}: {e}")
            await cls._update_document_status(
                document_id,
                PipelineStatus.FAILED,
                error=str(e),
            )
            cls._publish_event(
                document_id,
                IngestionErrorEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage="monitoring",
                    progress=cls._status_progress_map[PipelineStatus.EXTRACTING.value],
                    message="Document ingestion monitoring failed.",
                    error=str(e),
                ),
            )
        finally:
            cls._active_processes.pop(job_id, None)
    
    @classmethod
    async def _update_document_status(
        cls,
        document_id: str,
        status: PipelineStatus,
        progress: int = 0,
        error: Optional[str] = None
    ):
        """Update document status in database."""
        from ..models.database import get_db_with_claims
        from sqlalchemy import text
        
        try:
            # Use a new session for background updates
            async for db in get_db_with_claims():
                values = {"status": status.value, "doc_id": document_id}
                sql = "UPDATE documents SET status = :status WHERE id = :doc_id"
                
                if error:
                    values["notes"] = error
                    sql = "UPDATE documents SET status = :status, notes = :notes WHERE id = :doc_id"
                
                await db.execute(text(sql), values)
                await db.commit()
                break  # Exit after first session
        except Exception as e:
            logger.error(f"Failed to update document status: {e}")
    
    @classmethod
    async def get_pipeline_status(
        cls,
        document_id: str,
        db: AsyncSession,
    ) -> PipelineStatusResponse:
        """
        Get current pipeline status for a document.
        
        Args:
            document_id: Document UUID
            db: Database session
            
        Returns:
            Pipeline status information
        """
        # Query database for document status
        from sqlalchemy import text
        
        result = await db.execute(
            text(
                """
                SELECT
                    status,
                    created_at,
                    updated_at,
                    notes,
                    optimization_started_at,
                    optimization_completed_at,
                    optimization_error,
                    publication_status,
                    published_at,
                    publication_error,
                    indexed_chunk_count,
                    qdrant_collection
                FROM documents
                WHERE id = :doc_id
                """
            ),
            {"doc_id": document_id}
        )
        row = result.fetchone()
        
        if not row:
            raise ValueError(f"Document {document_id} not found")
        
        (
            status,
            created_at,
            updated_at,
            notes,
            optimization_started_at,
            optimization_completed_at,
            optimization_error,
            publication_status,
            published_at,
            publication_error,
            indexed_chunk_count,
            qdrant_collection,
        ) = row

        if status in {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
        }:
            artifact_status = _read_valid_optimized_artifact_metadata(document_id)
            if artifact_status is not None:
                from sqlalchemy import text

                artifact_completed_at = (
                    datetime.fromisoformat(str(artifact_status["completed_at"]))
                    if artifact_status.get("completed_at")
                    else None
                )
                artifact_is_newer_than_current_run = (
                    artifact_completed_at is not None
                    and optimization_started_at is not None
                    and artifact_completed_at >= optimization_started_at
                )

                if optimization_started_at is None or artifact_is_newer_than_current_run:
                    status = PipelineStatus.OPTIMIZATION_COMPLETE.value
                    if optimization_started_at is None and artifact_status["started_at"]:
                        optimization_started_at = datetime.fromisoformat(
                            str(artifact_status["started_at"])
                        )
                    if optimization_completed_at is None and artifact_status["completed_at"]:
                        optimization_completed_at = artifact_completed_at
                    optimization_error = None

                    await db.execute(
                        text(
                            """
                            UPDATE documents
                            SET status = :status,
                                optimization_started_at = COALESCE(optimization_started_at, :optimization_started_at),
                                optimization_completed_at = COALESCE(optimization_completed_at, :optimization_completed_at),
                                optimization_error = NULL,
                                updated_at = NOW()
                            WHERE id = :doc_id
                            """
                        ),
                        {
                            "doc_id": document_id,
                            "status": status,
                            "optimization_started_at": optimization_started_at,
                            "optimization_completed_at": optimization_completed_at,
                        },
                    )
                    await db.commit()
        
        # Check if pipeline is active
        is_active = status in [
            PipelineStatus.UPLOADING.value,
            PipelineStatus.EXTRACTING.value,
            PipelineStatus.VLM_VALIDATING.value,
        ]
        
        progress = cls._status_progress_map.get(status, 0)
        stage = cls._status_stage_map.get(status)

        optimization_statuses = {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.FAILED.value,
        }
        started_at = (optimization_started_at or created_at) if status in optimization_statuses else created_at
        completed_at = (
            optimization_completed_at
            if status in {
                PipelineStatus.OPTIMIZATION_COMPLETE.value,
                PipelineStatus.FAILED.value,
            } and optimization_completed_at is not None
            else (updated_at if progress == 100 or status == PipelineStatus.FAILED.value else None)
        )
        error = optimization_error or (notes if status == PipelineStatus.FAILED.value else None)
        normalized_publication_status = publication_status
        if normalized_publication_status is None and status == PipelineStatus.FINAL_APPROVED.value:
            normalized_publication_status = PublicationStatus.PENDING.value
        
        return PipelineStatusResponse(
            document_id=UUID(document_id),
            status=PipelineStatus(status),
            current_stage=stage,
            progress=progress,
            message=error if status == PipelineStatus.FAILED.value else None,
            started_at=started_at,
            completed_at=completed_at,
            error=error,
            publication_status=normalized_publication_status,
            published_at=published_at,
            publication_error=publication_error,
            indexed_chunk_count=indexed_chunk_count,
            qdrant_collection=qdrant_collection,
        )

    @classmethod
    async def stream_events(
        cls,
        document_id: str,
        initial_status: PipelineStatusResponse,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream normalized ingestion SSE events with history replay."""
        history = list(cls._event_history.get(document_id, []))
        if history:
            for event in history:
                yield event
            if history[-1].get("event") in {"complete", "error"}:
                return
        else:
            for event in cls._build_initial_events(document_id, initial_status):
                yield event
            if initial_status.status in {PipelineStatus.VALIDATION_COMPLETE, PipelineStatus.FAILED}:
                return

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        subscribers = cls._event_subscribers.setdefault(document_id, set())
        subscribers.add(queue)

        try:
            while True:
                event = await queue.get()
                yield event
                if event.get("event") in {"complete", "error"}:
                    return
        finally:
            subscribers.discard(queue)
            if not subscribers:
                cls._event_subscribers.pop(document_id, None)

    @classmethod
    def _build_initial_events(
        cls,
        document_id: str,
        initial_status: PipelineStatusResponse,
    ) -> list[dict[str, Any]]:
        """Build SSE events from the current persisted pipeline status."""
        job_id = cls._job_ids_by_document.get(document_id)
        stage = initial_status.current_stage or cls._status_stage_map.get(initial_status.status.value, "pending")

        if initial_status.status == PipelineStatus.FAILED:
            return [
                IngestionErrorEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage=stage,
                    progress=initial_status.progress,
                    message=initial_status.message or "Document ingestion failed.",
                    error=initial_status.error or "Unknown pipeline error",
                ).model_dump(mode="json", exclude_none=True)
            ]

        if initial_status.status == PipelineStatus.VALIDATION_COMPLETE:
            return [
                IngestionStageCompleteEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage=stage,
                    progress=100,
                    message="Pipeline validation stage completed.",
                    artifact_type="workspace",
                    artifact_path=str(Path(settings.PIPELINE_WORK_DIR) / document_id),
                ).model_dump(mode="json", exclude_none=True),
                IngestionCompleteEvent(
                    document_id=document_id,
                    job_id=job_id,
                    stage="completed",
                    progress=100,
                    message="Document ingestion completed successfully.",
                    artifact_type="workspace",
                    artifact_path=str(Path(settings.PIPELINE_WORK_DIR) / document_id),
                ).model_dump(mode="json", exclude_none=True),
            ]

        return [
            IngestionProgressEvent(
                document_id=document_id,
                job_id=job_id,
                stage=stage,
                progress=initial_status.progress,
                message=initial_status.message or f"Document is currently in {stage}.",
            ).model_dump(mode="json", exclude_none=True)
        ]

    @classmethod
    def _publish_event(
        cls,
        document_id: str,
        event_model: IngestionJobAcceptedEvent
        | IngestionProgressEvent
        | IngestionStageCompleteEvent
        | IngestionCompleteEvent
        | IngestionErrorEvent,
    ) -> None:
        """Publish an ingestion event to history and active subscribers."""
        event_payload = event_model.model_dump(mode="json", exclude_none=True)
        history = cls._event_history.setdefault(document_id, [])
        history.append(event_payload)
        if len(history) > 20:
            del history[:-20]

        for queue in list(cls._event_subscribers.get(document_id, set())):
            try:
                queue.put_nowait(event_payload)
            except asyncio.QueueFull:
                logger.warning("Dropping pipeline event for %s due to full subscriber queue", document_id)
    
    @classmethod
    async def get_artifact(
        cls,
        document_id: str,
        artifact_type: str,
    ) -> Path:
        """
        Get path to document artifact.
        
        Args:
            document_id: Document UUID
            artifact_type: Type of artifact (validation, manifest, qa_report, etc.)
            
        Returns:
            Path to artifact file
        """
        artifact_path = get_artifacts_path(document_id, artifact_type)
        
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact {artifact_type} not found for document {document_id}")
        
        return artifact_path
