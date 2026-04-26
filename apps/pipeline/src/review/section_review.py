#!/usr/bin/env python3
"""
Section-based Review System
Implements improvement #2: Split long docs into reviewable units
- Section-based review units
- Reviewer checklist per section
- Partial re-runs for affected sections only
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _section_has_images(content: str) -> bool:
    """Recognize both classic markdown images and description-mode figures."""
    return ('![' in content) or bool(re.search(r'\*\*\[Figure\s+\d+:', content, flags=re.IGNORECASE))


class ReviewStatus(Enum):
    """Review status for sections"""
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REWORK = "needs_rework"


@dataclass
class SectionChecklistItem:
    """Individual checklist item for section review"""
    item: str
    checked: bool
    notes: Optional[str] = None


@dataclass
class SectionChecklist:
    """Complete checklist for reviewing a section"""
    question_headings: SectionChecklistItem
    table_facts_extracted: SectionChecklistItem
    figure_descriptions: SectionChecklistItem
    citations_present: SectionChecklistItem
    no_hallucinations: SectionChecklistItem
    rag_optimized: SectionChecklistItem
    
    @classmethod
    def create_empty(cls):
        """Create empty checklist for reviewer to fill"""
        return cls(
            question_headings=SectionChecklistItem("Headings are questions", False),
            table_facts_extracted=SectionChecklistItem("Table facts extracted to bullets", False),
            figure_descriptions=SectionChecklistItem("Figures have text descriptions", False),
            citations_present=SectionChecklistItem("Source citations included", False),
            no_hallucinations=SectionChecklistItem("No AI-generated content", False),
            rag_optimized=SectionChecklistItem("Follows RAG guidelines", False)
        )
    
    def is_complete(self) -> bool:
        """Check if all items are checked"""
        items = [
            self.question_headings,
            self.table_facts_extracted,
            self.figure_descriptions,
            self.citations_present,
            self.no_hallucinations,
            self.rag_optimized
        ]
        return all(item.checked for item in items)
    
    def get_failed_items(self) -> List[str]:
        """Get list of failed checklist items"""
        failed = []
        items_dict = {
            "Question headings": self.question_headings,
            "Table facts": self.table_facts_extracted,
            "Figure descriptions": self.figure_descriptions,
            "Citations": self.citations_present,
            "No hallucinations": self.no_hallucinations,
            "RAG optimized": self.rag_optimized
        }
        
        for name, item in items_dict.items():
            if not item.checked:
                failed.append(name)
        
        return failed


@dataclass
class MarkdownSection:
    """Individual section for review"""
    section_id: str
    heading: str
    content: str
    start_line: int
    end_line: int
    page_numbers: List[int]  # Source PDF pages
    word_count: int
    has_tables: bool
    has_images: bool


@dataclass
class SectionReview:
    """Review record for a single section"""
    section_id: str
    reviewer: str
    timestamp: str
    status: str  # ReviewStatus enum value
    checklist: SectionChecklist
    issues: List[str]
    corrections: Optional[str] = None
    reviewer_notes: Optional[str] = None
    review_duration_minutes: Optional[int] = None


@dataclass
class DocumentSections:
    """Document broken into reviewable sections"""
    document_name: str
    total_sections: int
    sections: List[MarkdownSection]
    metadata: Dict


@dataclass
class ReviewPage:
    """Individual PDF page prepared for manual review."""
    page_id: str
    page_number: int
    markdown_content: str
    text_preview: str
    validation_issues: List[Dict[str, Any]]
    evidence_images: List[str]
    evidence: Dict[str, Any]


@dataclass
class DocumentPages:
    """Document broken into page-based review units."""
    document_name: str
    total_pages: int
    pages: List[ReviewPage]
    metadata: Dict[str, Any]


def _extract_validation_report_context(validation_report: Any) -> tuple[Optional[str], List[Any], Dict[str, Any]]:
    """Normalize object/dict validation report shape into common tuple context."""
    if hasattr(validation_report, "page_validations"):
        report_document_name = getattr(validation_report, "document_name", None)
        page_validations = validation_report.page_validations
        report_metadata = getattr(validation_report, "metadata", {}) or {}
        return report_document_name, page_validations, report_metadata

    report_document_name = validation_report.get("document_name")
    page_validations = validation_report.get("page_validations", [])
    report_metadata = validation_report.get("metadata", {}) or {}
    return report_document_name, page_validations, report_metadata


def _extract_page_validation_fields(page_validation: Any) -> tuple[Optional[int], Optional[str], Any, List[Any]]:
    """Extract page validation fields from object or dict payload."""
    if isinstance(page_validation, dict):
        return (
            page_validation.get("page_number"),
            page_validation.get("markdown_section"),
            page_validation.get("evidence", {}),
            page_validation.get("issues", []),
        )

    return (
        getattr(page_validation, "page_number", None),
        getattr(page_validation, "markdown_section", None),
        getattr(page_validation, "evidence", None),
        getattr(page_validation, "issues", None),
    )


def _coerce_evidence_dict(evidence: Any) -> Dict[str, Any]:
    """Normalize evidence payload to dictionary."""
    if hasattr(evidence, "__dict__"):
        return asdict(evidence)
    return dict(evidence or {})


def _coerce_issue_dicts(issues: List[Any]) -> List[Dict[str, Any]]:
    """Normalize issue payloads to list of dictionaries."""
    issue_dicts: List[Dict[str, Any]] = []
    for issue in issues or []:
        if hasattr(issue, "__dict__"):
            issue_dicts.append(asdict(issue))
        else:
            issue_dicts.append(dict(issue))
    return issue_dicts


def _build_review_page(
    *,
    page_number: int,
    markdown_content: Optional[str],
    evidence_dict: Dict[str, Any],
    issue_dicts: List[Dict[str, Any]],
) -> ReviewPage:
    """Build one normalized ReviewPage item."""
    thumbnail_path = evidence_dict.get("thumbnail_path")
    evidence_images = [thumbnail_path] if thumbnail_path else []
    text_preview = evidence_dict.get("text_preview") or ""
    page_markdown = markdown_content or ""

    return ReviewPage(
        page_id=f"page_{int(page_number):03d}",
        page_number=int(page_number),
        markdown_content=page_markdown,
        text_preview=text_preview,
        validation_issues=issue_dicts,
        evidence_images=evidence_images,
        evidence=evidence_dict,
    )


def _create_markdown_section(
    *,
    index: int,
    heading: str,
    content: str,
    start_line: int,
    end_line: int,
) -> MarkdownSection:
    """Build one markdown review section with computed metadata."""
    return MarkdownSection(
        section_id=f"section_{index:03d}",
        heading=heading,
        content=content,
        start_line=start_line,
        end_line=end_line,
        page_numbers=[],
        word_count=len(content.split()),
        has_tables='|' in content,
        has_images=_section_has_images(content),
    )


def _append_current_section_if_any(
    sections: List[MarkdownSection],
    current_section: Optional[str],
    current_content: List[str],
    current_start: int,
    end_line: int,
) -> None:
    """Append current buffered section if a heading is active."""
    if not current_section:
        return
    content = '\n'.join(current_content)
    sections.append(
        _create_markdown_section(
            index=len(sections) + 1,
            heading=current_section,
            content=content,
            start_line=current_start,
            end_line=end_line,
        )
    )


def extract_pages_from_validation(validation_report: Any, document_name: Optional[str] = None) -> DocumentPages:
    """Build page review units directly from the validation artifact."""
    report_document_name, page_validations, report_metadata = _extract_validation_report_context(validation_report)

    resolved_document_name = document_name or report_document_name or "document"
    pages: List[ReviewPage] = []

    for page_validation in page_validations:
        page_number, markdown_content, evidence, issues = _extract_page_validation_fields(page_validation)
        evidence_dict = _coerce_evidence_dict(evidence)
        issue_dicts = _coerce_issue_dicts(issues)
        pages.append(
            _build_review_page(
                page_number=int(page_number),
                markdown_content=markdown_content,
                evidence_dict=evidence_dict,
                issue_dicts=issue_dicts,
            )
        )

    return DocumentPages(
        document_name=resolved_document_name,
        total_pages=len(pages),
        pages=pages,
        metadata={
            "total_issues": sum(len(page.validation_issues) for page in pages),
            "pages_with_issues": sum(1 for page in pages if page.validation_issues),
            "validation_metadata": report_metadata,
        },
    )


def create_page_review_workspace(pages: DocumentPages, output_dir: str) -> Path:
    """Create a page-based review workspace alongside the legacy section workspace."""
    workspace = Path(output_dir)
    workspace.mkdir(exist_ok=True, parents=True)

    logger.info(f"📄 Creating page review workspace: {workspace}")

    manifest = {
        "document_name": pages.document_name,
        "review_unit": "page",
        "total_pages": pages.total_pages,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": pages.metadata,
        "pages": [],
    }

    for page in pages.pages:
        page_file = workspace / f"{page.page_id}.md"
        checklist_file = workspace / f"{page.page_id}_checklist.json"
        checklist = SectionChecklist.create_empty()

        page_body = page.markdown_content.strip() or f"# Page {page.page_number}\n\n{page.text_preview}".strip()

        with open(page_file, 'w', encoding='utf-8') as f:
            f.write(f"<!-- Page ID: {page.page_id} -->\n")
            f.write(f"<!-- Page Number: {page.page_number} -->\n")
            f.write(f"<!-- Status: pending -->\n")
            if page.evidence_images:
                f.write(f"<!-- Evidence Images: {', '.join(page.evidence_images)} -->\n")
            f.write(f"<!-- Validation Issues: {len(page.validation_issues)} -->\n\n")
            f.write(page_body)

        with open(checklist_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(checklist), f, indent=2)

        manifest["pages"].append(
            {
                "page_id": page.page_id,
                "page_number": page.page_number,
                "file": page_file.name,
                "checklist": checklist_file.name,
                "status": "pending",
                "text_preview": page.text_preview,
                "markdown_content": page.markdown_content,
                "validation_issues": page.validation_issues,
                "evidence": page.evidence,
                "evidence_images": page.evidence_images,
            }
        )

    manifest_file = workspace / "page_review_manifest.json"
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"✅ Page review workspace ready: {pages.total_pages} pages")
    return workspace


def extract_sections_from_markdown(markdown_content: str, document_name: str) -> DocumentSections:
    """
    Split markdown into section-based review units
    Each ## heading becomes a review unit
    """
    logger.info(f"📄 Extracting sections from: {document_name}")
    
    lines = markdown_content.split('\n')
    sections = []
    current_section = None
    current_content = []
    current_start = 0
    
    for i, line in enumerate(lines):
        # Detect section headings (## level)
        if line.startswith('## '):
            _append_current_section_if_any(
                sections,
                current_section,
                current_content,
                current_start,
                i - 1,
            )
            
            # Start new section
            current_section = line.replace('## ', '').strip()
            current_content = [line]
            current_start = i
        else:
            if current_section:
                current_content.append(line)
    
    _append_current_section_if_any(
        sections,
        current_section,
        current_content,
        current_start,
        len(lines) - 1,
    )
    
    logger.info(f"✅ Extracted {len(sections)} sections")
    
    return DocumentSections(
        document_name=document_name,
        total_sections=len(sections),
        sections=sections,
        metadata={
            "total_words": sum(s.word_count for s in sections),
            "sections_with_tables": sum(1 for s in sections if s.has_tables),
            "sections_with_images": sum(1 for s in sections if s.has_images)
        }
    )


def create_review_workspace(sections: DocumentSections, output_dir: str) -> Path:
    """
    Create review workspace with one file per section
    Enables parallel review and partial re-runs
    """
    workspace = Path(output_dir)
    workspace.mkdir(exist_ok=True, parents=True)
    
    logger.info(f"📁 Creating review workspace: {workspace}")
    
    # Create manifest
    manifest = {
        "document_name": sections.document_name,
        "total_sections": sections.total_sections,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sections": []
    }
    
    # Create section files
    for section in sections.sections:
        section_file = workspace / f"{section.section_id}.md"
        
        # Write section content with metadata header
        with open(section_file, 'w', encoding='utf-8') as f:
            f.write(f"<!-- Section ID: {section.section_id} -->\n")
            f.write(f"<!-- Heading: {section.heading} -->\n")
            f.write(f"<!-- Lines: {section.start_line}-{section.end_line} -->\n")
            if section.page_numbers:
                f.write(f"<!-- Pages: {', '.join(str(page) for page in section.page_numbers)} -->\n")
            f.write(f"<!-- Word Count: {section.word_count} -->\n")
            f.write(f"<!-- Has Tables: {section.has_tables} -->\n")
            f.write(f"<!-- Has Images: {section.has_images} -->\n")
            f.write(f"<!-- Status: PENDING -->\n\n")
            f.write(section.content)
        
        # Create checklist file
        checklist_file = workspace / f"{section.section_id}_checklist.json"
        checklist = SectionChecklist.create_empty()
        
        with open(checklist_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(checklist), f, indent=2)
        
        manifest["sections"].append({
            "section_id": section.section_id,
            "heading": section.heading,
            "file": str(section_file.name),
            "checklist": str(checklist_file.name),
            "status": "PENDING",
            "page_numbers": section.page_numbers,
        })
        
        logger.info(f"✅ Created: {section.section_id} - {section.heading}")
    
    # Save manifest
    manifest_file = workspace / "review_manifest.json"
    with open(manifest_file, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"💾 Manifest saved: {manifest_file}")
    logger.info(f"✅ Review workspace ready: {sections.total_sections} sections")
    
    return workspace


def submit_section_review(
    section_id: str,
    reviewer: str,
    checklist: SectionChecklist,
    corrections: Optional[str] = None,
    notes: Optional[str] = None,
    workspace_path: str = "review_workspace"
) -> SectionReview:
    """
    Submit review for a section
    Updates workspace with review status
    """
    workspace = Path(workspace_path)
    
    # Determine status based on checklist
    if checklist.is_complete():
        status = ReviewStatus.APPROVED
    else:
        status = ReviewStatus.NEEDS_REWORK
    
    review = SectionReview(
        section_id=section_id,
        reviewer=reviewer,
        timestamp=datetime.now(timezone.utc).isoformat(),
        status=status.value,
        checklist=checklist,
        issues=checklist.get_failed_items(),
        corrections=corrections,
        reviewer_notes=notes
    )
    
    # Save review
    review_file = workspace / f"{section_id}_review.json"
    with open(review_file, 'w', encoding='utf-8') as f:
        json.dump(asdict(review), f, indent=2)
    
    # Update manifest
    manifest_file = workspace / "review_manifest.json"
    with open(manifest_file, 'r') as f:
        manifest = json.load(f)
    
    for section in manifest["sections"]:
        if section["section_id"] == section_id:
            section["status"] = status.value
            section["reviewer"] = reviewer
            section["reviewed_at"] = review.timestamp
            break
    
    with open(manifest_file, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    logger.info(f"✅ Review submitted: {section_id} - {status.value}")
    
    return review


def reprocess_section(
    section_id: str,
    workspace_path: str,
    reformatter_func
) -> bool:
    """
    Reprocess only the affected section
    Enables partial re-runs instead of full document
    """
    workspace = Path(workspace_path)
    
    logger.info(f"🔄 Reprocessing section: {section_id}")
    
    # Load section content
    section_file = workspace / f"{section_id}.md"
    with open(section_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Apply reformatter to this section only
    try:
        reformatted = reformatter_func(content)
        
        # Save reformatted version
        output_file = workspace / f"{section_id}_reformatted.md"
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(reformatted)
        
        logger.info(f"✅ Section reprocessed: {section_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Reprocessing failed: {e}")
        return False


def get_review_progress(workspace_path: str) -> Dict:
    """Get review progress summary"""
    workspace = Path(workspace_path)
    page_manifest_file = workspace / "page_review_manifest.json"
    manifest_file = page_manifest_file if page_manifest_file.exists() else workspace / "review_manifest.json"
    
    with open(manifest_file, 'r') as f:
        manifest = json.load(f)
    
    review_items = manifest.get("pages") or manifest.get("sections") or []
    total = len(review_items)
    by_status = {}
    
    for item in review_items:
        status = item.get("status", "PENDING")
        by_status[status] = by_status.get(status, 0) + 1
    
    progress = {
        "total_sections": total,
        "by_status": by_status,
        "completion_percentage": (
            (by_status.get("APPROVED", 0) + by_status.get("reviewed", 0)) / total * 100
        ) if total > 0 else 0
    }
    
    return progress


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Section-based review system for long documents"
    )
    parser.add_argument("action", choices=["extract", "progress", "review"],
                       help="Action to perform")
    parser.add_argument("--markdown", help="Path to markdown file (for extract)")
    parser.add_argument("--workspace", default="review_workspace", help="Review workspace path")
    parser.add_argument("--section-id", help="Section ID (for review)")
    parser.add_argument("--reviewer", help="Reviewer name (for review)")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("📋 Section-based Review System")
    logger.info("=" * 80)
    
    if args.action == "extract":
        if not args.markdown:
            logger.error("❌ --markdown required for extract action")
            return 1
        
        with open(args.markdown, 'r', encoding='utf-8') as f:
            content = f.read()
        
        doc_name = Path(args.markdown).stem
        sections = extract_sections_from_markdown(content, doc_name)
        workspace = create_review_workspace(sections, args.workspace)
        
        logger.info(f"✅ Review workspace created: {workspace}")
        return 0
    
    elif args.action == "progress":
        progress = get_review_progress(args.workspace)
        logger.info(f"📊 Review Progress:")
        logger.info(f"   Total sections: {progress['total_sections']}")
        logger.info(f"   Completion: {progress['completion_percentage']:.1f}%")
        logger.info(f"   By status: {json.dumps(progress['by_status'], indent=2)}")
        return 0
    
    elif args.action == "review":
        logger.info("⚠️  Review submission requires interactive implementation")
        logger.info("   Use submit_section_review() function in your code")
        return 0
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
