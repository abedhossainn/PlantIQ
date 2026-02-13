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
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


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
    vlm_model
) -> PageValidationReport:
    """
    Validate a single page against its corresponding markdown section
    Uses VLM to identify issues with categorization
    """
    issues = []
    
    # Identify markdown section for this page
    # This is a simplified heuristic - should be improved based on actual page boundaries
    lines = markdown_content.split('\n')
    section_size = len(lines) // max(1, page_evidence.page_number)
    start_line = (page_evidence.page_number - 1) * section_size
    end_line = min(start_line + section_size, len(lines))
    markdown_section = '\n'.join(lines[start_line:end_line])
    
    # Check for missing tables
    if page_evidence.table_count > 0:
        table_count_in_md = markdown_section.count('|')  # Simple heuristic
        if table_count_in_md < page_evidence.table_count * 3:  # Expect at least 3 pipes per table
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
        image_refs = markdown_section.count('![')
        if image_refs < page_evidence.image_count:
            issues.append(ValidationIssue(
                issue_type=IssueType.IMAGE_LOSS.value,
                severity="critical",
                page_number=page_evidence.page_number,
                description=f"Page has {page_evidence.image_count} images, found {image_refs} in markdown",
                evidence=f"Images detected in PDF page {page_evidence.page_number}",
                suggested_fix="Add text descriptions for all figures with ![Figure: description](path)"
            ))
    
    # Calculate confidence score (simple heuristic - can be enhanced with VLM)
    confidence_score = 1.0
    if len(issues) > 0:
        confidence_score = max(0.0, 1.0 - (len(issues) * 0.15))
    
    return PageValidationReport(
        page_number=page_evidence.page_number,
        markdown_section=markdown_section[:200],  # Store preview only
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
    docling_version: str = "1.0.0"
) -> DocumentValidation:
    """
    Create comprehensive validation report with lineage tracking
    """
    logger.info("🔍 Creating enhanced validation report...")
    
    # Extract evidence from PDF
    page_evidences = extract_page_evidence(pdf_path)
    
    if not page_evidences:
        logger.error("❌ No page evidence extracted")
        return None
    
    # Load markdown
    with open(markdown_path, 'r', encoding='utf-8') as f:
        markdown_content = f.read()
    
    # Validate each page
    page_validations = []
    for evidence in page_evidences:
        validation = validate_page_against_markdown(
            evidence,
            markdown_content,
            vlm_model=None  # Will integrate VLM in next iteration
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
    parser.add_argument("--vlm-model", default="Qwen2.5-VL-32B-Instruct", help="VLM model name")
    parser.add_argument("--docling-version", default="1.0.0", help="Docling version")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🔍 Enhanced Validation Module")
    logger.info("=" * 80)
    
    report = create_validation_report(
        args.pdf,
        args.markdown,
        args.vlm_model,
        args.docling_version
    )
    
    if report:
        save_validation_report(report, args.output)
        logger.info("✅ Enhanced validation complete")
        return 0
    else:
        logger.error("❌ Validation failed")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
