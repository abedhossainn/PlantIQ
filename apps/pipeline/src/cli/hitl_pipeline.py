#!/usr/bin/env python3
"""
Enhanced HITL Pipeline Orchestrator
Integrates all improvements from the analysis:
1. Enhanced validation with per-page evidence
2. Section-based review workflow
3. QA gates with metrics
4. Lineage and audit trail
5. Improved table/figure handling

This orchestrator coordinates the entire manual HITL workflow.
"""

import json
import logging
import sys
import subprocess
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

# Import our enhanced modules
from ..validation.enhanced_validator import create_validation_report, save_validation_report
from ..review.section_review import (
    extract_pages_from_validation,
    extract_sections_from_markdown,
    create_page_review_workspace,
    create_review_workspace,
    get_review_progress
)
from ..qa.qa_gates import (
    compute_qa_metrics,
    evaluate_qa_gate,
    save_qa_report,
    AcceptanceCriteria,
    QADecision
)
from ..lineage.lineage_tracker import (
    create_document_manifest,
    save_manifest,
    update_manifest_timestamp,
    create_version,
    generate_audit_report
)
from ..utils.table_figure_handler import (
    extract_tables_from_pdf,
    extract_figures_from_markdown,
    generate_table_figure_report
)
from ..utils.vlm_options import get_text_model_id, get_vision_model_id

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _emit_event(
    event_type: str,
    stage: str,
    message: str,
    progress: int,
    step: Optional[str] = None,
) -> None:
    """Emit a structured JSON event to stdout so the backend can stream it as an SSE event.

    event_type: "stage_start" | "stage_done" | "progress"
    stage:      backend stage name (extraction, validation, ...)
    message:    human-readable detail line
    progress:   0-100 integer
    step:       optional display label shown as a section header on the frontend
    """
    payload: dict = {
        "event": event_type,
        "stage": stage,
        "message": message,
        "progress": progress,
    }
    if step is not None:
        payload["step"] = step
    print(f"PIPELINE_EVENT:{json.dumps(payload)}", flush=True)


PLACEHOLDER_MARKDOWN_SENTINELS = (
    "Initial placeholder markdown created by backend upload workflow.",
    "Replace with Docling-extracted markdown for full-quality pipeline results.",
)

DOCLING_IMAGE_MODE = "descriptions"


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_review_markdown(review_dir: Path, page_entry: dict[str, Any]) -> str:
    page_file = review_dir / str(page_entry.get("file") or "")
    if page_file.exists() and page_file.is_file():
        return page_file.read_text(encoding="utf-8").strip()
    return str(page_entry.get("markdown_content") or "").strip()


def _load_review_checklist(review_dir: Path, page_entry: dict[str, Any]) -> dict[str, Any]:
    checklist_path = review_dir / str(page_entry.get("checklist") or "")
    if checklist_path.exists() and checklist_path.is_file():
        return _load_json_file(checklist_path)
    return {}


def _extract_heading_candidates(markdown_content: str) -> list[str]:
    headings: list[str] = []
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings


def _extract_checklist_notes(checklist_payload: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for checklist_key, checklist_item in checklist_payload.items():
        if not isinstance(checklist_item, dict):
            continue
        note = checklist_item.get("notes")
        if note:
            notes.append(
                {
                    "checklist_item": checklist_key,
                    "checked": bool(checklist_item.get("checked")),
                    "note": str(note),
                }
            )
    return notes


def _extract_ambiguity_flags(checklist_payload: dict[str, Any], validation_issues: list[dict[str, Any]]) -> list[str]:
    ambiguity_flags: list[str] = []
    for checklist_key, checklist_item in checklist_payload.items():
        if not isinstance(checklist_item, dict):
            continue
        if not checklist_item.get("checked") and checklist_item.get("notes"):
            ambiguity_flags.append(f"{checklist_key}: {checklist_item['notes']}")

    for issue in validation_issues:
        if issue.get("severity") in {"critical", "major"}:
            ambiguity_flags.append(str(issue.get("description") or issue.get("evidence") or ""))

    return [flag for flag in ambiguity_flags if flag]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _build_optimization_segments(
    structured_pages: list[dict[str, Any]],
    *,
    target_chars: int = 18_000,
    min_chars_before_split: int = 6_000,
    max_pages_per_segment: int = 4,
) -> list[dict[str, Any]]:
    """Group reviewed pages into section-aware optimization batches.

    Stage 10 prompt quality drops sharply when the full reviewed document is sent in a
    single request. These segments keep the model input bounded while still preserving
    page-local provenance, tables, figures, and ambiguity flags.
    """

    segments: list[dict[str, Any]] = []
    current_pages: list[dict[str, Any]] = []
    current_chars = 0

    def flush_segment() -> None:
        nonlocal current_pages, current_chars
        if not current_pages:
            return

        page_numbers = [int(page.get("page_number") or 0) for page in current_pages]
        title_candidates = _dedupe_strings(
            [
                heading
                for page in current_pages
                for heading in (page.get("heading_candidates") or [])
            ]
        )
        segment_title = title_candidates[0] if title_candidates else f"Pages {page_numbers[0]}-{page_numbers[-1]}"

        segments.append(
            {
                "segment_id": f"segment_{len(segments) + 1:03d}",
                "title": segment_title,
                "page_numbers": page_numbers,
                "page_range": {"start": page_numbers[0], "end": page_numbers[-1]},
                "heading_candidates": title_candidates,
                "table_facts": _dedupe_strings(
                    [fact for page in current_pages for fact in (page.get("table_facts") or [])]
                ),
                "ambiguity_flags": _dedupe_strings(
                    [flag for page in current_pages for flag in (page.get("ambiguity_flags") or [])]
                ),
                "citations": [
                    citation
                    for page in current_pages
                    for citation in (page.get("citations") or [])
                    if isinstance(citation, dict)
                ],
                "reviewer_notes": [
                    note
                    for page in current_pages
                    for note in (page.get("reviewer_notes") or [])
                    if isinstance(note, dict)
                ],
                "pages": current_pages.copy(),
                "authoritative_markdown": "\n\n".join(
                    str(page.get("authoritative_markdown") or "").strip()
                    for page in current_pages
                    if str(page.get("authoritative_markdown") or "").strip()
                ).strip(),
            }
        )
        current_pages = []
        current_chars = 0

    for page in structured_pages:
        page_markdown = str(page.get("authoritative_markdown") or page.get("text_preview") or "")
        page_chars = max(len(page_markdown), 1)
        introduces_heading = bool(page.get("heading_candidates"))
        exceeds_page_budget = len(current_pages) >= max_pages_per_segment
        exceeds_char_budget = current_chars + page_chars > target_chars
        natural_heading_break = bool(current_pages) and introduces_heading and current_chars >= min_chars_before_split

        if current_pages and (exceeds_page_budget or exceeds_char_budget or natural_heading_break):
            flush_segment()

        current_pages.append(page)
        current_chars += page_chars

    flush_segment()
    return segments


def build_optimization_prep(
    *,
    document_id: str,
    document_name: str,
    review_dir: str,
    validation_report: dict[str, Any],
    table_figure_report: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create the structured optimization-prep artifact from reviewed page assets."""
    review_root = Path(review_dir)
    page_manifest_path = review_root / "page_review_manifest.json"
    page_manifest = _load_json_file(page_manifest_path)
    validation_pages = {
        int(page.get("page_number") or 0): page
        for page in validation_report.get("page_validations", [])
    }
    table_figure_report = table_figure_report or {}
    all_tables = table_figure_report.get("tables", []) or []
    all_figures = table_figure_report.get("figures", []) or []

    structured_pages: list[dict[str, Any]] = []
    unresolved_ambiguities: list[dict[str, Any]] = []

    for page_entry in page_manifest.get("pages", []):
        page_number = int(page_entry.get("page_number") or 0)
        authoritative_markdown = _load_review_markdown(review_root, page_entry)
        checklist_payload = _load_review_checklist(review_root, page_entry)
        validation_page = validation_pages.get(page_number, {})
        validation_issues = page_entry.get("validation_issues") or validation_page.get("issues") or []
        checklist_notes = _extract_checklist_notes(checklist_payload)
        ambiguity_flags = _extract_ambiguity_flags(checklist_payload, validation_issues)
        page_tables = [table for table in all_tables if int(table.get("page_number") or 0) == page_number]
        page_figures = [figure for figure in all_figures if int(figure.get("page_number") or 0) == page_number]

        page_record = {
            "page_id": page_entry.get("page_id", f"page_{page_number:03d}"),
            "page_number": page_number,
            "authoritative_markdown": authoritative_markdown,
            "heading_candidates": _extract_heading_candidates(authoritative_markdown),
            "text_preview": page_entry.get("text_preview") or (page_entry.get("evidence") or {}).get("text_preview") or "",
            "review_checklist": checklist_payload,
            "reviewer_notes": checklist_notes,
            "ambiguity_flags": ambiguity_flags,
            "validation_issues": validation_issues,
            "source_mapping": {
                "validation_page_number": page_number,
                "thumbnail_path": (page_entry.get("evidence") or {}).get("thumbnail_path"),
                "citation_reference": f"{document_name}, Page {page_number}",
            },
            "table_records": page_tables,
            "table_facts": [fact for table in page_tables for fact in table.get("key_facts", [])],
            "figure_records": page_figures,
            "citations": [
                {
                    "document_name": document_name,
                    "page_number": page_number,
                    "label": f"[Source: {document_name}, Page {page_number}]",
                }
            ],
        }
        structured_pages.append(page_record)

        if ambiguity_flags:
            unresolved_ambiguities.append(
                {
                    "page_number": page_number,
                    "page_id": page_record["page_id"],
                    "flags": ambiguity_flags,
                }
            )

    return {
        "schema_version": "1.0",
        "document_id": document_id,
        "document_name": document_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_workspace": str(review_root),
        "source_artifacts": {
            "page_review_manifest": str(page_manifest_path),
            "validation_report": validation_report.get("document_name") or document_name,
            "table_figure_report_present": bool(table_figure_report),
        },
        "validation_summary": validation_report.get("metadata", {}),
        "pages": structured_pages,
        "segments": _build_optimization_segments(structured_pages),
        "tables": all_tables,
        "figures": all_figures,
        "unresolved_ambiguities": unresolved_ambiguities,
        "combined_markdown": "\n\n".join(
            page["authoritative_markdown"]
            for page in structured_pages
            if page.get("authoritative_markdown")
        ).strip(),
    }


def _convert_pdf_to_markdown(*, pdf_path: str, output_path: str, image_mode: str, docling_url: str) -> None:
    from ..ingestion.docling_converter import convert_pdf_with_qwen

    convert_pdf_with_qwen(
        pdf_path=pdf_path,
        output_path=output_path,
        image_mode=image_mode,
        docling_url=docling_url,
    )


def _has_structurally_valid_optimized_output(result: dict[str, Any]) -> bool:
    chunks = result.get("chunks")
    if isinstance(chunks, list):
        for chunk in chunks:
            if isinstance(chunk, str) and chunk.strip():
                return True
            if not isinstance(chunk, dict):
                continue
            if any(str(chunk.get(key) or "").strip() for key in ("content", "markdown", "body", "text")):
                return True

    markdown_content = result.get("markdown")
    return isinstance(markdown_content, str) and bool(markdown_content.strip())


class HITLPipeline:
    """
    Enhanced HITL Pipeline for Document Optimization
    Implements all suggested improvements
    """
    
    def __init__(self, work_dir: str = "hitl_workspace"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True, parents=True)
        logger.info(f"📁 HITL workspace: {self.work_dir}")

    @staticmethod
    def _is_placeholder_markdown(markdown_path: Path) -> bool:
        if not markdown_path.exists() or not markdown_path.is_file():
            return True

        try:
            content = markdown_path.read_text(encoding="utf-8")
        except OSError:
            return True

        stripped_content = content.strip()
        if not stripped_content:
            return True

        return any(sentinel in stripped_content for sentinel in PLACEHOLDER_MARKDOWN_SENTINELS)

    def _ensure_docling_markdown(self, pdf_path: str, markdown_path: str) -> str:
        markdown_file = Path(markdown_path)
        markdown_file.parent.mkdir(parents=True, exist_ok=True)

        if not self._is_placeholder_markdown(markdown_file):
            logger.info(f"✅ Using existing markdown: {markdown_file}")
            return str(markdown_file)

        logger.info("\n" + "=" * 80)
        logger.info("📄 STAGE 0: Docling PDF → Markdown Extraction")
        logger.info("=" * 80)
        logger.info(f"🔄 Generating markdown from PDF: {Path(pdf_path).name}")

        docling_url = os.getenv("DOCLING_URL", "http://localhost:5001")
        temp_output = markdown_file.with_suffix(".docling.tmp.md")

        try:
            _convert_pdf_to_markdown(
                pdf_path=pdf_path,
                output_path=str(temp_output),
                image_mode=DOCLING_IMAGE_MODE,
                docling_url=docling_url,
            )

            generated_content = temp_output.read_text(encoding="utf-8")
            if not generated_content.strip():
                raise ValueError("Docling generated empty markdown output")
            if any(sentinel in generated_content for sentinel in PLACEHOLDER_MARKDOWN_SENTINELS):
                raise ValueError("Docling output still contains placeholder markdown sentinel text")

            markdown_file.write_text(generated_content, encoding="utf-8")
            logger.info(f"✅ Docling markdown saved: {markdown_file}")
            return str(markdown_file)
        finally:
            temp_output.unlink(missing_ok=True)

    def _run_validation_stage(
        self,
        *,
        pdf_path: str,
        markdown_path: str,
        vlm_model: str,
        docling_version: str,
        validation_path: Path,
        manifest,
        manifest_path: Path,
        reviewer: str,
        page_markdown_map: Optional[Dict[int, str]] = None,
    ):
        """Generate and persist the validation artifact for the current canonical markdown."""
        validation_report = create_validation_report(
            pdf_path,
            markdown_path,
            vlm_model,
            docling_version,
            page_markdown_map=page_markdown_map,
        )
        save_validation_report(validation_report, str(validation_path))

        manifest = update_manifest_timestamp(manifest, "validation", reviewer)
        save_manifest(manifest, str(manifest_path))
        return validation_report, manifest

    def _build_validation_page_markdown_map(self, pdf_path: str) -> Optional[Dict[int, str]]:
        """Return page markdown overrides for validation when a cheaper source exists.

        The primary ingestion path intentionally avoids rebuilding the document page by
        page with a second Docling conversion pass. Validation can derive page-aligned
        review slices from the authoritative full-document markdown, which removes the
        duplicate conversion/image-description loop that was saturating CPU.
        """
        del pdf_path
        return None
    
    def run_full_pipeline(
        self,
        pdf_path: str,
        markdown_path: str,
        reviewer: str,
        docling_version: str = "1.0.0",
        vlm_model: Optional[str] = None,
        reformatter_model: Optional[str] = None
    ) -> Dict:
        """
        Run complete HITL pipeline with all improvements
        
        Returns pipeline result summary
        """
        logger.info("=" * 80)
        logger.info("🚀 ENHANCED HITL PIPELINE - START")
        logger.info("=" * 80)

        vlm_model = vlm_model or get_vision_model_id()
        reformatter_model = reformatter_model or get_text_model_id()

        _emit_event("stage_start", "extraction", "Stage 0: PDF → Markdown Extraction", 5,
                    step="Stage 0: PDF → Markdown Extraction")
        _emit_event("progress", "extraction", "Stage 0a: Sending PDF to Docling for conversion...", 6)
        markdown_path = self._ensure_docling_markdown(pdf_path, markdown_path)
        _emit_event(
            "progress",
            "extraction",
            "PDF extracted. Reusing canonical markdown for page-aligned validation slices.",
            14,
        )
        _emit_event("progress", "extraction", "Stage 0b: Building per-page markdown alignment map...", 16)
        page_markdown_map = self._build_validation_page_markdown_map(pdf_path)
        _emit_event("progress", "extraction", "Stage 0c: Per-page markdown map ready.", 18)
        
        doc_name = Path(pdf_path).stem
        results = {"document": doc_name, "stages": {}}
        results["stages"]["docling_extraction"] = {
            "status": "complete",
            "output": str(markdown_path),
            "image_mode": DOCLING_IMAGE_MODE,
        }
        
        # Stage 1: Create lineage manifest
        logger.info("\n" + "=" * 80)
        logger.info("📋 STAGE 1: Create Document Manifest")
        logger.info("=" * 80)
        _emit_event("stage_start", "extraction", "Stage 1: Document Manifest", 20,
                    step="Stage 1: Document Manifest")
        
        manifest = create_document_manifest(
            pdf_path,
            docling_version,
            vlm_model,
            reformatter_model
        )
        manifest.primary_reviewer = reviewer
        manifest_path = self.work_dir / f"{doc_name}_manifest.json"
        save_manifest(manifest, str(manifest_path))
        _emit_event("progress", "extraction", f"Document manifest created for {doc_name}.", 23)
        
        results["stages"]["manifest"] = {
            "status": "complete",
            "output": str(manifest_path)
        }
        
        # Stage 2: Enhanced validation with the configured vision model
        logger.info("\n" + "=" * 80)
        logger.info(f"🔍 STAGE 2: VLM-Powered Validation ({vlm_model})")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 2: VLM-Powered Validation", 25,
                    step="Stage 2: VLM-Powered Validation")
        
        # First: Basic per-page evidence extraction
        logger.info("📊 Step 2a: Extracting per-page evidence...")
        _emit_event("progress", "validation", "Extracting per-page content evidence...", 26)
        validation_path = self.work_dir / f"{doc_name}_validation.json"
        validation_report, manifest = self._run_validation_stage(
            pdf_path=pdf_path,
            markdown_path=markdown_path,
            vlm_model=vlm_model,
            docling_version=docling_version,
            validation_path=validation_path,
            manifest=manifest,
            manifest_path=manifest_path,
            reviewer=reviewer,
            page_markdown_map=page_markdown_map,
        )
        _emit_event("progress", "validation",
                    f"Per-page evidence extracted "
                    f"({validation_report.metadata.get('total_issues', 0)} issues found).", 38)
        
        # Second: Deep VLM comparison (optional - can be skipped for speed)
        logger.info("\n📊 Step 2b: Running VLM deep comparison (this takes ~70-80 min)...")
        logger.info("⚠️  Note: You can skip VLM comparison by pressing Ctrl+C")
        logger.info("         Basic validation is already complete.")
        _emit_event("progress", "validation", "Running VLM deep comparison (this may take ~70 min)...", 40)
        
        try:
            # Import the VLM comparison function
            from ..validation.vlm_comparison import compare_with_vlm
            
            # Load markdown for VLM
            with open(markdown_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            
            # Run VLM comparison
            vlm_result = compare_with_vlm(markdown_content, pdf_path)
            
            # Merge VLM results into validation report
            if vlm_result and 'format_issues' in vlm_result:
                validation_report.metadata['vlm_validation'] = vlm_result
                logger.info("✅ VLM validation complete")
            _emit_event("progress", "validation", "VLM deep comparison complete.", 55)
            
        except KeyboardInterrupt:
            logger.warning("⚠️  VLM comparison skipped by user")
            _emit_event("progress", "validation", "VLM comparison skipped by user.", 55)
        except Exception as e:
            logger.warning(f"⚠️  VLM comparison failed (continuing with basic validation): {e}")
            _emit_event("progress", "validation", f"VLM comparison skipped: {e}", 55)
        
        results["stages"]["validation"] = {
            "status": "complete",
            "output": str(validation_path),
            "confidence": validation_report.overall_confidence,
            "total_issues": validation_report.metadata["total_issues"],
            "critical_issues": validation_report.metadata["critical_issues"]
        }
        
        # Stage 2b: VLM Image Description (if image loss detected)
        logger.info("\n" + "=" * 80)
        logger.info("🖼️  STAGE 2b: VLM Image Description Generation")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 2b: VLM Image Description Generation", 55,
                    step="Stage 2b: VLM Image Description Generation")
        
        # Count image loss issues
        image_loss_count = sum(
            1 for pv in validation_report.page_validations
            for issue in pv.issues
            if issue.issue_type == "image_loss"
        )
        
        if image_loss_count > 0:
            logger.info(f"📊 Detected {image_loss_count} pages with image loss")
            logger.info(f"🤖 Generating image descriptions with {vlm_model}...")
            logger.info("   This takes ~20-30 min...")
            _emit_event("progress", "validation",
                        f"Detected {image_loss_count} pages with image loss. Generating descriptions (~20-30 min)...", 56)
            
            # Create enhanced markdown with image descriptions
            markdown_enhanced_path = self.work_dir / f"{doc_name}_with_images.md"
            
            try:
                image_description_cmd = [
                    sys.executable,
                    "-m",
                    "pipeline.src.validation.vlm_image_describer",
                    "--pdf", pdf_path,
                    "--markdown", markdown_path,
                    "--validation", str(validation_path),
                    "--output", str(markdown_enhanced_path),
                    "--preset", "quality",
                ]
                result = subprocess.run(
                    image_description_cmd,
                    capture_output=True,
                    text=True,
                    timeout=2400,
                    cwd=str(Path(__file__).resolve().parents[3]),
                    env=os.environ.copy(),
                )
                
                if result.returncode == 0:
                    logger.info("✅ Image descriptions generated")
                    # Use enhanced markdown for rest of pipeline
                    markdown_path = str(markdown_enhanced_path)
                    with open(markdown_path) as f:
                        markdown_content = f.read()

                    logger.info("📊 Re-running validation against final markdown with image descriptions...")
                    validation_report, manifest = self._run_validation_stage(
                        pdf_path=pdf_path,
                        markdown_path=markdown_path,
                        vlm_model=vlm_model,
                        docling_version=docling_version,
                        validation_path=validation_path,
                        manifest=manifest,
                        manifest_path=manifest_path,
                        reviewer=reviewer,
                        page_markdown_map=page_markdown_map,
                    )
                    results["stages"]["validation"] = {
                        "status": "complete",
                        "output": str(validation_path),
                        "confidence": validation_report.overall_confidence,
                        "total_issues": validation_report.metadata["total_issues"],
                        "critical_issues": validation_report.metadata["critical_issues"],
                        "validated_markdown": str(markdown_enhanced_path),
                    }
                    
                    results["stages"]["image_descriptions"] = {
                        "status": "complete",
                        "output": str(markdown_enhanced_path),
                        "pages_processed": image_loss_count
                    }
                    _emit_event("progress", "validation",
                                f"Image descriptions generated for {image_loss_count} pages.", 64)
                else:
                    failure_output = (result.stderr or result.stdout or "")[:500]
                    logger.warning(f"⚠️  Image description failed: {failure_output}")
                    logger.info("   Continuing with original markdown...")
                    with open(markdown_path, 'r', encoding='utf-8') as f:
                        markdown_content = f.read()
                    results["stages"]["image_descriptions"] = {
                        "status": "failed",
                        "error": failure_output
                    }
                    _emit_event("progress", "validation", "Image description failed, using original markdown.", 64)
                    
            except subprocess.TimeoutExpired:
                logger.warning("⚠️  Image description timed out - continuing with original markdown")
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                results["stages"]["image_descriptions"] = {
                    "status": "timeout"
                }
                _emit_event("progress", "validation", "Image description timed out, continuing.", 64)
            except Exception as e:
                logger.warning(f"⚠️  Image description error: {e}")
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                results["stages"]["image_descriptions"] = {
                    "status": "error",
                    "error": str(e)
                }
                _emit_event("progress", "validation", f"Image description error: {e}", 64)
        else:
            logger.info("✅ No image loss detected - skipping image description")
            _emit_event("progress", "validation", "No image loss detected, skipping description generation.", 64)
            with open(markdown_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            results["stages"]["image_descriptions"] = {
                "status": "skipped",
                "reason": "no_image_loss"
            }
        
        # Stage 3: Table and figure extraction
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 3: Table and Figure Analysis")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 3: Table & Figure Analysis", 65,
                    step="Stage 3: Table & Figure Analysis")
        
        tables = extract_tables_from_pdf(pdf_path)
        figures = extract_figures_from_markdown(markdown_content)
        _emit_event("progress", "validation",
                    f"Extracted {len(tables)} table(s) and {len(figures)} figure(s).", 71)
        
        table_figure_report_path = self.work_dir / f"{doc_name}_tables_figures.json"
        generate_table_figure_report(tables, figures, str(table_figure_report_path))
        
        results["stages"]["table_figure"] = {
            "status": "complete",
            "output": str(table_figure_report_path),
            "tables": len(tables),
            "figures": len(figures)
        }
        
        # Stage 4: Page-based review workspace (primary) + section metadata (compatibility)
        logger.info("\n" + "=" * 80)
        logger.info("📋 STAGE 4: Create Page-Based Review Workspace")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 4: Building Review Workspace", 72,
                    step="Stage 4: Building Review Workspace")

        pages = extract_pages_from_validation(validation_report, doc_name)
        sections = extract_sections_from_markdown(markdown_content, doc_name)

        review_workspace = self.work_dir / f"{doc_name}_review"
        create_page_review_workspace(pages, str(review_workspace))
        create_review_workspace(sections, str(review_workspace))
        _emit_event("progress", "validation",
                    f"Review workspace ready: {pages.total_pages} pages, "
                    f"{sections.total_sections} sections.", 79)
        
        results["stages"]["review_workspace"] = {
            "status": "complete",
            "output": str(review_workspace),
            "review_unit": "page",
            "total_pages": pages.total_pages,
            "total_sections": sections.total_sections,
            "sections_with_tables": sections.metadata["sections_with_tables"],
            "sections_with_images": sections.metadata["sections_with_images"]
        }
        
        # Stage 5: Initial version
        logger.info("\n" + "=" * 80)
        logger.info("💾 STAGE 5: Create Initial Version")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 5: Versioning", 80,
                    step="Stage 5: Versioning")
        
        versions_dir = self.work_dir / f"{doc_name}_versions"
        manifest = create_version(
            manifest,
            markdown_content,
            str(versions_dir),
            version_notes="Initial extraction from Docling"
        )
        save_manifest(manifest, str(manifest_path))
        _emit_event("progress", "validation", "Initial v1 snapshot created.", 84)
        
        results["stages"]["versioning"] = {
            "status": "complete",
            "version": 1,
            "versions_dir": str(versions_dir)
        }
        
        # Stage 6: Compute QA metrics (pre-review)
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 6: Compute Pre-Review QA Metrics")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 6: Pre-Review QA Metrics", 85,
                    step="Stage 6: Pre-Review QA Metrics")
        
        sections_for_qa = [
            {
                "heading": s.heading,
                "content": s.content,
                "has_tables": s.has_tables
            }
            for s in sections.sections
        ]
        
        validation_dict = {
            "overall_confidence": validation_report.overall_confidence,
            "page_validations": [
                {
                    "issues": [
                        {
                            "issue_type": issue.issue_type,
                            "severity": issue.severity
                        }
                        for issue in pv.issues
                    ]
                }
                for pv in validation_report.page_validations
            ]
        }
        
        qa_metrics = compute_qa_metrics(
            sections_for_qa,
            validation_dict,
            None  # No review data yet
        )
        
        qa_criteria = AcceptanceCriteria()
        qa_result = evaluate_qa_gate(qa_metrics, qa_criteria)
        qa_result.document_name = doc_name
        
        qa_report_path = self.work_dir / f"{doc_name}_qa_pre_review.json"
        save_qa_report(qa_result, str(qa_report_path))
        
        results["stages"]["qa_pre_review"] = {
            "status": "complete",
            "output": str(qa_report_path),
            "decision": qa_result.decision,
            "passed_criteria": len(qa_result.passed_criteria),
            "failed_criteria": len(qa_result.failed_criteria)
        }
        _emit_event("progress", "validation",
                    f"QA gate: {qa_result.decision} "
                    f"({len(qa_result.passed_criteria)} passed, "
                    f"{len(qa_result.failed_criteria)} failed).", 92)
        
        # Stage 7: Generate audit report
        logger.info("\n" + "=" * 80)
        logger.info("📋 STAGE 7: Generate Audit Report")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 7: Audit Report", 92,
                    step="Stage 7: Audit Report")
        
        audit_report = generate_audit_report(manifest)
        audit_path = self.work_dir / f"{doc_name}_audit.txt"
        
        with open(audit_path, 'w') as f:
            f.write(audit_report)
        
        logger.info(f"💾 Audit report: {audit_path}")
        _emit_event("progress", "validation", f"Audit trail written to {audit_path.name}.", 98)
        
        results["stages"]["audit"] = {
            "status": "complete",
            "output": str(audit_path)
        }
        
        # Pipeline summary
        logger.info("\n" + "=" * 80)
        logger.info("✅ HITL PIPELINE COMPLETE")
        logger.info("=" * 80)
        logger.info(f"\n📊 PIPELINE SUMMARY:")
        logger.info(f"   Document: {doc_name}")
        logger.info(f"   Reviewer: {reviewer}")
        logger.info(f"   Validation Confidence: {validation_report.overall_confidence:.2%}")
        logger.info(f"   Total Issues: {validation_report.metadata['total_issues']}")
        logger.info(f"   Critical Issues: {validation_report.metadata['critical_issues']}")
        logger.info(f"   Review Pages: {pages.total_pages}")
        logger.info(f"   Sections: {sections.total_sections}")
        logger.info(f"   Tables: {len(tables)}")
        logger.info(f"   Figures: {len(figures)}")
        logger.info(f"   QA Decision: {qa_result.decision}")
        logger.info(f"\n📁 Outputs:")
        logger.info(f"   Workspace: {self.work_dir}")
        logger.info(f"   Review Sections: {review_workspace}")
        logger.info(f"   Manifest: {manifest_path}")
        logger.info(f"   Audit: {audit_path}")
        
        # Next steps
        logger.info(f"\n📋 NEXT STEPS FOR REVIEWER:")
        logger.info(f"   1. Review pages in: {review_workspace}")
        logger.info(f"   2. Fill out checklists for each page")
        logger.info(f"   3. Address {len(qa_result.failed_criteria)} failed QA criteria")
        logger.info(f"   4. Focus on {validation_report.metadata['critical_issues']} critical issues")
        
        if qa_result.recommendations:
            logger.info(f"\n💡 RECOMMENDATIONS:")
            for rec in qa_result.recommendations[:5]:
                logger.info(f"   - {rec}")
        
        results["summary"] = {
            "pipeline_status": "complete",
            "review_required": True,
            "workspace": str(self.work_dir),
            "next_action": "manual_review",
            "qa_decision": qa_result.decision
        }
        
        # Save pipeline results
        results_path = self.work_dir / f"{doc_name}_pipeline_results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n💾 Pipeline results saved: {results_path}")
        
        return results
    
    def run_post_approval_reformatting(
        self,
        doc_name: str,
        pdf_path: str,
        validation_report_path: str,
        markdown_path: Optional[str] = None,
        optimization_prep_path: Optional[str] = None,
    ) -> Dict:
        """
        Run shared text-model reformatting AFTER manual review approval
        This is Stage 10 - final AI-powered optimization
        """
        try:
            # Import reformatter
            from ..cli.text_reformatter import reformat_with_qwen, save_output
            optimization_prep = None
            markdown_content = ""

            if optimization_prep_path:
                with open(optimization_prep_path, 'r', encoding='utf-8') as f:
                    optimization_prep = json.load(f)
                markdown_content = str(optimization_prep.get("combined_markdown") or "")

            if not markdown_content and markdown_path:
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()

            if not markdown_content:
                raise ValueError("No authoritative reviewed markdown available for optimization")
            
            # Load validation report
            with open(validation_report_path, 'r') as f:
                validation_data = json.load(f)
            
            # Run reformatting
            result = reformat_with_qwen(
                markdown_content,
                validation_data,
                pdf_path,
                doc_name,
                optimization_prep=optimization_prep,
            )
            
            if not result:
                logger.error("Reformatting returned no result")
                return {"status": "failed"}

            if not _has_structurally_valid_optimized_output(result):
                logger.error("Reformatting produced incomplete optimized output")
                return {
                    "status": "error",
                    "message": "Optimization output is incomplete and not suitable for QA",
                }

            output_base = self.work_dir / f"{doc_name}_rag_optimized"
            save_output(result, str(output_base))
            output_json = output_base.with_suffix('.json')
            output_md = output_base.with_suffix('.md')

            logger.info("Reformatting complete")

            return {
                "status": "complete",
                "json_output": str(output_json),
                "markdown_output": str(output_md)
            }
                
        except Exception as e:
            logger.error(f"Reformatting failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    def get_review_status(self, doc_name: str) -> Dict:
        """Get current review status for a document"""
        review_workspace = self.work_dir / f"{doc_name}_review"
        
        if not review_workspace.exists():
            return {"error": "Review workspace not found"}
        
        progress = get_review_progress(str(review_workspace))
        
        logger.info(f"📊 Review Progress for {doc_name}:")
        logger.info(f"   Total sections: {progress['total_sections']}")
        logger.info(f"   Completion: {progress['completion_percentage']:.1f}%")
        logger.info(f"   By status:")
        for status, count in progress['by_status'].items():
            logger.info(f"     {status}: {count}")
        
        return progress


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Enhanced HITL Pipeline Orchestrator"
    )
    parser.add_argument("action", choices=["run", "status", "reformat"],
                       help="Action to perform")
    parser.add_argument("--pdf", help="PDF path (for run/reformat)")
    parser.add_argument("--markdown", help="Markdown path (for run/reformat)")
    parser.add_argument("--reviewer", default="human-reviewer", help="Reviewer name")
    parser.add_argument("--doc-name", help="Document name (for status/reformat)")
    parser.add_argument("--workspace", default="hitl_workspace", help="Workspace directory")
    parser.add_argument("--docling-version", default="1.0.0", help="Docling version")
    parser.add_argument(
        "--vlm-model",
        default=None,
        help="Vision model override (defaults to VISION_MODEL_ID from repo-root .env)",
    )
    parser.add_argument(
        "--reformatter-model",
        default=None,
        help="Text model override (defaults to TEXT_MODEL_ID from repo-root .env)",
    )
    parser.add_argument("--skip-vlm", action="store_true", help="Skip VLM deep comparison (faster)")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🚀 ENHANCED HITL PIPELINE ORCHESTRATOR")
    logger.info("=" * 80)
    
    pipeline = HITLPipeline(args.workspace)
    
    if args.action == "run":
        if not args.pdf or not args.markdown:
            logger.error("❌ --pdf and --markdown required for run action")
            return 1
        
        try:
            results = pipeline.run_full_pipeline(
                args.pdf,
                args.markdown,
                args.reviewer,
                args.docling_version,
                args.vlm_model,
                args.reformatter_model
            )
            
            logger.info("\n✅ Pipeline execution complete")
            
            # Show next action based on QA decision
            if results["summary"]["qa_decision"] == "approved":
                logger.info("\n🎉 Document APPROVED!")
                logger.info("   Next step: Run reformatting")
                logger.info(f"   Command: python3 rag_hitl_pipeline.py reformat --doc-name \"{Path(args.pdf).stem}\"")
            else:
                logger.info("\n⚠️  Document needs review")
                logger.info(f"   Review workspace: {results['stages']['review_workspace']['output']}")
            
            return 0
            
        except Exception as e:
            logger.error(f"❌ Pipeline failed: {e}", exc_info=True)
            return 1
    
    elif args.action == "status":
        if not args.doc_name:
            logger.error("❌ --doc-name required for status action")
            return 1
        
        try:
            status = pipeline.get_review_status(args.doc_name)
            
            if "error" in status:
                logger.error(f"❌ {status['error']}")
                return 1
            
            return 0
            
        except Exception as e:
            logger.error(f"❌ Status check failed: {e}")
            return 1
    
    elif args.action == "reformat":
        if not args.doc_name:
            # Try to infer from PDF
            if args.pdf:
                args.doc_name = Path(args.pdf).stem
            else:
                logger.error("❌ --doc-name or --pdf required for reformat action")
                return 1
        
        try:
            # Find paths
            workspace = Path(args.workspace)
            validation_path = workspace / f"{args.doc_name}_validation.json"
            
            if not args.markdown:
                # Try to find in workspace
                version_path = workspace / f"{args.doc_name}_versions" / f"{args.doc_name}_v1.md"
                if version_path.exists():
                    args.markdown = str(version_path)
                else:
                    logger.error("❌ --markdown required and could not auto-detect")
                    return 1
            
            if not args.pdf:
                logger.error("❌ --pdf required for reformat action")
                return 1
            
            logger.info(f"📄 Reformatting: {args.doc_name}")
            logger.info(f"   PDF: {args.pdf}")
            logger.info(f"   Markdown: {args.markdown}")
            logger.info(f"   Validation: {validation_path}")
            
            result = pipeline.run_post_approval_reformatting(
                args.doc_name,
                args.pdf,
                str(validation_path),
                markdown_path=args.markdown,
            )
            
            if result["status"] == "complete":
                logger.info("\n✅ Reformatting complete!")
                logger.info("   Ready for vector DB ingestion")
                return 0
            else:
                logger.error(f"\n❌ Reformatting failed: {result.get('message', 'Unknown error')}")
                return 1
                
        except Exception as e:
            logger.error(f"❌ Reformat failed: {e}", exc_info=True)
            return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
