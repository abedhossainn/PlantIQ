#!/usr/bin/env python3
"""
Convert PDF to Markdown using Docling with Qwen2.5-VL-32B-Instruct VLM

This script uses the Docling API to convert PDFs with high-accuracy VLM-powered
image and table descriptions using Qwen2.5-VL-32B-Instruct.

Usage:
    python3 docling_convert_with_qwen.py <input_pdf> <output_markdown> [--image-mode {placeholder|embedded|referenced}]

Example:
    python3 docling_convert_with_qwen.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" output.md --image-mode placeholder
"""

import sys
import json
import requests
import argparse
import io
import re
import base64
import tempfile
import torch
import hashlib
from pathlib import Path
from PIL import Image

# Import VLM infrastructure
try:
    from vlm_options import VLMOptions
    from progress_tracker import ProgressBar, log_operation
    VLM_INFRASTRUCTURE_AVAILABLE = True
except ImportError:
    VLM_INFRASTRUCTURE_AVAILABLE = False
    print("⚠️  VLM infrastructure not available. Using basic configuration.")

# Try to import docling locally for re-serialization
try:
    from docling_core.types.doc import ImageRefMode
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    DOCLING_AVAILABLE_LOCALLY = True
except ImportError:
    DOCLING_AVAILABLE_LOCALLY = False
    print("⚠️  Warning: Docling library not available locally. Image mode settings may not work.")

# Load Qwen2.5-VL model for image descriptions
def _load_qwen_model(vlm_options: 'VLMOptions' = None):
    """Load Qwen2.5-VL-32B-Instruct model from local cache"""
    try:
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
        from qwen_vl_utils import process_vision_info
        
        # Use VLMOptions if available
        if vlm_options is None and VLM_INFRASTRUCTURE_AVAILABLE:
            vlm_options = VLMOptions.get_default("quality")
            vlm_options.max_new_tokens = 120  # Short descriptions
        
        model_id = vlm_options.model_id if vlm_options else "Qwen/Qwen2.5-VL-32B-Instruct"
        
        print(f"🔄 Loading {model_id}...")
        
        # Load with options if available
        if vlm_options:
            processor = AutoProcessor.from_pretrained(
                model_id,
                **vlm_options.get_processor_kwargs()
            )
            model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id,
                **vlm_options.get_model_kwargs()
            )
        else:
            # Fallback to basic loading
            processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True, use_fast=False)
            model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                model_id,
                device_map="auto",
                dtype="auto",
                trust_remote_code=True,
            )
        
        print(f"✅ Model loaded successfully")
        return model, processor, process_vision_info
    except ImportError as e:
        print(f"❌ Error: Required libraries not found: {e}")
        print("   Install with: pip install transformers qwen_vl_utils")
        return None, None, None
    except Exception as e:
        print(f"❌ Error loading Qwen model: {e}")
        print(f"   Details: {str(e)[:200]}")
        return None, None, None

# Global model and processor
_qwen_model = None
_qwen_processor = None
_process_vision_info = None

def _get_qwen_model():
    """Get or load Qwen model (lazy loading)"""
    global _qwen_model, _qwen_processor, _process_vision_info
    if _qwen_model is None:
        _qwen_model, _qwen_processor, _process_vision_info = _load_qwen_model()
    return _qwen_model, _qwen_processor, _process_vision_info


def _convert_embedded_to_placeholders(md_content: str) -> str:
    """Convert embedded data URIs to simple [IMAGE] placeholders"""
    # Pattern for embedded images: ![alt](data:image/...)
    pattern = r'!\[([^\]]*)\]\(data:image/[^)]+\)'
    return re.sub(pattern, '[IMAGE]', md_content)


def _extract_referenced_images(md_content: str, output_path: str) -> tuple[str, list]:
    """
    Extract embedded images and save them as separate files,
    replacing data URIs with file references.
    
    Returns: (modified_md_content, list_of_image_files)
    """
    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    
    image_files = []
    image_counter = [0]  # Use list to make it mutable in nested function
    
    def replace_image(match):
        alt_text = match.group(1)
        data_uri = match.group(2)
        
        # Parse data URI
        if not data_uri.startswith('data:image/'):
            return match.group(0)
        
        try:
            # Extract format and base64 data
            header, data = data_uri.split(',', 1)
            img_format = header.split('/')[1].split(';')[0]
            
            # Decode base64
            image_data = base64.b64decode(data)
            
            # Save image
            image_counter[0] += 1
            filename = f"image_{image_counter[0]}.{img_format}"
            filepath = output_dir / filename
            filepath.write_bytes(image_data)
            image_files.append(str(filepath))
            
            # Return markdown reference
            return f'![{alt_text}]({filename})'
        except Exception as e:
            print(f"   ⚠️  Warning: Could not extract image: {e}")
            return match.group(0)
    
    # Replace all embedded images
    pattern = r'!\[([^\]]*)\]\((data:image/[^)]+)\)'
    modified_content = re.sub(pattern, replace_image, md_content)
    
    return modified_content, image_files


def _coalesce_consecutive_headings(md_content: str) -> str:
    """
    Coalesce multiple consecutive headings without intervening text.
    If multiple ## headings appear within 3 lines of each other with no prose,
    combine them into a single heading or reflow as a paragraph.
    """
    lines = md_content.split('\n')
    result = []
    heading_buffer = []
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Check if this is a heading
        if stripped.startswith('##') and not stripped.startswith('###'):
            heading_buffer.append(stripped)
        elif stripped:  # Non-empty, non-heading line
            # Flush heading buffer if we have multiple consecutive headings
            if len(heading_buffer) > 1:
                # Combine headings with " / " separator
                combined = heading_buffer[0] + ' / ' + ' / '.join(h.lstrip('#').strip() for h in heading_buffer[1:])
                result.append(combined)
            elif heading_buffer:
                result.append(heading_buffer[0])
            
            heading_buffer = []
            result.append(line)
        else:  # Empty line
            if heading_buffer:
                # Check if next non-empty line is also a heading
                next_is_heading = False
                for j in range(i + 1, min(i + 4, len(lines))):
                    next_stripped = lines[j].strip()
                    if next_stripped:
                        next_is_heading = next_stripped.startswith('##') and not next_stripped.startswith('###')
                        break
                
                if not next_is_heading:
                    # Flush buffer
                    if len(heading_buffer) > 1:
                        combined = heading_buffer[0] + ' / ' + ' / '.join(h.lstrip('#').strip() for h in heading_buffer[1:])
                        result.append(combined)
                    else:
                        result.append(heading_buffer[0])
                    heading_buffer = []
            
            result.append(line)
    
    # Flush any remaining headings
    if heading_buffer:
        if len(heading_buffer) > 1:
            combined = heading_buffer[0] + ' / ' + ' / '.join(h.lstrip('#').strip() for h in heading_buffer[1:])
            result.append(combined)
        else:
            result.append(heading_buffer[0])
    
    return '\n'.join(result)


def _normalize_table_cells(md_content: str) -> str:
    """
    Normalize table cells by:
    - Trimming leading/trailing spaces
    - Collapsing repeated spaces to single space
    - Normalizing chemical formulas (e.g., 'C 1 H 4' -> 'C1H4')
    """
    lines = md_content.split('\n')
    result = []
    
    for line in lines:
        # Detect table rows (contain |)
        if '|' in line and not line.strip().startswith('```'):
            # Split by pipe and process each cell
            cells = line.split('|')
            normalized_cells = []
            
            for cell in cells:
                # Trim and collapse spaces
                normalized = re.sub(r'\s{2,}', ' ', cell.strip())
                
                # Normalize chemical formulas: remove spaces between element and number
                # Pattern: Letter followed by space and digit (e.g., 'C 1' -> 'C1')
                normalized = re.sub(r'([A-Z])\s+(\d)', r'\1\2', normalized)
                # Pattern: digit followed by space and letter (e.g., '2 H' -> '2H')
                normalized = re.sub(r'(\d)\s+([A-Z])', r'\1\2', normalized)
                
                normalized_cells.append(normalized)
            
            # Reconstruct table row
            result.append('|'.join(normalized_cells))
        else:
            result.append(line)
    
    return '\n'.join(result)


def _generate_image_descriptions(
    md_content: str,
    docling_url: str = "http://localhost:5001",
    vlm_options: 'VLMOptions' = None
) -> str:
    """
    Replace embedded images with AI-generated descriptions using Qwen2.5-VL.
    Keeps markdown clean and text-only with no external image files.
    Uses byte-level hashing to detect and skip duplicate images.
    
    Args:
        md_content: Markdown content with embedded images
        docling_url: Base URL of Docling service (unused, here for compatibility)
        vlm_options: VLM configuration options
    
    Returns:
        Modified markdown with descriptions instead of images
    """
    model, processor, process_vision_info = _load_qwen_model(vlm_options)
    if model is None or processor is None:
        print("⚠️  Qwen model not available, using placeholder descriptions")
        image_counter = [0]
        def replace_with_placeholder(match):
            alt_text = match.group(1)
            image_counter[0] += 1
            description = alt_text.strip() if alt_text and alt_text.strip() else f"Image {image_counter[0]}"
            return f"\n**[Figure {image_counter[0]}: {description}]**\n"
        
        pattern = r'!\[([^\]]*)\]\((data:image/[^)]+)\)'
        return re.sub(pattern, replace_with_placeholder, md_content)
    
    image_counter = [0]
    descriptions_cache = {}  # Cache by image hash (bytes)
    hash_to_description = {}  # Map image hash to description
    
    def replace_with_description(match):
        alt_text = match.group(1)
        data_uri = match.group(2)
        
        if not data_uri.startswith('data:image/'):
            return match.group(0)
        
        image_counter[0] += 1
        image_num = image_counter[0]
        
        try:
            # Extract and decode base64 image
            header, data = data_uri.split(',', 1)
            img_format = header.split('/')[1].split(';')[0]
            image_data = base64.b64decode(data)
            
            # Compute hash of image bytes for deduplication
            image_hash = hashlib.sha256(image_data).hexdigest()
            
            # Check if we already generated this description (by byte hash)
            if image_hash in hash_to_description:
                description = hash_to_description[image_hash]
                print(f"   ↻ Image {image_num}: Duplicate detected, reusing description")
                return f"\n**[Figure {image_num}: {description}]**\n"
            
            # Save image temporarily
            with tempfile.NamedTemporaryFile(suffix=f".{img_format}", delete=False) as tmp:
                tmp.write(image_data)
                tmp_path = tmp.name
            
            try:
                # Open image with PIL
                image = Image.open(tmp_path)
                
                # Prepare messages for Qwen in the correct format
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "image": image,  # PIL Image directly
                            },
                            {
                                "type": "text",
                                "text": "Describe this image in detail with ONE complete sentence. Prioritize accuracy and completeness. Include the main subject, key details, and context. Be specific and technical.",
                            },
                        ],
                    }
                ]
                
                # Apply chat template and process vision info
                text = processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True
                )
                image_inputs, video_inputs = process_vision_info(messages)
                
                # Prepare inputs
                inputs = processor(
                    text=[text],
                    images=image_inputs,
                    videos=video_inputs,
                    padding=True,
                    return_tensors="pt",
                )
                
                # Move to device
                inputs = inputs.to(model.device)
                
                # Generate description with VLM options
                gen_kwargs = {'max_new_tokens': 120}
                if vlm_options:
                    gen_kwargs = vlm_options.get_generation_kwargs()
                    gen_kwargs['max_new_tokens'] = 120  # Override for short descriptions
                
                with torch.no_grad():
                    generated_ids = model.generate(**inputs, **gen_kwargs)
                
                # Trim and decode
                generated_ids_trimmed = [
                    out_ids[len(in_ids):] 
                    for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
                ]
                output_text = processor.batch_decode(
                    generated_ids_trimmed,
                    skip_special_tokens=True,
                    clean_up_tokenization_spaces=False
                )
                
                description = output_text[0].strip() if output_text else "Image"
                
                # Ensure sentence completion: take first complete sentence
                sentences = re.split(r'[.!?]\s+', description)
                if sentences:
                    description = sentences[0].strip()
                    # Ensure it ends with punctuation
                    if description and description[-1] not in '.!?':
                        description += '.'
                
                # Cache by image hash for deduplication
                hash_to_description[image_hash] = description
                
                print(f"   ✓ Image {image_num}: {description[:60]}...")
                
                return f"\n**[Figure {image_num}: {description}]**\n"
                
            finally:
                # Clean up temporary file
                Path(tmp_path).unlink(missing_ok=True)
                
        except Exception as e:
            print(f"   ⚠️  Image {image_num}: Failed to describe ({str(e)[:50]})")
            # Fallback to alt text or generic description
            description = alt_text.strip() if alt_text and alt_text.strip() else f"Image {image_num}"
            return f"\n**[Figure {image_num}: {description}]**\n"
    
    # Replace all embedded images with descriptions
    pattern = r'!\[([^\]]*)\]\((data:image/[^)]+)\)'
    modified_content = re.sub(pattern, replace_with_description, md_content)
    
    return modified_content


def convert_pdf_with_qwen(
    pdf_path: str,
    output_path: str,
    image_mode: str = "placeholder",
    docling_url: str = "http://localhost:5001",
    vlm_options: 'VLMOptions' = None
):
    """
    Convert PDF to Markdown using Docling with Qwen2.5-VL-32B-Instruct VLM
    
    Args:
        pdf_path: Path to input PDF
        output_path: Path to save output Markdown
        image_mode: Image handling mode: 'placeholder', 'embedded', 'referenced', or 'descriptions'
        docling_url: Base URL of Docling service
        vlm_options: VLM configuration options
    """
    pdf_file = Path(pdf_path)
    
    # Use context manager if available, otherwise just proceed
    if VLM_INFRASTRUCTURE_AVAILABLE:
        context = log_operation("PDF Conversion", pdf=pdf_file.name, mode=image_mode)
    else:
        from contextlib import nullcontext
        context = nullcontext()
    
    with context:
        if not pdf_file.exists():
            print(f"❌ Error: PDF file not found: {pdf_path}")
            sys.exit(1)
        
        print(f"📄 Input PDF: {pdf_file.name}")
        print(f"🎯 Using VLM: Qwen2.5-VL-32B-Instruct")
        print(f"🖼️  Image mode: {image_mode}")
        print(f"🔗 Docling API: {docling_url}/v1/convert/file")
        print("\n⏳ Converting PDF (this may take a few minutes for first run)...")
        
        # Settings - focus on pipeline options for richer structured data
        options = {
            "to_formats": ["markdown"],  # Request markdown format
            "pipeline_type": "standard",
            "do_ocr": True,
            "ocr_engine": "auto",
            "pdf_backend": "dlparse_v4",
            "table_mode": "accurate",  # Use accurate mode for better table extraction
            "do_formula_enrichment": True,
            "do_picture_description": True,
            "do_code_enrichment": False,
            "do_picture_classification": False,
            # Request structured data for better post-processing
            "generate_page_images": False,
            "generate_picture_images": True,
        }

        # Send PDF to Docling
        with open(pdf_file, "rb") as f:
            files = {"files": f}
            data = {"options": json.dumps(options)}
            try:
                response = requests.post(
                    f"{docling_url}/v1/convert/file",
                    files=files,
                    data=data,
                    timeout=900  # 15 minute timeout for large PDFs
                )
                response.raise_for_status()
            except requests.exceptions.ConnectionError:
                print(f"❌ Error: Cannot connect to Docling at {docling_url}")
                print("   Make sure docling-serve is running: docker ps | grep docling-serve")
                sys.exit(1)
            except requests.exceptions.Timeout:
                print(f"❌ Error: Timeout converting PDF (took > 15 min). Try with smaller PDF.")
                sys.exit(1)
            except Exception as e:
                print(f"❌ Error during conversion: {e}")
                sys.exit(1)
        
        # Parse response
        try:
            result = response.json()
        except json.JSONDecodeError:
            print(f"❌ Error: Invalid response from Docling")
            print(f"   Status: {response.status_code}")
            print(f"   Response: {response.text[:500]}")
            sys.exit(1)
        
        # Check for conversion errors
        if result.get("status") != "success":
            print(f"❌ Conversion failed: {result.get('errors', 'Unknown error')}")
            sys.exit(1)
        
        # Extract markdown content from API response
        document = result.get("document", {})
        md_content = document.get("md_content", "")
        
        if not md_content:
            print("❌ Error: No markdown content in response")
            sys.exit(1)
        
        # Instrumentation: Log document structure for debugging
        print(f"\n📊 Document structure:")
        print(f"   Pages: {len(document.get('pages', []))}")
        print(f"   Elements: {len(document.get('elements', []))}")
        print(f"   Raw MD size: {len(md_content):,} bytes")
        
        # Post-process markdown based on image_mode
        if image_mode == "placeholder":
            print("\n🔄 Converting embedded images to placeholders...")
            md_content = _convert_embedded_to_placeholders(md_content)
        elif image_mode == "referenced":
            print("\n🔄 Converting embedded images to referenced format...")
            md_content, image_refs = _extract_referenced_images(md_content, output_path)
            if image_refs:
                print(f"   Extracted {len(image_refs)} images to separate files")
        elif image_mode == "descriptions":
            print("\n🔄 Generating AI descriptions for images...")
            md_content = _generate_image_descriptions(md_content, docling_url, vlm_options)
        
        # Apply structural post-processing improvements
        print("\n🔧 Applying structural post-processing...")
        print("   ✓ Normalizing table cells and chemical formulas")
        md_content = _normalize_table_cells(md_content)
        print("   ✓ Coalescing consecutive headings")
        md_content = _coalesce_consecutive_headings(md_content)
        
        # Save to file
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(md_content, encoding="utf-8")
        
        print(f"\n✅ Conversion complete!")
        print(f"📝 Output: {output_file.resolve()}")
        print(f"📊 File size: {len(md_content):,} bytes ({len(md_content.split(chr(10)))} lines)")

def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown with Qwen2.5-VL-32B-Instruct VLM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 docling_convert_with_qwen.py input.pdf output.md
  python3 docling_convert_with_qwen.py input.pdf output.md --image-mode placeholder
  python3 docling_convert_with_qwen.py input.pdf output.md --image-mode descriptions
  python3 docling_convert_with_qwen.py input.pdf output.md --image-mode referenced
        """
    )
    
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument("output", nargs="?", default="output.md", help="Output Markdown file path (default: output.md)")
    parser.add_argument(
        "--image-mode",
        choices=["placeholder", "embedded", "referenced", "descriptions"],
        default="placeholder",
        help="Image handling mode (default: placeholder)"
    )
    parser.add_argument(
        "--docling-url",
        default="http://localhost:5001",
        help="Docling service URL (default: http://localhost:5001)"
    )
    parser.add_argument("--config", help="VLM options config file (YAML or JSON)")
    parser.add_argument("--preset", choices=["balanced", "fast", "quality", "low_memory"],
                        default="quality", help="VLM preset configuration")
    
    args = parser.parse_args()
    
    # Load VLM options if infrastructure available
    vlm_options = None
    if VLM_INFRASTRUCTURE_AVAILABLE:
        if args.config:
            if args.config.endswith('.yaml'):
                vlm_options = VLMOptions.from_yaml(args.config)
            else:
                vlm_options = VLMOptions.from_json(args.config)
        else:
            vlm_options = VLMOptions.get_default(args.preset)
            vlm_options.max_new_tokens = 120  # Short image descriptions
    
    # If only one positional arg provided, use default output name
    if args.output == "output.md" and len(sys.argv) == 2:
        args.output = "output.md"
    
    convert_pdf_with_qwen(
        pdf_path=args.pdf,
        output_path=args.output,
        image_mode=args.image_mode,
        docling_url=args.docling_url,
        vlm_options=vlm_options
    )


if __name__ == "__main__":
    main()

