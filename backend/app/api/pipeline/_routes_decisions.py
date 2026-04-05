"""Pipeline routes — review workflow decisions (QA, approval)."""
import logging
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import get_artifacts_path
from ...core.security import get_current_user_id
from ...models.database import get_db
from ...models.pipeline import PipelineStatus, PublicationStatus, QARescoreResponse
from ._constants import _CLEAR, _FINALIZED_STATUSES, _QA_RESCORE_ALLOWED_STATUSES
from ._db_ops import (
    _ensure_status_in,
    _ensure_status_not_in,
    _read_request_json_or_empty,
    _require_document_status,
    _set_document_status,
)
from ._document_ops import _approve_for_optimization
from ._filesystem import _load_json_file
from ._qa import _compute_and_persist_qa_report

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/documents/{document_id}/approve-for-optimization")
async def approve_for_optimization(
    document_id: UUID4,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Approve reviewed content for Stage 10 optimization and trigger the optimization flow."""
    return await _approve_for_optimization(document_id, background_tasks, current_user_id, db)


@router.post("/documents/{document_id}/review-complete")
async def mark_review_complete(
    document_id: UUID4,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Compatibility alias for approve-for-optimization."""
    return await _approve_for_optimization(document_id, background_tasks, current_user_id, db)


@router.post("/documents/{document_id}/qa-rescore", response_model=QARescoreResponse)
async def rescore_document_qa(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Recompute QA gate results from persisted optimization output artifacts."""
    del current_user_id

    try:
        document_status = await _require_document_status(document_id, db)
        _ensure_status_not_in(
            current_status=document_status,
            blocked_statuses=_FINALIZED_STATUSES,
            detail=f"Cannot rescore document in {document_status} status",
        )
        _ensure_status_in(
            current_status=document_status,
            allowed_statuses=_QA_RESCORE_ALLOWED_STATUSES,
            detail="QA rescore is only available for documents after optimization has completed",
        )

        result = await _compute_and_persist_qa_report(
            document_id=document_id,
            db=db,
            persisted_status=PipelineStatus.QA_REVIEW.value,
        )

        return QARescoreResponse(
            document_id=document_id,
            decision=result.decision,
            passed_criteria=result.passed_criteria,
            failed_criteria=result.failed_criteria,
            recommendations=result.recommendations,
            metrics=asdict(result.metrics),
            timestamp=result.timestamp,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error rescoring QA for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to rescore QA report",
        )


@router.post("/documents/{document_id}/qa-decision")
async def record_qa_decision(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Record QA gate decision (accept → qa-passed; reject → rejected)."""
    payload = await _read_request_json_or_empty(request)

    decision = payload.get("decision")
    if decision not in ("accept", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'accept' or 'reject'",
        )

    current_status = await _require_document_status(document_id, db)
    _ensure_status_not_in(
        current_status=current_status,
        blocked_statuses=_FINALIZED_STATUSES,
        detail=f"Cannot record QA decision for document in {current_status} status",
    )

    if decision == "accept":
        qa_report_path = get_artifacts_path(
            str(document_id),
            "qa_report",
            allow_legacy_qa_fallback=False,
        )
        if not qa_report_path.exists() or not qa_report_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="QA report not found; run QA rescore on the optimized output first",
            )

        try:
            qa_report = _load_json_file(qa_report_path)
        except Exception as exc:
            logger.error("Failed to read QA report for %s: %s", document_id, exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="QA report could not be read; it may be corrupt",
            )
        if qa_report.get("decision") == "rejected":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="QA criteria currently fail; rescore and resolve issues before accepting",
            )

    new_status = (
        PipelineStatus.QA_PASSED.value if decision == "accept" else PipelineStatus.REJECTED.value
    )
    try:
        await _set_document_status(db, document_id, new_status)
        return {"status": new_status}
    except Exception as exc:
        logger.error("Error recording QA decision for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record QA decision",
        )


@router.post("/documents/{document_id}/final-approve")
async def final_approve_document(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Record final approval or rejection decision."""
    payload = await _read_request_json_or_empty(request)

    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'approve' or 'reject'",
        )

    current_status = await _require_document_status(document_id, db)
    _ensure_status_not_in(
        current_status=current_status,
        blocked_statuses=_FINALIZED_STATUSES,
        detail=f"Document is already in {current_status} status",
    )

    if decision == "approve" and current_status != PipelineStatus.QA_PASSED.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Final approval requires a QA-passed document",
        )

    new_status = (
        PipelineStatus.FINAL_APPROVED.value if decision == "approve" else PipelineStatus.REJECTED.value
    )
    notes = payload.get("notes") or None
    try:
        await _set_document_status(
            db,
            document_id,
            new_status,
            approved_by=current_user_id,
            approved_at=True,
            notes=notes,
            publication_status=(PublicationStatus.PENDING.value if decision == "approve" else _CLEAR),
            published_at=_CLEAR,
            publication_error=_CLEAR,
            indexed_chunk_count=_CLEAR,
            qdrant_collection=_CLEAR,
        )
        return {"status": new_status}
    except Exception as exc:
        logger.error("Error recording final approval for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record approval decision",
        )
