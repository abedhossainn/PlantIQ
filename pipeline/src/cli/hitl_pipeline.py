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
from typing import Dict, Optional
from datetime import datetime

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
from ..ingestion.docling_converter import export_page_markdown_map

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


PLACEHOLDER_MARKDOWN_SENTINELS = (
    "Initial placeholder markdown created by backend upload workflow.",
    "Replace with Docling-extracted markdown for full-quality pipeline results.",
)

DOCLING_IMAGE_MODE = "descriptions"


def _convert_pdf_to_markdown(*, pdf_path: str, output_path: str, image_mode: str, docling_url: str) -> None:
    from ..ingestion.docling_converter import convert_pdf_with_qwen

    convert_pdf_with_qwen(
        pdf_path=pdf_path,
        output_path=output_path,
        image_mode=image_mode,
        docling_url=docling_url,
    )


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
        markdown_path = self._ensure_docling_markdown(pdf_path, markdown_path)
        page_markdown_map = export_page_markdown_map(
            pdf_path,
            image_mode=DOCLING_IMAGE_MODE,
        )
        
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
        
        manifest = create_document_manifest(
            pdf_path,
            docling_version,
            vlm_model,
            reformatter_model
        )
        manifest.primary_reviewer = reviewer
        manifest_path = self.work_dir / f"{doc_name}_manifest.json"
        save_manifest(manifest, str(manifest_path))
        
        results["stages"]["manifest"] = {
            "status": "complete",
            "output": str(manifest_path)
        }
        
        # Stage 2: Enhanced validation with the configured vision model
        logger.info("\n" + "=" * 80)
        logger.info(f"🔍 STAGE 2: VLM-Powered Validation ({vlm_model})")
        logger.info("=" * 80)
        
        # First: Basic per-page evidence extraction
        logger.info("📊 Step 2a: Extracting per-page evidence...")
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
        
        # Second: Deep VLM comparison (optional - can be skipped for speed)
        logger.info("\n📊 Step 2b: Running VLM deep comparison (this takes ~70-80 min)...")
        logger.info("⚠️  Note: You can skip VLM comparison by pressing Ctrl+C")
        logger.info("         Basic validation is already complete.")
        
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
            
        except KeyboardInterrupt:
            logger.warning("⚠️  VLM comparison skipped by user")
        except Exception as e:
            logger.warning(f"⚠️  VLM comparison failed (continuing with basic validation): {e}")
        
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
                    
            except subprocess.TimeoutExpired:
                logger.warning("⚠️  Image description timed out - continuing with original markdown")
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                results["stages"]["image_descriptions"] = {
                    "status": "timeout"
                }
            except Exception as e:
                logger.warning(f"⚠️  Image description error: {e}")
                with open(markdown_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
                results["stages"]["image_descriptions"] = {
                    "status": "error",
                    "error": str(e)
                }
        else:
            logger.info("✅ No image loss detected - skipping image description")
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
        
        tables = extract_tables_from_pdf(pdf_path)
        
        figures = extract_figures_from_markdown(markdown_content)
        
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

        pages = extract_pages_from_validation(validation_report, doc_name)
        sections = extract_sections_from_markdown(markdown_content, doc_name)

        review_workspace = self.work_dir / f"{doc_name}_review"
        create_page_review_workspace(pages, str(review_workspace))
        create_review_workspace(sections, str(review_workspace))
        
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
        
        versions_dir = self.work_dir / f"{doc_name}_versions"
        manifest = create_version(
            manifest,
            markdown_content,
            str(versions_dir),
            version_notes="Initial extraction from Docling"
        )
        save_manifest(manifest, str(manifest_path))
        
        results["stages"]["versioning"] = {
            "status": "complete",
            "version": 1,
            "versions_dir": str(versions_dir)
        }
        
        # Stage 6: Compute QA metrics (pre-review)
        logger.info("\n" + "=" * 80)
        logger.info("📊 STAGE 6: Compute Pre-Review QA Metrics")
        logger.info("=" * 80)
        
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
        
        # Stage 7: Generate audit report
        logger.info("\n" + "=" * 80)
        logger.info("📋 STAGE 7: Generate Audit Report")
        logger.info("=" * 80)
        
        audit_report = generate_audit_report(manifest)
        audit_path = self.work_dir / f"{doc_name}_audit.txt"
        
        with open(audit_path, 'w') as f:
            f.write(audit_report)
        
        logger.info(f"💾 Audit report: {audit_path}")
        
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
        markdown_path: str,
        pdf_path: str,
        validation_report_path: str
    ) -> Dict:
        """
        Run shared text-model reformatting AFTER manual review approval
        This is Stage 10 - final AI-powered optimization
        """
        logger.info("\n" + "=" * 80)
        logger.info(f"🤖 STAGE 10: Post-Approval Reformatting ({get_text_model_id()})")
        logger.info("=" * 80)
        logger.info("⏱️  This will take ~40-60 minutes")
        
        try:
            # Import reformatter
            from ..cli.text_reformatter import reformat_with_qwen
            import json
            
            # Load markdown
            with open(markdown_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
            
            # Load validation report
            with open(validation_report_path, 'r') as f:
                validation_data = json.load(f)
            
            # Run reformatting
            logger.info(f"📨 Sending to {get_text_model_id()} for RAG optimization...")
            result = reformat_with_qwen(
                markdown_content,
                validation_data,
                pdf_path,
                doc_name
            )
            
            if result:
                # Save outputs
                output_json = self.work_dir / f"{doc_name}_rag_optimized.json"
                output_md = self.work_dir / f"{doc_name}_rag_optimized.md"
                
                with open(output_json, 'w') as f:
                    json.dump(result, f, indent=2)
                
                if 'markdown' in result:
                    with open(output_md, 'w') as f:
                        f.write(result['markdown'])
                
                logger.info(f"✅ Reformatting complete")
                logger.info(f"   JSON: {output_json}")
                logger.info(f"   Markdown: {output_md}")
                
                return {
                    "status": "complete",
                    "json_output": str(output_json),
                    "markdown_output": str(output_md)
                }
            else:
                logger.error("❌ Reformatting returned no result")
                return {"status": "failed"}
                
        except Exception as e:
            logger.error(f"❌ Reformatting failed: {e}", exc_info=True)
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
                args.markdown,
                args.pdf,
                str(validation_path)
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
