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
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
            # Save previous section
            if current_section:
                content = '\n'.join(current_content)
                section = MarkdownSection(
                    section_id=f"section_{len(sections)+1:03d}",
                    heading=current_section,
                    content=content,
                    start_line=current_start,
                    end_line=i - 1,
                    page_numbers=[],  # Will be populated from validation evidence
                    word_count=len(content.split()),
                    has_tables='|' in content,
                    has_images='![' in content
                )
                sections.append(section)
            
            # Start new section
            current_section = line.replace('## ', '').strip()
            current_content = [line]
            current_start = i
        else:
            if current_section:
                current_content.append(line)
    
    # Save last section
    if current_section:
        content = '\n'.join(current_content)
        section = MarkdownSection(
            section_id=f"section_{len(sections)+1:03d}",
            heading=current_section,
            content=content,
            start_line=current_start,
            end_line=len(lines) - 1,
            page_numbers=[],
            word_count=len(content.split()),
            has_tables='|' in content,
            has_images='![' in content
        )
        sections.append(section)
    
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
        "created_at": datetime.utcnow().isoformat() + "Z",
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
            "status": "PENDING"
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
        timestamp=datetime.utcnow().isoformat() + "Z",
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
    manifest_file = workspace / "review_manifest.json"
    
    with open(manifest_file, 'r') as f:
        manifest = json.load(f)
    
    total = len(manifest["sections"])
    by_status = {}
    
    for section in manifest["sections"]:
        status = section.get("status", "PENDING")
        by_status[status] = by_status.get(status, 0) + 1
    
    progress = {
        "total_sections": total,
        "by_status": by_status,
        "completion_percentage": (by_status.get("APPROVED", 0) / total * 100) if total > 0 else 0
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
