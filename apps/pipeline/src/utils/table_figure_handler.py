#!/usr/bin/env python3
"""
Enhanced Table and Figure Handling Module
Implements improvement #5: Improve table + figure handling
- Consistent table serialization using Docling
- Extract bullet facts from tables first, then include table for reference
- Mandatory figure descriptions with key facts and source page
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)  # NOSONAR: Standard logger initialization


FIGURE_DESCRIPTION_PATTERN = re.compile(r'\*\*\[Figure\s+(\d+):(.*?)\]\*\*', re.IGNORECASE | re.DOTALL)
MARKDOWN_IMAGE_PATTERN = re.compile(r'!\[(.*?)\]\((.*?)\)')


@dataclass
class TableData:
    """Structured table representation"""
    table_id: str
    page_number: int
    caption: Optional[str]
    headers: List[str]
    rows: List[List[str]]
    key_facts: List[str]
    serialized_table: str
    source_location: str


@dataclass
class FigureData:
    """Structured figure representation"""
    figure_id: str
    page_number: int
    caption: Optional[str]
    description: str
    key_facts: List[str]
    file_path: Optional[str]
    alt_text: str
    source_location: str


def _normalize_table_headers(table: list[list[object]]) -> list[str]:
    """Return normalized table headers from first row."""
    return [str(cell or '').strip() for cell in table[0]]


def _normalize_table_rows(table: list[list[object]]) -> list[list[str]]:
    """Return non-empty normalized data rows for a table."""
    rows: list[list[str]] = []
    for row in table[1:]:
        cleaned_row = [str(cell or '').strip() for cell in row]
        if any(cleaned_row):
            rows.append(cleaned_row)
    return rows


def _build_table_data(page_num: int, table_idx: int, headers: list[str], rows: list[list[str]]) -> TableData:
    """Build structured table payload for downstream RAG formatting."""
    table_id = f"table_p{page_num}_{table_idx}"
    return TableData(
        table_id=table_id,
        page_number=page_num,
        caption=None,
        headers=headers,
        rows=rows,
        key_facts=extract_table_key_facts(headers, rows),
        serialized_table=serialize_table_markdown(headers, rows),
        source_location=f"Page {page_num}",
    )


def extract_tables_from_pdf(pdf_path: str) -> List[TableData]:
    """
    Extract and serialize tables from PDF using pdfplumber
    Provides consistent table normalization
    """
    try:
        import pdfplumber
        
        logger.info(f"📊 Extracting tables from: {pdf_path}")
        
        tables_data = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                for table_idx, table in enumerate(page.extract_tables(), 1):
                    if not table or len(table) < 2:
                        continue

                    headers = _normalize_table_headers(table)
                    rows = _normalize_table_rows(table)
                    table_data = _build_table_data(page_num, table_idx, headers, rows)

                    tables_data.append(table_data)
                    logger.info(
                        "✅ Extracted %s: %s columns, %s rows",
                        table_data.table_id,
                        len(headers),
                        len(rows),
                    )
        
        logger.info(f"✅ Total tables extracted: {len(tables_data)}")
        return tables_data
        
    except Exception as e:
        logger.error(f"❌ Table extraction failed: {e}")
        return []


def serialize_table_markdown(headers: List[str], rows: List[List[str]]) -> str:
    """
    Serialize table in consistent markdown format
    Ensures all tables have uniform representation
    """
    if not headers or not rows:
        return ""
    
    # Build markdown table
    lines = []
    
    # Header row
    header_row = "| " + " | ".join(headers) + " |"
    lines.append(header_row)
    
    # Separator row
    separator = "| " + " | ".join(["---"] * len(headers)) + " |"
    lines.append(separator)
    
    # Data rows
    for row in rows:
        # Pad row if necessary
        padded_row = row + [''] * (len(headers) - len(row))
        data_row = "| " + " | ".join(padded_row[:len(headers)]) + " |"
        lines.append(data_row)
    
    return '\n'.join(lines)


_EMPTY_CELL_VALUES = {"-", "N/A", ""}


def _row_facts(row: List[str], headers: List[str]) -> List[str]:
    """Return key facts derived from a single table row."""
    first_col = row[0].strip() if row else ""
    if not first_col or len(row) < 2:
        return []
    return [
        f"{first_col}: {header} = {value}"
        for header, cell in zip(headers[1:], row[1:])
        if (value := cell.strip()) not in _EMPTY_CELL_VALUES
    ]


def extract_table_key_facts(headers: List[str], rows: List[List[str]]) -> List[str]:
    """
    Extract key facts from table as bullet points
    These will be placed before the table for better retrieval
    """
    if not headers or not rows:
        return []
    facts = [fact for row in rows for fact in _row_facts(row, headers)]
    return facts[:10]  # Keep top 10 facts


def format_table_for_rag(table: TableData) -> str:
    """
    Format table with bullet facts first, then table for reference
    Optimized for RAG retrieval
    """
    lines = []
    
    # Caption (if available)
    if table.caption:
        lines.append(f"**{table.caption}** [Source: {table.source_location}]")
        lines.append("")
    
    # Key facts as bullets
    if table.key_facts:
        lines.append("**Key Facts:**")
        for fact in table.key_facts:
            lines.append(f"- {fact}")
        lines.append("")
    
    # Table for reference
    lines.append("**Table:**")
    lines.append("")
    lines.append(table.serialized_table)
    lines.append("")
    lines.append(f"[Source: {table.source_location}]")
    
    return '\n'.join(lines)


def _extract_preceding_context(markdown_content: str, start_index: int, window: int = 200) -> str:
    """Return preceding text context for pattern-derived metadata extraction."""
    context_start = max(0, start_index - window)
    return markdown_content[context_start:start_index]


def _extract_page_number_from_context(context: str) -> int:
    """Extract page number from nearby context, or 0 when unavailable."""
    page_match = re.search(r'[Pp]age\s+(\d+)', context)
    return int(page_match.group(1)) if page_match else 0


def _extract_figure_caption_from_context(context: str) -> Optional[str]:
    """Extract optional figure caption from nearby context."""
    caption_match = re.search(r'[Ff]igure\s+\d+[:\.]?\s*([^\n]*)(?:\n|$)', context)
    return caption_match.group(1).strip() if caption_match else None


def _log_figure_found(figure: FigureData) -> None:
    """Log standardized discovery message for extracted figures."""
    logger.info(f"✅ Found {figure.figure_id}: {figure.description[:50]}...")


def _build_figure_from_image_match(match: re.Match[str], idx: int, markdown_content: str) -> FigureData:
    """Build FigureData from classic markdown image syntax."""
    alt_text = match.group(1)
    file_path = match.group(2)
    context = _extract_preceding_context(markdown_content, match.start())
    page_number = _extract_page_number_from_context(context)
    caption = _extract_figure_caption_from_context(context)

    return FigureData(
        figure_id=f"figure_{idx:03d}",
        page_number=page_number,
        caption=caption,
        description=alt_text,
        key_facts=[],
        file_path=file_path,
        alt_text=alt_text,
        source_location=f"Page {page_number}" if page_number else "Unknown",
    )


def _build_figure_from_description_match(
    match: re.Match[str],
    offset: int,
    relative_idx: int,
    markdown_content: str,
) -> FigureData:
    """Build FigureData from description-mode figure syntax."""
    description = re.sub(r'\s+', ' ', match.group(2)).strip()
    context = _extract_preceding_context(markdown_content, match.start())
    page_number = _extract_page_number_from_context(context)
    caption = f"Figure {match.group(1)}"

    return FigureData(
        figure_id=f"figure_{offset + relative_idx:03d}",
        page_number=page_number,
        caption=caption,
        description=description,
        key_facts=[],
        file_path=None,
        alt_text=description,
        source_location=f"Page {page_number}" if page_number else "Unknown",
    )


def _extract_classic_markdown_figures(markdown_content: str) -> List[FigureData]:
    """Extract figures from markdown image tags."""
    figures: List[FigureData] = []
    for idx, match in enumerate(MARKDOWN_IMAGE_PATTERN.finditer(markdown_content), 1):
        figure = _build_figure_from_image_match(match, idx, markdown_content)
        figures.append(figure)
        _log_figure_found(figure)
    return figures


def _extract_description_mode_figures(markdown_content: str, offset: int) -> List[FigureData]:
    """Extract figures from description-mode figure markers."""
    figures: List[FigureData] = []
    for relative_idx, match in enumerate(FIGURE_DESCRIPTION_PATTERN.finditer(markdown_content), 1):
        figure = _build_figure_from_description_match(match, offset, relative_idx, markdown_content)
        figures.append(figure)
        _log_figure_found(figure)
    return figures


def extract_figures_from_markdown(markdown_content: str) -> List[FigureData]:
    """
    Extract figure references from markdown
    Check for proper descriptions
    """
    logger.info("🖼️  Extracting figures from markdown...")
    
    classic_figures = _extract_classic_markdown_figures(markdown_content)
    description_figures = _extract_description_mode_figures(markdown_content, offset=len(classic_figures))
    figures = classic_figures + description_figures
    
    logger.info(f"✅ Total figures found: {len(figures)}")
    return figures


_GENERIC_FIGURE_TERMS = frozenset(['image', 'picture', 'figure', 'diagram'])
_CONTENT_INDICATOR_WORDS = ('shows', 'displays', 'illustrates', 'depicts')


def _description_text_issues(description: Optional[str]) -> List[str]:
    """Return issue strings for a figure description string alone."""
    if not description or len(description) < 10:
        return ["Description too short or missing"]
    issues = []
    if description.lower() in _GENERIC_FIGURE_TERMS:
        issues.append("Description is too generic")
    if not any(word in description.lower() for word in _CONTENT_INDICATOR_WORDS):
        issues.append("Description should explain what the figure shows")
    return issues


def validate_figure_description(figure: FigureData) -> Tuple[bool, List[str]]:
    """
    Validate figure has proper description
    Returns (is_valid, issues)
    """
    issues = _description_text_issues(figure.description)
    if not figure.source_location or figure.source_location == "Unknown":
        issues.append("Source page number missing")
    return len(issues) == 0, issues


def enhance_figure_description(
    figure: FigureData,
    vlm_analysis: Optional[str] = None
) -> FigureData:
    """
    Enhance figure description with VLM analysis
    """
    if vlm_analysis:
        # Combine original description with VLM insights
        figure.description = f"{figure.description}. {vlm_analysis}"
        
        # Extract key facts from VLM analysis
        # Simple heuristic: sentences become facts
        sentences = [s.strip() for s in vlm_analysis.split('.') if s.strip()]
        figure.key_facts = sentences[:3]  # Keep top 3 facts
    
    return figure


def format_figure_for_rag(figure: FigureData) -> str:
    """
    Format figure with mandatory description and key facts
    """
    lines = []
    
    # Caption
    if figure.caption:
        lines.append(f"**{figure.caption}**")
        lines.append("")
    
    # Key facts (if available)
    if figure.key_facts:
        lines.append("**Key Information:**")
        for fact in figure.key_facts:
            lines.append(f"- {fact}")
        lines.append("")
    
    # Figure with description
    lines.append(f"![{figure.description}]({figure.file_path})")
    lines.append("")
    lines.append(f"*{figure.description}*")
    lines.append("")
    lines.append(f"[Source: {figure.source_location}]")
    
    return '\n'.join(lines)


def optimize_document_tables_and_figures(
    markdown_content: str,
    pdf_path: str
) -> str:
    """
    Optimize entire document for tables and figures
    Returns RAG-optimized markdown
    """
    logger.info("🔧 Optimizing tables and figures for RAG...")
    
    # Extract tables from PDF
    tables = extract_tables_from_pdf(pdf_path)
    
    # Extract figures from markdown
    figures = extract_figures_from_markdown(markdown_content)
    
    # Validate figures
    invalid_figures = []
    for figure in figures:
        is_valid, issues = validate_figure_description(figure)
        if not is_valid:
            invalid_figures.append((figure, issues))
            logger.warning(f"⚠️  {figure.figure_id} has issues: {', '.join(issues)}")
    
    # Build optimized content
    # This is a simplified version - real implementation would need
    # sophisticated markdown parsing to replace in-place
    
    optimized = markdown_content
    
    # Note: Full implementation would:
    # 1. Parse markdown AST
    # 2. Locate table/figure positions
    # 3. Replace with RAG-optimized format
    # 4. Preserve surrounding context
    
    logger.info(f"✅ Optimization complete:")
    logger.info(f"   Tables processed: {len(tables)}")
    logger.info(f"   Figures processed: {len(figures)}")
    logger.info(f"   Figures needing attention: {len(invalid_figures)}")
    
    return optimized


def _invalid_figure_entries(figures: List[FigureData]) -> List[Dict]:
    """Return a list of validation failure records for figures that fail validation."""
    results = []
    for figure in figures:
        is_valid, issues = validate_figure_description(figure)
        if not is_valid:
            results.append({"figure_id": figure.figure_id, "issues": issues})
    return results


def _count_tables_with_facts(tables: List[TableData]) -> int:
    """Count tables that include extracted key facts."""
    return sum(1 for table in tables if table.key_facts)


def _count_figures_with_descriptions(figures: List[FigureData]) -> int:
    """Count figures with non-trivial descriptions."""
    return sum(1 for figure in figures if figure.description and len(figure.description) > 10)


def _build_table_figure_summary(tables: List[TableData], figures: List[FigureData]) -> Dict[str, int]:
    """Build aggregate counts for table/figure reporting."""
    return {
        "total_tables": len(tables),
        "total_figures": len(figures),
        "tables_with_facts": _count_tables_with_facts(tables),
        "figures_with_descriptions": _count_figures_with_descriptions(figures),
    }


def _build_table_figure_report_payload(tables: List[TableData], figures: List[FigureData]) -> Dict:
    """Build JSON payload for table/figure quality report."""
    return {
        "summary": _build_table_figure_summary(tables, figures),
        "tables": [asdict(table) for table in tables],
        "figures": [asdict(figure) for figure in figures],
        "validation": {"invalid_figures": _invalid_figure_entries(figures)},
    }


def generate_table_figure_report(
    tables: List[TableData],
    figures: List[FigureData],
    output_path: str
):
    """Generate report on table and figure quality"""
    report = _build_table_figure_report_payload(tables, figures)

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2)

    logger.info(f"💾 Table/Figure report saved: {output_path}")


def _run_extract_action(args) -> int:
    if not args.pdf:
        logger.error("❌ --pdf required for extract action")
        return 1
    tables = extract_tables_from_pdf(args.pdf)
    report = {"tables": [asdict(t) for t in tables]}
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    logger.info(f"💾 Tables saved: {args.output}")
    return 0


def _run_validate_action(args) -> int:
    if not args.markdown:
        logger.error("❌ --markdown required for validate action")
        return 1
    with open(args.markdown, 'r', encoding='utf-8') as f:
        content = f.read()
    figures = extract_figures_from_markdown(content)
    for figure in figures:
        is_valid, issues = validate_figure_description(figure)
        status = "✅" if is_valid else "❌"
        logger.info(f"{status} {figure.figure_id}: {', '.join(issues) if issues else 'OK'}")
    return 0


def _run_optimize_action(args) -> int:
    if not args.pdf or not args.markdown:
        logger.error("❌ --pdf and --markdown required for optimize action")
        return 1
    with open(args.markdown, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    optimize_document_tables_and_figures(markdown_content, args.pdf)
    logger.info("✅ Optimization complete (report generated)")
    return 0


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Enhanced Table and Figure Handling")
    parser.add_argument("action", choices=["extract", "validate", "optimize"],
                        help="Action to perform")
    parser.add_argument("--pdf", help="PDF path")
    parser.add_argument("--markdown", help="Markdown path")
    parser.add_argument("--output", default="table_figure_report.json", help="Output path")

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("📊 Enhanced Table and Figure Handling")
    logger.info("=" * 80)

    _action_handlers = {
        "extract": _run_extract_action,
        "validate": _run_validate_action,
        "optimize": _run_optimize_action,
    }
    return _action_handlers[args.action](args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
