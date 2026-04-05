"""Pipeline routes — publishing, reprocessing, and artifact download."""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_artifacts_path
from ...core.security import get_current_user_id
from ...models.database import get_db
from ...models.pipeline import (
    ArtifactType,
    DocumentPublishResponse,
    PipelineStatus,
    PublicationStatus,
    ReprocessRequest,
    ReprocessResponse,
)
from ...services.pipeline_service import PipelineService
from ._constants import (
    _CLEAR,
    _FINALIZED_STATUSES,
    _QA_REPORT_AUTOGEN_ELIGIBLE_STATUSES,
    _SET_NOW,
    is_post_optimization_lifecycle,
)
from ._db_ops import (
    _build_artifact_file_response,
    _raise_artifact_not_found,
    _raise_document_not_found,
    _require_document_status,
    _set_document_status,
)
from ._document_ops import _normalize_publication_status, _publish_document_to_rag
from ._filesystem import _find_document_workspace
from sqlalchemy import text as _text
from ._qa import _compute_and_persist_qa_report

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/documents/{document_id}/publish", response_model=DocumentPublishResponse)
async def publish_document(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Publish a final-approved document into the RAG knowledge base."""
    del current_user_id

    result = await db.execute(
        _text(
            """
            SELECT title, system, document_type, status, publication_status
            FROM documents
            WHERE id = :doc_id
            """
        ),
        {"doc_id": str(document_id)},
    )
    row = result.mappings().first()

    if not row:
        _raise_document_not_found()

    document_status = row["status"]
    publication_status = _normalize_publication_status(document_status, row["publication_status"])

    if document_status != PipelineStatus.FINAL_APPROVED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only final-approved documents can be published to RAG",
        )

    if publication_status == PublicationStatus.PUBLISHING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document publication is already in progress",
        )

    if publication_status == PublicationStatus.PUBLISHED.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Document is already published to RAG",
        )

    work_dir = _find_document_workspace(document_id, require_document_dir=True)

    await _set_document_status(
        db,
        document_id,
        document_status,
        publication_status=PublicationStatus.PUBLISHING.value,
        published_at=_CLEAR,
        publication_error=_CLEAR,
        indexed_chunk_count=_CLEAR,
        qdrant_collection=_CLEAR,
    )

    try:
        publish_result = await _publish_document_to_rag(
            document_id=str(document_id),
            document_title=str(row["title"] or document_id),
            system=row["system"],
            document_type=row["document_type"],
            work_dir=work_dir,
        )

        await _set_document_status(
            db,
            document_id,
            document_status,
            publication_status=PublicationStatus.PUBLISHED.value,
            published_at=_SET_NOW,
            publication_error=_CLEAR,
            indexed_chunk_count=publish_result["indexed_chunk_count"],
            qdrant_collection=publish_result["qdrant_collection"],
        )

        status_result = await db.execute(
            _text(
                """
                SELECT published_at, publication_error, indexed_chunk_count, qdrant_collection
                FROM documents
                WHERE id = :doc_id
                """
            ),
            {"doc_id": str(document_id)},
        )
        status_row = status_result.mappings().first() or {}

        return DocumentPublishResponse(
            document_id=document_id,
            status=PipelineStatus(document_status),
            publication_status=PublicationStatus.PUBLISHED,
            published_at=status_row.get("published_at"),
            publication_error=status_row.get("publication_error"),
            indexed_chunk_count=status_row.get("indexed_chunk_count"),
            qdrant_collection=status_row.get("qdrant_collection"),
            message="Document published to RAG knowledge base successfully.",
        )
    except HTTPException:
        raise
    except Exception as exc:
        await _set_document_status(
            db,
            document_id,
            document_status,
            publication_status=PublicationStatus.FAILED.value,
            published_at=_CLEAR,
            publication_error=str(exc),
            indexed_chunk_count=_CLEAR,
        )
        logger.error("Error publishing document %s to RAG: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to publish document to RAG",
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
    Looks up the original file_path from the database row and re-runs the pipeline.
    force=True allows reprocessing approved/rejected documents.
    """
    try:
        result = await db.execute(
            _text("SELECT status, file_path FROM documents WHERE id = :doc_id"),
            {"doc_id": str(document_id)},
        )
        row = result.mappings().first()
    except Exception as exc:
        logger.error("DB lookup failed for reprocess %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to look up document",
        )

    if not row:
        _raise_document_not_found()

    if row["status"] in _FINALIZED_STATUSES and not getattr(request, "force", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is {row['status']}. Pass force=true to reprocess.",
        )

    pdf_path = row["file_path"]
    if not Path(pdf_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Original PDF file not found on disk",
        )

    try:
        job_id = await PipelineService.trigger_pipeline(
            document_id=str(document_id),
            pdf_path=pdf_path,
            reviewer=str(current_user_id),
            db=db,
        )
        return ReprocessResponse(
            document_id=document_id,
            job_id=job_id,
            status=PipelineStatus.EXTRACTING,
            message=f"Reprocessing started. Job {job_id}.",
        )
    except Exception as exc:
        logger.error("Reprocess failed for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Reprocess failed due to an internal error",
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
        document_status = await _require_document_status(document_id, db)

        if artifact_type == ArtifactType.QA_REPORT:
            allow_legacy_qa_fallback = not is_post_optimization_lifecycle(document_status)
            artifact_path = get_artifacts_path(
                str(document_id),
                artifact_type.value,
                allow_legacy_qa_fallback=allow_legacy_qa_fallback,
            )
            if not artifact_path.exists():
                if not allow_legacy_qa_fallback:
                    if document_status in _QA_REPORT_AUTOGEN_ELIGIBLE_STATUSES:
                        target_status = (
                            PipelineStatus.QA_REVIEW.value
                            if document_status == PipelineStatus.OPTIMIZATION_COMPLETE.value
                            else document_status
                        )
                        try:
                            await _compute_and_persist_qa_report(
                                document_id=document_id,
                                db=db,
                                persisted_status=target_status,
                            )
                            artifact_path = get_artifacts_path(
                                str(document_id),
                                artifact_type.value,
                                allow_legacy_qa_fallback=False,
                            )
                        except HTTPException as exc:
                            logger.warning(
                                "Unable to auto-generate QA report for %s during artifact fetch: %s",
                                document_id,
                                exc.detail,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Unexpected failure auto-generating QA report for %s: %s",
                                document_id,
                                exc,
                            )

                    if artifact_path.exists():
                        return _build_artifact_file_response(artifact_path)

                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=(
                            "Post-optimization QA report not found; "
                            "run QA rescore on the optimized output first"
                        ),
                    )
                _raise_artifact_not_found(artifact_type)
        else:
            artifact_path = await PipelineService.get_artifact(
                document_id=str(document_id),
                artifact_type=artifact_type.value,
            )

        if not artifact_path.exists():
            _raise_artifact_not_found(artifact_type)

        return _build_artifact_file_response(artifact_path)

    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error getting artifact: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve artifact",
        )
