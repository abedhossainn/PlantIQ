"""
Review workspace helpers: checklist management, page manifest loading,
evidence resolution, and page/review response builders.
"""
import re
import sys
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from pydantic import UUID4

from ...core.config import REPO_ROOT, settings
from ...models.pipeline import (
    PageEvidenceResponse,
    ReviewChecklistResponse,
    ReviewPageResponse,
    ReviewProgressResponse,
    ValidationIssueResponse,
)
from ._filesystem import (
    _candidate_work_roots,
    _find_validation_report,
    _load_json_file,
)


# ---------------------------------------------------------------------------
# Checklist helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Evidence resolution
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Section / page text utilities
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

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


def _build_evidence_images(
    thumbnail_url: Optional[str],
    evidence_images: list[str],
) -> list[str]:
    resolved_images: list[str] = []
    if thumbnail_url:
        resolved_images.append(thumbnail_url)
    for image_path in evidence_images:
        if image_path not in resolved_images:
            resolved_images.append(image_path)
    return resolved_images


def _build_validation_issues(issues: object) -> list[ValidationIssueResponse]:
    return [ValidationIssueResponse(**issue) for issue in (issues or [])]


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

    evidence_images = _build_evidence_images(
        thumbnail_url,
        page_entry.get("evidence_images") or [],
    )

    validation_issues = _build_validation_issues(page_entry.get("validation_issues"))

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
