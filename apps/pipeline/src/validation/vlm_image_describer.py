#!/usr/bin/env python3
"""
VLM Image Description Generator
Uses the shared vision model from repo-root .env to generate descriptions for missing images in markdown
"""

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any
import pdfplumber
import re

# Import new VLM infrastructure
from ..utils.vlm_options import VLMOptions, ensure_gpu1_runtime, get_vision_model_id
from ..utils.vlm_response_parser import parse_vlm_response, ImageDescription
from ..utils.progress_tracker import ProgressBar, TimeEstimator, PersistentProgressTracker, log_operation

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)  # NOSONAR: Standard logger initialization


def _is_local_model_path(model_id: str) -> bool:
    """Return True when the configured model id should be resolved as a filesystem path."""
    return model_id.startswith(("/", "./", "../", "~"))


def _missing_dependency_error(package_name: str, original_error: ImportError) -> ImportError:
    """Build actionable dependency errors for missing VLM runtime packages."""
    return ImportError(
        "VLM image description dependency is missing: "
        f"{package_name}. Install pipeline dependencies (including qwen-vl-utils) "
        "in the active runtime environment before re-running this stage. "
        f"Original error: {original_error}"
    )


def _validate_model_reference(vlm_options: VLMOptions) -> None:
    """Validate model reference before attempting to load large VLM resources."""
    model_id = vlm_options.model_id
    if _is_local_model_path(model_id):
        resolved_path = Path(model_id).expanduser()
        if not resolved_path.exists():
            raise RuntimeError(
                "Configured VISION_MODEL_ID points to a local path that does not exist: "
                f"{resolved_path}. "
                "Set VISION_MODEL_ID to an available local model directory or a reachable "
                "Hugging Face model id."
            )


def _build_image_description_prompt(expected_count: int | None = None) -> str:
    count_instruction = ""
    if expected_count and expected_count > 0:
        count_instruction = (
            f"\n\nDetected image count for this page: {expected_count}. "
            f"Return exactly {expected_count} description object(s), one per detected image."
        )

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

If there are NO visual elements (only text), return: []''' + count_instruction


def _build_image_description_retry_prompt(expected_count: int | None = None) -> str:
    """Stricter retry prompt used when initial response is malformed but non-empty."""
    count_instruction = ""
    if expected_count and expected_count > 0:
        count_instruction = f"\n- Return exactly {expected_count} items."

    return '''Return ONLY valid JSON.

Required format:
[
  {"title": "Figure X: [Title]", "description": "[Detailed description]"}
]

Rules:
- Output must be a JSON array.
- Each array item must be an object with exactly keys: title, description.
- Do not include markdown fences, comments, or trailing text.
- If no images/figures are present, return [].''' + count_instruction


def _build_image_description_missing_items_prompt(
    *,
    expected_count: int,
    already_generated_count: int,
    missing_count: int,
) -> str:
    """Prompt for one focused retry when generated descriptions are under expected count."""
    return f'''Return ONLY valid JSON.

Detected image count for this page: {expected_count}
Already generated descriptions: {already_generated_count}
Missing descriptions needed now: {missing_count}

Return exactly {missing_count} NEW description object(s) for the remaining visual elements not yet described.

Required format:
[
  {{"title": "Figure X: [Title]", "description": "[Detailed description]"}}
]

Rules:
- Output must be a JSON array.
- Each array item must be an object with exactly keys: title, description.
- Do not repeat or paraphrase already-generated items.
- Do not include markdown fences, comments, or trailing text.
- If you cannot determine remaining visuals, still return best-effort placeholders with clear titles/descriptions for the missing items.'''


def _build_placeholder_descriptions(
    *,
    page_num: int,
    expected_count: int,
    generated_count: int,
    missing_count: int,
) -> List[Dict[str, str]]:
    """Create deterministic placeholder descriptions for uncovered image slots."""
    placeholders: List[Dict[str, str]] = []
    for offset in range(missing_count):
        figure_index = generated_count + offset + 1
        placeholders.append(
            {
                "title": f"Figure {figure_index}: Placeholder description (page {page_num})",
                "description": (
                    "Placeholder generated because the vision model returned fewer "
                    f"descriptions than detected images on this page. "
                    f"Expected {expected_count}, generated {generated_count}. "
                    "Manual reviewer follow-up recommended."
                ),
            }
        )
    return placeholders


def _merge_descriptions_dedup(
    existing: List[Dict[str, str]],
    incoming: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Merge description lists while preserving order and skipping obvious duplicates."""
    merged: List[Dict[str, str]] = list(existing)
    seen_pairs = {
        (str(item.get("title", "")).strip(), str(item.get("description", "")).strip())
        for item in merged
    }
    for item in incoming:
        key = (str(item.get("title", "")).strip(), str(item.get("description", "")).strip())
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        merged.append(item)
    return merged


def _iter_json_array_candidates(response: str) -> List[str]:
    """Yield likely JSON-array substrings in parse-priority order."""
    candidates: List[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        cleaned = candidate.strip()
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        candidates.append(cleaned)

    stripped = response.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
        _append(stripped)

    for block in re.findall(r"```(?:json)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE):
        if "[" in block and "]" in block:
            _append(block)

    # Balanced bracket scan for inline arrays
    for start_idx, char in enumerate(response):
        if char != "[":
            continue
        depth = 0
        for end_idx in range(start_idx, len(response)):
            token = response[end_idx]
            if token == "[":
                depth += 1
            elif token == "]":
                depth -= 1
                if depth == 0:
                    _append(response[start_idx:end_idx + 1])
                    break

    return candidates


def _extract_json_array_candidate(response: str) -> list[dict[str, str]]:
    """Parse the first JSON array found in a VLM response."""
    for candidate in _iter_json_array_candidates(response):
        try:
            descriptions = json.loads(candidate)
        except json.JSONDecodeError:
            continue

        if not isinstance(descriptions, list):
            continue

        parsed = []
        for desc in descriptions:
            if isinstance(desc, dict) and "title" in desc and "description" in desc:
                parsed.append(
                    {
                        "title": str(desc.get("title") or "Unknown"),
                        "description": str(desc.get("description") or ""),
                    }
                )
        if parsed:
            return parsed
    return []


def _extract_partial_json_objects(response: str) -> list[dict[str, str]]:
    """Recover descriptions from partially emitted JSON objects."""
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
        except (json.JSONDecodeError, TypeError):
            continue

    # Salvage title/description pairs even when object delimiters are malformed.
    if extracted:
        return extracted

    pair_pattern = re.compile(
        r'"title"\s*:\s*"(?P<title>(?:\\.|[^"\\])*)".*?'
        r'"description"\s*:\s*"(?P<description>(?:\\.|[^"\\])*)"',
        re.DOTALL,
    )

    for match in pair_pattern.finditer(response):
        title_fragment = match.group("title")
        description_fragment = match.group("description")
        try:
            title_text = json.loads(f'"{title_fragment}"')
            description_text = json.loads(f'"{description_fragment}"')
        except json.JSONDecodeError:
            continue

        extracted.append({
            "title": title_text or "Unknown",
            "description": description_text or "",
        })

    return extracted


def _extract_descriptions_from_response(response: str) -> List[Dict[str, str]]:
    if not response or not response.strip():
        return []

    extracted = _extract_json_array_candidate(response)
    if extracted:
        return extracted
    return _extract_partial_json_objects(response)


def _run_vlm_generation(
    *,
    model: Any,
    processor: Any,
    process_vision_info: Any,
    messages: list[dict[str, Any]],
    inference_device: Any,
    torch: Any,
    vlm_options: VLMOptions,
) -> str:
    """Execute one VLM generation pass and return decoded response text."""
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    inputs = inputs.to(inference_device)

    with torch.no_grad():
        output_ids = model.generate(**inputs, **vlm_options.get_generation_kwargs())

    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(inputs.input_ids, output_ids)
    ]
    return processor.batch_decode(
        generated_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]


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


def _append_page_error_log(workspace: Path, page_num: int, error: Exception) -> None:
    error_log = workspace / "image_description_page_errors.log"
    with error_log.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now(timezone.utc).isoformat()} | page={page_num} | {type(error).__name__}: {error}\n")


def _generate_descriptions_for_single_page(
    *,
    page: Any,
    page_num: int,
    pdf_path: str,
    model: Any,
    processor: Any,
    process_vision_info: Any,
    torch: Any,
    gc: Any,
    vlm_options: VLMOptions,
    expected_image_count: int,
) -> List[Dict[str, str]]:
    """Render one PDF page and run VLM inference to extract image descriptions."""
    image_path = f"/tmp/page_{page_num}_temp.png"  # NOSONAR: Safe in containerized env; temporary image storage
    try:
        try:
            im = page.to_image(resolution=vlm_options.image_resolution)
            im.save(image_path)
        except (RuntimeError, OSError, TypeError) as render_err:
            logger.warning(
                f"   [WARN] pdfplumber render failed on page {page_num} ({render_err}), trying fitz fallback..."
            )
            try:
                import fitz
                fitz_doc = fitz.open(pdf_path)
                fitz_page = fitz_doc[page_num - 1]
                pix = fitz_page.get_pixmap(dpi=vlm_options.image_resolution)
                pix.save(image_path)
                fitz_doc.close()
                logger.info(f"   [OK] fitz fallback rendered page {page_num}")
            except ImportError:
                raise RuntimeError(
                    f"pdfplumber render failed (page {page_num}: {render_err}) "
                    "and PyMuPDF (fitz) is not installed. "
                    "Add pymupdf to pipeline requirements to enable the fallback renderer."
                ) from render_err
            except Exception as fitz_err:
                raise RuntimeError(
                    f"Both pdfplumber and fitz rendering failed for page {page_num}. "
                    f"pdfplumber: {render_err}; fitz: {fitz_err}"
                ) from fitz_err

        gc.collect()
        torch.cuda.empty_cache()

        prompt = _build_image_description_prompt(expected_image_count)
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": f"file://{image_path}"},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        inference_device = next(model.parameters()).device
        if getattr(inference_device, "type", None) != "cuda":
            raise RuntimeError(
                "Vision model is not running on CUDA. "
                "CPU fallback is disabled for this pipeline path."
            )
        response = _run_vlm_generation(
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            messages=messages,
            inference_device=inference_device,
            torch=torch,
            vlm_options=vlm_options,
        )

        if vlm_options.verbose:
            logger.info(f"   VLM Response: {response[:500]}")

        descriptions = _extract_descriptions_from_response(response)
        if expected_image_count <= 0:
            if descriptions or not response.strip():
                return descriptions
        elif len(descriptions) >= expected_image_count:
            return descriptions[:expected_image_count]

        if not descriptions and response.strip():
            logger.warning("   [WARN] VLM output was malformed JSON; retrying once with stricter format instruction...")
        elif expected_image_count > 0:
            logger.warning(
                "   [WARN] VLM output under expected count on page %s (%s/%s); "
                "retrying once with stricter format instruction...",
                page_num,
                len(descriptions),
                expected_image_count,
            )
        retry_messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": f"file://{image_path}"},
                    {"type": "text", "text": _build_image_description_retry_prompt(expected_image_count)},
                ],
            }
        ]
        retry_response = _run_vlm_generation(
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            messages=retry_messages,
            inference_device=inference_device,
            torch=torch,
            vlm_options=vlm_options,
        )
        if vlm_options.verbose:
            logger.info(f"   VLM Retry Response: {retry_response[:500]}")

        retry_descriptions = _extract_descriptions_from_response(retry_response)
        descriptions = _merge_descriptions_dedup(descriptions, retry_descriptions)

        if expected_image_count > 0 and len(descriptions) < expected_image_count:
            missing_count = expected_image_count - len(descriptions)
            logger.warning(
                "   [WARN] Under-generated descriptions on page %s (%s/%s). "
                "Retrying once for missing items...",
                page_num,
                len(descriptions),
                expected_image_count,
            )
            missing_retry_messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "image": f"file://{image_path}"},
                        {
                            "type": "text",
                            "text": _build_image_description_missing_items_prompt(
                                expected_count=expected_image_count,
                                already_generated_count=len(descriptions),
                                missing_count=missing_count,
                            ),
                        },
                    ],
                }
            ]
            missing_retry_response = _run_vlm_generation(
                model=model,
                processor=processor,
                process_vision_info=process_vision_info,
                messages=missing_retry_messages,
                inference_device=inference_device,
                torch=torch,
                vlm_options=vlm_options,
            )
            if vlm_options.verbose:
                logger.info(f"   VLM Missing-Items Retry Response: {missing_retry_response[:500]}")

            missing_retry_descriptions = _extract_descriptions_from_response(missing_retry_response)
            descriptions = _merge_descriptions_dedup(descriptions, missing_retry_descriptions)

        if expected_image_count > 0 and len(descriptions) < expected_image_count:
            generated_count = len(descriptions)
            missing_count = expected_image_count - generated_count
            logger.warning(
                "   [WARN] Still under expected description count on page %s (%s/%s). "
                "Backfilling %s deterministic placeholder(s).",
                page_num,
                generated_count,
                expected_image_count,
                missing_count,
            )
            descriptions.extend(
                _build_placeholder_descriptions(
                    page_num=page_num,
                    expected_count=expected_image_count,
                    generated_count=generated_count,
                    missing_count=missing_count,
                )
            )

        if expected_image_count > 0:
            return descriptions[:expected_image_count]
        return descriptions
    finally:
        Path(image_path).unlink(missing_ok=True)


def _store_page_result(
    *,
    page_descriptions: Dict[int, List[Dict[str, str]]],
    page_num: int,
    descriptions: List[Dict[str, str]],
) -> None:
    """Store extracted descriptions and emit consistent logging."""
    page_descriptions[page_num] = descriptions
    if descriptions:
        logger.info(f"   [OK] Extracted {len(descriptions)} image descriptions on page {page_num}")
        return
    logger.warning("   [WARNING] Could not extract any valid descriptions")


def _should_skip_page(page_num: int, total_pages: int, progress_tracker: PersistentProgressTracker | None) -> tuple[bool, str | None]:
    """Return skip decision and optional failure reason for a page."""
    if progress_tracker and progress_tracker.is_completed(page_num):
        return True, None
    if page_num > total_pages:
        return True, "Page not found"
    return False, None


def _build_default_description_options(vlm_options: VLMOptions | None) -> VLMOptions:
    """Return initialized VLM options for image description generation."""
    if vlm_options is not None:
        return vlm_options

    default_options = VLMOptions.get_default("quality")
    default_options.model_id = get_vision_model_id()
    default_options.max_new_tokens = 2048
    default_options.verbose = True
    return default_options


def _log_pages_with_images(pages_with_images: Dict[int, int], vlm_options: VLMOptions) -> None:
    """Emit standard startup logging for image description generation."""
    logger.info(f"[INFO] Generating image descriptions with {vlm_options.model_id}...")
    logger.info(f"   Processing {len(pages_with_images)} pages with images")


def _load_vlm_generation_resources(vlm_options: VLMOptions) -> tuple[Any, Any, Any, Any, Any]:
    """Load multimodal model resources for page image description generation."""
    _validate_model_reference(vlm_options)

    try:
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as e:
        logger.error(f"[ERROR] Required transformers library not available: {e}")
        raise _missing_dependency_error("transformers", e) from e

    try:
        from qwen_vl_utils import process_vision_info
    except ImportError as e:
        logger.error(f"[ERROR] Required qwen_vl_utils library not available: {e}")
        raise _missing_dependency_error("qwen-vl-utils", e) from e

    try:
        import torch
        import gc
    except ImportError as e:
        logger.error(f"[ERROR] Required torch library not available: {e}")
        raise _missing_dependency_error("torch", e) from e

    gc.collect()
    required_cuda_index = ensure_gpu1_runtime(torch)
    required_cuda_device = torch.device(f"cuda:{required_cuda_index}")
    torch.cuda.empty_cache()

    try:
        processor = AutoProcessor.from_pretrained(
            vlm_options.model_id,
            **vlm_options.get_processor_kwargs()
        )
        model = AutoModelForImageTextToText.from_pretrained(
            vlm_options.model_id,
            **vlm_options.get_model_kwargs()
        )
        first_param = next(model.parameters())
        if getattr(first_param.device, "type", None) != "cuda" or first_param.device.index != required_cuda_index:
            raise RuntimeError(
                "Vision model device mismatch. "
                f"Expected cuda:{required_cuda_index}, got {first_param.device}. "
                "CPU fallback is disabled."
            )
        model = model.to(required_cuda_device)
    except Exception as e:
        raise RuntimeError(
            "Failed to initialize vision model resources for image description stage. "
            f"Model id: {vlm_options.model_id}. "
            "If running in an air-gapped/offline environment, pre-download the model and "
            "set VISION_MODEL_ID to that local directory. "
            f"Original error: {e}"
        ) from e

    return model, processor, process_vision_info, torch, gc


def _process_pages_with_progress(
    *,
    pdf: Any,
    pdf_path: str,
    pages_to_process: List[tuple[int, int]],
    total_pages: int,
    model: Any,
    processor: Any,
    process_vision_info: Any,
    torch: Any,
    gc: Any,
    vlm_options: VLMOptions,
    progress_tracker: PersistentProgressTracker | None,
    page_descriptions: Dict[int, List[Dict[str, str]]],
    workspace: Path | None,
) -> None:
    """Process target pages with progress reporting and ETA updates."""
    estimator = TimeEstimator(total_items=len(pages_to_process))

    with ProgressBar(pages_to_process, desc="Image descriptions", unit="page") as pbar:
        for page_num, expected_image_count in pbar:
            if estimator.completed > 0:
                logger.info(f"[INFO] Processing page {page_num} | ETA: {estimator.get_eta()}")

            should_advance = _process_target_page(
                page_item=(page_num, expected_image_count),
                total_pages=total_pages,
                pdf=pdf,
                pdf_path=pdf_path,
                model=model,
                processor=processor,
                process_vision_info=process_vision_info,
                torch=torch,
                gc=gc,
                vlm_options=vlm_options,
                progress_tracker=progress_tracker,
                page_descriptions=page_descriptions,
                workspace=workspace,
            )

            if should_advance:
                estimator.update()


def _cleanup_vlm_generation_resources(model: Any, processor: Any, gc: Any, torch: Any) -> None:
    """Release multimodal generation resources and clear CUDA cache."""
    logger.info("🗑️  Unloading VLM model from GPU...")
    del model
    del processor
    gc.collect()
    torch.cuda.empty_cache()
    logger.info("[OK] Model unloaded")


def _process_target_page(
    *,
    page_item: tuple[int, int],
    total_pages: int,
    pdf: Any,
    pdf_path: str,
    model: Any,
    processor: Any,
    process_vision_info: Any,
    torch: Any,
    gc: Any,
    vlm_options: VLMOptions,
    progress_tracker: PersistentProgressTracker | None,
    page_descriptions: Dict[int, List[Dict[str, str]]],
    workspace: Path | None,
) -> bool:
    """Process one page and return whether ETA/progress should advance."""
    page_num, expected_image_count = page_item
    should_skip, skip_reason = _should_skip_page(page_num, total_pages, progress_tracker)
    if should_skip and skip_reason is None:
        logger.info(f"⏭️  Skipping page {page_num} (already done)")
        return True

    if should_skip and skip_reason is not None:
        logger.warning(f"[WARNING] Page {page_num} not found in PDF")
        if progress_tracker:
            progress_tracker.mark_failed(page_num, skip_reason)
        return False

    try:
        page = pdf.pages[page_num - 1]
        descriptions = _generate_descriptions_for_single_page(
            page=page,
            page_num=page_num,
            pdf_path=pdf_path,
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            torch=torch,
            gc=gc,
            vlm_options=vlm_options,
            expected_image_count=expected_image_count,
        )
        _store_page_result(
            page_descriptions=page_descriptions,
            page_num=page_num,
            descriptions=descriptions,
        )
        coverage_complete = expected_image_count <= 0 or len(descriptions) >= expected_image_count
        if coverage_complete:
            if progress_tracker:
                progress_tracker.mark_completed(page_num)
            return True

        if progress_tracker:
            progress_tracker.mark_failed(
                page_num,
                f"Coverage incomplete: expected >= {expected_image_count} descriptions, got {len(descriptions)}",
            )
        logger.warning(
            "   [WARNING] Coverage incomplete on page %s: expected >= %s descriptions, got %s",
            page_num,
            expected_image_count,
            len(descriptions),
        )
        return False
    except (RuntimeError, OSError, TypeError, json.JSONDecodeError) as e:
        logger.error(f"   [ERROR] Error processing page {page_num}: {e}")
        page_descriptions[page_num] = []
        if progress_tracker:
            progress_tracker.mark_failed(page_num, str(e))
        if workspace:
            _append_page_error_log(workspace, page_num, e)
        return False


def generate_image_descriptions_vlm(
    pdf_path: str,
    pages_with_images: Dict[int, int],
    vlm_options: VLMOptions = None,
    workspace: Path = None,
    resume_progress: bool = False,
) -> Dict[int, List[Dict[str, str]]]:
    """
    Use VLM to generate descriptions for images on specific pages
    
    Args:
        pdf_path: Path to PDF
        pages_with_images: Dict of page_number -> image_count
        vlm_options: VLM configuration (uses default if None)
        workspace: Workspace for persistent progress tracking
        resume_progress: If True, resume from existing progress file; otherwise reset
            progress for a fresh stage run.
        
    Returns:
        Dict mapping page_number -> list of image descriptions
    """
    vlm_options = _build_default_description_options(vlm_options)
    _log_pages_with_images(pages_with_images, vlm_options)
    
    # Setup progress tracking
    doc_name = Path(pdf_path).stem
    if workspace:
        progress_tracker = PersistentProgressTracker(workspace, doc_name)
        if not resume_progress:
            progress_tracker.reset()
        progress_tracker.start_stage("Image Descriptions", total_items=len(pages_with_images))
    else:
        progress_tracker = None

    with log_operation("Load VLM Model", model=vlm_options.model_id):
        try:
            model, processor, process_vision_info, torch, gc = _load_vlm_generation_resources(vlm_options)
        except (ImportError, RuntimeError) as e:
            logger.error(f"[ERROR] Unable to initialize image description VLM resources: {e}")
            return {}
    
    page_descriptions = {}
    
    with pdfplumber.open(pdf_path) as pdf:
        pages_to_process = [
            (page_num, pages_with_images.get(page_num, 0))
            for page_num in sorted(pages_with_images.keys())
        ]
        total_pages = len(pdf.pages)
        _process_pages_with_progress(
            pdf=pdf,
            pdf_path=pdf_path,
            pages_to_process=pages_to_process,
            total_pages=total_pages,
            model=model,
            processor=processor,
            process_vision_info=process_vision_info,
            torch=torch,
            gc=gc,
            vlm_options=vlm_options,
            progress_tracker=progress_tracker,
            page_descriptions=page_descriptions,
            workspace=workspace,
        )
    
    # End progress tracking
    if progress_tracker:
        progress_tracker.end_stage("Image Descriptions")
        logger.info(f"\n{progress_tracker.get_progress_summary()}")
    
    _cleanup_vlm_generation_resources(model, processor, gc, torch)
    
    logger.info(f"[OK] Generated descriptions for {len(page_descriptions)} pages")
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
    logger.info("[INFO] Inserting image descriptions into markdown...")
    
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
                f"{image_section}\n<!-- Page {page_num + 1} -->",
                1,
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
    
    logger.info(f"[OK] Inserted {total_inserted} image descriptions")
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
    logger.info("VLM IMAGE DESCRIPTION GENERATOR")
    logger.info("=" * 80)
    
    # Step 1: Extract pages with image loss
    pages_with_images = extract_images_from_validation(args.validation)
    if not pages_with_images:
        logger.info("[OK] No image loss detected - nothing to do")
        # Copy markdown as-is
        import shutil
        shutil.copy(args.markdown, args.output)
        return 0
    
    logger.info(f"[INFO] Found {len(pages_with_images)} pages with image loss")
    
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
        logger.error("[ERROR] No descriptions generated")
        return 1
    
    # Step 3: Insert descriptions
    total_inserted = insert_image_descriptions(
        args.markdown,
        page_descriptions,
        args.output
    )

    if total_inserted == 0 and pages_with_images:
        logger.error("[ERROR] No image descriptions were inserted")
        return 1
    
    logger.info("=" * 80)
    logger.info(f"[OK] Image description complete: {total_inserted} descriptions added")
    logger.info(f"[INFO] Output: {args.output}")
    logger.info("=" * 80)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
