#!/usr/bin/env python3
"""
Convert PDF to Markdown using Docling with the shared vision model from repo-root .env

This script uses the Docling API to convert PDFs with high-accuracy VLM-powered
image and table descriptions using the configured vision model.

Usage:
    python3 docling_convert_with_qwen.py <input_pdf> <output_markdown> [--image-mode {placeholder|embedded|referenced|descriptions}]

Example:
    python3 docling_convert_with_qwen.py "InjestDocs/COMMON Module 3 Characteristics of LNG.pdf" output.md --image-mode descriptions
"""

import sys
import json
import requests
import argparse
import io
import re
import os
import base64
import tempfile
import torch
import hashlib
import logging
from pathlib import Path
from PIL import Image
from typing import Any, Optional

# Use "placeholder" mode by default to avoid expensive VLM inference on every image in PDFs
# This significantly speeds up Docling PDF conversion. For production image analysis,
# consider implementing async batch VLM description as a separate post-processing stage.
DEFAULT_IMAGE_MODE = "placeholder"

# Import VLM infrastructure
try:
    from ..utils.vlm_options import VLMOptions, get_vision_model_id
    from ..utils.progress_tracker import ProgressBar, log_operation
    VLM_INFRASTRUCTURE_AVAILABLE = True
except ImportError:
    VLM_INFRASTRUCTURE_AVAILABLE = False
    def get_vision_model_id() -> str:
        return "Qwen/Qwen3-VL-4B-Instruct"

    print("⚠️  VLM infrastructure not available. Using basic configuration.")

# Try to import docling locally for optional re-serialization helpers.
# These imports are not required for description-only mode, so failures
# should not block conversion through the Docling service.
try:
    from docling_core.types.doc import ImageRefMode
    from docling_core.transforms.serializer.markdown import MarkdownDocSerializer, MarkdownParams
    DOCLING_AVAILABLE_LOCALLY = True
except ImportError:
    DOCLING_AVAILABLE_LOCALLY = False
    ImageRefMode = None
    MarkdownDocSerializer = None
    MarkdownParams = None


logger = logging.getLogger(__name__)

DEFAULT_DOCLING_CHUNK_PAGES = 4
DEFAULT_DOCLING_CHUNK_READ_TIMEOUT_SECONDS = 300
DEFAULT_DOCLING_CONNECT_TIMEOUT_SECONDS = 10
EMBEDDED_IMAGE_PATTERN = r'!\[([^\]]*)\]\((data:image/[^)]+)\)'
DEFAULT_DOCLING_URL = "http://localhost:5001"
DOCLING_CONVERT_ENDPOINT = "/v1/convert/file"
DEFAULT_OUTPUT_FILENAME = "output.md"

# Load the configured vision-language model for image descriptions
def _load_qwen_model(vlm_options: 'VLMOptions' = None):
    """Load the configured vision-language model from local cache."""
    try:
        from transformers import AutoModelForImageTextToText, AutoProcessor
        from qwen_vl_utils import process_vision_info
        
        # Use VLMOptions if available
        if vlm_options is None and VLM_INFRASTRUCTURE_AVAILABLE:
            vlm_options = VLMOptions.get_default("quality")
            vlm_options.model_id = get_vision_model_id()
            vlm_options.max_new_tokens = 120  # Short descriptions
        
        model_id = vlm_options.model_id if vlm_options else get_vision_model_id()
        
        print(f"🔄 Loading {model_id}...")
        
        # Load with options if available
        if vlm_options:
            processor = AutoProcessor.from_pretrained(
                model_id,
                **vlm_options.get_processor_kwargs()
            )
            model = AutoModelForImageTextToText.from_pretrained(
                model_id,
                **vlm_options.get_model_kwargs()
            )
        else:
            # Fallback to basic loading
            processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True, use_fast=False)
            model = AutoModelForImageTextToText.from_pretrained(
                model_id,
                device_map="auto",
                torch_dtype="auto",
                trust_remote_code=True,
            )
        
        print(f"✅ Model loaded successfully")
        return model, processor, process_vision_info
    except ImportError as e:
        print(f"❌ Error: Required libraries not found: {e}")
        print("   Install with: pip install transformers qwen-vl-utils")
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
    return re.sub(EMBEDDED_IMAGE_PATTERN, '[IMAGE]', md_content)


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
    modified_content = re.sub(EMBEDDED_IMAGE_PATTERN, replace_image, md_content)
    
    return modified_content, image_files


def _is_h2_heading(line_text: str) -> bool:
    """Return True for level-2 markdown headings, excluding deeper levels."""
    return line_text.startswith('##') and not line_text.startswith('###')


def _flush_h2_heading_buffer(buffer: list[str], output: list[str]) -> None:
    """Flush buffered consecutive H2 headings into output with coalescing."""
    if not buffer:
        return
    if len(buffer) == 1:
        output.append(buffer[0])
        return
    combined = buffer[0] + ' / ' + ' / '.join(h.lstrip('#').strip() for h in buffer[1:])
    output.append(combined)


def _next_non_empty_line_is_h2(all_lines: list[str], current_index: int) -> bool:
    """Look ahead up to 3 lines and check whether the next non-empty line is an H2."""
    for j in range(current_index + 1, min(current_index + 4, len(all_lines))):
        next_stripped = all_lines[j].strip()
        if not next_stripped:
            continue
        return _is_h2_heading(next_stripped)
    return False


def _coalesce_consecutive_headings(md_content: str) -> str:
    """
    Coalesce multiple consecutive headings without intervening text.
    If multiple ## headings appear within 3 lines of each other with no prose,
    combine them into a single heading or reflow as a paragraph.
    """
    lines = md_content.split('\n')
    result: list[str] = []
    heading_buffer: list[str] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if _is_h2_heading(stripped):
            heading_buffer.append(stripped)
            continue

        if stripped:
            _flush_h2_heading_buffer(heading_buffer, result)
            heading_buffer = []
            result.append(line)
            continue

        if heading_buffer and not _next_non_empty_line_is_h2(lines, i):
            _flush_h2_heading_buffer(heading_buffer, result)
            heading_buffer = []
        result.append(line)

    _flush_h2_heading_buffer(heading_buffer, result)
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


def _decode_embedded_image(data_uri: str) -> tuple[str, bytes]:
    """Decode a data URI into image format and raw bytes."""
    header, data = data_uri.split(',', 1)
    img_format = header.split('/')[1].split(';')[0]
    return img_format, base64.b64decode(data)


def _build_qwen_image_messages(image: Image.Image) -> list[dict[str, Any]]:
    """Build Qwen chat messages payload for image description."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "image": image,
                },
                {
                    "type": "text",
                    "text": "Describe this image in detail with ONE complete sentence. Prioritize accuracy and completeness. Include the main subject, key details, and context. Be specific and technical.",
                },
            ],
        }
    ]


def _normalize_description_sentence(description: str) -> str:
    """Keep only the first sentence and ensure trailing punctuation."""
    sentences = re.split(r'[.!?]\s+', description)
    if sentences:
        description = sentences[0].strip()
        if description and description[-1] not in '.!?':
            description += '.'
    return description


def _generate_description_from_temp_image(
    *,
    image_data: bytes,
    img_format: str,
    model: Any,
    processor: Any,
    process_vision_info: Any,
    vlm_options: 'VLMOptions' = None,
) -> str:
    """Generate one image description using a temporary image file."""
    with tempfile.NamedTemporaryFile(suffix=f".{img_format}", delete=False) as tmp:
        tmp.write(image_data)
        tmp_path = tmp.name

    try:
        image = Image.open(tmp_path)
        messages = _build_qwen_image_messages(image)

        text = processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        inputs = inputs.to(model.device)

        gen_kwargs = {'max_new_tokens': 120}
        if vlm_options:
            gen_kwargs = vlm_options.get_generation_kwargs()
            gen_kwargs['max_new_tokens'] = 120

        with torch.no_grad():
            generated_ids = model.generate(**inputs, **gen_kwargs)

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
        return _normalize_description_sentence(description)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _replace_with_placeholder_description(match: re.Match[str], image_counter: list[int]) -> str:
    """Replace one embedded image with a placeholder figure description."""
    alt_text = match.group(1)
    image_counter[0] += 1
    description = alt_text.strip() if alt_text and alt_text.strip() else f"Image {image_counter[0]}"
    return f"\n**[Figure {image_counter[0]}: {description}]**\n"


def _replace_with_qwen_image_description(
    match: re.Match[str],
    *,
    image_counter: list[int],
    hash_to_description: dict[str, str],
    model: Any,
    processor: Any,
    process_vision_info: Any,
    vlm_options: 'VLMOptions' = None,
) -> str:
    """Replace one embedded image with a generated Qwen figure description."""
    alt_text = match.group(1)
    data_uri = match.group(2)

    if not data_uri.startswith('data:image/'):
        return match.group(0)

    image_counter[0] += 1
    image_num = image_counter[0]

    try:
        img_format, image_data = _decode_embedded_image(data_uri)
        image_hash = hashlib.sha256(image_data).hexdigest()

        if image_hash in hash_to_description:
            description = hash_to_description[image_hash]
            print(f"   ↻ Image {image_num}: Duplicate detected, reusing description")
            return f"\n**[Figure {image_num}: {description}]**\n"

        description = _generate_description_from_temp_image(
            image_data=image_data,
            img_format=img_format,
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            vlm_options=vlm_options,
        )
        hash_to_description[image_hash] = description

        print(f"   ✓ Image {image_num}: {description[:60]}...")
        return f"\n**[Figure {image_num}: {description}]**\n"
    except Exception as e:
        print(f"   ⚠️  Image {image_num}: Failed to describe ({str(e)[:50]})")
        description = alt_text.strip() if alt_text and alt_text.strip() else f"Image {image_num}"
        return f"\n**[Figure {image_num}: {description}]**\n"


def _generate_image_descriptions(
    md_content: str,
    _docling_url: str = DEFAULT_DOCLING_URL,
    vlm_options: 'VLMOptions' = None,
    starting_figure_number: int = 1,
) -> str:
    """
    Replace embedded images with AI-generated descriptions using the configured vision model.
    Keeps markdown clean and text-only with no external image files.
    Uses byte-level hashing to detect and skip duplicate images.
    
    Args:
        md_content: Markdown content with embedded images
        docling_url: Base URL of Docling service (unused, here for compatibility)
        vlm_options: VLM configuration options
    
    Returns:
        Modified markdown with descriptions instead of images
    """
    global _qwen_model, _qwen_processor, _process_vision_info

    if _qwen_model is None or _qwen_processor is None or _process_vision_info is None:
        _qwen_model, _qwen_processor, _process_vision_info = _load_qwen_model(vlm_options)

    model, processor, process_vision_info = _qwen_model, _qwen_processor, _process_vision_info
    if model is None or processor is None:
        print("⚠️  Qwen model not available, using placeholder descriptions")
        image_counter = [0]
        return re.sub(
            EMBEDDED_IMAGE_PATTERN,
            lambda match: _replace_with_placeholder_description(match, image_counter),
            md_content,
        )
    
    image_counter = [max(0, starting_figure_number - 1)]
    hash_to_description = {}  # Map image hash to description
    
    # Replace all embedded images with descriptions
    return re.sub(
        EMBEDDED_IMAGE_PATTERN,
        lambda match: _replace_with_qwen_image_description(
            match,
            image_counter=image_counter,
            hash_to_description=hash_to_description,
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            vlm_options=vlm_options,
        ),
        md_content,
    )


def _resolve_docling_image_mode(image_mode: str):
    """Resolve Docling image export mode for local page conversion."""
    if image_mode == "placeholder":
        return ImageRefMode.PLACEHOLDER
    return ImageRefMode.EMBEDDED


def _resolve_accelerator_device(accelerator_device_enum: Any):
    """Resolve the preferred Docling accelerator device from environment."""
    preferred_device = str(os.getenv("DOCLING_ACCELERATOR_DEVICE", "cuda")).strip().lower()
    device_name_map = {
        "cpu": "CPU",
        "mps": "MPS",
        "auto": "AUTO",
    }
    requested_name = device_name_map.get(preferred_device, "CUDA")
    accelerator_device = getattr(accelerator_device_enum, requested_name, None)
    if accelerator_device is None:
        accelerator_device = getattr(accelerator_device_enum, "AUTO", None)
    return accelerator_device


def _configure_page_export_pipeline_options(
    *,
    pdf_pipeline_options_cls: Any,
    accelerator_device_enum: Any,
    accelerator_options_cls: Any,
) -> Any:
    """Build pipeline options for page-scoped markdown export."""
    pipeline_options = pdf_pipeline_options_cls()
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_page_images = False
    pipeline_options.do_picture_description = False
    pipeline_options.enable_remote_services = False

    accelerator_device = _resolve_accelerator_device(accelerator_device_enum)
    if accelerator_device is not None:
        pipeline_options.accelerator_options = accelerator_options_cls(device=accelerator_device)

    ocr_options = getattr(pipeline_options, "ocr_options", None)
    if ocr_options is not None and hasattr(ocr_options, "use_gpu"):
        setattr(
            ocr_options,
            "use_gpu",
            accelerator_device == getattr(accelerator_device_enum, "CUDA", None),
        )
    if hasattr(pipeline_options, "min_picture_page_surface_ratio"):
        pipeline_options.min_picture_page_surface_ratio = 0
    return pipeline_options


def _post_process_page_markdown(
    *,
    page_markdown: str,
    page_no: int,
    image_mode: str,
    pdf_path: str,
    vlm_options: 'VLMOptions' = None,
    figure_number: int,
) -> tuple[str, int]:
    """Apply image-mode-specific and structural post-processing to page markdown."""
    next_figure_number = figure_number

    if image_mode == "placeholder":
        page_markdown = _convert_embedded_to_placeholders(page_markdown)
    elif image_mode == "referenced":
        page_markdown, _ = _extract_referenced_images(page_markdown, f"{pdf_path}.page_{page_no}.md")
    elif image_mode == "descriptions":
        embedded_images = len(re.findall(EMBEDDED_IMAGE_PATTERN, page_markdown))
        page_markdown = _generate_image_descriptions(
            page_markdown,
            vlm_options=vlm_options,
            starting_figure_number=figure_number,
        )
        next_figure_number += embedded_images

    page_markdown = _normalize_table_cells(page_markdown)
    page_markdown = _coalesce_consecutive_headings(page_markdown)
    return page_markdown.strip(), next_figure_number


def export_page_markdown_map(
    pdf_path: str,
    image_mode: str = DEFAULT_IMAGE_MODE,
    vlm_options: 'VLMOptions' = None,
) -> dict[int, str]:
    """Export exact page-scoped markdown directly from Docling provenance.

    This is used for manual page review so each review unit contains only the
    markdown generated from its source PDF page, rather than a heuristic slice
    from the full-document markdown.
    """
    try:
        from docling.document_converter import DocumentConverter
        from docling.document_converter import PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    except ImportError:
        logger.warning("Local Docling package unavailable; cannot export page-scoped markdown")
        return {}

    if ImageRefMode is None:
        logger.warning("Local Docling image modes unavailable; cannot export page-scoped markdown")
        return {}

    docling_image_mode = _resolve_docling_image_mode(image_mode)

    page_markdown_map: dict[int, str] = {}
    figure_number = 1
    pipeline_options = _configure_page_export_pipeline_options(
        pdf_pipeline_options_cls=PdfPipelineOptions,
        accelerator_device_enum=AcceleratorDevice,
        accelerator_options_cls=AcceleratorOptions,
    )

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            )
        }
    )

    try:
        import pdfplumber
    except ImportError:
        logger.warning("pdfplumber unavailable; cannot determine page count for page-scoped markdown export")
        return {}

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    for page_no in range(1, total_pages + 1):
        page_document = converter.convert(pdf_path, page_range=(page_no, page_no)).document
        page_markdown = page_document.export_to_markdown(
            image_mode=docling_image_mode,
        )

        page_markdown, figure_number = _post_process_page_markdown(
            page_markdown=page_markdown,
            page_no=page_no,
            image_mode=image_mode,
            pdf_path=pdf_path,
            vlm_options=vlm_options,
            figure_number=figure_number,
        )
        page_markdown_map[int(page_no)] = page_markdown

    return page_markdown_map


def _build_conversion_options(image_mode: str) -> dict[str, Any]:
    """Build Docling conversion options aligned to the requested image strategy."""
    image_export_mode = "embedded" if image_mode in {"embedded", "referenced", "descriptions"} else "placeholder"
    return {
        "to_formats": ["md"],
        "do_ocr": True,
        "pdf_backend": "dlparse_v4",
        "table_mode": "accurate",
        "do_table_structure": True,
        "do_formula_enrichment": False,
        "do_picture_description": False,
        "do_code_enrichment": False,
        "do_picture_classification": False,
        "abort_on_error": True,
        "image_export_mode": image_export_mode,
        "include_images": image_export_mode == "embedded",
        "images_scale": 1.0,
    }


def _convert_markdown_for_selected_image_mode(
    *,
    md_content: str,
    image_mode: str,
    output_path: str,
    docling_url: str,
    vlm_options: 'VLMOptions' = None,
) -> str:
    """Apply requested image-mode post-processing to converted markdown."""
    if image_mode == "placeholder":
        print("\n🔄 Converting embedded images to placeholders...")
        return _convert_embedded_to_placeholders(md_content)
    if image_mode == "referenced":
        print("\n🔄 Converting embedded images to referenced format...")
        converted_content, image_refs = _extract_referenced_images(md_content, output_path)
        if image_refs:
            print(f"   Extracted {len(image_refs)} images to separate files")
        return converted_content
    if image_mode == "descriptions":
        print("\n🔄 Generating AI descriptions for images...")
        return _generate_image_descriptions(md_content, docling_url, vlm_options)
    return md_content


def _finalize_markdown_output(md_content: str, output_path: str) -> None:
    """Run structural normalization and save the markdown output."""
    print("\n🔧 Applying structural post-processing...")
    print("   ✓ Normalizing table cells and chemical formulas")
    md_content = _normalize_table_cells(md_content)
    print("   ✓ Coalescing consecutive headings")
    md_content = _coalesce_consecutive_headings(md_content)

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(md_content, encoding="utf-8")

    print("\n✅ Conversion complete!")
    print(f"📝 Output: {output_file.resolve()}")
    print(f"📊 File size: {len(md_content):,} bytes ({len(md_content.split(chr(10)))} lines)")


def _get_pdf_page_count(pdf_path: str) -> int:
    """Return the total page count for a PDF."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise RuntimeError("pdfplumber is required to process Docling page chunks") from exc

    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def _append_docling_form_value(form_data: list[tuple[str, str]], key: str, value: Any) -> None:
    """Append one normalized Docling multipart field."""
    if isinstance(value, bool):
        form_data.append((key, "true" if value else "false"))
        return

    if isinstance(value, (list, tuple)):
        for item in value:
            form_data.append((key, str(item)))
        return

    form_data.append((key, str(value)))


def _build_docling_form_data(options: dict, page_range: Optional[tuple[int, int]] = None) -> list[tuple[str, str]]:
    """Build multipart form fields for Docling Serve endpoints."""
    form_data: list[tuple[str, str]] = []

    for key, value in options.items():
        if value is None:
            continue
        _append_docling_form_value(form_data, key, value)

    if page_range is not None:
        form_data.append(("page_range", str(page_range[0])))
        form_data.append(("page_range", str(page_range[1])))

    return form_data


def _emit_error(message: str, *, include_error_label: bool = True) -> None:
    """Emit a conversion error to both stderr and stdout."""
    rendered = f"❌ Error: {message}" if include_error_label else f"❌ {message}"
    print(rendered, file=sys.stderr)
    print(rendered)


def _exit_with_error(
    message: str,
    *,
    include_error_label: bool = True,
    hints: Optional[list[str]] = None,
) -> None:
    """Emit a conversion error and terminate with non-zero status."""
    _emit_error(message, include_error_label=include_error_label)
    for hint in hints or []:
        print(f"   {hint}")
    sys.exit(1)


def _get_docling_page_ranges(total_pages: int, pages_per_chunk: int) -> list[tuple[int, int]]:
    """Build sequential inclusive page ranges for chunked conversion."""
    return [
        (start, min(start + pages_per_chunk - 1, total_pages))
        for start in range(1, total_pages + 1, pages_per_chunk)
    ]


def _convert_docling_page_range_chunk(
    *,
    pdf_path: str,
    docling_url: str,
    options: dict,
    page_range: tuple[int, int],
    connect_timeout: int,
    read_timeout: int,
) -> dict:
    """Convert one page-range chunk synchronously via Docling."""
    with open(pdf_path, "rb") as pdf_handle:
        response = requests.post(
            f"{docling_url}{DOCLING_CONVERT_ENDPOINT}",
            files={"files": (Path(pdf_path).name, pdf_handle, "application/pdf")},
            data=_build_docling_form_data(options, page_range=page_range),
            timeout=(connect_timeout, read_timeout),
        )
    response.raise_for_status()
    return response.json()


def _merge_docling_chunk_payloads(chunk_results: list[dict], page_ranges: list[tuple[int, int]]) -> dict:
    """Merge chunk payloads into one Docling-compatible markdown result."""
    md_chunks: list[str] = []
    total_processing_time = 0.0
    aggregated_errors: list = []

    for chunk_payload in chunk_results:
        if chunk_payload.get("status") != "success":
            raise RuntimeError(f"Docling chunk conversion failed: {chunk_payload}")

        document = chunk_payload.get("document", {}) or {}
        md_content = str(document.get("md_content") or "").strip()
        if not md_content:
            raise RuntimeError(f"Docling chunk returned no markdown content: {chunk_payload}")
        md_chunks.append(md_content)

        try:
            total_processing_time += float(chunk_payload.get("processing_time") or 0.0)
        except (TypeError, ValueError):
            pass

        chunk_errors = chunk_payload.get("errors") or []
        if isinstance(chunk_errors, list):
            aggregated_errors.extend(chunk_errors)

    merged_markdown = "\n\n".join(chunk.strip() for chunk in md_chunks if chunk.strip())
    return {
        "status": "success",
        "processing_time": total_processing_time,
        "errors": aggregated_errors,
        "document": {
            "md_content": merged_markdown,
            "pages": [{"page_range": [start, end]} for start, end in page_ranges],
            "elements": [],
        },
    }


def _convert_pdf_with_docling_sync_chunks(
    *,
    pdf_path: str,
    docling_url: str,
    options: dict,
    pages_per_chunk: int,
    connect_timeout: int,
    read_timeout: int,
) -> dict:
    """Convert a PDF using bounded synchronous page-range chunks.

    This avoids the original hang caused by requesting one massive full-document
    response body, while also avoiding the unstable async queue path in the
    current Docling server version.
    """
    total_pages = _get_pdf_page_count(pdf_path)
    page_ranges = _get_docling_page_ranges(total_pages, pages_per_chunk)

    print(
        f"📚 Large PDF detected ({total_pages} pages). "
        f"Using Docling sequential chunking with {len(page_ranges)} chunk(s) of up to {pages_per_chunk} pages."
    )

    chunk_results: list[dict] = []
    for index, page_range in enumerate(page_ranges, start=1):
        print(f"   ⏳ Converting chunk {index}/{len(page_ranges)} (pages {page_range[0]}-{page_range[1]})...")
        chunk_payload = _convert_docling_page_range_chunk(
            pdf_path=pdf_path,
            docling_url=docling_url,
            options=options,
            page_range=page_range,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        chunk_results.append(chunk_payload)
    return _merge_docling_chunk_payloads(chunk_results, page_ranges)


def _run_docling_chunked_conversion(
    *,
    pdf_file: Path,
    docling_url: str,
    options: dict,
    pages_per_chunk: int,
    connect_timeout: int,
    read_timeout: int,
) -> dict:
    """Execute chunked Docling conversion with normalized error handling."""
    try:
        return _convert_pdf_with_docling_sync_chunks(
            pdf_path=str(pdf_file),
            docling_url=docling_url,
            options=options,
            pages_per_chunk=pages_per_chunk,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        _exit_with_error(
            f"Cannot connect to Docling at {docling_url}: {exc}",
            hints=["Make sure docling-serve is running: docker ps | grep docling-serve"],
        )
    except requests.exceptions.Timeout as exc:
        _exit_with_error(
            f"Timeout converting PDF with chunked processing: {exc}",
            hints=["This may indicate the Docling service is overloaded or stuck."],
        )
    except requests.exceptions.ChunkedEncodingError as exc:
        _exit_with_error(
            f"Docling response was incomplete or corrupted: {exc}",
            hints=["This may indicate a network issue or Docling service problem."],
        )
    except Exception as exc:
        _exit_with_error(f"Error during PDF conversion: {type(exc).__name__}: {exc}")


def _extract_markdown_or_exit(result: dict) -> str:
    """Extract markdown content from Docling response or terminate with error."""
    if result.get("status") != "success":
        _exit_with_error(
            f"Docling conversion failed: {result.get('errors', 'Unknown error')}",
            include_error_label=False,
        )

    document = result.get("document", {})
    md_content = document.get("md_content", "")
    if not md_content:
        _exit_with_error("No markdown content in Docling response")
    return str(md_content)


def convert_pdf_with_qwen(
    pdf_path: str,
    output_path: str,
    image_mode: str = DEFAULT_IMAGE_MODE,
    docling_url: str = DEFAULT_DOCLING_URL,
    vlm_options: 'VLMOptions' = None
):
    """
    Convert PDF to Markdown using Docling with the configured vision model
    
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
        active_model_id = vlm_options.model_id if vlm_options else get_vision_model_id()
        print(f"🎯 Using VLM: {active_model_id}")
        print(f"🖼️  Image mode: {image_mode}")
        print(f"🔗 Docling API: {docling_url}{DOCLING_CONVERT_ENDPOINT}")
        print("\n⏳ Converting PDF (this may take a few minutes for first run)...")

        if image_mode == "descriptions" and not DOCLING_AVAILABLE_LOCALLY:
            logger.info(
                "Local Docling serializer extras are unavailable, but description mode will proceed via the Docling service and Qwen image description generation."
            )
        
        pages_per_chunk = int(os.getenv("DOCLING_CHUNK_PAGES", str(DEFAULT_DOCLING_CHUNK_PAGES)))
        connect_timeout = int(
            os.getenv("DOCLING_CONNECT_TIMEOUT_SECONDS", str(DEFAULT_DOCLING_CONNECT_TIMEOUT_SECONDS))
        )
        read_timeout = int(os.getenv("DOCLING_CHUNK_READ_TIMEOUT_SECONDS", str(DEFAULT_DOCLING_CHUNK_READ_TIMEOUT_SECONDS)))
        options = _build_conversion_options(image_mode)

        # Use bounded synchronous page-range chunks so large PDFs do not hang on a
        # single giant response body.
        result = _run_docling_chunked_conversion(
            pdf_file=pdf_file,
            docling_url=docling_url,
            options=options,
            pages_per_chunk=pages_per_chunk,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )
        md_content = _extract_markdown_or_exit(result)

        document = result.get("document", {})
        
        # Instrumentation: Log document structure for debugging
        print(f"\n📊 Document structure:")
        print(f"   Pages: {len(document.get('pages', []))}")
        print(f"   Elements: {len(document.get('elements', []))}")
        print(f"   Raw MD size: {len(md_content):,} bytes")
        
        md_content = _convert_markdown_for_selected_image_mode(
            md_content=md_content,
            image_mode=image_mode,
            output_path=output_path,
            docling_url=docling_url,
            vlm_options=vlm_options,
        )
        _finalize_markdown_output(md_content, output_path)

def main():
    parser = argparse.ArgumentParser(
        description="Convert PDF to Markdown with the configured vision-language model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 docling_convert_with_qwen.py input.pdf output.md
  python3 docling_convert_with_qwen.py input.pdf output.md --image-mode descriptions
  python3 docling_convert_with_qwen.py input.pdf output.md --image-mode referenced
        """
    )
    
    parser.add_argument("pdf", help="Input PDF file path")
    parser.add_argument(
        "output",
        nargs="?",
        default=DEFAULT_OUTPUT_FILENAME,
        help=f"Output Markdown file path (default: {DEFAULT_OUTPUT_FILENAME})",
    )
    parser.add_argument(
        "--image-mode",
        choices=["placeholder", "embedded", "referenced", "descriptions"],
        default=DEFAULT_IMAGE_MODE,
        help=f"Image handling mode (default: {DEFAULT_IMAGE_MODE})"
    )
    parser.add_argument(
        "--docling-url",
        default=DEFAULT_DOCLING_URL,
        help=f"Docling service URL (default: {DEFAULT_DOCLING_URL})"
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
            vlm_options.model_id = get_vision_model_id()
            vlm_options.max_new_tokens = 120  # Short image descriptions
    
    # If only one positional arg provided, use default output name
    if args.output == DEFAULT_OUTPUT_FILENAME and len(sys.argv) == 2:
        args.output = DEFAULT_OUTPUT_FILENAME
    
    convert_pdf_with_qwen(
        pdf_path=args.pdf,
        output_path=args.output,
        image_mode=args.image_mode,
        docling_url=args.docling_url,
        vlm_options=vlm_options
    )


if __name__ == "__main__":
    main()

