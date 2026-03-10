#!/usr/bin/env python3
"""
Lineage and Audit Trail Module
Implements improvement #4: Add lineage + audit trail
- Document manifest with PDF hash, versions, reviewer, etc.
- Review notes with correction rationale
- Versioned outputs for rollback capability
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict, field
from datetime import datetime
import shutil

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """Version information for tools and models"""
    docling_version: str
    vlm_model: str
    vlm_model_hash: Optional[str] = None
    reformatter_model: str = ""
    reformatter_model_hash: Optional[str] = None
    prompt_version: str = "1.0.0"
    prompt_hash: Optional[str] = None


@dataclass
class ReviewNote:
    """Individual review note with rationale"""
    timestamp: str
    reviewer: str
    section_id: str
    issue_type: str
    original_content: str
    corrected_content: str
    rationale: str
    ambiguity_flags: List[str] = field(default_factory=list)


@dataclass
class DocumentManifest:
    """Complete lineage and audit trail for document"""
    # Document identification
    document_name: str
    pdf_path: str
    pdf_hash: str
    pdf_size_bytes: int
    pdf_page_count: int
    
    # Version tracking
    versions: VersionInfo
    
    # Processing timestamps
    extraction_timestamp: str
    validation_timestamp: Optional[str] = None
    reformatting_timestamp: Optional[str] = None
    qa_approval_timestamp: Optional[str] = None
    
    # Reviewer information
    primary_reviewer: Optional[str] = None
    secondary_reviewer: Optional[str] = None
    qa_approver: Optional[str] = None
    
    # Review notes
    review_notes: List[ReviewNote] = field(default_factory=list)
    
    # Output tracking
    markdown_versions: List[str] = field(default_factory=list)
    current_version: int = 1
    
    # Metadata
    metadata: Dict = field(default_factory=dict)


def compute_file_hash(file_path: str) -> str:
    """Compute SHA256 hash for file"""
    sha256_hash = hashlib.sha256()
    
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    
    return sha256_hash.hexdigest()


def compute_string_hash(content: str) -> str:
    """Compute SHA256 hash for string content"""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def get_pdf_page_count(pdf_path: str) -> int:
    """Get page count from PDF"""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            return len(pdf.pages)
    except Exception as e:
        logger.warning(f"⚠️  Could not get page count: {e}")
        return 0


def create_document_manifest(
    pdf_path: str,
    docling_version: str,
    vlm_model: str,
    reformatter_model: str,
    prompt_path: Optional[str] = None
) -> DocumentManifest:
    """
    Create initial document manifest with lineage tracking
    """
    logger.info(f"📋 Creating document manifest for: {pdf_path}")
    
    pdf_file = Path(pdf_path)
    
    # Compute hashes
    pdf_hash = compute_file_hash(pdf_path)
    pdf_size = pdf_file.stat().st_size
    page_count = get_pdf_page_count(pdf_path)
    
    # Version information
    prompt_hash = None
    if prompt_path and Path(prompt_path).exists():
        prompt_hash = compute_file_hash(prompt_path)
    
    versions = VersionInfo(
        docling_version=docling_version,
        vlm_model=vlm_model,
        reformatter_model=reformatter_model,
        prompt_hash=prompt_hash
    )
    
    manifest = DocumentManifest(
        document_name=pdf_file.stem,
        pdf_path=str(pdf_file.absolute()),
        pdf_hash=pdf_hash,
        pdf_size_bytes=pdf_size,
        pdf_page_count=page_count,
        versions=versions,
        extraction_timestamp=datetime.utcnow().isoformat() + "Z",
        metadata={
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source": "docling_extraction"
        }
    )
    
    logger.info(f"✅ Manifest created:")
    logger.info(f"   Document: {manifest.document_name}")
    logger.info(f"   PDF Hash: {pdf_hash[:16]}...")
    logger.info(f"   Pages: {page_count}")
    logger.info(f"   Size: {pdf_size / 1024:.1f} KB")
    
    return manifest


def add_review_note(
    manifest: DocumentManifest,
    reviewer: str,
    section_id: str,
    issue_type: str,
    original: str,
    corrected: str,
    rationale: str,
    ambiguity_flags: Optional[List[str]] = None
) -> DocumentManifest:
    """Add review note to manifest"""
    note = ReviewNote(
        timestamp=datetime.utcnow().isoformat() + "Z",
        reviewer=reviewer,
        section_id=section_id,
        issue_type=issue_type,
        original_content=original[:200],  # Store preview
        corrected_content=corrected[:200],  # Store preview
        rationale=rationale,
        ambiguity_flags=ambiguity_flags or []
    )
    
    manifest.review_notes.append(note)
    logger.info(f"✅ Review note added: {section_id} - {issue_type}")
    
    return manifest


def create_version(
    manifest: DocumentManifest,
    markdown_content: str,
    output_dir: str,
    version_notes: Optional[str] = None
) -> DocumentManifest:
    """
    Create versioned output for rollback capability
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True, parents=True)
    
    version_num = manifest.current_version
    version_file = output_path / f"{manifest.document_name}_v{version_num}.md"
    
    # Save versioned markdown
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(f"<!-- Version: {version_num} -->\n")
        f.write(f"<!-- Created: {datetime.utcnow().isoformat()}Z -->\n")
        if version_notes:
            f.write(f"<!-- Notes: {version_notes} -->\n")
        f.write(f"<!-- Hash: {compute_string_hash(markdown_content)} -->\n\n")
        f.write(markdown_content)
    
    # Update manifest
    manifest.markdown_versions.append(str(version_file.absolute()))
    manifest.current_version = version_num + 1
    
    logger.info(f"💾 Version {version_num} saved: {version_file}")
    
    return manifest


def rollback_to_version(
    manifest: DocumentManifest,
    version_num: int,
    output_path: str
) -> bool:
    """
    Rollback to a specific version
    """
    if version_num < 1 or version_num > len(manifest.markdown_versions):
        logger.error(f"❌ Invalid version: {version_num}")
        return False
    
    version_file = manifest.markdown_versions[version_num - 1]
    
    if not Path(version_file).exists():
        logger.error(f"❌ Version file not found: {version_file}")
        return False
    
    # Copy version to output
    shutil.copy(version_file, output_path)
    logger.info(f"✅ Rolled back to version {version_num}: {output_path}")
    
    return True


def save_manifest(manifest: DocumentManifest, output_path: str):
    """Save manifest to JSON"""
    output_file = Path(output_path)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(asdict(manifest), f, indent=2)
    
    logger.info(f"💾 Manifest saved: {output_file}")


def load_manifest(manifest_path: str) -> DocumentManifest:
    """Load manifest from JSON"""
    with open(manifest_path, 'r') as f:
        data = json.load(f)
    
    # Reconstruct dataclasses
    versions = VersionInfo(**data['versions'])
    
    review_notes = [
        ReviewNote(**note) for note in data.get('review_notes', [])
    ]
    
    manifest = DocumentManifest(
        document_name=data['document_name'],
        pdf_path=data['pdf_path'],
        pdf_hash=data['pdf_hash'],
        pdf_size_bytes=data['pdf_size_bytes'],
        pdf_page_count=data['pdf_page_count'],
        versions=versions,
        extraction_timestamp=data['extraction_timestamp'],
        validation_timestamp=data.get('validation_timestamp'),
        reformatting_timestamp=data.get('reformatting_timestamp'),
        qa_approval_timestamp=data.get('qa_approval_timestamp'),
        primary_reviewer=data.get('primary_reviewer'),
        secondary_reviewer=data.get('secondary_reviewer'),
        qa_approver=data.get('qa_approver'),
        review_notes=review_notes,
        markdown_versions=data.get('markdown_versions', []),
        current_version=data.get('current_version', 1),
        metadata=data.get('metadata', {})
    )
    
    logger.info(f"✅ Manifest loaded: {manifest.document_name}")
    return manifest


def update_manifest_timestamp(
    manifest: DocumentManifest,
    stage: str,
    reviewer: Optional[str] = None
) -> DocumentManifest:
    """Update manifest with stage completion timestamp"""
    timestamp = datetime.utcnow().isoformat() + "Z"
    
    if stage == "validation":
        manifest.validation_timestamp = timestamp
    elif stage == "reformatting":
        manifest.reformatting_timestamp = timestamp
    elif stage == "qa_approval":
        manifest.qa_approval_timestamp = timestamp
        if reviewer:
            manifest.qa_approver = reviewer
    
    logger.info(f"✅ Manifest updated: {stage} completed at {timestamp}")
    
    return manifest


def generate_audit_report(manifest: DocumentManifest) -> str:
    """
    Generate human-readable audit report
    """
    report_lines = [
        "=" * 80,
        "DOCUMENT AUDIT TRAIL",
        "=" * 80,
        "",
        f"Document: {manifest.document_name}",
        f"PDF Path: {manifest.pdf_path}",
        f"PDF Hash: {manifest.pdf_hash}",
        f"Pages: {manifest.pdf_page_count}",
        f"Size: {manifest.pdf_size_bytes / 1024:.1f} KB",
        "",
        "=" * 80,
        "PROCESSING PIPELINE",
        "=" * 80,
        "",
        f"Extraction: {manifest.extraction_timestamp}",
        f"  Docling Version: {manifest.versions.docling_version}",
        "",
        f"Validation: {manifest.validation_timestamp or 'Not completed'}",
        f"  VLM Model: {manifest.versions.vlm_model}",
        "",
        f"Reformatting: {manifest.reformatting_timestamp or 'Not completed'}",
        f"  Model: {manifest.versions.reformatter_model}",
        f"  Prompt Version: {manifest.versions.prompt_version}",
        "",
        f"QA Approval: {manifest.qa_approval_timestamp or 'Not completed'}",
        f"  Approver: {manifest.qa_approver or 'N/A'}",
        "",
        "=" * 80,
        "REVIEWERS",
        "=" * 80,
        "",
        f"Primary: {manifest.primary_reviewer or 'N/A'}",
        f"Secondary: {manifest.secondary_reviewer or 'N/A'}",
        f"QA Approver: {manifest.qa_approver or 'N/A'}",
        "",
        "=" * 80,
        f"REVIEW NOTES ({len(manifest.review_notes)})",
        "=" * 80,
        ""
    ]
    
    for i, note in enumerate(manifest.review_notes, 1):
        report_lines.extend([
            f"{i}. [{note.section_id}] {note.issue_type}",
            f"   Reviewer: {note.reviewer}",
            f"   Timestamp: {note.timestamp}",
            f"   Rationale: {note.rationale}",
            f"   Ambiguity Flags: {', '.join(note.ambiguity_flags) if note.ambiguity_flags else 'None'}",
            ""
        ])
    
    report_lines.extend([
        "=" * 80,
        f"VERSIONS ({len(manifest.markdown_versions)})",
        "=" * 80,
        ""
    ])
    
    for i, version_path in enumerate(manifest.markdown_versions, 1):
        report_lines.append(f"{i}. {Path(version_path).name}")
    
    report_lines.extend([
        "",
        f"Current Version: {manifest.current_version}",
        "",
        "=" * 80
    ])
    
    return '\n'.join(report_lines)


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Lineage and Audit Trail Module"
    )
    parser.add_argument("action", choices=["create", "load", "report", "version"],
                       help="Action to perform")
    parser.add_argument("--pdf", help="PDF path (for create)")
    parser.add_argument("--manifest", help="Manifest JSON path")
    parser.add_argument("--output", help="Output path")
    parser.add_argument("--docling-version", default="1.0.0", help="Docling version")
    parser.add_argument("--vlm-model", default="Qwen2.5-VL-32B-Instruct", help="VLM model")
    parser.add_argument("--reformatter-model", default="Qwen2.5-32B-Instruct", help="Reformatter model")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("📋 Lineage and Audit Trail")
    logger.info("=" * 80)
    
    if args.action == "create":
        if not args.pdf:
            logger.error("❌ --pdf required for create action")
            return 1
        
        manifest = create_document_manifest(
            args.pdf,
            args.docling_version,
            args.vlm_model,
            args.reformatter_model
        )
        
        output = args.output or f"{Path(args.pdf).stem}_manifest.json"
        save_manifest(manifest, output)
        
        return 0
    
    elif args.action == "load":
        if not args.manifest:
            logger.error("❌ --manifest required for load action")
            return 1
        
        manifest = load_manifest(args.manifest)
        logger.info(f"✅ Loaded manifest: {manifest.document_name}")
        logger.info(f"   Versions: {len(manifest.markdown_versions)}")
        logger.info(f"   Review notes: {len(manifest.review_notes)}")
        
        return 0
    
    elif args.action == "report":
        if not args.manifest:
            logger.error("❌ --manifest required for report action")
            return 1
        
        manifest = load_manifest(args.manifest)
        report = generate_audit_report(manifest)
        
        if args.output:
            with open(args.output, 'w') as f:
                f.write(report)
            logger.info(f"💾 Audit report saved: {args.output}")
        else:
            print(report)
        
        return 0
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
