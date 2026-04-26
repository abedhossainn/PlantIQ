#!/usr/bin/env python3
"""
Enhanced Validation Module - Per-page validation with evidence snapshots
Implements improvements from HITL analysis:
1. Per-page validation coverage
2. Evidence snapshots for reviewer cross-check
3. Issue labeling (missing content, formatting, semantic mismatch)
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

from ..utils.vlm_options import get_vision_model_id

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _normalize_text_for_match(text: str) -> str:
    """Normalize text for fuzzy matching between PDF previews and markdown."""
    cleaned = text.replace("&amp;", "&")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"[^\w\s|%-]", "", cleaned)
    return cleaned.lower().strip()


def _preview_anchor_candidates(text_preview: str) -> List[str]:
    """Build candidate anchor phrases from extracted PDF preview text."""
    candidates: List[str] = []
    for raw_line in text_preview.splitlines():
        normalized = _normalize_text_for_match(raw_line)
        if not normalized:
            continue
        if len(normalized) >= 18 or len(normalized.split()) >= 3:
            candidates.append(normalized)
    return candidates


def _fallback_markdown_section(markdown_content: str, page_number: int, total_pages: int) -> str:
    """Fallback heuristic when preview anchoring cannot locate a section."""
    lines = markdown_content.splitlines()
    if not lines:
        return ""

    total_pages = max(1, total_pages)
    section_size = max(40, len(lines) // total_pages)
    start_line = max(0, min((page_number - 1) * section_size, max(0, len(lines) - section_size)))
    end_line = min(len(lines), start_line + section_size)
    return "\n".join(lines[start_line:end_line])


def _extract_relevant_markdown_section(
    markdown_content: str,
    text_preview: str,
    page_number: int,
    total_pages: int,
) -> str:
    """Locate the most relevant markdown slice for a page using its extracted text preview."""
    lines = markdown_content.splitlines()
    if not lines:
        return ""

    anchor_candidates = _preview_anchor_candidates(text_preview)
    if not anchor_candidates:
        return _fallback_markdown_section(markdown_content, page_number, total_pages)

    normalized_lines = [_normalize_text_for_match(line) for line in lines]
    best_index, best_score = _find_best_anchor_line(normalized_lines, anchor_candidates)
    if best_index is None or best_score <= 0:
        return _fallback_markdown_section(markdown_content, page_number, total_pages)

    start_line = max(0, best_index - 40)
    end_line = min(len(lines), best_index + 120)
    return "\n".join(lines[start_line:end_line])


def _score_anchor_matches(normalized_line: str, anchor_candidates: List[str]) -> int:
    """Score a normalized markdown line against normalized anchor candidates."""
    return sum(
        1
        for candidate in anchor_candidates
        if candidate and (candidate in normalized_line or normalized_line in candidate)
    )


def _find_best_anchor_line(
    normalized_lines: List[str],
    anchor_candidates: List[str],
) -> tuple[Optional[int], int]:
    """Return best matching line index and its score for preview anchors."""
    best_index: Optional[int] = None
    best_score = -1
    for idx, normalized_line in enumerate(normalized_lines):
        if not normalized_line:
            continue
        score = _score_anchor_matches(normalized_line, anchor_candidates)
        if score > best_score:
            best_score = score
            best_index = idx
    return best_index, best_score


def _count_table_markers(markdown_section: str) -> int:
    """Estimate whether markdown section contains serialized tables."""
    return sum(1 for line in markdown_section.splitlines() if line.count("|") >= 2)


def _count_figure_markers(markdown_section: str) -> int:
    """Count both classic markdown image refs and description-mode figure markers."""
    markdown_images = markdown_section.count("![")
    described_figures = len(re.findall(r"\*\*\[Figure\s+\d+:", markdown_section, flags=re.IGNORECASE))
    return markdown_images + described_figures


def _candidate_sort_key(item: tuple[int, int], expected_center: int) -> tuple[int, int, int]:
    line_index, score = item
    return (-score, abs(line_index - expected_center), line_index)


def _sorted_page_evidences(page_evidences: List["PageEvidence"]) -> List["PageEvidence"]:
    """Return page evidences sorted by ascending page number."""
    return sorted(page_evidences, key=lambda item: item.page_number)


def _build_search_window(
    *,
    idx: int,
    total_pages: int,
    lines_count: int,
    search_floor: int,
) -> tuple[int, int, int]:
    """Build expected center and bounded search window for one page."""
    expected_center = int((idx - 0.5) * lines_count / total_pages)
    window_start = max(0, min(search_floor, lines_count - 1))
    next_expected = int((idx + 0.5) * lines_count / total_pages) if idx < total_pages else lines_count - 1
    window_end = min(lines_count, max(window_start + 160, next_expected + 120))
    return expected_center, window_start, window_end


def _collect_scored_candidates(
    *,
    anchors: List[str],
    normalized_lines: List[str],
    window_start: int,
    window_end: int,
) -> List[tuple[int, int]]:
    """Collect scored line candidates in the current search window."""
    if not anchors:
        return []

    candidates: List[tuple[int, int]] = []
    for line_index in range(window_start, window_end):
        normalized_line = normalized_lines[line_index]
        if not normalized_line:
            continue
        score = _score_anchor_matches(normalized_line, anchors)
        if score > 0:
            candidates.append((line_index, score))
    return candidates


def _resolve_candidate_indices(
    *,
    candidates: List[tuple[int, int]],
    expected_center: int,
    lines_count: int,
) -> tuple[List[int], bool]:
    """Resolve candidate line indices and whether they came from anchor matches."""
    has_candidates = bool(candidates)
    if not has_candidates:
        return [max(0, min(expected_center, lines_count - 1))], False

    candidates.sort(
        key=lambda item, expected_center=expected_center: _candidate_sort_key(item, expected_center)
    )
    return [candidate_index for candidate_index, _ in candidates], True


def _select_section_from_candidates(
    *,
    candidate_indices: List[int],
    has_candidates: bool,
    lines: List[str],
    window_start: int,
    previous_hash: Optional[int],
) -> tuple[str, int, int, int, bool]:
    """Select a non-empty section from top candidates with duplicate avoidance."""
    for candidate_index in candidate_indices[:8]:
        start_line = max(window_start, candidate_index - 40) if has_candidates else max(0, candidate_index - 40)
        end_line = min(len(lines), start_line + 160)
        section = "\n".join(lines[start_line:end_line]).strip()
        if not section:
            continue

        section_hash = hash(section)
        if section_hash != previous_hash:
            return section, start_line, end_line, section_hash, True
        return section, start_line, end_line, section_hash, False

    return "", window_start, window_start, hash(""), False


def _build_fallback_selection(
    *,
    markdown_content: str,
    page_number: int,
    total_pages: int,
    expected_center: int,
    window_start: int,
    lines_count: int,
) -> tuple[str, int, int, int]:
    """Build fallback page section selection when anchor matching fails."""
    fallback = _fallback_markdown_section(markdown_content, page_number, total_pages).strip()
    start_line = max(window_start, min(expected_center, lines_count - 1))
    end_line = min(lines_count, start_line + 160)
    return fallback, start_line, end_line, hash(fallback)


def _dedupe_section_with_fallback(
    *,
    selected_section: str,
    selected_hash: int,
    seen_hashes: set[int],
    markdown_content: str,
    page_number: int,
    total_pages: int,
) -> tuple[str, int]:
    """Avoid duplicate sections across pages by applying fallback when needed."""
    if selected_hash not in seen_hashes:
        return selected_section, selected_hash

    fallback = _fallback_markdown_section(markdown_content, page_number, total_pages).strip()
    if fallback:
        return fallback, hash(fallback)
    return selected_section, selected_hash


def _compute_progression_step(selected_start: int, selected_end: int) -> int:
    """Compute bounded forward progression step in markdown scan."""
    return max(1, int((selected_end - selected_start) * 0.35))


class IssueType(Enum):
    """Issue categorization for systematic tracking"""
    MISSING_CONTENT = "missing_content"
    FORMATTING = "formatting"
    SEMANTIC_MISMATCH = "semantic_mismatch"
    TABLE_FIDELITY = "table_fidelity"
    IMAGE_LOSS = "image_loss"


@dataclass
class PageEvidence:
    """Evidence snapshot for a single PDF page"""
    page_number: int
    text_preview: str
    image_count: int
    table_count: int
    has_figures: bool
    thumbnail_path: Optional[str] = None


@dataclass
class ValidationIssue:
    """Structured validation issue with categorization"""
    issue_type: str  # IssueType enum value
    severity: str  # "critical", "major", "minor"
    page_number: int
    description: str
    evidence: str
    suggested_fix: str


@dataclass
class PageValidationReport:
    """Per-page validation result"""
    page_number: int
    markdown_section: str
    evidence: PageEvidence
    issues: List[ValidationIssue]
    confidence_score: float  # 0.0-1.0
    reviewer_notes: Optional[str] = None


@dataclass
class DocumentValidation:
    """Complete document validation with lineage"""
    document_name: str
    pdf_hash: str
    markdown_hash: str
    docling_version: str
    vlm_model: str
    timestamp: str
    page_validations: List[PageValidationReport]
    overall_confidence: float
    metadata: Dict


def _build_page_markdown_map_from_previews(
    markdown_content: str,
    page_evidences: List["PageEvidence"],
) -> Dict[int, str]:
    """Build stable page-aligned markdown slices without a second Docling pass.

    Root-cause mitigation: the legacy per-page fallback searched the whole markdown
    for every page independently, so repeated boilerplate text could map many pages
    to the same anchor. This builder enforces forward progression through markdown
    while still using preview anchors, which keeps slices page-local and prevents
    repeated identical sections across multiple page numbers.
    """
    lines = markdown_content.splitlines()
    if not lines or not page_evidences:
        return {}

    normalized_lines = [_normalize_text_for_match(line) for line in lines]
    total_pages = max(1, len(page_evidences))
    search_floor = 0
    previous_hash = None
    seen_hashes: set[int] = set()
    page_map: Dict[int, str] = {}

    for idx, evidence in enumerate(_sorted_page_evidences(page_evidences), start=1):
        anchors = _preview_anchor_candidates(evidence.text_preview or "")
        expected_center, window_start, window_end = _build_search_window(
            idx=idx,
            total_pages=total_pages,
            lines_count=len(lines),
            search_floor=search_floor,
        )
        candidates = _collect_scored_candidates(
            anchors=anchors,
            normalized_lines=normalized_lines,
            window_start=window_start,
            window_end=window_end,
        )
        candidate_indices, has_candidates = _resolve_candidate_indices(
            candidates=candidates,
            expected_center=expected_center,
            lines_count=len(lines),
        )
        selected_section, selected_start, selected_end, selected_hash, is_new_hash = _select_section_from_candidates(
            candidate_indices=candidate_indices,
            has_candidates=has_candidates,
            lines=lines,
            window_start=window_start,
            previous_hash=previous_hash,
        )

        if not selected_section:
            selected_section, selected_start, selected_end, selected_hash = _build_fallback_selection(
                markdown_content=markdown_content,
                page_number=evidence.page_number,
                total_pages=total_pages,
                expected_center=expected_center,
                window_start=window_start,
                lines_count=len(lines),
            )
            is_new_hash = True

        if is_new_hash:
            previous_hash = selected_hash

        selected_section, selected_hash = _dedupe_section_with_fallback(
            selected_section=selected_section,
            selected_hash=selected_hash,
            seen_hashes=seen_hashes,
            markdown_content=markdown_content,
            page_number=evidence.page_number,
            total_pages=total_pages,
        )
        seen_hashes.add(selected_hash)

        page_map[evidence.page_number] = selected_section

        progression_step = _compute_progression_step(selected_start, selected_end)
        search_floor = min(len(lines) - 1, max(search_floor, selected_start + progression_step))

    return page_map


def extract_page_evidence(pdf_path: str) -> List[PageEvidence]:
    """
    Extract evidence snapshots from each PDF page
    Captures text preview, image/table counts for reviewer cross-check
    """
    try:
        import pdfplumber
        from PIL import Image
        import io
        
        logger.info(f"📥 Extracting page evidence: {pdf_path}")
        
        evidence_list = []
        output_dir = Path("validation_evidence")
        output_dir.mkdir(exist_ok=True)
        
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                # Extract text preview
                text = page.extract_text() or ""
                text_preview = text[:500] if text else "[No text extracted]"
                
                # Count tables and images
                tables = page.find_tables()
                images = page.images
                
                # Detect figures (images that aren't table backgrounds)
                has_figures = len(images) > 0
                
                # Create thumbnail for manual review
                thumbnail_path = None
                try:
                    # Convert page to image
                    im = page.to_image(resolution=150)
                    thumbnail_path = str(output_dir / f"page_{i+1}_thumbnail.png")
                    im.save(thumbnail_path)
                except Exception as e:
                    logger.warning(f"⚠️  Could not create thumbnail for page {i+1}: {e}")
                
                evidence = PageEvidence(
                    page_number=i + 1,
                    text_preview=text_preview,
                    image_count=len(images),
                    table_count=len(tables),
                    has_figures=has_figures,
                    thumbnail_path=thumbnail_path
                )
                
                evidence_list.append(evidence)
                logger.info(f"✅ Page {i+1}: {len(tables)} tables, {len(images)} images")
        
        logger.info(f"✅ Extracted evidence for {len(evidence_list)} pages")
        return evidence_list
        
    except Exception as e:
        logger.error(f"❌ Page evidence extraction failed: {e}")
        return []


def validate_page_against_markdown(
    page_evidence: PageEvidence,
    markdown_content: str,
    total_pages: int,
    vlm_model=None,
    page_markdown_map: Optional[Dict[int, str]] = None,
) -> PageValidationReport:
    """
    Validate a single page against its corresponding markdown section
    Uses VLM to identify issues with categorization
    """
    if vlm_model is not None:
        logger.debug(
            "VLM semantic validation hook enabled for page %s",
            page_evidence.page_number,
        )
    issues = []
    
    markdown_section = ""
    if page_markdown_map:
        markdown_section = (page_markdown_map.get(page_evidence.page_number) or "").strip()

    if not markdown_section:
        markdown_section = _extract_relevant_markdown_section(
            markdown_content,
            page_evidence.text_preview,
            page_evidence.page_number,
            total_pages,
        )
    
    # Check for missing tables
    if page_evidence.table_count > 0:
        table_rows_in_md = _count_table_markers(markdown_section)
        if table_rows_in_md < page_evidence.table_count * 2:
            issues.append(ValidationIssue(
                issue_type=IssueType.TABLE_FIDELITY.value,
                severity="major",
                page_number=page_evidence.page_number,
                description=f"Page has {page_evidence.table_count} tables, but markdown section appears incomplete",
                evidence=f"Text preview: {page_evidence.text_preview[:100]}...",
                suggested_fix="Extract table data as bullet points and preserve table structure"
            ))
    
    # Check for missing images
    if page_evidence.has_figures:
        image_refs = _count_figure_markers(markdown_section)
        if image_refs < page_evidence.image_count:
            issues.append(ValidationIssue(
                issue_type=IssueType.IMAGE_LOSS.value,
                severity="critical",
                page_number=page_evidence.page_number,
                description=f"Page has {page_evidence.image_count} images, found {image_refs} in markdown",
                evidence=f"Images detected in PDF page {page_evidence.page_number}",
                suggested_fix="Add text descriptions for all figures in markdown using the standard Figure description format"
            ))
    
    # Calculate confidence score (simple heuristic - can be enhanced with VLM)
    confidence_score = 1.0
    if len(issues) > 0:
        confidence_score = max(0.0, 1.0 - (len(issues) * 0.15))
    
    return PageValidationReport(
        page_number=page_evidence.page_number,
        markdown_section=markdown_section,
        evidence=page_evidence,
        issues=issues,
        confidence_score=confidence_score,
        reviewer_notes=None
    )


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash for lineage tracking"""
    import hashlib
    
    with open(file_path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def create_validation_report(
    pdf_path: str,
    markdown_path: str,
    vlm_model_name: str,
    docling_version: str = "1.0.0",
    page_markdown_map: Optional[Dict[int, str]] = None,
) -> DocumentValidation:
    """
    Create comprehensive validation report with lineage tracking
    """
    logger.info("🔍 Creating enhanced validation report...")
    
    # Extract evidence from PDF
    page_evidences = extract_page_evidence(pdf_path)
    
    if not page_evidences:
        raise RuntimeError("No page evidence extracted")
    
    # Load markdown
    with open(markdown_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    # Build deterministic page-level markdown mapping when exact page map is unavailable.
    resolved_page_markdown_map = page_markdown_map or _build_page_markdown_map_from_previews(
        markdown_content,
        page_evidences,
    )

    # Validate each page
    page_validations = []
    total_pages = len(page_evidences)
    for evidence in page_evidences:
        validation = validate_page_against_markdown(
            evidence,
            markdown_content,
            vlm_model=None,  # Will integrate VLM in next iteration
            total_pages=total_pages,
            page_markdown_map=resolved_page_markdown_map,
        )
        page_validations.append(validation)
        logger.info(f"✅ Validated page {evidence.page_number}: {len(validation.issues)} issues found")
    
    # Calculate overall confidence
    overall_confidence = sum(v.confidence_score for v in page_validations) / len(page_validations)
    
    # Create validation report with lineage
    report = DocumentValidation(
        document_name=Path(pdf_path).stem,
        pdf_hash=compute_file_hash(pdf_path),
        markdown_hash=compute_file_hash(markdown_path),
        docling_version=docling_version,
        vlm_model=vlm_model_name,
        timestamp=datetime.utcnow().isoformat() + "Z",
        page_validations=page_validations,
        overall_confidence=overall_confidence,
        metadata={
            "total_pages": len(page_validations),
            "total_issues": sum(len(v.issues) for v in page_validations),
            "critical_issues": sum(
                len([i for i in v.issues if i.severity == "critical"]) 
                for v in page_validations
            )
        }
    )
    
    logger.info(f"✅ Validation complete: {overall_confidence:.2%} confidence")
    logger.info(f"📊 Total issues: {report.metadata['total_issues']} ({report.metadata['critical_issues']} critical)")
    
    return report


def save_validation_report(report: DocumentValidation, output_path: str):
    """Save validation report as JSON with proper structure"""
    output_file = Path(output_path)
    
    # Convert to dict (handle nested dataclasses)
    def to_dict(obj):
        if hasattr(obj, '__dict__'):
            return {k: to_dict(v) for k, v in asdict(obj).items()}
        elif isinstance(obj, list):
            return [to_dict(item) for item in obj]
        return obj
    
    report_dict = to_dict(report)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report_dict, f, indent=2)
    
    logger.info(f"💾 Validation report saved: {output_file}")


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Enhanced per-page validation with evidence tracking"
    )
    parser.add_argument("pdf", help="Path to PDF file")
    parser.add_argument("--markdown", required=True, help="Path to markdown file")
    parser.add_argument("--output", default="validation_enhanced.json", help="Output JSON path")
    parser.add_argument(
        "--vlm-model",
        default=None,
        help="Vision model name (defaults to VISION_MODEL_ID from repo-root .env)",
    )
    parser.add_argument("--docling-version", default="1.0.0", help="Docling version")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🔍 Enhanced Validation Module")
    logger.info("=" * 80)
    
    try:
        report = create_validation_report(
            args.pdf,
            args.markdown,
            args.vlm_model or get_vision_model_id(),
            args.docling_version
        )
        save_validation_report(report, args.output)
    except Exception as exc:
        logger.error("❌ Validation failed: %s", exc)
        return 1

    logger.info("✅ Enhanced validation complete")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
