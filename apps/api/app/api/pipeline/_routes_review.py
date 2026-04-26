"""Pipeline routes — document review workspace (sections, pages, chunks)."""
import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.security import get_current_user_id
from ...models.database import get_db
from ...models.pipeline import (
    DocumentOptimizedChunksResponse,
    DocumentPagesResponse,
    OptimizedChunkResponse,
    OptimizedChunkUpdate,
    PageContentUpdate,
    PipelineStatus,
)
from ._chunks import (
    _build_editable_optimized_chunks,
    _extract_page_numbers_from_chunk,
    _preview_text,
    _save_optimized_chunks,
)
from ._constants import _CLEAR, _OPTIMIZED_OUTPUT_AVAILABLE_STATUSES, _OPTIMIZED_OUTPUT_EDITABLE_STATUSES
from ._db_ops import _ensure_status_in, _require_document_status, _set_document_status
from ._filesystem import _find_document_workspace, _find_review_workspace, _load_json_file
from ._review import (
    _build_page_response,
    _build_review_progress,
    _derive_section_page_numbers,
    _ensure_page_review_manifest,
    _resolve_evidence_file,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _safe_subpath(base: Path, rel: str) -> Path:
    """Resolve *rel* under *base*; raise HTTP 400 if the resolved path escapes *base*."""
    resolved = (base / rel).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid path in document manifest",
        )
    return resolved


def _section_page_numbers(sec: dict, content: str, page_entries: list[dict]) -> list[int]:
    raw_page_numbers = sec.get("page_numbers", [])
    page_numbers = [int(page) for page in raw_page_numbers]
    if page_numbers:
        return page_numbers

    pages_match = re.search(r"<!-- Pages: ([0-9, ]+) -->", content)
    if pages_match:
        return [
            int(page.strip())
            for page in pages_match.group(1).split(",")
            if page.strip().isdigit()
        ]

    return _derive_section_page_numbers(content, page_entries)


def _section_payload(section: dict, content: str, checklist: dict, page_numbers: list[int]) -> dict:
    page_start = page_numbers[0] if page_numbers else None
    page_end = page_numbers[-1] if page_numbers else None
    sec_id = section.get("section_id", "")
    return {
        "id": sec_id,
        "heading": section.get("heading", sec_id),
        "status": section.get("status", "PENDING").lower(),
        "content": content,
        "checklist": checklist,
        "pageRange": {"start": page_start, "end": page_end},
        "pageNumbers": page_numbers,
    }


async def _parse_optimized_chunk_update_request(request: Request) -> OptimizedChunkUpdate:
    try:
        return OptimizedChunkUpdate.model_validate(await request.json())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="heading and markdown_content are required",
        )


def _get_target_editable_chunk(editable_chunks: list[dict], chunk_id: str) -> dict:
    target_chunk = next((chunk for chunk in editable_chunks if chunk["id"] == chunk_id), None)
    if target_chunk is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Optimized chunk not found",
        )
    return target_chunk


def _apply_optimized_chunk_update(target_chunk: dict, payload: OptimizedChunkUpdate) -> None:
    target_chunk["heading"] = payload.heading.strip()
    target_chunk["markdown_content"] = payload.markdown_content.strip()
    target_chunk["table_facts"] = [fact.strip() for fact in payload.table_facts if fact.strip()]
    target_chunk["ambiguity_flags"] = [flag.strip() for flag in payload.ambiguity_flags if flag.strip()]
    target_chunk["source_pages"] = _extract_page_numbers_from_chunk(
        target_chunk,
        target_chunk["markdown_content"],
    )


def _load_editable_optimized_chunk_bundle(work_dir: Path) -> tuple[dict, str, list[dict], Path, Path]:
    (
        optimized_payload,
        document_name,
        editable_chunks,
        optimized_json_path,
        optimized_markdown_path,
    ) = _build_editable_optimized_chunks(work_dir)
    return (
        optimized_payload,
        document_name,
        editable_chunks,
        optimized_json_path,
        optimized_markdown_path,
    )


def _persist_optimized_chunk_updates(
    *,
    optimized_payload: dict,
    document_name: str,
    editable_chunks: list[dict],
    optimized_json_path: Path,
    optimized_markdown_path: Path,
    work_dir: Path,
) -> None:
    _save_optimized_chunks(
        optimized_payload=optimized_payload,
        document_name=document_name,
        editable_chunks=editable_chunks,
        optimized_json_path=optimized_json_path,
        optimized_markdown_path=optimized_markdown_path,
        work_dir=work_dir,
    )


@router.get("/documents/{document_id}/sections")
async def get_document_sections(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return sections from the pipeline review workspace for a document."""
    work_dir = _find_document_workspace(document_id, require_document_dir=True)
    review_dir = _find_review_workspace(document_id)
    manifest_path = review_dir / "review_manifest.json"
    if not manifest_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="review_manifest.json not found",
        )
    try:
        manifest = _load_json_file(manifest_path)
        page_manifest = _ensure_page_review_manifest(review_dir, work_dir)
        page_entries = page_manifest.get("pages", [])
        sections_out = []
        for sec in manifest.get("sections", []):
            content_path = _safe_subpath(review_dir, sec.get("file", ""))
            content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""

            checklist_path = _safe_subpath(review_dir, sec.get("checklist", ""))
            checklist = _load_json_file(checklist_path) if checklist_path.exists() else {}

            page_numbers = _section_page_numbers(sec, content, page_entries)
            sections_out.append(_section_payload(sec, content, checklist, page_numbers))
        return {"documentName": manifest.get("document_name", ""), "sections": sections_out}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error loading sections for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load document sections",
        )


@router.get("/documents/{document_id}/pages", response_model=DocumentPagesResponse)
async def get_document_pages(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
):
    """Return page-based review units sourced from validation artifacts."""
    del current_user_id

    try:
        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        review_dir = _find_review_workspace(document_id)
        page_manifest = _ensure_page_review_manifest(review_dir, work_dir)
        pages = [
            _build_page_response(document_id, review_dir, work_dir, page_entry)
            for page_entry in page_manifest.get("pages", [])
        ]
        return DocumentPagesResponse(
            document_name=page_manifest.get("document_name", ""),
            pages=pages,
            progress=_build_review_progress(pages),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error loading page review units for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load document pages",
        )


@router.get("/documents/{document_id}/pages/{page_number}/thumbnail")
async def get_document_page_thumbnail(
    document_id: UUID4,
    page_number: int,
    current_user_id: str = Depends(get_current_user_id),
):
    """Return the thumbnail image for a single review page when available."""
    del current_user_id

    review_dir = _find_review_workspace(document_id)
    work_dir = _find_document_workspace(document_id, require_document_dir=True)
    page_manifest = _ensure_page_review_manifest(review_dir, work_dir)

    page_entry = next(
        (
            entry
            for entry in page_manifest.get("pages", [])
            if int(entry.get("page_number", -1)) == page_number
        ),
        None,
    )
    if page_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page review unit not found",
        )

    evidence_payload = dict(page_entry.get("evidence") or {})
    thumbnail_file = _resolve_evidence_file(work_dir, evidence_payload.get("thumbnail_path"))
    if thumbnail_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Thumbnail not found for this page",
        )

    return FileResponse(path=str(thumbnail_file), media_type="image/png", filename=thumbnail_file.name)


@router.patch("/documents/{document_id}/pages/{page_id}/content")
async def update_document_page_content(
    document_id: UUID4,
    page_id: str,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
):
    """Persist updated markdown content for a page review unit."""
    del current_user_id

    try:
        payload = PageContentUpdate.model_validate(await request.json())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="markdown_content is required",
        )

    review_dir = _find_review_workspace(document_id)
    work_dir = _find_document_workspace(document_id, require_document_dir=True)
    page_manifest = _ensure_page_review_manifest(review_dir, work_dir)
    page_entry = next(
        (page for page in page_manifest.get("pages", []) if page.get("page_id") == page_id),
        None,
    )

    if page_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page review unit not found",
        )

    file_path = _safe_subpath(review_dir, str(page_entry.get("file") or ""))
    manifest_path = review_dir / "page_review_manifest.json"

    page_entry["markdown_content"] = payload.markdown_content

    try:
        file_path.write_text(payload.markdown_content, encoding="utf-8")
        manifest_path.write_text(json.dumps(page_manifest, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Error saving page content for %s/%s: %s", document_id, page_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save page content",
        )

    return {"page_id": page_id, "status": "saved"}


@router.get("/documents/{document_id}/optimized-chunks", response_model=DocumentOptimizedChunksResponse)
async def get_document_optimized_chunks(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return editable optimized chunks for the post-optimization editor."""
    del current_user_id

    document_status = await _require_document_status(document_id, db)
    _ensure_status_in(
        current_status=document_status,
        allowed_statuses=_OPTIMIZED_OUTPUT_AVAILABLE_STATUSES,
        detail="Optimized output is only available after optimization has completed",
    )

    try:
        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        _optimized_payload, document_name, editable_chunks, _json_path, _markdown_path = (
            _build_editable_optimized_chunks(work_dir)
        )
        return DocumentOptimizedChunksResponse(
            document_name=document_name,
            chunks=[
                OptimizedChunkResponse(
                    id=chunk["id"],
                    chunk_number=index,
                    heading=chunk["heading"],
                    markdown_content=chunk["markdown_content"],
                    text_preview=_preview_text(chunk["markdown_content"]),
                    source_pages=chunk.get("source_pages") or [],
                    table_facts=chunk.get("table_facts") or [],
                    ambiguity_flags=chunk.get("ambiguity_flags") or [],
                )
                for index, chunk in enumerate(editable_chunks, start=1)
            ],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error loading optimized chunks for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load optimized chunks",
        )


@router.patch("/documents/{document_id}/optimized-chunks/{chunk_id}")
async def update_document_optimized_chunk(
    document_id: UUID4,
    chunk_id: str,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Persist updated optimized chunk content and invalidate stale QA results."""
    del current_user_id

    document_status = await _require_document_status(document_id, db)
    _ensure_status_in(
        current_status=document_status,
        allowed_statuses=_OPTIMIZED_OUTPUT_EDITABLE_STATUSES,
        detail="Optimized output can only be edited before QA has passed",
    )

    payload = await _parse_optimized_chunk_update_request(request)

    try:
        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        (
            optimized_payload,
            document_name,
            editable_chunks,
            optimized_json_path,
            optimized_markdown_path,
        ) = _load_editable_optimized_chunk_bundle(work_dir)

        target_chunk = _get_target_editable_chunk(editable_chunks, chunk_id)
        _apply_optimized_chunk_update(target_chunk, payload)

        _persist_optimized_chunk_updates(
            optimized_payload=optimized_payload,
            document_name=document_name,
            editable_chunks=editable_chunks,
            optimized_json_path=optimized_json_path,
            optimized_markdown_path=optimized_markdown_path,
            work_dir=work_dir,
        )

        from ._qa import _remove_stale_qa_report

        _remove_stale_qa_report(document_id, work_dir)

        await _set_document_status(
            db,
            document_id,
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            qa_score=_CLEAR,
        )
    except HTTPException:
        raise
    except OSError as exc:
        logger.error("Error saving optimized chunk for %s/%s: %s", document_id, chunk_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save optimized chunk",
        )
    except Exception as exc:
        logger.error("Error updating optimized chunk for %s/%s: %s", document_id, chunk_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update optimized chunk",
        )

    return {"chunk_id": chunk_id, "status": "saved"}
