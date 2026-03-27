"""
Pipeline API Endpoints.

Endpoints for document upload, pipeline control, and artifact retrieval.
"""
import asyncio
import json
import logging
import re
import shutil
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Optional
from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import UUID4
from uuid import UUID, NAMESPACE_URL, uuid5

from ..core.config import REPO_ROOT, settings, get_artifacts_path, get_upload_path
from ..core.sse import create_sse_response, encode_sse_event
from ..core.security import get_current_user_id
from ..core.optimization_log import OptimizationLogManager, OptimizationLogHandler
from ..models.database import get_db, AsyncSessionLocal
from ..models.pipeline import (
    DocumentPublishResponse,
    DocumentOptimizedChunksResponse,
    DocumentPagesResponse,
    DocumentUploadResponse,
    OptimizedChunkResponse,
    OptimizedChunkUpdate,
    PageEvidenceResponse,
    PageContentUpdate,
    PipelineStatusResponse,
    PublicationStatus,
    QARescoreResponse,
    ReprocessRequest,
    ReprocessResponse,
    ReviewChecklistResponse,
    ReviewPageResponse,
    ReviewProgressResponse,
    ReviewChecklistItemResponse,
    ValidationIssueResponse,
    ArtifactType,
    PipelineStatus,
)
from ..services.embedding_service import EmbeddingService
from ..services.qdrant_service import QdrantService
from ..services.pipeline_service import PipelineService

logger = logging.getLogger(__name__)

_UNCHANGED = object()
_SET_NOW = object()
_CLEAR = object()

router = APIRouter(prefix="/api/v1", tags=["Pipeline"])

_POST_OPTIMIZATION_LIFECYCLE_STATUSES = {
    PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    PipelineStatus.OPTIMIZING.value,
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
    PipelineStatus.QA_PASSED.value,
    PipelineStatus.FINAL_APPROVED.value,
}


def _normalize_publication_status(
    document_status: Optional[str],
    publication_status: Optional[str],
) -> Optional[str]:
    if publication_status:
        return publication_status
    if document_status == PipelineStatus.FINAL_APPROVED.value:
        return PublicationStatus.PENDING.value
    return None


def _candidate_work_roots() -> list[Path]:
    configured_root = Path(settings.PIPELINE_WORK_DIR).expanduser()
    roots = [configured_root]

    if not configured_root.is_absolute():
        relative_root = Path(str(configured_root).lstrip("./"))
        roots.extend(
            [
                REPO_ROOT / relative_root,
                REPO_ROOT / "backend" / relative_root,
            ]
        )
    elif (
        configured_root.name == "hitl_workspace"
        and configured_root.parent.name == "artifacts"
        and configured_root.parent.parent.name == "data"
    ):
        absolute_base = configured_root.parent.parent.parent
        roots.extend(
            [
                absolute_base / "backend" / "data" / "artifacts" / "hitl_workspace",
                absolute_base.parent / "data" / "artifacts" / "hitl_workspace"
                if absolute_base.name == "backend"
                else absolute_base / "data" / "artifacts" / "hitl_workspace",
            ]
        )

    roots.extend(
        [
            REPO_ROOT / "data" / "artifacts" / "hitl_workspace",
            REPO_ROOT / "backend" / "data" / "artifacts" / "hitl_workspace",
        ]
    )

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved not in seen:
            seen.add(resolved)
            unique_roots.append(resolved)

    return unique_roots


def _find_document_workspace(document_id: UUID4 | str, *, require_document_dir: bool = False) -> Path:
    for root in _candidate_work_roots():
        document_dir = root / str(document_id)
        if document_dir.exists():
            return document_dir

    if require_document_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review workspace not found for this document",
        )

    for root in _candidate_work_roots():
        if root.exists():
            return root

    return _candidate_work_roots()[0]


def _find_review_workspace(document_id: UUID4 | str) -> Path:
    work_dir = _find_document_workspace(document_id)
    review_dirs = sorted(work_dir.glob("*_review"))
    if review_dirs:
        return review_dirs[0]

    if work_dir not in _candidate_work_roots():
        for root in _candidate_work_roots():
            root_review_dirs = sorted(root.glob("*_review"))
            if root_review_dirs:
                return root_review_dirs[0]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Review workspace not found for this document",
    )


def _find_validation_report(work_dir: Path) -> Path:
    validation_files = sorted(work_dir.glob("*_validation.json"))
    if validation_files:
        return validation_files[0]

    for root in _candidate_work_roots():
        root_validation_files = sorted(root.glob("*_validation.json"))
        if root_validation_files:
            return root_validation_files[0]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Validation report not found for this document",
    )


def _load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _default_checklist_payload() -> dict:
    return {
        "question_headings": {"item": "Headings are questions", "checked": False, "notes": None},
        "table_facts_extracted": {"item": "Table facts extracted to bullets", "checked": False, "notes": None},
        "figure_descriptions": {"item": "Figures have text descriptions", "checked": False, "notes": None},
        "citations_present": {"item": "Source citations included", "checked": False, "notes": None},
        "no_hallucinations": {"item": "No AI-generated content", "checked": False, "notes": None},
        "rag_optimized": {"item": "Follows RAG guidelines", "checked": False, "notes": None},
    }


def _load_checklist(checklist_path: Path) -> dict:
    if checklist_path.exists() and checklist_path.is_file():
        return _load_json_file(checklist_path)
    return _default_checklist_payload()


def _build_checklist_model(checklist_payload: dict) -> ReviewChecklistResponse:
    merged_payload = _default_checklist_payload()
    merged_payload.update(checklist_payload or {})
    return ReviewChecklistResponse(**merged_payload)


def _derive_review_status(checklist_payload: dict) -> str:
    checked_values = [
        bool(item.get("checked"))
        for item in checklist_payload.values()
        if isinstance(item, dict) and "checked" in item
    ]
    if not checked_values:
        return "pending"
    if all(checked_values):
        return "reviewed"
    if any(checked_values):
        return "in-review"
    return "pending"


def _resolve_evidence_file(work_dir: Path, evidence_path: Optional[str]) -> Optional[Path]:
    if not evidence_path:
        return None

    candidate = Path(evidence_path)
    candidates = [
        candidate,
        work_dir / evidence_path,
        Path(settings.PIPELINE_WORK_DIR) / evidence_path,
        Path(settings.ARTIFACTS_DIR) / evidence_path,
        REPO_ROOT / evidence_path,
    ]

    for item in candidates:
        if item.exists():
            return item.resolve()
    return None


def _tokenize_for_overlap(text: str) -> set[str]:
    return {token for token in re.findall(r"[A-Za-z0-9]{3,}", text.lower())}


def _derive_section_page_numbers(section_content: str, page_entries: list[dict]) -> list[int]:
    section_tokens = _tokenize_for_overlap(section_content)
    if not section_tokens:
        return []

    page_numbers: list[int] = []
    for page in page_entries:
        page_text = page.get("markdown_content") or page.get("text_preview") or ""
        if not page_text:
            continue
        overlap = section_tokens & _tokenize_for_overlap(page_text)
        if overlap:
            page_numbers.append(int(page.get("page_number")))

    return sorted(dict.fromkeys(page_numbers))


def _ensure_page_review_manifest(review_dir: Path, work_dir: Path) -> dict:
    manifest_path = review_dir / "page_review_manifest.json"
    if manifest_path.exists():
        return _load_json_file(manifest_path)

    validation_path = _find_validation_report(work_dir)
    validation_report = _load_json_file(validation_path)

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from pipeline.src.review.section_review import (  # noqa: WPS433
        create_page_review_workspace,
        extract_pages_from_validation,
    )

    pages = extract_pages_from_validation(validation_report, validation_report.get("document_name"))
    create_page_review_workspace(pages, str(review_dir))
    return _load_json_file(manifest_path)


def _strip_embedded_html_comments(content: str) -> str:
    return re.sub(r"<!--[\s\S]*?-->", "", content or "").strip()


def _extract_page_heading(markdown_content: str, page_number: int) -> str:
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or f"Page {page_number}"
    return f"Page {page_number}"


def _load_page_markdown(review_dir: Path, page_entry: dict) -> str:
    page_file = review_dir / str(page_entry.get("file") or "")
    if page_file.exists() and page_file.is_file():
        file_content = _strip_embedded_html_comments(page_file.read_text(encoding="utf-8"))
        if file_content:
            return file_content

    manifest_markdown = _strip_embedded_html_comments(page_entry.get("markdown_content") or "")
    if manifest_markdown:
        return manifest_markdown

    text_preview = (page_entry.get("text_preview") or "").strip()
    page_number = int(page_entry.get("page_number") or 0)
    if text_preview:
        return f"# Page {page_number}\n\n{text_preview}".strip()

    return f"# Page {page_number}".strip()


def _extract_page_numbers_from_chunk(chunk: dict, content: str) -> list[int]:
    source_pages = chunk.get("source_pages")
    if isinstance(source_pages, list):
        normalized_pages: list[int] = []
        for page_number in source_pages:
            if isinstance(page_number, int) and page_number not in normalized_pages:
                normalized_pages.append(page_number)
        if normalized_pages:
            return normalized_pages

    return [
        page_number
        for page_number in dict.fromkeys(
            int(match)
            for match in re.findall(r"Page\s+(\d+)", content or "", flags=re.IGNORECASE)
        )
    ]


def _preview_text(content: str, *, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", _strip_embedded_html_comments(content or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def _optimized_chunk_id(chunk: dict, index: int) -> str:
    explicit_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if explicit_id:
        return explicit_id
    return f"chunk_{index:03d}"


def _coerce_optimized_chunk(chunk: dict, index: int) -> dict:
    content = str(chunk.get("content") or chunk.get("markdown") or chunk.get("body") or chunk.get("text") or "").strip()
    heading = str(
        chunk.get("heading")
        or chunk.get("title")
        or chunk.get("question")
        or f"Chunk {index}"
    ).strip()

    table_facts = [
        str(fact).strip()
        for fact in (chunk.get("table_facts") or chunk.get("facts") or [])
        if str(fact).strip()
    ]
    ambiguity_flags = [
        str(flag).strip()
        for flag in (chunk.get("ambiguity_flags") or chunk.get("ambiguities") or [])
        if str(flag).strip()
    ]

    return {
        "id": _optimized_chunk_id(chunk, index),
        "heading": heading,
        "markdown_content": content,
        "source_pages": _extract_page_numbers_from_chunk(chunk, content),
        "table_facts": table_facts,
        "ambiguity_flags": ambiguity_flags,
    }


def _build_markdown_from_optimized_chunks(document_name: str, chunks: list[dict]) -> str:
    sections: list[str] = [f"# {document_name}"]
    for chunk in chunks:
        content = str(chunk.get("markdown_content") or chunk.get("content") or "").strip()
        if content:
            sections.append(content)
    return "\n\n".join(section for section in sections if section.strip()).strip() + "\n"


def _build_editable_optimized_chunks(work_dir: Path) -> tuple[dict, str, list[dict], Optional[Path], Optional[Path]]:
    optimized_json_path, optimized_markdown_path = _find_optimized_artifact_paths(work_dir)
    optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)
    document_name = str(optimized_payload.get("document_name") or work_dir.name).strip() or work_dir.name

    editable_chunks: list[dict] = []
    raw_chunks = optimized_payload.get("chunks") or []
    if isinstance(raw_chunks, list) and raw_chunks:
        for index, raw_chunk in enumerate(raw_chunks, start=1):
            if isinstance(raw_chunk, dict):
                editable_chunks.append(_coerce_optimized_chunk(raw_chunk, index))

    if not editable_chunks and markdown_content:
        for index, section in enumerate(_split_markdown_into_sections(markdown_content), start=1):
            content = str(section.get("content") or "").strip()
            if not content:
                continue
            editable_chunks.append(
                {
                    "id": f"chunk_{index:03d}",
                    "heading": str(section.get("heading") or f"Chunk {index}").strip(),
                    "markdown_content": content,
                    "source_pages": _extract_page_numbers_from_chunk({}, content),
                    "table_facts": [],
                    "ambiguity_flags": [],
                }
            )

    if not editable_chunks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimization output is incomplete; rerun optimization before editing",
        )

    return optimized_payload, document_name, editable_chunks, optimized_json_path, optimized_markdown_path


def _save_optimized_chunks(
    *,
    optimized_payload: dict,
    document_name: str,
    editable_chunks: list[dict],
    optimized_json_path: Optional[Path],
    optimized_markdown_path: Optional[Path],
    work_dir: Path,
) -> None:
    json_path = optimized_json_path or (work_dir / f"{document_name}_rag_optimized.json")
    markdown_path = optimized_markdown_path or (work_dir / f"{document_name}_rag_optimized.md")

    persisted_chunks = [
        {
            "heading": chunk["heading"],
            "content": chunk["markdown_content"],
            "source_pages": chunk.get("source_pages") or [],
            "table_facts": chunk.get("table_facts") or [],
            "ambiguity_flags": chunk.get("ambiguity_flags") or [],
        }
        for chunk in editable_chunks
    ]

    optimized_payload = dict(optimized_payload or {})
    optimized_payload["document_name"] = document_name
    optimized_payload["chunks"] = persisted_chunks
    optimized_payload["markdown"] = _build_markdown_from_optimized_chunks(document_name, persisted_chunks)

    json_path.write_text(json.dumps(optimized_payload, indent=2), encoding="utf-8")
    markdown_path.write_text(str(optimized_payload["markdown"]), encoding="utf-8")


def _remove_stale_qa_report(document_id: UUID4 | str, work_dir: Path) -> None:
    qa_report_path = get_artifacts_path(
        str(document_id),
        "qa_report",
        allow_legacy_qa_fallback=False,
    )
    if qa_report_path.exists() and qa_report_path.is_file():
        qa_report_path.unlink()

    validation_path = _find_validation_report(work_dir)
    fallback_qa_report_path = _resolve_qa_report_path(document_id, validation_path)
    if fallback_qa_report_path.exists() and fallback_qa_report_path.is_file():
        fallback_qa_report_path.unlink()


def _build_qa_sections_from_pages(review_dir: Path, page_manifest: dict) -> list[dict]:
    sections: list[dict] = []
    for page_entry in page_manifest.get("pages", []):
        page_number = int(page_entry.get("page_number") or 0)
        markdown_content = _load_page_markdown(review_dir, page_entry)
        sections.append(
            {
                "heading": _extract_page_heading(markdown_content, page_number),
                "content": markdown_content,
                "page_number": page_number,
                "page_id": page_entry.get("page_id", f"page_{page_number:03d}"),
            }
        )
    return sections


def _resolve_qa_report_path(document_id: UUID4 | str, validation_path: Path) -> Path:
    qa_report_path = get_artifacts_path(
        str(document_id),
        "qa_report",
        allow_legacy_qa_fallback=False,
    )
    if qa_report_path.exists():
        return qa_report_path

    validation_name = validation_path.name
    if validation_name.endswith("_validation.json"):
        return validation_path.with_name(validation_name.replace("_validation.json", "_qa_report.json"))

    return validation_path.with_name("qa_report.json")


def _find_manifest_path(work_dir: Path) -> Optional[Path]:
    manifest_files = sorted(work_dir.glob("*_manifest.json"))
    return manifest_files[0] if manifest_files else None


def _find_table_figure_report_path(work_dir: Path) -> Optional[Path]:
    report_files = sorted(work_dir.glob("*_tables_figures.json"))
    return report_files[0] if report_files else None


def _find_optimized_artifact_paths(work_dir: Path) -> tuple[Optional[Path], Optional[Path]]:
    optimized_json = sorted(work_dir.glob("*_rag_optimized.json"))
    optimized_markdown = sorted(work_dir.glob("*_rag_optimized.md"))
    return (
        optimized_json[0] if optimized_json else None,
        optimized_markdown[0] if optimized_markdown else None,
    )


def _is_post_optimization_lifecycle(status_value: Optional[str]) -> bool:
    return status_value in _POST_OPTIMIZATION_LIFECYCLE_STATUSES


def _has_usable_optimized_chunks(optimized_payload: dict) -> bool:
    chunks = optimized_payload.get("chunks")
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


def _extract_optimized_markdown(optimized_payload: dict, optimized_markdown_path: Optional[Path]) -> str:
    payload_markdown = optimized_payload.get("markdown")
    if isinstance(payload_markdown, str) and payload_markdown.strip():
        return payload_markdown.strip()

    if optimized_markdown_path and optimized_markdown_path.exists() and optimized_markdown_path.is_file():
        markdown_content = optimized_markdown_path.read_text(encoding="utf-8").strip()
        if markdown_content:
            return markdown_content

    return ""


def _load_validated_optimized_output(work_dir: Path) -> tuple[dict, str]:
    optimized_json_path, optimized_markdown_path = _find_optimized_artifact_paths(work_dir)
    optimized_payload = _load_optional_json(optimized_json_path)
    markdown_content = _extract_optimized_markdown(optimized_payload, optimized_markdown_path)

    if not _has_usable_optimized_chunks(optimized_payload) and not markdown_content:
        raise ValueError(
            "Optimization output is incomplete; rerun optimization before QA or finalization"
        )

    return optimized_payload, markdown_content


def _load_optional_json(path: Optional[Path]) -> dict:
    if path is None or not path.exists() or not path.is_file():
        return {}
    return _load_json_file(path)


def _split_markdown_into_sections(markdown_content: str) -> list[dict]:
    stripped_content = markdown_content.strip()
    if not stripped_content:
        return []

    heading_matches = list(re.finditer(r"^##\s+(.+)$", stripped_content, flags=re.MULTILINE))
    if not heading_matches:
        first_heading = _extract_page_heading(stripped_content, 1)
        return [{"heading": first_heading, "content": stripped_content, "has_tables": "|" in stripped_content}]

    sections: list[dict] = []
    for index, match in enumerate(heading_matches):
        start = match.start()
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(stripped_content)
        section_content = stripped_content[start:end].strip()
        sections.append(
            {
                "heading": match.group(1).strip(),
                "content": section_content,
                "has_tables": "|" in section_content,
            }
        )
    return sections


def _build_qa_sections_from_optimized_output(work_dir: Path) -> list[dict]:
    try:
        optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    sections: list[dict] = []
    chunks = optimized_payload.get("chunks") or []
    if isinstance(chunks, list) and chunks:
        for index, chunk in enumerate(chunks, start=1):
            if not isinstance(chunk, dict):
                continue
            content = str(chunk.get("content") or chunk.get("markdown") or "").strip()
            if not content:
                content = json.dumps(chunk, indent=2)
            heading = str(
                chunk.get("heading")
                or chunk.get("title")
                or chunk.get("question")
                or f"Chunk {index}"
            ).strip()
            sections.append(
                {
                    "heading": heading,
                    "content": content,
                    "has_tables": "|" in content or bool(chunk.get("table_facts")),
                    "table_facts": chunk.get("table_facts") or chunk.get("facts") or [],
                }
            )

    if sections:
        return sections

    if markdown_content:
        return _split_markdown_into_sections(markdown_content)

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Optimization output is incomplete; rerun optimization before QA or finalization",
    )


async def _set_document_status(
    db: AsyncSession,
    document_id: UUID4 | str,
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
    if qa_score is _CLEAR:
        assignments.append("qa_score = NULL")
    elif qa_score is not _UNCHANGED:
        assignments.append("qa_score = :qa_score")
        params["qa_score"] = qa_score
    if approved_by is not None:
        assignments.append("approved_by = :approved_by")
        params["approved_by"] = approved_by
    if approved_at:
        assignments.append("approved_at = NOW()")
    if notes is not None:
        assignments.append("notes = :notes")
        params["notes"] = notes
    if optimization_started_at is _SET_NOW:
        assignments.append("optimization_started_at = NOW()")
    elif optimization_started_at is _CLEAR:
        assignments.append("optimization_started_at = NULL")
    elif optimization_started_at is not _UNCHANGED:
        assignments.append("optimization_started_at = :optimization_started_at")
        params["optimization_started_at"] = optimization_started_at

    if optimization_completed_at is _SET_NOW:
        assignments.append("optimization_completed_at = NOW()")
    elif optimization_completed_at is _CLEAR:
        assignments.append("optimization_completed_at = NULL")
    elif optimization_completed_at is not _UNCHANGED:
        assignments.append("optimization_completed_at = :optimization_completed_at")
        params["optimization_completed_at"] = optimization_completed_at

    if optimization_error is _CLEAR:
        assignments.append("optimization_error = NULL")
    elif optimization_error is not _UNCHANGED:
        assignments.append("optimization_error = :optimization_error")
        params["optimization_error"] = optimization_error

    if publication_status is _CLEAR:
        assignments.append("publication_status = NULL")
    elif publication_status is not _UNCHANGED:
        assignments.append("publication_status = :publication_status")
        params["publication_status"] = publication_status

    if published_at is _SET_NOW:
        assignments.append("published_at = NOW()")
    elif published_at is _CLEAR:
        assignments.append("published_at = NULL")
    elif published_at is not _UNCHANGED:
        assignments.append("published_at = :published_at")
        params["published_at"] = published_at

    if publication_error is _CLEAR:
        assignments.append("publication_error = NULL")
    elif publication_error is not _UNCHANGED:
        assignments.append("publication_error = :publication_error")
        params["publication_error"] = publication_error

    if indexed_chunk_count is _CLEAR:
        assignments.append("indexed_chunk_count = NULL")
    elif indexed_chunk_count is not _UNCHANGED:
        assignments.append("indexed_chunk_count = :indexed_chunk_count")
        params["indexed_chunk_count"] = indexed_chunk_count

    if qdrant_collection is _CLEAR:
        assignments.append("qdrant_collection = NULL")
    elif qdrant_collection is not _UNCHANGED:
        assignments.append("qdrant_collection = :qdrant_collection")
        params["qdrant_collection"] = qdrant_collection

    await db.execute(
        _text(f"UPDATE documents SET {', '.join(assignments)} WHERE id = :doc_id"),
        params,
    )
    await db.commit()


def _emit_optimization_log(document_id: str, level: str, message: str) -> None:
    normalized_level = level.upper()
    if normalized_level not in {"INFO", "WARNING", "ERROR"}:
        normalized_level = "INFO"
    OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": pipeline_timestamp(),
            "level": normalized_level,
            "message": message,
        },
    )


def pipeline_timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def _execute_optimization_stage(
    *,
    document_id: str,
    reviewer: str,
    work_dir: str,
    optimization_prep_path: str,
) -> None:
    work_root = Path(work_dir)
    OptimizationLogManager.start(document_id)
    closed_stream = False
    started_monotonic = time.monotonic()
    try:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        # Resolve all paths synchronously before touching the DB
        manifest_path = _find_manifest_path(work_root)
        validation_path = get_artifacts_path(document_id, "validation")
        if not validation_path.exists():
            raise FileNotFoundError("Validation artifact not found for optimization")

        manifest = _load_optional_json(manifest_path)
        document_name = str(
            manifest.get("document_name")
            or validation_path.name.replace("_validation.json", "")
        )
        pdf_path = manifest.get("pdf_path")
        if not pdf_path:
            raise FileNotFoundError("Manifest is missing source PDF path")

        from pipeline.src.cli.hitl_pipeline import HITLPipeline  # noqa: WPS433
        from pipeline.src.lineage.lineage_tracker import (  # noqa: WPS433
            load_manifest,
            save_manifest,
            update_manifest_timestamp,
        )

        async with AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.OPTIMIZING.value,
                review_progress=100,
                optimization_started_at=_SET_NOW,
                optimization_completed_at=_CLEAR,
                optimization_error=_CLEAR,
            )

        _emit_optimization_log(
            document_id,
            "INFO",
            "Optimization started",
        )

        logger.info("Starting Stage 10 reformatting for %s in thread pool", document_id)
        pipeline_runner = HITLPipeline(str(work_root))

        # Wire per-document log capture so the SSE /optimization/logs endpoint
        # can stream live log lines from the thread-pool worker to the browser.
        _loop = asyncio.get_event_loop()
        _opt_handler = OptimizationLogHandler(document_id, _loop)
        _opt_logger_names = [
            "pipeline.src.cli.hitl_pipeline",
            "pipeline.src.cli.text_reformatter",
            "pipeline.src.utils.progress_tracker",
        ]
        for _lname in _opt_logger_names:
            logging.getLogger(_lname).addHandler(_opt_handler)

        # Run the blocking ~40-60 min reformatting in a thread so the event loop stays free
        result = None
        try:
            result = await asyncio.to_thread(
                pipeline_runner.run_post_approval_reformatting,
                doc_name=document_name,
                pdf_path=str(pdf_path),
                validation_report_path=str(validation_path),
                optimization_prep_path=optimization_prep_path,
            )
        finally:
            for _lname in _opt_logger_names:
                logging.getLogger(_lname).removeHandler(_opt_handler)

        if result.get("status") != "complete":
            _emit_optimization_log(
                document_id,
                "ERROR",
                result.get("message") or "Optimization stage failed",
            )
            OptimizationLogManager.close(document_id, "failed")
            closed_stream = True
            raise RuntimeError(result.get("message") or "Optimization stage failed")

        _load_validated_optimized_output(work_root)

        duration_seconds = int(time.monotonic() - started_monotonic)
        _emit_optimization_log(
            document_id,
            "INFO",
            f"Optimization completed in {duration_seconds}s",
        )

        if manifest_path and manifest_path.exists():
            manifest_record = load_manifest(str(manifest_path))
            manifest_record = update_manifest_timestamp(manifest_record, "reformatting", reviewer)
            save_manifest(manifest_record, str(manifest_path))

        async with AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.OPTIMIZATION_COMPLETE.value,
                review_progress=100,
                optimization_completed_at=_SET_NOW,
                optimization_error=_CLEAR,
            )

        OptimizationLogManager.close(document_id, "optimization-complete")
        closed_stream = True

    except Exception as exc:
        _emit_optimization_log(document_id, "ERROR", f"Optimization failed: {exc}")
        if not closed_stream:
            OptimizationLogManager.close(document_id, "failed")
        logger.error("Optimization stage failed for %s: %s", document_id, exc, exc_info=True)
        async with AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.FAILED.value,
                review_progress=100,
                notes=str(exc),
                optimization_completed_at=_SET_NOW,
                optimization_error=str(exc),
            )


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


def _build_page_response(
    document_id: UUID4,
    review_dir: Path,
    work_dir: Path,
    page_entry: dict,
) -> ReviewPageResponse:
    page_number = int(page_entry["page_number"])
    checklist = _load_checklist(review_dir / page_entry.get("checklist", ""))
    status_value = _derive_review_status(checklist)

    evidence_payload = dict(page_entry.get("evidence") or {})
    thumbnail_path = evidence_payload.get("thumbnail_path")
    thumbnail_file = _resolve_evidence_file(work_dir, thumbnail_path)
    thumbnail_url = (
        f"/api/v1/documents/{document_id}/pages/{page_number}/thumbnail"
        if thumbnail_file is not None
        else None
    )

    evidence_images = []
    if thumbnail_url:
        evidence_images.append(thumbnail_url)
    for image_path in page_entry.get("evidence_images") or []:
        if image_path not in evidence_images:
            evidence_images.append(image_path)

    validation_issues = [
        ValidationIssueResponse(**issue)
        for issue in (page_entry.get("validation_issues") or [])
    ]

    evidence_model = PageEvidenceResponse(
        page_number=page_number,
        text_preview=evidence_payload.get("text_preview") or page_entry.get("text_preview") or "",
        image_count=int(evidence_payload.get("image_count") or 0),
        table_count=int(evidence_payload.get("table_count") or 0),
        has_figures=bool(evidence_payload.get("has_figures")),
        thumbnail_path=thumbnail_path,
        thumbnail_url=thumbnail_url,
    )

    return ReviewPageResponse(
        id=page_entry.get("page_id", f"page_{page_number:03d}"),
        page_number=page_number,
        status=status_value,
        markdown_content=page_entry.get("markdown_content") or "",
        text_preview=page_entry.get("text_preview") or evidence_model.text_preview,
        validation_issues=validation_issues,
        evidence_images=evidence_images,
        evidence=evidence_model,
        checklist=_build_checklist_model(checklist),
    )


def _build_review_progress(pages: list[ReviewPageResponse]) -> ReviewProgressResponse:
    by_status: dict[str, int] = {}
    for page in pages:
        by_status[page.status] = by_status.get(page.status, 0) + 1

    reviewed_pages = sum(count for state, count in by_status.items() if state == "reviewed")
    total_pages = len(pages)

    return ReviewProgressResponse(
        total_pages=total_pages,
        reviewed_pages=reviewed_pages,
        pending_pages=total_pages - reviewed_pages,
        completion_percentage=(reviewed_pages / total_pages * 100) if total_pages else 0.0,
        by_status=by_status,
    )


def _build_publishable_chunks(work_dir: Path) -> list[dict]:
    optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)

    publishable_chunks: list[dict] = []
    raw_chunks = optimized_payload.get("chunks") or []
    if isinstance(raw_chunks, list) and raw_chunks:
        for index, raw_chunk in enumerate(raw_chunks, start=1):
            if not isinstance(raw_chunk, dict):
                continue
            normalized_chunk = _coerce_optimized_chunk(raw_chunk, index)
            if normalized_chunk["markdown_content"]:
                publishable_chunks.append(normalized_chunk)

    if not publishable_chunks and markdown_content:
        for index, section in enumerate(_split_markdown_into_sections(markdown_content), start=1):
            content = str(section.get("content") or "").strip()
            if not content:
                continue
            publishable_chunks.append(
                {
                    "id": f"chunk_{index:03d}",
                    "heading": str(section.get("heading") or f"Chunk {index}").strip(),
                    "markdown_content": content,
                    "source_pages": _extract_page_numbers_from_chunk({}, content),
                    "table_facts": [],
                    "ambiguity_flags": [],
                }
            )

    if not publishable_chunks:
        raise ValueError("Optimization output is incomplete; nothing is available to publish")

    return publishable_chunks


async def _publish_document_to_rag(
    *,
    document_id: str,
    document_title: str,
    system: Optional[str],
    work_dir: Path,
) -> dict[str, object]:
    publishable_chunks = _build_publishable_chunks(work_dir)
    chunk_contents = [chunk["markdown_content"] for chunk in publishable_chunks]

    if not await QdrantService.ensure_collection():
        raise RuntimeError("Failed to ensure Qdrant collection exists")

    embeddings = await EmbeddingService.embed_batch(chunk_contents)
    if len(embeddings) != len(publishable_chunks):
        raise RuntimeError("Embedding generation returned an unexpected number of vectors")

    if not await QdrantService.delete_document_chunks(document_id):
        raise RuntimeError("Failed to clear existing Qdrant chunks for this document")

    qdrant_chunks: list[dict[str, object]] = []
    for index, (chunk, vector) in enumerate(zip(publishable_chunks, embeddings, strict=True), start=1):
        source_pages = [int(page) for page in chunk.get("source_pages") or []]
        point_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{chunk['id'] or index}"))
        qdrant_chunks.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "chunk_id": chunk["id"],
                    "document_id": document_id,
                    "document_title": document_title,
                    "system": system,
                    "content": chunk["markdown_content"],
                    "section_heading": chunk["heading"],
                    "page_number": source_pages[0] if source_pages else None,
                    "source_pages": source_pages,
                    "table_facts": chunk.get("table_facts") or [],
                    "ambiguity_flags": chunk.get("ambiguity_flags") or [],
                },
            }
        )

    if not await QdrantService.upsert_chunks(qdrant_chunks):
        raise RuntimeError("Failed to upsert optimized chunks into Qdrant")

    return {
        "indexed_chunk_count": len(qdrant_chunks),
        "qdrant_collection": settings.QDRANT_COLLECTION,
    }


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
    from sqlalchemy import text as _text
    try:
        result = await db.execute(
            _text("""
                SELECT
                    id, title, version, system, document_type,
                    status, file_path, uploaded_by, notes,
                    uploaded_at, updated_at,
                    total_pages, total_sections, review_progress, qa_score,
                    approved_by, approved_at,
                    publication_status, published_at, publication_error,
                    indexed_chunk_count, qdrant_collection
                FROM documents
                ORDER BY uploaded_at DESC
            """)
        )
        rows = result.mappings().all()
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
        # Lazily populate NULL metadata from pipeline artifact files
        if any(d["totalPages"] is None or d["totalSections"] is None or d["qaScore"] is None for d in docs):
            docs = await _enrich_metadata_from_artifacts(docs, db)
        return docs
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list documents",
        )


async def _enrich_metadata_from_artifacts(docs: list, db: AsyncSession) -> list:
    """Read pipeline artifact files to populate totalPages/totalSections/qaScore for docs with NULL metadata."""
    import glob as _glob
    import json as _json
    from sqlalchemy import text as _text

    root = Path(settings.PIPELINE_WORK_DIR)
    index: dict[str, dict] = {}  # doc_name → {total_pages, total_sections, qa_score}

    # Collect from manifest files (pdf_page_count)
    for m_path in _glob.glob(str(root / "*_manifest.json")):
        try:
            data = _json.loads(Path(m_path).read_text())
            name = data.get("document_name") or data.get("document", "")
            if name:
                index.setdefault(name, {})["total_pages"] = data.get("pdf_page_count")
        except Exception:
            pass

    # Collect from pipeline_results files (total_sections)
    for pr_path in _glob.glob(str(root / "*_pipeline_results.json")):
        try:
            data = _json.loads(Path(pr_path).read_text())
            name = data.get("document", "")
            if name:
                total_sections = (data.get("stages", {}).get("review_workspace") or {}).get("total_sections")
                if total_sections is not None:
                    index.setdefault(name, {})["total_sections"] = total_sections
        except Exception:
            pass

    # Collect from QA report artifacts (optimization QA preferred, legacy pre-review fallback)
    for qa_pattern in ("*_qa_report.json", "*_qa_pre_review.json"):
        for qa_path in _glob.glob(str(root / qa_pattern)):
            try:
                data = _json.loads(Path(qa_path).read_text())
                name = data.get("document_name") or data.get("document", "")
                if name:
                    score = (data.get("metrics") or {}).get("overall_confidence_score")
                    if score is not None and ("qa_score" not in index.setdefault(name, {}) or qa_pattern == "*_qa_report.json"):
                        index.setdefault(name, {})["qa_score"] = score
            except Exception:
                pass

    if not index:
        return docs

    enriched = []
    updates: list[dict] = []
    for doc in docs:
        title = doc["title"]
        meta = index.get(title, {})
        new_doc = dict(doc)
        changed = False
        if doc["totalPages"] is None and "total_pages" in meta:
            new_doc["totalPages"] = meta["total_pages"]
            changed = True
        if doc["totalSections"] is None and "total_sections" in meta:
            new_doc["totalSections"] = meta["total_sections"]
            changed = True
        if doc["qaScore"] is None and "qa_score" in meta:
            new_doc["qaScore"] = float(meta["qa_score"])
            changed = True
        if changed:
            updates.append({
                "doc_id": doc["id"],
                "tp": new_doc["totalPages"],
                "ts": new_doc["totalSections"],
                "qs": new_doc["qaScore"],
            })
        enriched.append(new_doc)

    # Persist to DB so future reads don't need filesystem enrichment
    for u in updates:
        try:
            await db.execute(
                _text("""
                    UPDATE documents
                    SET total_pages    = COALESCE(total_pages,    :tp),
                        total_sections = COALESCE(total_sections, :ts),
                        qa_score       = COALESCE(qa_score,       :qs),
                        updated_at     = NOW()
                    WHERE id = :doc_id
                """),
                u,
            )
        except Exception as exc:
            logger.warning(f"Failed to persist metadata for {u['doc_id']}: {exc}")
    try:
        await db.commit()
    except Exception as exc:
        logger.warning(f"Failed to commit metadata updates: {exc}")

    return enriched


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    version: Optional[str] = Form(None),
    system: Optional[str] = Form(None),
    document_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a new PDF document and trigger processing pipeline.
    
    - Validates file type and size
    - Saves file to storage
    - Creates database record
    - Triggers HITL pipeline subprocess
    - Returns document ID and initial status
    """
    # Validate file extension
    if not file.filename or not file.filename.endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed"
        )
    
    # Validate file size
    file.file.seek(0, 2)  # Seek to end
    file_size = file.file.tell()
    file.file.seek(0)  # Reset to start
    
    max_size = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds maximum of {settings.MAX_UPLOAD_SIZE_MB}MB"
        )
    
    logger.info(f"Uploading document: {file.filename} ({file_size} bytes)")
    
    try:
        # Generate unique document ID
        import uuid
        document_id = str(uuid.uuid4())
        
        # Save file to upload directory
        safe_filename = f"{document_id}_{file.filename}"
        file_path = get_upload_path(safe_filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        logger.info(f"File saved to: {file_path}")
        
        # Create document record in database
        from sqlalchemy import text
        await db.execute(
            text("""
                INSERT INTO documents (
                    id, title, version, system, document_type, 
                    file_path, status, uploaded_by, notes,
                    uploaded_at, created_at, updated_at
                )
                VALUES (
                    :id, :title, :version, :system, :doc_type,
                    :file_path, :status, :user_id, :notes,
                    NOW(), NOW(), NOW()
                )
            """),
            {
                "id": document_id,
                "title": title,
                "version": version,
                "system": system,
                "doc_type": document_type,
                "file_path": str(file_path),
                "status": PipelineStatus.UPLOADING.value,
                "user_id": current_user_id,
                "notes": notes,
            }
        )
        await db.commit()
        
        logger.info(f"Document record created: {document_id}")
        
        # Trigger pipeline asynchronously
        job_id = await PipelineService.trigger_pipeline(
            document_id=document_id,
            pdf_path=str(file_path),
            reviewer=str(current_user_id),
            db=db,
        )
        
        return DocumentUploadResponse(
            document_id=UUID(document_id),
            status=PipelineStatus.EXTRACTING,
            file_path=str(file_path),
            message=f"Document uploaded successfully. Pipeline job {job_id} started.",
        )
        
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}"
        )


@router.get("/documents/{document_id}/status", response_model=PipelineStatusResponse)
async def get_document_status(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get current processing status for a document.
    
    Returns:
        - Current status (pending, extracting, validating, complete, etc.)
        - Progress percentage
        - Current stage
        - Start/completion timestamps
        - Error message if failed
    """
    try:
        status_info = await PipelineService.get_pipeline_status(
            document_id=str(document_id),
            db=db,
        )
        return status_info
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Error getting status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get document status"
        )


@router.get("/documents/{document_id}/events")
async def stream_document_events(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Stream normalized ingestion progress events as SSE."""
    try:
        status_info = await PipelineService.get_pipeline_status(
            document_id=str(document_id),
            db=db,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error streaming document events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to stream document events",
        )

    async def event_generator():
        event_stream = PipelineService.stream_events(
            document_id=str(document_id),
            initial_status=status_info,
        )
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(anext(event_stream), timeout=15.0)
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue

                yield encode_sse_event(event)
        except asyncio.CancelledError:
            return
        finally:
            await event_stream.aclose()

    return create_sse_response(event_generator())


@router.get("/documents/{document_id}/optimization/logs")
async def stream_optimization_logs(
    document_id: UUID4,
    request: Request,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Stream Stage 10 optimization log lines as SSE.

    Events:
      - ``log``  — ``{"event": "log", "timestamp": "<iso>", "level": "INFO|WARNING|ERROR", "message": "<text>"}``
      - ``done`` — ``{"event": "done", "status": "optimization-complete"|"failed"}``

    Replays the in-memory buffer on connect (so late joiners see history),
    then delivers live lines until the optimization finishes.
    Heartbeat comment lines are emitted every 15 s to keep the connection open.
    """
    doc_id = str(document_id)

    async def log_generator():
        buffer, queue = OptimizationLogManager.subscribe(doc_id)

        # Replay history for late-joining clients
        for entry in buffer:
            yield encode_sse_event({"event": "log", **entry})

        # Already finished — emit done and close
        if queue is None:
            yield encode_sse_event({
                "event": "done",
                "status": OptimizationLogManager.get_final_status(doc_id) or "optimization-complete",
            })
            return

        status_info = await PipelineService.get_pipeline_status(document_id=doc_id, db=db)
        current_status = status_info.status.value
        if not buffer and current_status in {
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.FAILED.value,
        }:
            yield encode_sse_event({
                "event": "done",
                "status": "failed" if current_status == PipelineStatus.FAILED.value else "optimization-complete",
            })
            return

        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        return
                    yield ": heartbeat\n\n"
                    continue

                if kind == "log":
                    yield encode_sse_event({"event": "log", **payload})
                elif kind == "done":
                    yield encode_sse_event({"event": "done", **payload})
                    return
        except asyncio.CancelledError:
            return
        finally:
            OptimizationLogManager.unsubscribe(doc_id, queue)

    return create_sse_response(log_generator())


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
            sec_id = sec.get("section_id", "")
            content = ""
            content_path = review_dir / sec.get("file", "")
            if content_path.exists():
                content = content_path.read_text(encoding="utf-8")

            checklist: dict = {}
            checklist_path = review_dir / sec.get("checklist", "")
            if checklist_path.exists():
                checklist = _load_json_file(checklist_path)

            page_numbers = [int(page) for page in sec.get("page_numbers", [])]
            if not page_numbers:
                pages_match = re.search(r"<!-- Pages: ([0-9, ]+) -->", content)
                if pages_match:
                    page_numbers = [
                        int(page.strip())
                        for page in pages_match.group(1).split(",")
                        if page.strip().isdigit()
                    ]
            if not page_numbers:
                page_numbers = _derive_section_page_numbers(content, page_entries)

            page_start = page_numbers[0] if page_numbers else None
            page_end = page_numbers[-1] if page_numbers else None

            sections_out.append({
                "id": sec_id,
                "heading": sec.get("heading", sec_id),
                "status": sec.get("status", "PENDING").lower(),
                "content": content,
                "checklist": checklist,
                "pageRange": {"start": page_start, "end": page_end},
                "pageNumbers": page_numbers,
            })
        return {"documentName": manifest.get("document_name", ""), "sections": sections_out}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error loading sections for {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load document sections",
        )


@router.get("/documents/{document_id}/pages", response_model=DocumentPagesResponse)
async def get_document_pages(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return page-based review units sourced from validation artifacts."""
    del current_user_id, db

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
        logger.error(f"Error loading page review units for {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to load document pages",
        )


@router.get("/documents/{document_id}/pages/{page_number}/thumbnail")
async def get_document_page_thumbnail(
    document_id: UUID4,
    page_number: int,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return the thumbnail image for a single review page when available."""
    del current_user_id, db

    review_dir = _find_review_workspace(document_id)
    work_dir = _find_document_workspace(document_id, require_document_dir=True)
    page_manifest = _ensure_page_review_manifest(review_dir, work_dir)

    page_entry = next(
        (entry for entry in page_manifest.get("pages", []) if int(entry.get("page_number", -1)) == page_number),
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
    db: AsyncSession = Depends(get_db),
):
    """Persist updated markdown content for a page review unit."""
    del current_user_id, db

    try:
        payload = PageContentUpdate.model_validate(await request.json())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="markdown_content is required",
        )

    review_dir = _find_review_workspace(document_id)
    page_manifest = _ensure_page_review_manifest(review_dir, review_dir.parent)
    page_entry = next((page for page in page_manifest.get("pages", []) if page.get("page_id") == page_id), None)

    if page_entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Page review unit not found",
        )

    file_path = review_dir / str(page_entry.get("file") or "")
    manifest_path = review_dir / "page_review_manifest.json"

    try:
        file_path.write_text(payload.markdown_content, encoding="utf-8")
        page_entry["markdown_content"] = payload.markdown_content
        manifest_path.write_text(json.dumps(page_manifest, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error(f"Error saving page content for {document_id}/{page_id}: {exc}")
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

    document_status = await _get_document_status_value(document_id, db)
    if document_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document_status not in {
        PipelineStatus.OPTIMIZATION_COMPLETE.value,
        PipelineStatus.QA_REVIEW.value,
        PipelineStatus.QA_PASSED.value,
        PipelineStatus.FINAL_APPROVED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimized output is only available after optimization has completed",
        )

    try:
        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        _optimized_payload, document_name, editable_chunks, _json_path, _markdown_path = _build_editable_optimized_chunks(work_dir)
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
        logger.error(f"Error loading optimized chunks for {document_id}: {exc}")
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

    document_status = await _get_document_status_value(document_id, db)
    if document_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if document_status not in {
        PipelineStatus.OPTIMIZATION_COMPLETE.value,
        PipelineStatus.QA_REVIEW.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimized output can only be edited before QA has passed",
        )

    try:
        payload = OptimizedChunkUpdate.model_validate(await request.json())
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="heading and markdown_content are required",
        )

    try:
        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        optimized_payload, document_name, editable_chunks, optimized_json_path, optimized_markdown_path = _build_editable_optimized_chunks(work_dir)
        target_chunk = next((chunk for chunk in editable_chunks if chunk["id"] == chunk_id), None)
        if target_chunk is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Optimized chunk not found",
            )

        target_chunk["heading"] = payload.heading.strip()
        target_chunk["markdown_content"] = payload.markdown_content.strip()
        target_chunk["table_facts"] = [fact.strip() for fact in payload.table_facts if fact.strip()]
        target_chunk["ambiguity_flags"] = [flag.strip() for flag in payload.ambiguity_flags if flag.strip()]
        target_chunk["source_pages"] = _extract_page_numbers_from_chunk(target_chunk, target_chunk["markdown_content"])

        _save_optimized_chunks(
            optimized_payload=optimized_payload,
            document_name=document_name,
            editable_chunks=editable_chunks,
            optimized_json_path=optimized_json_path,
            optimized_markdown_path=optimized_markdown_path,
            work_dir=work_dir,
        )
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
        logger.error(f"Error saving optimized chunk for {document_id}/{chunk_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save optimized chunk",
        )
    except Exception as exc:
        logger.error(f"Error updating optimized chunk for {document_id}/{chunk_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update optimized chunk",
        )

    return {"chunk_id": chunk_id, "status": "saved"}


async def _approve_for_optimization(
    document_id: UUID4,
    background_tasks: BackgroundTasks,
    current_user_id: str,
    db: AsyncSession,
):
    """Generate optimization-prep artifacts and trigger Stage 10 after fidelity review."""
    try:
        document_status = await _get_document_status_value(document_id, db)
        if document_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        if document_status in {
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            PipelineStatus.OPTIMIZING.value,
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.QA_REVIEW.value,
            PipelineStatus.QA_PASSED.value,
            PipelineStatus.FINAL_APPROVED.value,
            PipelineStatus.APPROVED.value,
            PipelineStatus.REJECTED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot approve document in {document_status} status",
            )

        if document_status not in {
            PipelineStatus.VALIDATION_COMPLETE.value,
            PipelineStatus.IN_REVIEW.value,
            PipelineStatus.REVIEW_COMPLETE.value,
            PipelineStatus.FAILED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Approve for optimization is only available for documents in "
                    "validation-complete, in-review, review-complete, or failed status"
                ),
            )

        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        review_dir = _find_review_workspace(document_id)
        page_manifest = _ensure_page_review_manifest(review_dir, work_dir)

        validation_path = get_artifacts_path(str(document_id), "validation")
        if not validation_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validation artifact not found for this document",
            )

        validation_report = _load_json_file(validation_path)
        table_figure_report = _load_optional_json(_find_table_figure_report_path(work_dir))

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from pipeline.src.cli.hitl_pipeline import build_optimization_prep  # noqa: WPS433

        document_name = page_manifest.get("document_name") or validation_report.get("document_name") or str(document_id)
        optimization_prep = build_optimization_prep(
            document_id=str(document_id),
            document_name=document_name,
            review_dir=str(review_dir),
            validation_report=validation_report,
            table_figure_report=table_figure_report,
        )

        optimization_prep_path = work_dir / f"{document_name}_optimization_prep.json"
        optimization_prep_path.write_text(json.dumps(optimization_prep, indent=2), encoding="utf-8")

        await _set_document_status(
            db,
            document_id,
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            review_progress=100,
            optimization_started_at=_CLEAR,
            optimization_completed_at=_CLEAR,
            optimization_error=_CLEAR,
        )
        background_tasks.add_task(
            _execute_optimization_stage,
            document_id=str(document_id),
            reviewer=str(current_user_id),
            work_dir=str(work_dir),
            optimization_prep_path=str(optimization_prep_path),
        )

        return {
            "document_id": str(document_id),
            "status": PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            "optimization_triggered": True,
            "optimization_prep_path": str(optimization_prep_path),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Error approving optimization for {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve document for optimization",
        )


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
        document_status = await _get_document_status_value(document_id, db)
        if document_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        if document_status in {
            PipelineStatus.APPROVED.value,
            PipelineStatus.FINAL_APPROVED.value,
            PipelineStatus.REJECTED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot rescore document in {document_status} status",
            )

        if document_status not in {
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            PipelineStatus.QA_REVIEW.value,
            PipelineStatus.QA_PASSED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "QA rescore is only available for documents after optimization "
                    "has completed"
                ),
            )

        work_dir = _find_document_workspace(document_id, require_document_dir=True)

        validation_path = get_artifacts_path(str(document_id), "validation")
        if not validation_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validation artifact not found for this document",
            )

        validation_report = _load_json_file(validation_path)

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from pipeline.src.qa.qa_gates import (  # noqa: WPS433
            AcceptanceCriteria,
            compute_qa_metrics,
            evaluate_qa_gate,
            save_qa_report,
        )

        await _set_document_status(db, document_id, PipelineStatus.QA_REVIEW.value)

        sections = _build_qa_sections_from_optimized_output(work_dir)
        metrics = compute_qa_metrics(sections, validation_report)
        result = evaluate_qa_gate(metrics, AcceptanceCriteria())
        result.document_name = validation_report.get("document_name") or str(document_id)

        qa_report_path = _resolve_qa_report_path(document_id, validation_path)
        qa_report_path.parent.mkdir(parents=True, exist_ok=True)
        save_qa_report(result, str(qa_report_path))

        await _set_document_status(
            db,
            document_id,
            PipelineStatus.QA_REVIEW.value,
            qa_score=float(result.metrics.overall_confidence_score),
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
        logger.error(f"Error rescoring QA for {document_id}: {exc}")
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
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    decision = payload.get("decision")
    if decision not in ("accept", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'accept' or 'reject'",
        )

    current_status = await _get_document_status_value(document_id, db)
    if current_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    if current_status in {
        PipelineStatus.FINAL_APPROVED.value,
        PipelineStatus.APPROVED.value,
        PipelineStatus.REJECTED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
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

        qa_report = _load_json_file(qa_report_path)
        if qa_report.get("decision") == "rejected":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="QA criteria currently fail; rescore and resolve issues before accepting",
            )

    new_status = PipelineStatus.QA_PASSED.value if decision == "accept" else PipelineStatus.REJECTED.value
    try:
        await _set_document_status(db, document_id, new_status)
        return {"status": new_status}
    except Exception as exc:
        logger.error(f"Error recording QA decision for {document_id}: {exc}")
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
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    decision = payload.get("decision")
    if decision not in ("approve", "reject"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="decision must be 'approve' or 'reject'",
        )

    current_status = await _get_document_status_value(document_id, db)
    if current_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if current_status in {
        PipelineStatus.FINAL_APPROVED.value,
        PipelineStatus.APPROVED.value,
        PipelineStatus.REJECTED.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is already in {current_status} status",
        )

    if decision == "approve" and current_status != PipelineStatus.QA_PASSED.value:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Final approval requires a QA-passed document",
        )

    new_status = PipelineStatus.FINAL_APPROVED.value if decision == "approve" else PipelineStatus.REJECTED.value
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
        logger.error(f"Error recording final approval for {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record approval decision",
        )


@router.post("/documents/{document_id}/publish", response_model=DocumentPublishResponse)
async def publish_document(
    document_id: UUID4,
    current_user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Publish a final-approved document into the RAG knowledge base."""
    del current_user_id

    from sqlalchemy import text as _text

    result = await db.execute(
        _text(
            """
            SELECT title, system, status, publication_status
            FROM documents
            WHERE id = :doc_id
            """
        ),
        {"doc_id": str(document_id)},
    )
    row = result.mappings().first()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

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
        logger.error(f"Error publishing document {document_id} to RAG: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to publish document to RAG: {exc}",
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
    from sqlalchemy import text as _text
    try:
        result = await db.execute(
            _text("SELECT status, file_path FROM documents WHERE id = :doc_id"),
            {"doc_id": str(document_id)},
        )
        row = result.mappings().first()
    except Exception as exc:
        logger.error(f"DB lookup failed for reprocess {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to look up document",
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    locked_statuses = {PipelineStatus.APPROVED.value, PipelineStatus.FINAL_APPROVED.value, PipelineStatus.REJECTED.value}
    if row["status"] in locked_statuses and not getattr(request, "force", False):
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
        logger.error(f"Reprocess failed for {document_id}: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Reprocess failed: {exc}",
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
        document_status = await _get_document_status_value(document_id, db)
        if document_status is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Document not found",
            )

        if artifact_type == ArtifactType.QA_REPORT:
            allow_legacy_qa_fallback = not _is_post_optimization_lifecycle(document_status)
            artifact_path = get_artifacts_path(
                str(document_id),
                artifact_type.value,
                allow_legacy_qa_fallback=allow_legacy_qa_fallback,
            )
            if not artifact_path.exists():
                if not allow_legacy_qa_fallback:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Post-optimization QA report not found; run QA rescore on the optimized output first",
                    )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Artifact {artifact_type} not found",
                )
        else:
            artifact_path = await PipelineService.get_artifact(
                document_id=str(document_id),
                artifact_type=artifact_type.value,
            )

        if not artifact_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Artifact {artifact_type} not found",
            )

        return FileResponse(
            path=str(artifact_path),
            filename=artifact_path.name,
            media_type="application/json" if artifact_path.suffix == ".json" else "application/octet-stream",
        )

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting artifact: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve artifact",
        )

