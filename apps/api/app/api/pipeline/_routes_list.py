"""Pipeline routes — document listing and deletion."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import UUID4
from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.optimization_log import OptimizationLogManager
from ...core.security import get_current_user_id
from ...models.database import get_db
from ...models.pipeline import DocumentDeleteResponse, PipelineStatus
from ...services.pipeline_service import PipelineService
from ...services.qdrant_service import QdrantService
from ._constants import _DELETE_BLOCKED_STATUSES
from ._db_ops import _fetch_document_rows, _raise_document_not_found
from ._document_ops import _enrich_metadata_from_artifacts, _normalize_publication_status
from ._filesystem import _delete_document_storage

logger = logging.getLogger(__name__)

router = APIRouter()


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

        stale_document_ids: list[str] = []
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

        if stale_document_ids:
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
            SELECT title, file_path, status
            FROM documents
            WHERE id = :doc_id
            """
        ),
        {"doc_id": str(document_id)},
    )
    row = result.mappings().first()

    if not row:
        _raise_document_not_found()

    if row["status"] in _DELETE_BLOCKED_STATUSES:
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
