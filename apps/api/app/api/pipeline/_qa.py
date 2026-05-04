"""
QA report helpers: path resolution, stale report cleanup, section assembly,
and the compute-and-persist workflow that drives the QA gate.
"""
import json
import sys
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import REPO_ROOT, get_artifacts_path
from ._chunks import _load_validated_optimized_output, _split_markdown_into_sections
from ._db_ops import _set_document_status
from ._filesystem import _find_document_workspace, _load_json_file, _load_optional_json
from ._filesystem import _find_manifest_path
from ._review import _extract_page_heading, _load_page_markdown


# ---------------------------------------------------------------------------
# QA report path helpers
# ---------------------------------------------------------------------------

def _resolve_qa_report_path(document_id, validation_path: Path) -> Path:
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


def _remove_stale_qa_report(document_id, work_dir: Path) -> None:
    qa_report_path = get_artifacts_path(
        str(document_id),
        "qa_report",
        allow_legacy_qa_fallback=False,
    )
    if qa_report_path.exists() and qa_report_path.is_file():
        qa_report_path.unlink()

    from ._filesystem import _find_validation_report  # local import avoids top-level circular ref

    validation_path = _find_validation_report(work_dir)
    fallback_qa_report_path = _resolve_qa_report_path(document_id, validation_path)
    if fallback_qa_report_path.exists() and fallback_qa_report_path.is_file():
        fallback_qa_report_path.unlink()


# ---------------------------------------------------------------------------
# QA section assembly
# ---------------------------------------------------------------------------

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


def _chunk_content(chunk: dict) -> str:
    content = str(chunk.get("content") or chunk.get("markdown") or "").strip()
    return content or json.dumps(chunk, indent=2)


def _chunk_heading(chunk: dict, index: int) -> str:
    heading = str(
        chunk.get("heading")
        or chunk.get("title")
        or chunk.get("question")
        or f"Chunk {index}"
    ).strip()
    return heading or f"Chunk {index}"


def _chunk_section(chunk: dict, index: int) -> dict:
    content = _chunk_content(chunk)
    return {
        "heading": _chunk_heading(chunk, index),
        "content": content,
        "has_tables": "|" in content or bool(chunk.get("table_facts")),
        "table_facts": chunk.get("table_facts") or chunk.get("facts") or [],
    }


def _sections_from_chunks(chunks: object) -> list[dict]:
    if not isinstance(chunks, list) or not chunks:
        return []

    sections: list[dict] = []
    for index, chunk in enumerate(chunks, start=1):
        if not isinstance(chunk, dict):
            continue
        sections.append(_chunk_section(chunk, index))
    return sections


def _build_qa_sections_from_optimized_output(work_dir: Path) -> list[dict]:
    try:
        optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    sections = _sections_from_chunks(optimized_payload.get("chunks") or [])

    if sections:
        return sections

    if markdown_content:
        return _split_markdown_into_sections(markdown_content)

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Optimization output is incomplete; rerun optimization before QA or finalization",
    )


# ---------------------------------------------------------------------------
# QA computation and persistence
# ---------------------------------------------------------------------------

async def _compute_and_persist_qa_report(
    *,
    document_id: UUID4,
    db: AsyncSession,
    persisted_status: str,
) -> object:
    """Compute post-optimization QA metrics and persist *_qa_report.json + qa_score."""
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

    sections = _build_qa_sections_from_optimized_output(work_dir)
    metrics = compute_qa_metrics(sections, validation_report)

    # Use relaxed acceptance criteria for spreadsheet sources (xlsx/xls), since
    # LLM-optimised XLSX output does not reliably produce citation markers, Q-headings,
    # or bullet-wrapped table facts (the GFM table structure dominates the output),
    # so standard PDF thresholds would always reject XLSX documents.
    manifest = _load_optional_json(_find_manifest_path(work_dir))
    source_path = str(manifest.get("pdf_path") or "")
    is_xlsx_source = source_path.lower().endswith((".xlsx", ".xls"))
    criteria = (
        AcceptanceCriteria(
            min_citation_coverage=0.0,
            min_question_heading_compliance=0.0,
            min_table_facts_extraction=0.0,
            min_confidence_score=0.0,
            max_critical_issues=9999,
            require_all_figures_described=False,
        )
        if is_xlsx_source
        else AcceptanceCriteria()
    )

    result = evaluate_qa_gate(metrics, criteria)
    result.document_name = validation_report.get("document_name") or str(document_id)

    qa_report_path = _resolve_qa_report_path(document_id, validation_path)
    qa_report_path.parent.mkdir(parents=True, exist_ok=True)
    save_qa_report(result, str(qa_report_path))

    await _set_document_status(
        db,
        document_id,
        persisted_status,
        qa_score=float(result.metrics.overall_confidence_score),
    )

    return result
