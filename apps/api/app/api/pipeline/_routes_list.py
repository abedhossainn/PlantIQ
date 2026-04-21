"""Pipeline routes — document listing and deletion."""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import UUID4
from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.optimization_log import OptimizationLogManager
from ...core.config import settings
from ...core.security import get_current_user_id
from ...models.database import get_db
from ...models.pipeline import DocumentDeleteResponse, PipelineStatus
from ...services.pipeline_service import PipelineService
from ...services.pipeline_artifact_service import _read_valid_optimized_artifact_metadata
from ...services.qdrant_service import QdrantService
from ._constants import _DELETE_BLOCKED_STATUSES
from ._db_ops import _fetch_document_rows, _raise_document_not_found
from ._document_ops import _enrich_metadata_from_artifacts, _normalize_publication_status
from ._filesystem import _delete_document_storage

logger = logging.getLogger(__name__)

router = APIRouter()


_INGESTION_BLOCKED_STATUSES = {
    PipelineStatus.UPLOADING.value,
    PipelineStatus.EXTRACTING.value,
    PipelineStatus.VLM_VALIDATING.value,
}

_OPTIMIZATION_BLOCKED_STATUSES = {
    PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    PipelineStatus.OPTIMIZING.value,
}


def _is_recently_updated(updated_at: datetime | str | None) -> bool:
    """Return True when the row was updated within the stale grace interval."""
    if updated_at is None:
        return True

    normalized_updated_at = updated_at
    if isinstance(normalized_updated_at, str):
        try:
            normalized_updated_at = datetime.fromisoformat(normalized_updated_at)
        except ValueError:
            return True

    if normalized_updated_at.tzinfo is None:
        normalized_updated_at = normalized_updated_at.replace(tzinfo=timezone.utc)

    age_seconds = (datetime.now(timezone.utc) - normalized_updated_at).total_seconds()
    return age_seconds < settings.PIPELINE_STALLED_GRACE_SECONDS


def _delete_is_blocked_for_live_processing(
    *,
    document_id: str,
    status_value: str,
    updated_at: datetime | str | None,
) -> bool:
    """Block delete only when processing appears genuinely live (not stale)."""
    if status_value in _INGESTION_BLOCKED_STATUSES:
        if PipelineService._document_has_live_process(document_id):
            return True
        return _is_recently_updated(updated_at)

    if status_value in _OPTIMIZATION_BLOCKED_STATUSES:
        if OptimizationLogManager.is_active(document_id):
            return True
        return _is_recently_updated(updated_at)

    return status_value in _DELETE_BLOCKED_STATUSES


def _artifact_completed_after_status_update(
    *,
    artifact_completed_at: str | None,
    status_updated_at: datetime | str | None,
) -> bool:
    """Return True when optimized artifact completion is newer than current status update."""
    if not artifact_completed_at:
        return False

    try:
        completed = datetime.fromisoformat(artifact_completed_at)
    except ValueError:
        return False

    if completed.tzinfo is None:
        completed = completed.replace(tzinfo=timezone.utc)

    normalized_updated_at = status_updated_at
    if isinstance(normalized_updated_at, str):
        try:
            normalized_updated_at = datetime.fromisoformat(normalized_updated_at)
        except ValueError:
            normalized_updated_at = None

    if normalized_updated_at is None:
        return True

    if normalized_updated_at.tzinfo is None:
        normalized_updated_at = normalized_updated_at.replace(tzinfo=timezone.utc)

    return completed >= normalized_updated_at


@router.get("/documents")
async def list_documents(
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    List all documents with their current pipeline status.
    Returns rows from the `documents` table ordered by upload date descending.
    Lazily enriches NULL metadata from pipeline artifact files on first call.
    """
    try:
        rows = await _fetch_document_rows(db)

        stale_error = (
            "Ingestion appears to have stopped unexpectedly because no active "
            "pipeline process is running. Please reprocess this document."
        )
        stale_optimization_error = (
            "Optimization appears to have stopped unexpectedly because no active "
            "optimization process is running. Please retry optimization or delete this document."
        )

        stale_document_ids: list[str] = []
        stale_optimization_document_ids: list[str] = []
        reconciled_optimization_document_ids: list[str] = []
        for row in rows:
            row_id = str(row["id"])
            row_status = row["status"]
            row_updated_at = row["updated_at"]
            if PipelineService._is_stale_ingestion_status(
                document_id=row_id,
                status_value=row_status,
                updated_at=row_updated_at,
            ):
                stale_document_ids.append(row_id)

            if row_status in _OPTIMIZATION_BLOCKED_STATUSES:
                if OptimizationLogManager.is_active(row_id):
                    continue

                artifact_metadata = _read_valid_optimized_artifact_metadata(row_id)
                if artifact_metadata and _artifact_completed_after_status_update(
                    artifact_completed_at=artifact_metadata.get("completed_at"),
                    status_updated_at=row_updated_at,
                ):
                    reconciled_optimization_document_ids.append(row_id)
                    continue

                if not _is_recently_updated(row_updated_at):
                    stale_optimization_document_ids.append(row_id)

        if stale_document_ids or stale_optimization_document_ids or reconciled_optimization_document_ids:
            for stale_id in stale_document_ids:
                await db.execute(
                    _text(
                        """
                        UPDATE documents
                        SET status = 'failed',
                            notes = :notes,
                            updated_at = NOW()
                        WHERE id = :doc_id
                        """
                    ),
                    {"doc_id": stale_id, "notes": stale_error},
                )

            for stale_id in stale_optimization_document_ids:
                await db.execute(
                    _text(
                        """
                        UPDATE documents
                        SET status = 'failed',
                            notes = :notes,
                            optimization_completed_at = COALESCE(optimization_completed_at, NOW()),
                            optimization_error = COALESCE(optimization_error, :notes),
                            updated_at = NOW()
                        WHERE id = :doc_id
                        """
                    ),
                    {"doc_id": stale_id, "notes": stale_optimization_error},
                )

            for reconciled_id in reconciled_optimization_document_ids:
                await db.execute(
                    _text(
                        """
                        UPDATE documents
                        SET status = :status,
                            optimization_completed_at = COALESCE(optimization_completed_at, NOW()),
                            optimization_error = NULL,
                            updated_at = NOW()
                        WHERE id = :doc_id
                        """
                    ),
                    {
                        "doc_id": reconciled_id,
                        "status": PipelineStatus.OPTIMIZATION_COMPLETE.value,
                    },
                )

            await db.commit()
            rows = await _fetch_document_rows(db)

        docs = [
            {
                "id": str(row["id"]),
                "title": row["title"] or f"Document {str(row['id'])[:8]}…",
                "version": row["version"] or "1.0",
                "system": row["system"] or "—",
                "documentType": row["document_type"] or "PDF",
                "status": row["status"],
                "uploadedBy": row["uploaded_by"] or "—",
                "uploadedAt": row["uploaded_at"].isoformat() if row["uploaded_at"] else None,
                "notes": row["notes"],
                "totalPages": row["total_pages"],
                "totalSections": row["total_sections"],
                "reviewProgress": row["review_progress"],
                "qaScore": float(row["qa_score"]) if row["qa_score"] is not None else None,
                "approvedBy": str(row["approved_by"]) if row["approved_by"] else None,
                "approvedAt": row["approved_at"].isoformat() if row["approved_at"] else None,
                "publicationStatus": _normalize_publication_status(row["status"], row["publication_status"]),
                "publishedAt": row["published_at"].isoformat() if row["published_at"] else None,
                "publicationError": row["publication_error"],
                "indexedChunkCount": row["indexed_chunk_count"],
                "qdrantCollection": row["qdrant_collection"],
            }
            for row in rows
        ]
        if any(d["totalPages"] is None or d["totalSections"] is None or d["qaScore"] is None for d in docs):
            docs = await _enrich_metadata_from_artifacts(docs, db)
        return docs
    except Exception as exc:
        logger.error("Error listing documents: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents",
        )


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def delete_document(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a document and its related storage artifacts."""
    logger.info(
        "delete_document: user=%s is deleting document_id=%s",
        current_user_id,
        document_id,
    )

    result = await db.execute(
        _text(
            """
            SELECT title, file_path, status, updated_at
            FROM documents
            WHERE id = :doc_id
            """
        ),
        {"doc_id": str(document_id)},
    )
    row = result.mappings().first()

    if not row:
        _raise_document_not_found()

    if _delete_is_blocked_for_live_processing(
        document_id=str(document_id),
        status_value=row["status"],
        updated_at=row.get("updated_at"),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Documents cannot be deleted while ingestion or optimization is still running",
        )

    qdrant_deleted = await QdrantService.delete_document_chunks(str(document_id))
    if not qdrant_deleted:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove document chunks from vector storage",
        )

    try:
        deleted_paths = _delete_document_storage(
            document_id=document_id,
            document_title=row.get("title"),
            file_path=row.get("file_path"),
        )
    except OSError as exc:
        logger.error("Error deleting storage for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove document files from storage",
        ) from exc

    await db.execute(
        _text("DELETE FROM documents WHERE id = :doc_id"),
        {"doc_id": str(document_id)},
    )
    await db.commit()

    PipelineService._event_history.pop(str(document_id), None)
    PipelineService._event_subscribers.pop(str(document_id), None)
    PipelineService._job_ids_by_document.pop(str(document_id), None)
    PipelineService._status_cache.pop(str(document_id), None)
    OptimizationLogManager.clear_document(str(document_id))

    return DocumentDeleteResponse(
        document_id=document_id,
        qdrant_chunks_deleted=True,
        deleted_paths=deleted_paths,
        message="Document and related artifacts deleted successfully.",
    )
