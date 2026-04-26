"""Pipeline status mixin - status query and update class methods for PipelineService.

This mixin is designed to be used as a base class for PipelineService. The methods
defined here reference class attributes that must be provided by the concrete class:

    - _active_processes: Dict[str, asyncio.subprocess.Process]
    - _job_ids_by_document: Dict[str, str]
    - _active_ingestion_statuses: set[str]
    - _status_progress_map: dict[str, int]
    - _status_stage_map: dict[str, str]
    - _publish_event: classmethod

All attributes are resolved at runtime via `cls`, so the concrete class must define
them before any of these methods are called.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import settings
from ..models.pipeline import (
    PipelineStatus,
    PipelineStatusResponse,
    PublicationStatus,
)
from ..models.sse import IngestionErrorEvent
from .pipeline_artifact_service import _read_valid_optimized_artifact_metadata

logger = logging.getLogger(__name__)


class PipelineStatusMixin:
    """Mixin providing status query and update methods for PipelineService."""

    @classmethod
    def _document_has_live_process(cls, document_id: str) -> bool:
        job_id = cls._job_ids_by_document.get(document_id)
        if not job_id:
            return False

        process = cls._active_processes.get(job_id)
        return process is not None and process.returncode is None

    @classmethod
    def _is_stale_ingestion_status(
        cls,
        *,
        document_id: str,
        status_value: str,
        updated_at: Optional[datetime],
    ) -> bool:
        if status_value not in cls._active_ingestion_statuses:
            return False

        if cls._document_has_live_process(document_id):
            return False

        if updated_at is None:
            return False

        normalized_updated_at = updated_at
        if isinstance(normalized_updated_at, str):
            try:
                normalized_updated_at = datetime.fromisoformat(normalized_updated_at)
            except ValueError:
                return False

        if normalized_updated_at.tzinfo is None:
            normalized_updated_at = normalized_updated_at.replace(tzinfo=timezone.utc)

        age_seconds = (datetime.now(timezone.utc) - normalized_updated_at).total_seconds()
        return age_seconds >= settings.PIPELINE_STALLED_GRACE_SECONDS

    @classmethod
    async def _update_document_status(
        cls,
        document_id: str,
        status: PipelineStatus,
        progress: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Update document status in database."""
        from ..models.database import get_db_with_claims

        try:
            # Use a new session for background updates
            async for db in get_db_with_claims():
                values: dict[str, Any] = {"status": status.value, "doc_id": document_id}
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
            {"doc_id": document_id},
        )
        row = result.fetchone()

        if not row:
            raise ValueError(f"Document {document_id} not found")
        status_payload = cls._status_payload_from_row(row)
        status_payload = await cls._reconcile_stale_ingestion_status(
            document_id=document_id,
            db=db,
            status_payload=status_payload,
        )
        status_payload = await cls._reconcile_optimization_completion_status(
            document_id=document_id,
            db=db,
            status_payload=status_payload,
        )

        return cls._build_pipeline_status_response(document_id, status_payload)

    @classmethod
    def _status_payload_from_row(cls, row: Any) -> dict[str, Any]:
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
        return {
            "status": status,
            "created_at": created_at,
            "updated_at": updated_at,
            "notes": notes,
            "optimization_started_at": optimization_started_at,
            "optimization_completed_at": optimization_completed_at,
            "optimization_error": optimization_error,
            "publication_status": publication_status,
            "published_at": published_at,
            "publication_error": publication_error,
            "indexed_chunk_count": indexed_chunk_count,
            "qdrant_collection": qdrant_collection,
        }

    @classmethod
    async def _reconcile_stale_ingestion_status(
        cls,
        *,
        document_id: str,
        db: AsyncSession,
        status_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not cls._is_stale_ingestion_status(
            document_id=document_id,
            status_value=status_payload["status"],
            updated_at=status_payload["updated_at"],
        ):
            return status_payload

        stale_error = (
            "Ingestion appears to have stopped unexpectedly because no active "
            "pipeline process is running. Please reprocess this document."
        )

        await db.execute(
            text(
                """
                UPDATE documents
                SET status = :failed_status,
                    notes = :notes,
                    updated_at = NOW()
                WHERE id = :doc_id
                """
            ),
            {
                "doc_id": document_id,
                "failed_status": PipelineStatus.FAILED.value,
                "notes": stale_error,
            },
        )
        await db.commit()

        status_payload["status"] = PipelineStatus.FAILED.value
        status_payload["notes"] = stale_error
        status_payload["updated_at"] = datetime.now(timezone.utc)

        cls._publish_event(
            document_id,
            IngestionErrorEvent(
                document_id=document_id,
                job_id=cls._job_ids_by_document.get(document_id),
                stage="monitoring",
                progress=cls._status_progress_map[PipelineStatus.EXTRACTING.value],
                message="Document ingestion stalled.",
                error=stale_error,
            ),
        )

        return status_payload

    @classmethod
    async def _reconcile_optimization_completion_status(
        cls,
        *,
        document_id: str,
        db: AsyncSession,
        status_payload: dict[str, Any],
    ) -> dict[str, Any]:
        if not cls._needs_optimization_completion_reconcile(status_payload["status"]):
            return status_payload

        artifact_status = _read_valid_optimized_artifact_metadata(document_id)
        if artifact_status is None:
            return status_payload

        artifact_completed_at = cls._parse_iso_datetime(artifact_status.get("completed_at"))
        optimization_started_at = status_payload["optimization_started_at"]
        if not cls._is_valid_artifact_for_current_run(
            artifact_completed_at=artifact_completed_at,
            optimization_started_at=optimization_started_at,
        ):
            return status_payload

        optimization_started_at = cls._resolve_optimization_started_at(
            optimization_started_at=optimization_started_at,
            artifact_started_at=artifact_status.get("started_at"),
        )

        optimization_completed_at = cls._resolve_optimization_completed_at(
            optimization_completed_at=status_payload["optimization_completed_at"],
            artifact_completed_at=artifact_completed_at,
            raw_artifact_completed_at=artifact_status.get("completed_at"),
        )

        status_payload["status"] = PipelineStatus.OPTIMIZATION_COMPLETE.value
        status_payload["optimization_started_at"] = optimization_started_at
        status_payload["optimization_completed_at"] = optimization_completed_at
        status_payload["optimization_error"] = None

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
                "status": status_payload["status"],
                "optimization_started_at": status_payload["optimization_started_at"],
                "optimization_completed_at": status_payload["optimization_completed_at"],
            },
        )
        await db.commit()
        return status_payload

    @classmethod
    def _needs_optimization_completion_reconcile(cls, status: str) -> bool:
        return status in {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
        }

    @classmethod
    def _parse_iso_datetime(cls, value: Any) -> datetime | None:
        if not value:
            return None
        return datetime.fromisoformat(str(value))

    @classmethod
    def _is_valid_artifact_for_current_run(
        cls,
        *,
        artifact_completed_at: datetime | None,
        optimization_started_at: datetime | None,
    ) -> bool:
        if optimization_started_at is None:
            return True
        if artifact_completed_at is None:
            return False
        return artifact_completed_at >= optimization_started_at

    @classmethod
    def _resolve_optimization_started_at(
        cls,
        *,
        optimization_started_at: datetime | None,
        artifact_started_at: Any,
    ) -> datetime | None:
        if optimization_started_at is not None:
            return optimization_started_at
        return cls._parse_iso_datetime(artifact_started_at)

    @classmethod
    def _resolve_optimization_completed_at(
        cls,
        *,
        optimization_completed_at: datetime | None,
        artifact_completed_at: datetime | None,
        raw_artifact_completed_at: Any,
    ) -> datetime | None:
        if optimization_completed_at is not None:
            return optimization_completed_at
        if not raw_artifact_completed_at:
            return optimization_completed_at
        return artifact_completed_at

    @classmethod
    def _build_pipeline_status_response(
        cls,
        document_id: str,
        status_payload: dict[str, Any],
    ) -> PipelineStatusResponse:
        status = status_payload["status"]
        progress = cls._status_progress_map.get(status, 0)
        stage = cls._status_stage_map.get(status)

        started_at = cls._resolve_status_started_at(status=status, status_payload=status_payload)
        completed_at = cls._resolve_status_completed_at(
            status=status,
            progress=progress,
            status_payload=status_payload,
        )
        error = cls._resolve_status_error(status=status, status_payload=status_payload)
        normalized_publication_status = cls._resolve_publication_status(
            status=status,
            publication_status=status_payload["publication_status"],
        )

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
            published_at=status_payload["published_at"],
            publication_error=status_payload["publication_error"],
            indexed_chunk_count=status_payload["indexed_chunk_count"],
            qdrant_collection=status_payload["qdrant_collection"],
        )

    @classmethod
    def _resolve_status_started_at(cls, *, status: str, status_payload: dict[str, Any]) -> datetime:
        optimization_statuses = {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.FAILED.value,
        }
        if status not in optimization_statuses:
            return status_payload["created_at"]
        return status_payload["optimization_started_at"] or status_payload["created_at"]

    @classmethod
    def _resolve_status_completed_at(
        cls,
        *,
        status: str,
        progress: int,
        status_payload: dict[str, Any],
    ) -> datetime | None:
        if status in {
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.FAILED.value,
        } and status_payload["optimization_completed_at"] is not None:
            return status_payload["optimization_completed_at"]
        if progress == 100 or status == PipelineStatus.FAILED.value:
            return status_payload["updated_at"]
        return None

    @classmethod
    def _resolve_status_error(cls, *, status: str, status_payload: dict[str, Any]) -> Any:
        if status_payload["optimization_error"]:
            return status_payload["optimization_error"]
        if status == PipelineStatus.FAILED.value:
            return status_payload["notes"]
        return None

    @classmethod
    def _resolve_publication_status(cls, *, status: str, publication_status: Any) -> Any:
        if publication_status is None and status == PipelineStatus.FINAL_APPROVED.value:
            return PublicationStatus.PENDING.value
        return publication_status
