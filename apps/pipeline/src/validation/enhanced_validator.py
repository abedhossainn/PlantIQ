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
logger = logging.getLogger(__name__)  # NOSONAR: Standard logger initialization

FIGURE_DESCRIPTION_PATTERN = re.compile(
    r"\*\*\s*\[?\s*Figure\s+\d+\s*:",
    flags=re.IGNORECASE,
)

ADDITIONAL_VISUAL_BLOCK_HEADING_PATTERN = re.compile(
    r"(?m)^##\s+Additional\s+Visual\s+Elements\s*\(\s*Page\s*(?P<page_number>\d+)\s*\)\s*$"
)


def _extract_additional_visual_blocks(markdown_content: str) -> tuple[str, Dict[int, str]]:
    """Extract per-page visual appendix blocks and return markdown without those blocks.

    Returns:
        (clean_markdown, appendix_blocks_by_page)

    Appendix blocks are expected in this format:
        ## Additional Visual Elements (Page N)
        ...block content...

    Each extracted block is preserved exactly as it appears in source markdown.
    """
    matches = list(ADDITIONAL_VISUAL_BLOCK_HEADING_PATTERN.finditer(markdown_content))
    if not matches:
        return markdown_content, {}

    clean_parts: List[str] = []
    appendix_blocks_by_page: Dict[int, str] = {}
    cursor = 0

    for index, match in enumerate(matches):
        block_start = match.start()
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_content)

        clean_parts.append(markdown_content[cursor:block_start])

        block_text = markdown_content[block_start:block_end]
        page_number = int(match.group("page_number"))

        existing_block = appendix_blocks_by_page.get(page_number)
        if existing_block:
            appendix_blocks_by_page[page_number] = f"{existing_block.rstrip()}\n\n{block_text.lstrip()}"
        else:
            appendix_blocks_by_page[page_number] = block_text

        cursor = block_end

    clean_parts.append(markdown_content[cursor:])
    clean_markdown = "".join(clean_parts)
    return clean_markdown, appendix_blocks_by_page


def _append_additional_visual_blocks_to_page_map(
    page_map: Dict[int, str],
    appendix_blocks_by_page: Dict[int, str],
) -> Dict[int, str]:
    """Append extracted visual appendix blocks to only their intended page entries."""
    if not page_map or not appendix_blocks_by_page:
        return page_map

    for page_number, appendix_block in appendix_blocks_by_page.items():
        if page_number not in page_map:
            continue

        page_content = (page_map.get(page_number) or "").rstrip()
        appendix_content = appendix_block.strip()

        if not appendix_content:
            continue

        if page_content:
            page_map[page_number] = f"{page_content}\n\n{appendix_content}"
        else:
            page_map[page_number] = appendix_content

    return page_map


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


def _compute_adaptive_window_params(lines_count: int, total_pages: int) -> tuple[int, int]:
    """Compute adaptive window size and lookback based on document density.

    Returns: (section_window, lookback)
    """
    lines_per_page = max(1.0, lines_count / max(1, total_pages))
    section_window = max(15, min(160, int(lines_per_page * 1.5)))
    lookback = max(3, min(40, int(lines_per_page * 0.4)))
    return section_window, lookback


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

    section_window, lookback = _compute_adaptive_window_params(len(lines), total_pages)

    start_line = max(0, best_index - lookback)
    end_line = min(len(lines), start_line + section_window)
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


def _count_vlm_image_descriptions_in_ave(markdown_section: str) -> int:
    """Count VLM-generated image descriptions inside Additional Visual Elements blocks.

    The VLM image describer emits standalone bold-title lines (**Title**) for each
    described image inside those blocks.  Each such line counts as one represented image.
    """
    ave_match = ADDITIONAL_VISUAL_BLOCK_HEADING_PATTERN.search(markdown_section)
    if not ave_match:
        return 0
    ave_content = markdown_section[ave_match.start():]
    return len(re.findall(r'^\*\*[^*\n]+\*\*\s*$', ave_content, re.M))


def _count_figure_markers(markdown_section: str) -> int:
    """Count both classic markdown image refs and description-mode figure markers."""
    markdown_images = markdown_section.count("![")
    described_figures = len(FIGURE_DESCRIPTION_PATTERN.findall(markdown_section))
    # VLM image describer replaces images with **Bold Title** + description text inside
    # Additional Visual Elements blocks — count those as represented images too.
    vlm_descriptions = _count_vlm_image_descriptions_in_ave(markdown_section)
    return markdown_images + described_figures + vlm_descriptions


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
    section_window: int = 160,
) -> tuple[int, int, int]:
    """Build expected center and bounded search window for one page."""
    expected_center = int((idx - 0.5) * lines_count / total_pages)
    window_start = max(0, min(search_floor, lines_count - 1))
    next_expected = int((idx + 0.5) * lines_count / total_pages) if idx < total_pages else lines_count - 1
    window_end = min(
        lines_count,
        max(window_start + section_window, next_expected + int(section_window * 0.75)),
    )
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
    section_window: int = 160,
    lookback: int = 40,
) -> tuple[str, int, int, int, bool]:
    """Select a non-empty section from top candidates with duplicate avoidance."""
    for candidate_index in candidate_indices[:8]:
        start_line = max(window_start, candidate_index - lookback) if has_candidates else max(0, candidate_index - lookback)
        end_line = min(len(lines), start_line + section_window)
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
    section_window: int = 160,
) -> tuple[str, int, int, int]:
    """Build fallback page section selection when anchor matching fails."""
    fallback = _fallback_markdown_section(markdown_content, page_number, total_pages).strip()
    start_line = max(window_start, min(expected_center, lines_count - 1))
    end_line = min(lines_count, start_line + section_window)
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


def _resolve_monotonic_anchor_starts(
    *,
    sorted_evidences: List["PageEvidence"],
    normalized_lines: List[str],
    lines_count: int,
    total_pages: int,
    search_radius: int,
) -> List[int]:
    """Resolve one forward-only anchor start index per page."""
    anchor_starts: List[int] = []
    search_floor = 0

    for idx, evidence in enumerate(sorted_evidences, start=1):
        anchors = _preview_anchor_candidates(evidence.text_preview or "")
        expected_center = int((idx - 0.5) * lines_count / total_pages)
        expected_center = max(search_floor, min(expected_center, lines_count - 1))

        window_start = max(search_floor, expected_center - search_radius)
        window_end = min(lines_count, max(window_start + 1, expected_center + search_radius))

        candidates = _collect_scored_candidates(
            anchors=anchors,
            normalized_lines=normalized_lines,
            window_start=window_start,
            window_end=window_end,
        )
        candidate_indices, has_candidates = _resolve_candidate_indices(
            candidates=candidates,
            expected_center=expected_center,
            lines_count=lines_count,
        )

        anchor_start = max(search_floor, candidate_indices[0] if has_candidates else expected_center)
        anchor_start = min(anchor_start, lines_count - 1)
        if anchor_starts and anchor_start <= anchor_starts[-1]:
            anchor_start = min(lines_count - 1, anchor_starts[-1] + 1)

        anchor_starts.append(anchor_start)
        search_floor = min(lines_count - 1, anchor_start + 1)

    return anchor_starts


def _bounded_slice_lines(
    *,
    lines: List[str],
    start_line: int,
    next_start: int,
    has_next_anchor: bool,
    lines_count: int,
    min_section_lines: int,
    max_section_lines: int,
    boundary_backfill: int,
) -> str:
    """Slice bounded page-local markdown using [start_i, start_{i+1}) semantics."""
    if next_start <= start_line:
        next_start = min(lines_count, start_line + max(min_section_lines, 1))

    if has_next_anchor:
        end_line = min(next_start, start_line + max_section_lines)
    else:
        end_line = min(lines_count, max(next_start, start_line + min_section_lines))

    if end_line <= start_line:
        end_line = min(lines_count, start_line + max(min_section_lines, 1))

    selected_section = "\n".join(lines[start_line:end_line]).strip()
    if selected_section or boundary_backfill <= 0:
        return selected_section

    backfilled_start = max(0, start_line - boundary_backfill)
    return "\n".join(lines[backfilled_start:end_line]).strip()


def _build_non_overlapping_page_sections(
    *,
    sorted_evidences: List["PageEvidence"],
    anchor_starts: List[int],
    lines: List[str],
    markdown_content: str,
    total_pages: int,
    section_window: int,
    min_section_lines: int,
    max_section_lines: int,
    boundary_backfill: int,
) -> Dict[int, str]:
    """Build page map from monotonic anchors with duplicate-safe fallback."""
    lines_count = len(lines)
    seen_hashes: set[int] = set()
    page_map: Dict[int, str] = {}

    for index, evidence in enumerate(sorted_evidences):
        start_line = anchor_starts[index]
        has_next_anchor = index + 1 < len(anchor_starts)
        next_start = anchor_starts[index + 1] if has_next_anchor else lines_count

        selected_section = _bounded_slice_lines(
            lines=lines,
            start_line=start_line,
            next_start=next_start,
            has_next_anchor=has_next_anchor,
            lines_count=lines_count,
            min_section_lines=min_section_lines,
            max_section_lines=max_section_lines,
            boundary_backfill=boundary_backfill,
        )

        if not selected_section:
            selected_section, _, _, _ = _build_fallback_selection(
                markdown_content=markdown_content,
                page_number=evidence.page_number,
                total_pages=total_pages,
                expected_center=start_line,
                window_start=start_line,
                lines_count=lines_count,
                section_window=section_window,
            )
            selected_section = selected_section.strip()

        selected_hash = hash(selected_section)
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

    return page_map


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
    clean_markdown_content, appendix_blocks_by_page = _extract_additional_visual_blocks(markdown_content)

    lines = clean_markdown_content.splitlines()
    if not lines or not page_evidences:
        return {}

    sorted_evidences = _sorted_page_evidences(page_evidences)
    total_pages = max(1, len(sorted_evidences))
    lines_count = len(lines)
    normalized_lines = [_normalize_text_for_match(line) for line in lines]

    lines_per_page = max(1.0, lines_count / total_pages)
    section_window, _ = _compute_adaptive_window_params(lines_count, total_pages)
    max_section_lines = max(20, min(section_window, int(lines_per_page * 2.0)))
    min_section_lines = max(8, min(max_section_lines, int(lines_per_page * 0.45)))
    search_radius = max(40, min(lines_count, int(lines_per_page * 2.2)))
    boundary_backfill = max(3, min(24, int(lines_per_page * 0.25)))

    anchor_starts = _resolve_monotonic_anchor_starts(
        sorted_evidences=sorted_evidences,
        normalized_lines=normalized_lines,
        lines_count=lines_count,
        total_pages=total_pages,
        search_radius=search_radius,
    )
    page_map = _build_non_overlapping_page_sections(
        sorted_evidences=sorted_evidences,
        anchor_starts=anchor_starts,
        lines=lines,
        markdown_content=clean_markdown_content,
        total_pages=total_pages,
        section_window=section_window,
        min_section_lines=min_section_lines,
        max_section_lines=max_section_lines,
        boundary_backfill=boundary_backfill,
    )
    return _append_additional_visual_blocks_to_page_map(page_map, appendix_blocks_by_page)


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
        # Each VLM-described image on a page may represent an image-table (UI screenshot /
        # grid captured as an image by the PDF renderer).  Reduce the expected markdown-table
        # count by the number of such VLM descriptions before comparing against the threshold
        # so that image-tables that were VLM-described do not produce false table_fidelity alarms.
        vlm_image_count = _count_vlm_image_descriptions_in_ave(markdown_section)
        effective_table_count = max(0, page_evidence.table_count - vlm_image_count)
        if table_rows_in_md < effective_table_count * 2:
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
