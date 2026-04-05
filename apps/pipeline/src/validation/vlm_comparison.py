#!/usr/bin/env python3
"""
Step 2b: VLM Comparison
Compare markdown with original PDF using the shared vision model from repo-root .env
Generates validation report for the reformatter
"""

import json
import re
from pathlib import Path
import logging

# Import new VLM infrastructure
from ..utils.vlm_options import VLMOptions, get_vision_model_id
from ..utils.vlm_response_parser import parse_vlm_response, ValidationResult, enforce_pydantic_schema
from ..utils.progress_tracker import log_operation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def extract_pdf_info(pdf_path: str) -> dict:
    """Extract PDF content for validation context"""
    try:
        import pdfplumber
        
        logger.info(f"📥 Extracting PDF: {pdf_path}")
        
        pdf_info = {"page_count": 0, "pages": []}
        
        with pdfplumber.open(pdf_path) as pdf:
            pdf_info["page_count"] = len(pdf.pages)
            
            for i, page in enumerate(pdf.pages[:3]):
                text = page.extract_text() or ""
                pdf_info["pages"].append({
                    "page_number": i + 1,
                    "text_preview": text[:500]
                })
        
        logger.info(f"✅ PDF extracted: {pdf_info['page_count']} pages")
        return pdf_info
        
    except Exception as e:
        logger.warning(f"⚠️  PDF extraction failed: {e}")
        return {"page_count": 0, "pages": []}


def compare_with_vlm(markdown_content: str, pdf_path: str, vlm_options: VLMOptions = None) -> dict:
    """
    Use the configured shared vision model to compare markdown with PDF
    
    Args:
        markdown_content: Markdown content to validate
        pdf_path: Path to source PDF
        vlm_options: VLM configuration (uses default if None)
        
    Returns:
        Validation result as dict
    """
    # Use default options if not provided
    if vlm_options is None:
        vlm_options = VLMOptions.get_default("balanced")
        vlm_options.model_id = get_vision_model_id()
        vlm_options.verbose = True
    
    with log_operation("VLM Comparison", model=vlm_options.model_id):
        try:
            # Use the generic multimodal auto-loader because exact Qwen3-VL class names
            # vary across Transformers releases.
            from transformers import AutoModelForImageTextToText, AutoProcessor
            from qwen_vl_utils import process_vision_info
            import torch
            import gc
            
            # Clear memory
            gc.collect()
            torch.cuda.empty_cache()
            
            # Load model with options
            processor = AutoProcessor.from_pretrained(
                vlm_options.model_id,
                **vlm_options.get_processor_kwargs()
            )
            model = AutoModelForImageTextToText.from_pretrained(
                vlm_options.model_id,
                **vlm_options.get_model_kwargs()
            )
            
            # Prepare comparison prompt with schema enforcement
            base_prompt = f"""Analyze this markdown content from a PDF conversion.
Identify issues:
1. Missing content
2. Formatting errors (tables, images, headings)
3. Content that should be questions instead of statements

Markdown excerpt (first 2000 chars):
{markdown_content[:2000]}"""
            
            comparison_prompt = enforce_pydantic_schema(base_prompt, ValidationResult)
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": comparison_prompt}
                    ],
                }
            ]
            
            logger.info("📨 Sending to VLM...")
            
            text = processor.apply_chat_template(messages, add_generation_prompt=True)
            image_inputs, video_inputs = process_vision_info(messages)
            
            inputs = processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
            
            inputs = inputs.to(model.device)
            
            # Generate with options
            generated_ids = model.generate(**inputs, **vlm_options.get_generation_kwargs())
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            response = processor.batch_decode(
                generated_ids_trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
            
            # Unload model from GPU
            logger.info("🗑️  Unloading VLM model from GPU...")
            del model
            del processor
            gc.collect()
            torch.cuda.empty_cache()
            logger.info("✅ Model unloaded, GPU memory freed")
            
            # Parse response with structured parser
            fallback = ValidationResult(
                format_issues=[
                    "Images need text descriptions",
                    "Tables should be converted to bullet facts",
                    "Headings should be questions"
                ],
                missing_content=[],
                improvement_suggestions=[],
                confidence=0.5
            )
            
            result = parse_vlm_response(
                response,
                ValidationResult,
                fallback=fallback,
                verbose=vlm_options.verbose
            )
            
            # Convert to dict for compatibility
            return {
                "format_issues": result.format_issues,
                "missing_content": result.missing_content,
                "improvement_suggestions": result.improvement_suggestions,
                "confidence": result.confidence
            }
            
        except Exception as e:
            logger.error(f"❌ VLM comparison failed: {e}")
            # Clean up on error too
            try:
                del model
                del processor
                gc.collect()
                torch.cuda.empty_cache()
            except:
                pass
            
            return {
                "format_issues": ["VLM analysis failed - please review manually"],
                "missing_content": [],
                "improvement_suggestions": [],
                "confidence": 0.0
            }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="VLM PDF-Markdown comparison")
    parser.add_argument("pdf", help="Path to PDF")
    parser.add_argument("--markdown", default="output.md", help="Markdown file")
    parser.add_argument("--output", default="validation_report.json", help="Output report")
    parser.add_argument("--config", help="VLM options config file (YAML or JSON)")
    parser.add_argument("--preset", choices=["balanced", "fast", "quality", "low_memory"],
                        default="balanced", help="VLM preset configuration")
    
    args = parser.parse_args()
    
    # Load VLM options
    if args.config:
        if args.config.endswith('.yaml'):
            vlm_options = VLMOptions.from_yaml(args.config)
        else:
            vlm_options = VLMOptions.from_json(args.config)
    else:
        vlm_options = VLMOptions.get_default(args.preset)
    
    logger.info(f"Using VLM configuration: {args.preset if not args.config else args.config}")
    
    logger.info("=" * 80)
    logger.info("🔍 Step 2b: VLM Comparison")
    logger.info("=" * 80)
    
    # Load markdown
    logger.info("\n[1/3] Loading markdown...")
    with open(args.markdown, 'r') as f:
        markdown_content = f.read()
    logger.info(f"✅ Loaded {len(markdown_content)} characters")
    
    # Extract PDF info
    logger.info("\n[2/3] Extracting PDF...")
    pdf_info = extract_pdf_info(args.pdf)
    
    # Compare with VLM
    logger.info("\n[3/3] Running VLM comparison...")
    validation_report = compare_with_vlm(markdown_content, args.pdf, vlm_options)
    
    # Save report
    output_path = Path(args.output)
    with open(output_path, 'w') as f:
        json.dump(validation_report, f, indent=2)
    
    logger.info(f"\n✅ Validation report saved: {output_path}")
    logger.info("\nReport contents:")
    logger.info(json.dumps(validation_report, indent=2))


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
