"""
Database helpers: status updates, document queries, status guard checks,
and HTTP response/error utilities shared across route handlers.
"""
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.pipeline import ArtifactType
from ._constants import _CLEAR, _LIST_DOCUMENTS_SQL, _SET_NOW, _UNCHANGED


def _apply_nullable_field_assignment(
    *,
    assignments: list[str],
    params: dict[str, object],
    column_name: str,
    param_name: str,
    value: object,
) -> None:
    if value is _CLEAR:
        assignments.append(f"{column_name} = NULL")
        return
    if value is _UNCHANGED:
        return
    assignments.append(f"{column_name} = :{param_name}")
    params[param_name] = value


def _apply_timestamp_field_assignment(
    *,
    assignments: list[str],
    params: dict[str, object],
    column_name: str,
    param_name: str,
    value: object,
) -> None:
    if value is _SET_NOW:
        assignments.append(f"{column_name} = NOW()")
        return
    if value is _CLEAR:
        assignments.append(f"{column_name} = NULL")
        return
    if value is _UNCHANGED:
        return
    assignments.append(f"{column_name} = :{param_name}")
    params[param_name] = value


# ---------------------------------------------------------------------------
# Status transition helpers
# ---------------------------------------------------------------------------

async def _set_document_status(
    db: AsyncSession,
    document_id,
    new_status: str,
    *,
    review_progress: Optional[int] = None,
    qa_score: object = _UNCHANGED,
    approved_by: Optional[str] = None,
    approved_at: bool = False,
    notes: Optional[str] = None,
    optimization_started_at: object = _UNCHANGED,
    optimization_completed_at: object = _UNCHANGED,
    optimization_error: object = _UNCHANGED,
    publication_status: object = _UNCHANGED,
    published_at: object = _UNCHANGED,
    publication_error: object = _UNCHANGED,
    indexed_chunk_count: object = _UNCHANGED,
    qdrant_collection: object = _UNCHANGED,
) -> None:
    from sqlalchemy import text as _text

    assignments = ["status = :new_status", "updated_at = NOW()"]
    params: dict[str, object] = {"doc_id": str(document_id), "new_status": new_status}

    if review_progress is not None:
        assignments.append("review_progress = :review_progress")
        params["review_progress"] = review_progress

    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="qa_score",
        param_name="qa_score",
        value=qa_score,
    )

    if approved_by is not None:
        assignments.append("approved_by = :approved_by")
        params["approved_by"] = approved_by
    if approved_at:
        assignments.append("approved_at = NOW()")
    if notes is not None:
        assignments.append("notes = :notes")
        params["notes"] = notes

    _apply_timestamp_field_assignment(
        assignments=assignments,
        params=params,
        column_name="optimization_started_at",
        param_name="optimization_started_at",
        value=optimization_started_at,
    )
    _apply_timestamp_field_assignment(
        assignments=assignments,
        params=params,
        column_name="optimization_completed_at",
        param_name="optimization_completed_at",
        value=optimization_completed_at,
    )
    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="optimization_error",
        param_name="optimization_error",
        value=optimization_error,
    )
    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="publication_status",
        param_name="publication_status",
        value=publication_status,
    )
    _apply_timestamp_field_assignment(
        assignments=assignments,
        params=params,
        column_name="published_at",
        param_name="published_at",
        value=published_at,
    )
    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="publication_error",
        param_name="publication_error",
        value=publication_error,
    )
    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="indexed_chunk_count",
        param_name="indexed_chunk_count",
        value=indexed_chunk_count,
    )
    _apply_nullable_field_assignment(
        assignments=assignments,
        params=params,
        column_name="qdrant_collection",
        param_name="qdrant_collection",
        value=qdrant_collection,
    )

    await db.execute(
        _text(f"UPDATE documents SET {', '.join(assignments)} WHERE id = :doc_id"),
        params,
    )
    await db.commit()


async def _fetch_document_rows(db: AsyncSession) -> list[dict]:
    from sqlalchemy import text as _text

    result = await db.execute(_text(_LIST_DOCUMENTS_SQL))
    return result.mappings().all()


async def _get_document_status_value(document_id: UUID4, db: AsyncSession) -> Optional[str]:
    from sqlalchemy import text as _text

    result = await db.execute(
        _text("SELECT status FROM documents WHERE id = :doc_id"),
        {"doc_id": str(document_id)},
    )
    row = result.fetchone()
    if not row:
        return None
    return row[0]


async def _require_document_status(document_id: UUID4, db: AsyncSession) -> str:
    """Return current document status or raise 404 when the document is missing."""
    document_status = await _get_document_status_value(document_id, db)
    if document_status is None:
        _raise_document_not_found()
    return document_status


# ---------------------------------------------------------------------------
# Status guard assertions
# ---------------------------------------------------------------------------

def _ensure_status_in(
    *,
    current_status: str,
    allowed_statuses: set[str],
    detail: str,
    error_status_code: int = status.HTTP_409_CONFLICT,
) -> None:
    """Raise HTTPException when a status is outside the allowed set."""
    if current_status not in allowed_statuses:
        raise HTTPException(
            status_code=error_status_code,
            detail=detail,
        )


def _ensure_status_not_in(
    *,
    current_status: str,
    blocked_statuses: set[str],
    detail: str,
    error_status_code: int = status.HTTP_409_CONFLICT,
) -> None:
    """Raise HTTPException when a status is inside a blocked set."""
    if current_status in blocked_statuses:
        raise HTTPException(
            status_code=error_status_code,
            detail=detail,
        )


# ---------------------------------------------------------------------------
# Request / response utilities
# ---------------------------------------------------------------------------

async def _read_request_json_or_empty(request: Request) -> dict:
    """Best-effort JSON payload parsing for permissive decision endpoints."""
    try:
        payload = await request.json()
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _raise_artifact_not_found(artifact_type: ArtifactType) -> None:
    """Raise a standardized artifact-not-found HTTP error."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Artifact {artifact_type} not found",
    )


def _raise_document_not_found() -> None:
    """Raise a standardized document-not-found HTTP error."""
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Document not found",
    )


def _build_artifact_file_response(artifact_path: Path) -> FileResponse:
    """Build a standardized FileResponse for artifact payloads."""
    return FileResponse(
        path=str(artifact_path),
        filename=artifact_path.name,
        media_type="application/json" if artifact_path.suffix == ".json" else "application/octet-stream",
    )
