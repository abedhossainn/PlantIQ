#!/usr/bin/env python3
"""
VLM Image Description Generator
Uses the shared vision model from repo-root .env to generate descriptions for missing images in markdown
"""

import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Any
import pdfplumber
import re

# Import new VLM infrastructure
from ..utils.vlm_options import VLMOptions, get_vision_model_id
from ..utils.vlm_response_parser import parse_vlm_response, ImageDescription
from ..utils.progress_tracker import ProgressBar, TimeEstimator, PersistentProgressTracker, log_operation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _build_image_description_prompt() -> str:
    return '''You are analyzing a technical document page.

Identify and describe ALL images, diagrams, figures, charts, and visual elements on this page.
For each visual element, provide:
1. A clear, descriptive title
2. A detailed description of what it shows
3. Any labels, legends, or key information visible

Format your response as a JSON array:
[
  {"title": "Figure X: [Title]", "description": "[Detailed description]"},
  ...
]

If there are NO visual elements (only text), return: []'''


def _extract_descriptions_from_response(response: str) -> List[Dict[str, str]]:
    match = re.search(r'\[[^\]]*\]', response, re.DOTALL)
    if match:
        json_str = match.group(0)
        descriptions = json.loads(json_str)
        return [
            {
                "title": desc.get("title", "Unknown"),
                "description": desc.get("description", ""),
            }
            for desc in descriptions
            if isinstance(desc, dict) and "title" in desc and "description" in desc
        ]

    partial_objects = re.findall(r'\{[^}]*"title"[^}]*"description"[^}]*\}', response, re.DOTALL)
    extracted: List[Dict[str, str]] = []
    for obj_str in partial_objects:
        try:
            obj_str_clean = obj_str.strip()
            if not obj_str_clean.endswith('}'):
                obj_str_clean += '}'
            obj = json.loads(obj_str_clean)
            extracted.append({
                "title": obj.get("title", "Unknown"),
                "description": obj.get("description", ""),
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return extracted


def extract_images_from_validation(validation_path: str) -> Dict[int, int]:
    """
    Extract pages with image loss from validation report
    
    Args:
        validation_path: Path to validation JSON
        
    Returns:
        Dict mapping page_number -> image_count
    """
    with open(validation_path) as f:
        validation = json.load(f)
    
    pages_with_images = {}
    for page_val in validation.get("page_validations", []):
        for issue in page_val.get("issues", []):
            if issue.get("issue_type") == "image_loss":
                page_num = page_val["page_number"]
                image_count = page_val["evidence"]["image_count"]
                pages_with_images[page_num] = image_count
    
    return pages_with_images


def generate_image_descriptions_vlm(
    pdf_path: str,
    pages_with_images: Dict[int, int],
    vlm_options: VLMOptions = None,
    workspace: Path = None
) -> Dict[int, List[Dict[str, str]]]:
    """
    Use VLM to generate descriptions for images on specific pages
    
    Args:
        pdf_path: Path to PDF
        pages_with_images: Dict of page_number -> image_count
        vlm_options: VLM configuration (uses default if None)
        workspace: Workspace for persistent progress tracking
        
    Returns:
        Dict mapping page_number -> list of image descriptions
    """
    # Use default options if not provided
    if vlm_options is None:
        vlm_options = VLMOptions.get_default("quality")  # Use quality preset for image descriptions
        vlm_options.model_id = get_vision_model_id()
        vlm_options.max_new_tokens = 2048  # Ensure longer descriptions
        vlm_options.verbose = True
    
    logger.info(f"🤖 Generating image descriptions with {vlm_options.model_id}...")
    logger.info(f"   Processing {len(pages_with_images)} pages with images")
    
    # Setup progress tracking
    doc_name = Path(pdf_path).stem
    if workspace:
        progress_tracker = PersistentProgressTracker(workspace, doc_name)
        progress_tracker.start_stage("Image Descriptions", total_items=len(pages_with_images))
    else:
        progress_tracker = None
    
    # Time estimation
    estimator = TimeEstimator(total_items=len(pages_with_images))
    
    with log_operation("Load VLM Model", model=vlm_options.model_id):
        try:
            # Use the generic multimodal auto-loader because exact Qwen3-VL class names
            # vary across Transformers releases.
            from transformers import AutoModelForImageTextToText, AutoProcessor
            from qwen_vl_utils import process_vision_info
            import torch
            import gc
        except ImportError as e:
            logger.error(f"❌ Required libraries not available: {e}")
            return {}
        
        # Clear GPU cache first
        gc.collect()
        torch.cuda.empty_cache()
        
        processor = AutoProcessor.from_pretrained(
            vlm_options.model_id,
            **vlm_options.get_processor_kwargs()
        )
        model = AutoModelForImageTextToText.from_pretrained(
            vlm_options.model_id,
            **vlm_options.get_model_kwargs()
        )
    
    page_descriptions = {}
    
    # Process each page with progress bar
    with pdfplumber.open(pdf_path) as pdf:
        pages_to_process = sorted(pages_with_images.keys())
        
        with ProgressBar(pages_to_process, desc="🖼️  Image descriptions", unit="page") as pbar:
            for page_num in pbar:
                # Check if already completed
                if progress_tracker and progress_tracker.is_completed(page_num):
                    logger.info(f"⏭️  Skipping page {page_num} (already done)")
                    estimator.update()
                    continue
                
                if page_num > len(pdf.pages):
                    logger.warning(f"⚠️  Page {page_num} not found in PDF")
                    if progress_tracker:
                        progress_tracker.mark_failed(page_num, "Page not found")
                    continue
                
                # Show ETA
                if estimator.completed > 0:
                    logger.info(f"📄 Processing page {page_num} | ETA: {estimator.get_eta()}")
                
                try:
                    # Convert page to image
                    page = pdf.pages[page_num - 1]
                    im = page.to_image(resolution=vlm_options.image_resolution)
                    img_path = f"/tmp/page_{page_num}_temp.png"
                    im.save(img_path)
                    
                    # Clear GPU cache before processing
                    gc.collect()
                    torch.cuda.empty_cache()
                    
                    # Prepare prompt
                    prompt = _build_image_description_prompt()
                    
                    messages = [
                        {
                            "role": "user",
                            "content": [
                                {"type": "image", "image": f"file://{img_path}"},
                                {"type": "text", "text": prompt}
                            ]
                        }
                    ]
                    
                    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
                    image_inputs, video_inputs = process_vision_info(messages)
                    
                    inputs = processor(
                        text=[text],
                        images=image_inputs,
                        videos=video_inputs,
                        padding=True,
                        return_tensors="pt"
                    )
                    inference_device = next(model.parameters()).device
                    inputs = inputs.to(inference_device)
                    
                    # Generate with VLM options
                    with torch.no_grad():
                        output_ids = model.generate(
                            **inputs,
                            **vlm_options.get_generation_kwargs()
                        )
                    
                    # Decode only the generated tokens
                    generated_ids = [
                        output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, output_ids)
                    ]
                    
                    response = processor.batch_decode(
                        generated_ids,
                        skip_special_tokens=True,
                        clean_up_tokenization_spaces=False
                    )[0]
                    
                    if vlm_options.verbose:
                        logger.info(f"   VLM Response: {response[:500]}")
                
                    # Extract JSON from response
                    descriptions = _extract_descriptions_from_response(response)
                    if descriptions:
                        page_descriptions[page_num] = descriptions
                        logger.info(f"   ✅ Extracted {len(descriptions)} image descriptions on page {page_num}")
                    else:
                        page_descriptions[page_num] = []
                        logger.warning("   ⚠️  Could not extract any valid descriptions")
                    
                    # Mark as completed
                    if progress_tracker:
                        progress_tracker.mark_completed(page_num)
                    
                    estimator.update()
                    
                except (RuntimeError, OSError, TypeError, ValueError, json.JSONDecodeError) as e:
                    logger.error(f"   ❌ Error processing page {page_num}: {e}")
                    page_descriptions[page_num] = []
                    if progress_tracker:
                        progress_tracker.mark_failed(page_num, str(e))
    
    # End progress tracking
    if progress_tracker:
        progress_tracker.end_stage("Image Descriptions")
        logger.info(f"\n{progress_tracker.get_progress_summary()}")
    
    # Unload model from GPU
    logger.info("🗑️  Unloading VLM model from GPU...")
    del model
    del processor
    gc.collect()
    torch.cuda.empty_cache()
    logger.info("✅ Model unloaded")
    
    logger.info(f"✅ Generated descriptions for {len(page_descriptions)} pages")
    return page_descriptions


def insert_image_descriptions(
    markdown_path: str,
    page_descriptions: Dict[int, List[Dict[str, str]]],
    output_path: str
) -> int:
    """
    Insert image descriptions into markdown
    
    Args:
        markdown_path: Path to original markdown
        page_descriptions: Dict of page_number -> list of image dicts
        output_path: Path to save updated markdown
        
    Returns:
        Number of descriptions inserted
    """
    logger.info("📝 Inserting image descriptions into markdown...")
    
    with open(markdown_path) as f:
        markdown = f.read()
    
    total_inserted = 0
    
    # For each page with descriptions, find location in markdown and insert
    # Strategy: Insert at the end of the page's section based on page markers
    for page_num in sorted(page_descriptions.keys()):
        descriptions = page_descriptions[page_num]
        if not descriptions:
            continue
        
        # Format descriptions as markdown
        image_section = "\n\n### Visual Elements\n\n"
        for img_desc in descriptions:
            title = img_desc.get("title", f"Figure on page {page_num}")
            description = img_desc.get("description", "")
            image_section += f"**{title}**\n\n{description}\n\n"
        
        # Try to find page marker or section boundary
        # Insert before next page or at end
        page_pattern = rf"<!-- Page {page_num} -->"
        next_page_pattern = rf"<!-- Page {page_num + 1} -->"
        
        if next_page_pattern in markdown:
            # Insert before next page
            markdown = markdown.replace(
                f"<!-- Page {page_num + 1} -->",
                f"{image_section}\n<!-- Page {page_num + 1} -->"
            )
            total_inserted += len(descriptions)
        elif page_pattern in markdown:
            # Find end of this page's content
            # Insert after current page marker
            parts = markdown.split(page_pattern, 1)
            if len(parts) == 2:
                markdown = parts[0] + page_pattern + image_section + parts[1]
                total_inserted += len(descriptions)
        else:
            # No page markers - append to end of document
            markdown += f"\n\n## Additional Visual Elements (Page {page_num})\n{image_section}"
            total_inserted += len(descriptions)
    
    # Save updated markdown
    with open(output_path, 'w') as f:
        f.write(markdown)
    
    logger.info(f"✅ Inserted {total_inserted} image descriptions")
    return total_inserted


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate image descriptions using VLM"
    )
    parser.add_argument("--pdf", required=True, help="PDF path")
    parser.add_argument("--markdown", required=True, help="Original markdown path")
    parser.add_argument("--validation", required=True, help="Validation JSON path")
    parser.add_argument("--output", required=True, help="Output markdown path")
    parser.add_argument("--config", help="VLM options config file (YAML or JSON)")
    parser.add_argument("--preset", choices=["balanced", "fast", "quality", "low_memory"],
                        default="quality", help="VLM preset configuration")
    
    args = parser.parse_args()
    
    # Load VLM options
    if args.config:
        if args.config.endswith('.yaml'):
            vlm_options = VLMOptions.from_yaml(args.config)
        else:
            vlm_options = VLMOptions.from_json(args.config)
    else:
        vlm_options = VLMOptions.get_default(args.preset)
        vlm_options.max_new_tokens = 2048  # Ensure long descriptions
    
    logger.info(f"Using VLM configuration: {args.preset if not args.config else args.config}")
    
    logger.info("=" * 80)
    logger.info("🖼️  VLM IMAGE DESCRIPTION GENERATOR")
    logger.info("=" * 80)
    
    # Step 1: Extract pages with image loss
    pages_with_images = extract_images_from_validation(args.validation)
    if not pages_with_images:
        logger.info("✅ No image loss detected - nothing to do")
        # Copy markdown as-is
        import shutil
        shutil.copy(args.markdown, args.output)
        return 0
    
    logger.info(f"📊 Found {len(pages_with_images)} pages with image loss")
    
    # Workspace for progress tracking
    workspace = Path(args.validation).parent
    
    # Step 2: Generate descriptions with VLM options
    page_descriptions = generate_image_descriptions_vlm(
        args.pdf,
        pages_with_images,
        vlm_options,
        workspace
    )
    
    if not page_descriptions:
        logger.error("❌ No descriptions generated")
        return 1
    
    # Step 3: Insert descriptions
    total_inserted = insert_image_descriptions(
        args.markdown,
        page_descriptions,
        args.output
    )

    if total_inserted == 0 and pages_with_images:
        logger.error("❌ No image descriptions were inserted")
        return 1
    
    logger.info("=" * 80)
    logger.info(f"✅ Image description complete: {total_inserted} descriptions added")
    logger.info(f"📄 Output: {args.output}")
    logger.info("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
