"""Pipeline Service - Manages HITL pipeline subprocess execution."""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, AsyncIterator
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings, get_artifacts_path
from ..models.pipeline import (
    PipelineStatus,
    PipelineStatusResponse,
)
from ..models.sse import (
    IngestionCompleteEvent,
    IngestionErrorEvent,
    IngestionJobAcceptedEvent,
    IngestionProgressEvent,
    IngestionStageCompleteEvent,
)

logger = logging.getLogger(__name__)

from .pipeline_status_service import PipelineStatusMixin


class PipelineService(PipelineStatusMixin):
    """Service for managing pipeline subprocess execution.
    
    HITL Pipeline Lifecycle:
    The pipeline orchestrates document processing through distinct phases:
    
    INGESTION (fast, automated):
    1. UPLOADING: File receipt and storage
    2. EXTRACTING: Docling PDF-to-markdown conversion
    3. VLM_VALIDATING: Vision-language model checks content and issues
    => VALIDATION_COMPLETE: Ingestion terminal state (ready for human review)
    
    REVIEW (human-driven):
    1. IN_REVIEW: Reviewer examines pages, facts, figures; optional edits
    2. REVIEW_COMPLETE: All pages reviewed; ready for decision
    => APPROVED_FOR_OPTIMIZATION or REJECTED
    
    OPTIMIZATION (heavy computation, optional):
    1. OPTIMIZING: Chunking, cleaning, semantic enhancement for RAG
    2. OPTIMIZATION_COMPLETE: Output ready for QA decision
    => QA_REVIEW
    
    QA (automated metric checks):
    1. QA_REVIEW: Re-score chunks, assess coverage, emit recommendation
    2. QA_PASSED: Metrics acceptable, eligible for final approval
    => FINAL_APPROVED
    
    TERMINAL STATES: APPROVED, REJECTED, FAILED (no further transitions)
    
    Operational Notes:
    - Only one active ingestion request per document
    - Status changes drive state machine logic (e.g., can't delete while optimizing)
    - Event stream subscribers notified on progress changes
    - Subprocess stdout/stderr captured for artifact logs
    """
    
    # Track active subprocess processes keyed by job_id (UUID)
    _active_processes: Dict[str, asyncio.subprocess.Process] = {}
    
    # Cache latest status for each document (avoids repeated DB queries during polling)
    _status_cache: Dict[str, PipelineStatusResponse] = {}
    
    # Map document_id -> job_id for process lifecycle tracking
    _job_ids_by_document: Dict[str, str] = {}
    
    # Event history retained per document (enables client reconnect without losing updates)
    _event_history: Dict[str, list[dict[str, Any]]] = {}
    
    # SSE subscribers listening for real-time updates per document
    _event_subscribers: Dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}

    # Progress percentage thresholds for each ingestion/review/optimization status.
    # Used for frontend progress bar rendering (0-100%).
    # INGESTION phases: 10% -> 30% -> 60% -> 100% (completion)
    # REVIEW phases: maintained at 100% (human-driven, no ETA)
    # OPTIMIZATION/QA: similar stepped progression
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

    # Map status values to operational stage names (used in UI + APIs).
    # Enables frontend grouping of statuses (e.g., all review-related statuses -> "review" stage).
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

    # Status values representing active ingestion (subprocess running, no human input).
    # Used to detect stalled processes (if status is stale AND no live subprocess).
    _active_ingestion_statuses = {
        PipelineStatus.UPLOADING.value,
        PipelineStatus.EXTRACTING.value,
        PipelineStatus.VLM_VALIDATING.value,
    }

    _source_type_extensions = {
        "pdf": {".pdf"},
        "xlsx": {".xlsx", ".xls"},
    }

    @classmethod
    def detect_source_type(cls, source_path: str, source_type: Optional[str] = None) -> str:
        """Resolve the canonical pipeline source type from explicit input or file extension."""
        if source_type in cls._source_type_extensions:
            return str(source_type)

        suffix = Path(source_path).suffix.lower()
        for candidate, suffixes in cls._source_type_extensions.items():
            if suffix in suffixes:
                return candidate

        raise ValueError(f"Unsupported pipeline source type for path: {source_path}")

    @classmethod
    def _build_pipeline_subprocess_env(cls, *, source_type: str) -> dict[str, str]:
        """Build subprocess environment with explicit source-type and XLSX feature flags."""
        env = os.environ.copy()
        env["PIPELINE_SOURCE_TYPE"] = source_type
        env["PIPELINE_XLSX_DISPATCH_ENABLED"] = str(settings.PIPELINE_XLSX_DISPATCH_ENABLED).lower()
        env["PIPELINE_XLSX_STRUCTURED_RELATIONS_ENABLED"] = (
            str(settings.PIPELINE_XLSX_STRUCTURED_RELATIONS_ENABLED).lower()
        )
        env["PIPELINE_XLSX_RETRIEVAL_ENABLED"] = str(settings.PIPELINE_XLSX_RETRIEVAL_ENABLED).lower()
        env["PIPELINE_CE_EXTRACTION_ENABLED"] = env["PIPELINE_XLSX_STRUCTURED_RELATIONS_ENABLED"]
        env["PIPELINE_CE_RETRIEVAL_ENABLED"] = env["PIPELINE_XLSX_RETRIEVAL_ENABLED"]
        return env

    @classmethod
    def _publish_pipeline_progress_event(
        cls,
        *,
        document_id: str,
        job_id: str,
        stage: str,
        progress: int,
        message: str,
        event_type: str,
        step: Optional[str],
    ) -> None:
        """Publish normalized ingestion progress events parsed from pipeline output."""
        if event_type == "stage_start":
            message = step if step else message

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

    @classmethod
    async def _stream_pipeline_stdout_events(
        cls,
        *,
        process: asyncio.subprocess.Process,
        document_id: str,
        job_id: str,
        pipeline_event_prefix: bytes,
    ) -> None:
        """Parse structured stdout events emitted by the pipeline subprocess."""
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            if not line.startswith(pipeline_event_prefix):
                continue

            raw = line[len(pipeline_event_prefix):].strip()
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue

            event_type = str(payload.get("event", "progress"))
            stage = str(payload.get("stage", "extraction"))
            progress = min(100, max(0, int(payload.get("progress", 0))))
            message = str(payload.get("message", ""))
            step = str(payload["step"]) if payload.get("step") else None

            cls._publish_pipeline_progress_event(
                document_id=document_id,
                job_id=job_id,
                stage=stage,
                progress=progress,
                message=message,
                event_type=event_type,
                step=step,
            )

    @classmethod
    async def _drain_pipeline_stderr(
        cls,
        *,
        process: asyncio.subprocess.Process,
    ) -> bytes:
        """Read and return the full stderr stream from a pipeline subprocess."""
        assert process.stderr is not None
        chunks: list[bytes] = []
        while True:
            chunk = await process.stderr.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    async def _handle_pipeline_success(
        cls,
        *,
        document_id: str,
        job_id: str,
        work_dir: Path,
    ) -> None:
        """Persist and publish successful completion state/events."""
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

    @classmethod
    async def _handle_pipeline_failed_exit(
        cls,
        *,
        document_id: str,
        job_id: str,
        stderr_raw: bytes | None,
    ) -> None:
        """Persist and publish failure state/events for non-zero process exits."""
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

    @classmethod
    async def _handle_pipeline_timeout(
        cls,
        *,
        document_id: str,
        job_id: str,
        process: asyncio.subprocess.Process,
        stdout_task: asyncio.Task[Any],
        stderr_task: asyncio.Task[Any],
    ) -> None:
        """Handle pipeline timeout by cancelling streams, killing process, and publishing failure."""
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

    @classmethod
    async def _handle_pipeline_monitoring_exception(
        cls,
        *,
        document_id: str,
        job_id: str,
        error: Exception,
        stdout_task: asyncio.Task[Any],
        stderr_task: asyncio.Task[Any],
    ) -> None:
        """Handle unexpected monitoring errors and publish failure state."""
        stdout_task.cancel()
        stderr_task.cancel()
        logger.error(f"Pipeline monitoring error for document {document_id}: {error}")
        await cls._update_document_status(
            document_id,
            PipelineStatus.FAILED,
            error=str(error),
        )
        cls._publish_event(
            document_id,
            IngestionErrorEvent(
                document_id=document_id,
                job_id=job_id,
                stage="monitoring",
                progress=cls._status_progress_map[PipelineStatus.EXTRACTING.value],
                message="Document ingestion monitoring failed.",
                error=str(error),
            ),
        )

    @classmethod
    async def trigger_pipeline(
        cls,
        document_id: str,
        pdf_path: str,
        reviewer: str,
        db: AsyncSession,
        *,
        source_path: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> str:
        """
        Trigger HITL pipeline for a document.
        
        Args:
            document_id: Document UUID
            pdf_path: Backward-compatible path to uploaded source file
            reviewer: Reviewer username
            db: Database session
            source_path: Explicit source path override
            source_type: Explicit source type override (pdf|xlsx)
            
        Returns:
            Job ID for tracking
        """
        document_id = str(document_id)
        resolved_source_path = str(source_path or pdf_path)
        resolved_source_type = cls.detect_source_type(resolved_source_path, source_type)
        reviewer = str(reviewer)
        job_id = str(uuid.uuid4())
        logger.info(
            "Starting pipeline for document %s, job %s (source_type=%s)",
            document_id,
            job_id,
            resolved_source_type,
        )
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
        resolved_source_path = str(Path(resolved_source_path).expanduser().resolve())
        work_dir = Path(settings.PIPELINE_WORK_DIR).expanduser().resolve() / document_id
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate markdown path (pipeline will create the real Docling output)
        markdown_path = work_dir / f"{Path(resolved_source_path).stem}.md"
        
        pipeline_script = Path(settings.PIPELINE_SCRIPT_PATH).resolve()
        repo_root = pipeline_script.parents[4]

        cmd = [
            settings.PIPELINE_PYTHON_PATH,
            "-m",
            "pipeline.src.cli.hitl_pipeline",
            "run",
            "--pdf", resolved_source_path,
            "--markdown", str(markdown_path),
            "--workspace", str(work_dir),
            "--reviewer", reviewer,
            "--source-type", resolved_source_type,
        ]
        
        # Start subprocess asynchronously
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_root),
                env=cls._build_pipeline_subprocess_env(source_type=resolved_source_type),
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
        PIPELINE_EVENT_PREFIX = b"PIPELINE_EVENT:"

        stdout_task = asyncio.create_task(
            cls._stream_pipeline_stdout_events(
                process=process,
                document_id=document_id,
                job_id=job_id,
                pipeline_event_prefix=PIPELINE_EVENT_PREFIX,
            )
        )
        stderr_task = asyncio.create_task(cls._drain_pipeline_stderr(process=process))

        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=settings.PIPELINE_TIMEOUT_SECONDS,
            )
            exit_code = process.returncode

            # Drain remaining buffered output before inspecting results.
            gather_results = await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

            if exit_code == 0:
                await cls._handle_pipeline_success(
                    document_id=document_id,
                    job_id=job_id,
                    work_dir=work_dir,
                )
            else:
                stderr_raw = gather_results[1]
                await cls._handle_pipeline_failed_exit(
                    document_id=document_id,
                    job_id=job_id,
                    stderr_raw=stderr_raw if isinstance(stderr_raw, bytes) else None,
                )

        except asyncio.TimeoutError:
            await cls._handle_pipeline_timeout(
                document_id=document_id,
                job_id=job_id,
                process=process,
                stdout_task=stdout_task,
                stderr_task=stderr_task,
            )
        except Exception as e:
            await cls._handle_pipeline_monitoring_exception(
                document_id=document_id,
                job_id=job_id,
                error=e,
                stdout_task=stdout_task,
                stderr_task=stderr_task,
            )
        finally:
            cls._active_processes.pop(job_id, None)
    
    @classmethod
    async def stream_events(
        cls,
        document_id: str,
        initial_status: PipelineStatusResponse,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream normalized ingestion SSE events with history replay."""
        should_continue = cls._replay_history_or_initial_events(
            document_id=document_id,
            initial_status=initial_status,
        )
        async for event in should_continue:
            yield event

        if should_continue.is_terminal:
            return

        queue = cls._subscribe_event_queue(document_id)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=14.0)
                except asyncio.TimeoutError:
                    yield cls._build_ping_event(document_id)
                    continue
                yield event
                if cls._is_terminal_event(event):
                    return
        finally:
            cls._unsubscribe_event_queue(document_id=document_id, queue=queue)

    @classmethod
    def _is_terminal_event(cls, event: dict[str, Any]) -> bool:
        return event.get("event") in {"complete", "error"}

    @classmethod
    def _build_ping_event(cls, document_id: str) -> dict[str, Any]:
        return {
            "event": "ping",
            "document_id": document_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    class _ReplayResult:
        def __init__(self, events: list[dict[str, Any]], is_terminal: bool):
            self.events = events
            self.is_terminal = is_terminal

        def __aiter__(self):
            async def _generator():
                for event in self.events:
                    yield event

            return _generator()

    @classmethod
    def _replay_history_or_initial_events(
        cls,
        *,
        document_id: str,
        initial_status: PipelineStatusResponse,
    ) -> _ReplayResult:
        history = list(cls._event_history.get(document_id, []))
        if history:
            return cls._ReplayResult(
                events=history,
                is_terminal=cls._is_terminal_event(history[-1]),
            )

        initial_events = cls._build_initial_events(document_id, initial_status)
        is_terminal = initial_status.status in {PipelineStatus.VALIDATION_COMPLETE, PipelineStatus.FAILED}
        return cls._ReplayResult(events=initial_events, is_terminal=is_terminal)

    @classmethod
    def _subscribe_event_queue(cls, document_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        subscribers = cls._event_subscribers.setdefault(document_id, set())
        subscribers.add(queue)
        return queue

    @classmethod
    def _unsubscribe_event_queue(cls, *, document_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        subscribers = cls._event_subscribers.get(document_id)
        if not subscribers:
            return
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
