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

        if cls._is_stale_ingestion_status(
            document_id=document_id,
            status_value=status,
            updated_at=updated_at,
        ):
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

            status = PipelineStatus.FAILED.value
            notes = stale_error
            updated_at = datetime.now(timezone.utc)

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

        if status in {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
        }:
            artifact_status = _read_valid_optimized_artifact_metadata(document_id)
            if artifact_status is not None:
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
