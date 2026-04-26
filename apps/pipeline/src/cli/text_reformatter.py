#!/usr/bin/env python3
"""
Step 2c: RAG Text Reformatter
Use the shared text model from repo-root .env to reformat markdown to RAG-optimized format
Uses validation report from VLM comparison
"""

import json
import re
import time
from pathlib import Path
import logging
import queue
from threading import Thread
from typing import Any, Iterable

# Import VLM infrastructure
from ..utils.vlm_options import (
    VLMOptions,
    get_generation_timeout_seconds,
    get_text_model_id,
    resolve_model_reference,
)
from ..utils.vlm_response_parser import extract_json_from_text, lax_json_parse
from ..utils.progress_tracker import log_operation

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_DEFAULT_SEGMENT_ID = "segment_001"


DEFAULT_REFORMATTER_PROMPT = """You are a precise document optimization assistant for RAG ingestion.

Transform the reviewed markdown into retrieval-friendly chunks while preserving fidelity to the reviewed source.

Rules:
- Treat the reviewed markdown and optimization prep as the only source of truth.
- Do not invent facts, page numbers, tables, or figure details.
- Prefer concise, factual chunk content with clear question-style headings when possible.
- Preserve ambiguity explicitly when the source is uncertain.
- Preserve citations and source page numbers.
- Return valid JSON only. No prose, no explanations, no code fences.

Return this exact top-level structure:
{
  "document_name": "string",
  "input_contract": {
    "primary_source": "optimization_prep",
    "document_name": "string"
  },
  "chunks": [
    {
      "heading": "string",
      "content": "markdown string with source citations",
      "source_pages": [1],
      "table_facts": ["optional fact"],
      "ambiguity_flags": ["optional ambiguity note"]
    }
  ],
  "markdown": "full optimized markdown document"
}
"""


def load_reformatter_prompt(prompt_path: Path | None = None) -> str:
    """Load the RAG markdown reformatter system prompt"""
    prompt_path = prompt_path or (Path(__file__).parent / "rag_markdown_reformatter_prompt.md")
    
    if not prompt_path.exists():
        logger.info(f"Using built-in reformatter prompt fallback because file is missing: {prompt_path}")
        return DEFAULT_REFORMATTER_PROMPT
    
    prompt = prompt_path.read_text(encoding='utf-8').strip()
    if not prompt:
        logger.info(f"Using built-in reformatter prompt fallback because file is empty: {prompt_path}")
        return DEFAULT_REFORMATTER_PROMPT
    return prompt


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, indent=2, ensure_ascii=False)
    return str(value).strip()


def _heading_to_question(heading: str, fallback_page: int | None = None) -> str:
    cleaned = re.sub(r"\s+", " ", heading).strip(" #:-\t\n")
    if not cleaned:
        return f"What is covered on page {fallback_page}?" if fallback_page else "What should you know from this section?"
    if cleaned.endswith("?"):
        return cleaned
    if re.fullmatch(r"Page\s+\d+", cleaned, flags=re.IGNORECASE):
        return f"What is covered on {cleaned.lower()}?"
    return f"What does this section explain about {cleaned}?"


def _extract_page_numbers(text: str) -> list[int]:
    page_numbers = [int(match) for match in re.findall(r"Page\s+(\d+)", text or "", flags=re.IGNORECASE)]
    seen: set[int] = set()
    ordered: list[int] = []
    for page_number in page_numbers:
        if page_number not in seen:
            seen.add(page_number)
            ordered.append(page_number)
    return ordered


def _strip_html_comments(markdown_content: str) -> str:
    return re.sub(r"<!--.*?-->", "", markdown_content or "", flags=re.DOTALL).strip()


def _ensure_citation(content: str, document_name: str, page_numbers: Iterable[int]) -> str:
    cleaned = content.strip()
    if "[Source:" in cleaned:
        return cleaned

    valid_pages = [page for page in page_numbers if isinstance(page, int)]
    if not valid_pages:
        return cleaned

    citation_lines = [f"[Source: {document_name}, Page {page}]" for page in valid_pages]
    citation_block = "\n".join(citation_lines)
    return f"{cleaned}\n\n{citation_block}" if cleaned else citation_block


def _build_markdown_from_chunks(document_name: str, chunks: list[dict[str, Any]]) -> str:
    sections: list[str] = [f"# {document_name}"]
    for chunk in chunks:
        content = _stringify(chunk.get("content") or chunk.get("markdown"))
        if content:
            sections.append(content)
    return "\n\n".join(section for section in sections if section.strip()).strip() + "\n"


def _format_elapsed_seconds(started_at: float) -> str:
    return f"{time.monotonic() - started_at:.1f}s"


def _log_generation_progress(*, token_count: int, max_new_tokens: int, started_at: float) -> None:
    percent = min(99, int((token_count / max_new_tokens) * 100)) if max_new_tokens else 0
    elapsed_seconds = int(time.monotonic() - started_at)
    minutes, seconds = divmod(elapsed_seconds, 60)
    logger.info(
        "Generation progress: %s%% (%s/%s tokens, %02d:%02d elapsed)",
        percent,
        token_count,
        max_new_tokens,
        minutes,
        seconds,
    )


def _describe_generation_exception(exc: Exception) -> str:
    detail = str(exc).strip()
    if detail:
        return detail
    return type(exc).__name__


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _dedupe_ints(values: Iterable[Any]) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for value in values:
        if not isinstance(value, int):
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _extract_pages_from_candidates(candidates: Any) -> list[int]:
    """Extract integer page numbers from a list or a single integer candidate."""
    if isinstance(candidates, list):
        return [page for page in candidates if isinstance(page, int)]
    if isinstance(candidates, int):
        return [candidates]
    return []


def _extract_citation_page_numbers(citations: Any) -> list[int]:
    """Extract integer page numbers from a citations list of dicts."""
    if not isinstance(citations, list):
        return []
    return [
        citation.get("page_number")
        for citation in citations
        if isinstance(citation, dict) and isinstance(citation.get("page_number"), int)
    ]


def _collect_source_pages_from_chunk(chunk: dict[str, Any], content: str) -> list[int]:
    """Collect and de-duplicate source pages from chunk fields and citations."""
    source_page_candidates = chunk.get("source_pages") or chunk.get("page_numbers") or chunk.get("pages")
    source_pages = _extract_pages_from_candidates(source_page_candidates)
    source_pages.extend(_extract_citation_page_numbers(chunk.get("citations")))
    source_pages.extend(_extract_page_numbers(content))
    return _dedupe_ints(source_pages)


def _resolve_chunk_content_from_optimization_prep(
    *,
    content: str,
    source_pages: list[int],
    optimization_prep: dict | None,
) -> str:
    """Fallback to matching optimization-prep page markdown when content is empty."""
    if content or not optimization_prep:
        return content

    matching_page = next(
        (
            page for page in optimization_prep.get("pages", [])
            if isinstance(page, dict)
            and any(page.get("page_number") == page_number for page_number in source_pages)
        ),
        None,
    )
    if isinstance(matching_page, dict):
        return _strip_html_comments(_stringify(matching_page.get("authoritative_markdown")))
    return content


def _select_raw_chunks(payload: dict[str, Any]) -> list[Any]:
    """Return first available non-empty chunk-like collection from payload."""
    for key in ("chunks", "sections", "items"):
        candidate = payload.get(key)
        if isinstance(candidate, list) and candidate:
            return candidate
    return []


def _build_response_parse_candidates(response: str) -> list[dict[str, Any] | None]:
    """Build ordered parse candidates from strict, lax and repaired JSON extraction."""
    candidates: list[dict[str, Any] | None] = [
        extract_json_from_text(response),
        lax_json_parse(response),
        _parse_first_json_object(response),
    ]

    json_block_match = re.search(r"```(?:json)?\s*(\{.*)$", response, flags=re.DOTALL)
    if json_block_match:
        repaired_candidate = _repair_partial_json(json_block_match.group(1))
        try:
            candidates.append(json.loads(repaired_candidate))
        except json.JSONDecodeError:
            pass

    return candidates


def _get_optimization_pages(optimization_prep: dict | None) -> list[dict[str, Any]]:
    if not optimization_prep:
        return []

    pages = optimization_prep.get("pages")
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _build_segmented_generation_segments(optimization_prep: dict | None) -> list[dict[str, Any]]:
    if not optimization_prep:
        return []

    segments = optimization_prep.get("segments")
    if not isinstance(segments, list) or not segments:
        return []
    return [segment for segment in segments if isinstance(segment, dict)]


def _collect_page_string_field(pages: list[dict[str, Any]], field_name: str) -> list[str]:
    return _dedupe_strings(
        item
        for page in pages
        for item in (page.get(field_name) or [])
    )


def _collect_page_citations(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        citation
        for page in pages
        for citation in (page.get("citations") or [])
        if isinstance(citation, dict)
    ]


def _build_full_document_generation_segment(
    markdown_content: str,
    pages: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "segment_id": _DEFAULT_SEGMENT_ID,
        "title": "Full Document",
        "page_numbers": [
            int(page.get("page_number"))
            for page in pages
            if isinstance(page.get("page_number"), int)
        ],
        "heading_candidates": _collect_page_string_field(pages, "heading_candidates"),
        "table_facts": _collect_page_string_field(pages, "table_facts"),
        "ambiguity_flags": _collect_page_string_field(pages, "ambiguity_flags"),
        "citations": _collect_page_citations(pages),
        "pages": pages,
        "authoritative_markdown": markdown_content,
    }


def _build_fallback_generation_segment(markdown_content: str) -> dict[str, Any]:
    return {
        "segment_id": _DEFAULT_SEGMENT_ID,
        "title": "Full Document",
        "page_numbers": _extract_page_numbers(markdown_content),
        "heading_candidates": [],
        "table_facts": [],
        "ambiguity_flags": [],
        "citations": [],
        "pages": [],
        "authoritative_markdown": markdown_content,
    }


def _build_generation_segments(markdown_content: str, optimization_prep: dict | None) -> list[dict[str, Any]]:
    segments = _build_segmented_generation_segments(optimization_prep)
    if segments:
        return segments

    pages = _get_optimization_pages(optimization_prep)
    if pages:
        return [_build_full_document_generation_segment(markdown_content, pages)]

    return [_build_fallback_generation_segment(markdown_content)]


def _build_page_outline_entry(page: dict[str, Any]) -> dict[str, Any]:
    """Build one page outline entry for segment prompt context."""
    return {
        "page_number": page.get("page_number"),
        "heading_candidates": page.get("heading_candidates") or [],
        "text_preview": _stringify(page.get("text_preview"))[:500],
        "table_facts": page.get("table_facts") or [],
        "ambiguity_flags": page.get("ambiguity_flags") or [],
        "citations": page.get("citations") or [],
    }


def _extract_segment_pages(segment: dict[str, Any]) -> list[dict[str, Any]]:
    pages = segment.get("pages") or []
    if not isinstance(pages, list):
        return []
    return [page for page in pages if isinstance(page, dict)]


def _build_segment_prompt_context(segment: dict[str, Any], doc_name: str) -> dict[str, Any]:
    segment_pages = _extract_segment_pages(segment)
    page_outline = [_build_page_outline_entry(page) for page in segment_pages]

    return {
        "document_name": doc_name,
        "segment_id": segment.get("segment_id") or _DEFAULT_SEGMENT_ID,
        "segment_title": segment.get("title") or "Document Segment",
        "page_numbers": segment.get("page_numbers") or [],
        "heading_candidates": segment.get("heading_candidates") or [],
        "table_facts": segment.get("table_facts") or [],
        "ambiguity_flags": segment.get("ambiguity_flags") or [],
        "citations": segment.get("citations") or [],
        "page_outline": page_outline,
    }


def _build_reformatter_messages(
    *,
    doc_name: str,
    system_prompt: str,
    segment: dict[str, Any],
    validation_payload: str,
    total_segments: int,
    segment_index: int,
) -> list[dict[str, str]]:
    segment_title = str(segment.get("title") or f"Segment {segment_index}")
    segment_markdown = str(segment.get("authoritative_markdown") or "")
    segment_context = json.dumps(_build_segment_prompt_context(segment, doc_name), indent=2, ensure_ascii=False)

    user_message = f"""Apply RAG optimization guidelines to this markdown segment.

DOCUMENT: {doc_name}
SEGMENT: {segment_index}/{total_segments} - {segment_title}
SEGMENT MARKDOWN SIZE: {len(segment_markdown)} characters
SEGMENT CONTEXT:

{segment_context}

AUTHORITATIVE REVIEWED MARKDOWN FOR THIS SEGMENT:

{segment_markdown}

DOCUMENT VALIDATION SUMMARY:
{validation_payload}

TASK:
0. Use the segment context as the primary source of provenance, page mapping, reviewer notes, table facts, and ambiguity flags.
1. Reformat headings as retrieval-friendly questions where appropriate.
2. Create RAG-optimized chunks for THIS SEGMENT ONLY.
3. Preserve exact source-page citations and uncertainty markers.
4. Do not invent facts from pages outside this segment.
5. Output valid JSON only.

Provide valid JSON output only."""

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def _collect_streamed_generation_output(
    *,
    streamer: Any,
    tokenizer: Any,
    max_new_tokens: int,
    generation_started_at: float,
) -> tuple[str, int]:
    """Collect streamed generation text and periodically log progress."""
    response_chunks: list[str] = []
    generated_token_count = 0
    last_progress_log_at = generation_started_at

    for text_chunk in streamer:
        if not text_chunk:
            continue

        response_chunks.append(text_chunk)
        generated_token_count += len(tokenizer.encode(text_chunk, add_special_tokens=False))

        now = time.monotonic()
        if now - last_progress_log_at >= 5:
            _log_generation_progress(
                token_count=generated_token_count,
                max_new_tokens=max_new_tokens,
                started_at=generation_started_at,
            )
            last_progress_log_at = now

    return "".join(response_chunks), generated_token_count


def _generate_segment_response(
    *,
    tokenizer: Any,
    model: Any,
    torch: Any,
    messages: list[dict[str, str]],
    vlm_options: VLMOptions,
    segment_label: str,
) -> str:
    from transformers import TextIteratorStreamer

    model_inputs = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
        return_tensors="pt",
        return_dict=True,
    ).to(model.device)
    prompt_token_count = int(model_inputs["input_ids"].shape[-1])

    logger.info(
        "Generating output for %s (%s prompt tokens, %s max tokens)...",
        segment_label,
        prompt_token_count,
        vlm_options.max_new_tokens,
    )

    gen_kwargs = vlm_options.get_generation_kwargs()
    gen_kwargs["use_cache"] = True
    if not gen_kwargs.get("do_sample", True):
        gen_kwargs.pop("temperature", None)
        gen_kwargs.pop("top_p", None)

    streamer = TextIteratorStreamer(
        tokenizer,
        skip_prompt=True,
        skip_special_tokens=True,
        timeout=vlm_options.generation_timeout_seconds,
    )
    gen_kwargs["streamer"] = streamer

    generation_error: dict[str, Exception] = {}

    def _run_generate() -> None:
        try:
            with torch.no_grad():
                model.generate(**model_inputs, **gen_kwargs)
        except Exception as exc:
            generation_error["error"] = exc

    generation_started_at = time.monotonic()
    generation_thread = Thread(target=_run_generate, daemon=True)
    generation_thread.start()

    response_text, generated_token_count = _collect_streamed_generation_output(
        streamer=streamer,
        tokenizer=tokenizer,
        max_new_tokens=vlm_options.max_new_tokens,
        generation_started_at=generation_started_at,
    )

    generation_thread.join()
    if "error" in generation_error:
        raise generation_error["error"]

    logger.info(
        "Generation complete for %s (%s tokens in %s)",
        segment_label,
        generated_token_count,
        _format_elapsed_seconds(generation_started_at),
    )
    return response_text


def _merge_segment_payloads(
    payloads: list[dict[str, Any]],
    *,
    markdown_content: str,
    doc_name: str,
    optimization_prep: dict | None,
) -> dict[str, Any]:
    merged_chunks: list[dict[str, Any]] = []
    for payload in payloads:
        merged_chunks.extend(payload.get("chunks") or [])

    return normalize_reformatter_payload(
        {
            "document_name": doc_name,
            "input_contract": {
                "primary_source": "optimization_prep" if optimization_prep is not None else "markdown",
                "document_name": doc_name,
                "segmented_generation": len(payloads) > 1,
            },
            "chunks": merged_chunks,
            "markdown": _build_markdown_from_chunks(doc_name, merged_chunks),
            "validation_summary": (optimization_prep or {}).get("validation_summary"),
        },
        markdown_content=markdown_content,
        doc_name=doc_name,
        optimization_prep=optimization_prep,
    )


def _safe_cleanup_model_resources(model: Any, tokenizer: Any, torch_module: Any, gc_module: Any) -> None:
    logger.info("Unloading model resources...")
    try:
        if model is not None:
            del model
        if tokenizer is not None:
            del tokenizer
    finally:
        if gc_module is not None:
            gc_module.collect()
        if torch_module is not None and getattr(torch_module, "cuda", None) is not None:
            try:
                torch_module.cuda.empty_cache()
            except Exception:
                pass
        logger.info("Model resources released")


def _get_cuda_free_memory_gib(torch_module: Any) -> float | None:
    try:
        if torch_module is None or not torch_module.cuda.is_available():
            return None
        free_bytes, _total_bytes = torch_module.cuda.mem_get_info()
        return free_bytes / (1024 ** 3)
    except Exception:
        return None


def _get_page_heading_source(page: dict[str, Any]) -> str:
    heading_candidates = page.get("heading_candidates") or []
    if not isinstance(heading_candidates, list):
        return ""
    return next((str(item).strip() for item in heading_candidates if str(item).strip()), "")


def _get_page_source_pages(page: dict[str, Any], page_number: int | None) -> list[int]:
    source_pages = [page_number] if page_number is not None else []
    citations = page.get("citations") or []
    if isinstance(citations, list):
        source_pages.extend(
            citation.get("page_number")
            for citation in citations
            if isinstance(citation, dict) and isinstance(citation.get("page_number"), int)
        )
    return _dedupe_ints(source_pages)


def _get_page_synthesis_content(page: dict[str, Any]) -> str:
    raw_content = _strip_html_comments(_stringify(page.get("authoritative_markdown")))
    if raw_content:
        return raw_content
    return _stringify(page.get("text_preview"))


def _build_synthesized_chunk_from_page(page: dict[str, Any], doc_name: str) -> dict[str, Any] | None:
    page_number = page.get("page_number") if isinstance(page.get("page_number"), int) else None
    raw_content = _get_page_synthesis_content(page)
    if not raw_content:
        return None

    heading = _heading_to_question(_get_page_heading_source(page), fallback_page=page_number)
    source_pages = _get_page_source_pages(page, page_number)
    return {
        "heading": heading,
        "content": _ensure_citation(raw_content, doc_name, source_pages),
        "source_pages": source_pages,
        "table_facts": page.get("table_facts") or [],
        "ambiguity_flags": page.get("ambiguity_flags") or [],
    }


def _build_fallback_synthesized_chunk(markdown_content: str, doc_name: str) -> dict[str, Any]:
    source_pages = _extract_page_numbers(markdown_content)
    fallback_content = _ensure_citation(_strip_html_comments(markdown_content), doc_name, source_pages)
    return {
        "heading": _heading_to_question(doc_name),
        "content": fallback_content,
        "source_pages": source_pages,
        "table_facts": [],
        "ambiguity_flags": [],
    }


def _synthesize_chunks_from_optimization_prep(
    *,
    markdown_content: str,
    doc_name: str,
    optimization_prep: dict | None,
) -> list[dict[str, Any]]:
    pages = _get_optimization_pages(optimization_prep)
    synthesized_chunks = [
        chunk
        for page in pages
        for chunk in [_build_synthesized_chunk_from_page(page, doc_name)]
        if chunk is not None
    ]
    if synthesized_chunks:
        return synthesized_chunks

    return [_build_fallback_synthesized_chunk(markdown_content, doc_name)]


def _process_repair_char(
    char: str,
    output: list[str],
    stack: list[str],
    in_string: bool,
    escape: bool,
) -> tuple[bool, bool]:
    """Process one character during JSON repair. Returns updated (in_string, escape)."""
    output.append(char)
    if escape:
        return in_string, False
    if char == "\\":
        return in_string, True
    if char == '"':
        return not in_string, False
    if in_string:
        return in_string, False
    if char == '{':
        stack.append('}')
    elif char == '[':
        stack.append(']')
    elif char in {'}', ']'} and stack and char == stack[-1]:
        stack.pop()
    return in_string, False


def _repair_partial_json(candidate: str) -> str:
    text = candidate.strip()
    if not text:
        return text

    output: list[str] = []
    stack: list[str] = []
    in_string = False
    escape = False

    for char in text:
        in_string, escape = _process_repair_char(char, output, stack, in_string, escape)

    repaired = "".join(output).rstrip()
    repaired = re.sub(r",\s*$", "", repaired)
    if in_string:
        repaired += '"'
    while repaired.rstrip().endswith(','):
        repaired = repaired.rstrip()[:-1]
    if stack:
        repaired += "".join(reversed(stack))
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def _parse_first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[{\[]", text):
        candidate = text[match.start():].strip()
        try:
            parsed, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            repaired = _repair_partial_json(candidate)
            try:
                parsed = json.loads(repaired)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _coerce_string_chunk(chunk: str, doc_name: str, fallback_index: int) -> dict[str, Any] | None:
    content = chunk.strip()
    if not content:
        return None

    source_pages = _extract_page_numbers(content)
    return {
        "heading": _heading_to_question(f"Chunk {fallback_index}"),
        "content": _ensure_citation(content, doc_name, source_pages),
        "source_pages": source_pages,
        "table_facts": [],
        "ambiguity_flags": [],
    }


def _get_chunk_heading(chunk: dict[str, Any], fallback_index: int) -> str:
    return _stringify(
        chunk.get("heading")
        or chunk.get("title")
        or chunk.get("question")
        or chunk.get("section_heading")
        or f"Chunk {fallback_index}"
    )


def _get_chunk_content(chunk: dict[str, Any]) -> str:
    return _stringify(chunk.get("content") or chunk.get("markdown") or chunk.get("body") or chunk.get("text"))


def _build_coerced_chunk_payload(
    *,
    heading: str,
    content: str,
    source_pages: list[int],
    chunk: dict[str, Any],
) -> dict[str, Any]:
    return {
        "heading": _heading_to_question(heading, fallback_page=source_pages[0] if source_pages else None),
        "content": content,
        "source_pages": source_pages,
        "table_facts": chunk.get("table_facts") or chunk.get("facts") or [],
        "ambiguity_flags": chunk.get("ambiguity_flags") or chunk.get("ambiguities") or [],
    }


def _coerce_dict_chunk(
    *,
    chunk: dict[str, Any],
    doc_name: str,
    fallback_index: int,
    optimization_prep: dict | None,
) -> dict[str, Any] | None:
    """Coerce one dict chunk into normalized structure."""
    heading = _get_chunk_heading(chunk, fallback_index)
    content = _get_chunk_content(chunk)
    source_pages = _collect_source_pages_from_chunk(chunk, content)
    content = _resolve_chunk_content_from_optimization_prep(
        content=content,
        source_pages=source_pages,
        optimization_prep=optimization_prep,
    )

    content = _ensure_citation(content, doc_name, source_pages)
    if not content:
        return None

    return _build_coerced_chunk_payload(
        heading=heading,
        content=content,
        source_pages=source_pages,
        chunk=chunk,
    )


def _coerce_chunk(chunk: Any, doc_name: str, fallback_index: int, optimization_prep: dict | None) -> dict[str, Any] | None:
    if isinstance(chunk, str):
        return _coerce_string_chunk(chunk, doc_name, fallback_index)

    if not isinstance(chunk, dict):
        return None

    return _coerce_dict_chunk(
        chunk=chunk,
        doc_name=doc_name,
        fallback_index=fallback_index,
        optimization_prep=optimization_prep,
    )


def _resolve_document_name(
    payload: dict[str, Any],
    optimization_prep: dict | None,
    fallback: str,
) -> str:
    """Resolve the canonical document name from payload, optimization_prep, or fallback."""
    return _stringify(
        payload.get("document_name")
        or (optimization_prep or {}).get("document_name")
        or fallback
    )


def _build_input_contract(
    payload: dict[str, Any],
    optimization_prep: dict | None,
    document_name: str,
) -> dict[str, Any]:
    """Build and return the input_contract dict with required defaults."""
    input_contract = payload.get("input_contract") if isinstance(payload.get("input_contract"), dict) else {}
    input_contract.setdefault(
        "primary_source",
        "optimization_prep" if optimization_prep is not None else "markdown",
    )
    input_contract.setdefault("document_name", document_name)
    return input_contract


def normalize_reformatter_payload(
    payload: dict[str, Any] | None,
    *,
    markdown_content: str,
    doc_name: str,
    optimization_prep: dict | None,
) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    document_name = _resolve_document_name(payload, optimization_prep, doc_name)

    raw_chunks = _select_raw_chunks(payload)

    normalized_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(raw_chunks, start=1):
        normalized_chunk = _coerce_chunk(chunk, document_name, index, optimization_prep)
        if normalized_chunk:
            normalized_chunks.append(normalized_chunk)

    if not normalized_chunks:
        normalized_chunks = _synthesize_chunks_from_optimization_prep(
            markdown_content=markdown_content,
            doc_name=document_name,
            optimization_prep=optimization_prep,
        )

    top_level_markdown = _stringify(payload.get("markdown")) or _build_markdown_from_chunks(document_name, normalized_chunks)
    input_contract = _build_input_contract(payload, optimization_prep, document_name)

    normalized_payload = {
        "document_name": document_name,
        "input_contract": input_contract,
        "chunks": normalized_chunks,
        "markdown": top_level_markdown,
    }
    if isinstance(payload.get("validation_summary"), dict):
        normalized_payload["validation_summary"] = payload["validation_summary"]
    return normalized_payload


def parse_reformatter_response(
    response: str,
    *,
    markdown_content: str,
    doc_name: str,
    optimization_prep: dict | None,
) -> dict[str, Any]:
    candidates = _build_response_parse_candidates(response)

    for candidate in candidates:
        if isinstance(candidate, dict):
            normalized = normalize_reformatter_payload(
                candidate,
                markdown_content=markdown_content,
                doc_name=doc_name,
                optimization_prep=optimization_prep,
            )
            if normalized.get("chunks"):
                return normalized

    logger.info("Structured JSON response could not be recovered; using deterministic optimization-prep synthesis")
    return normalize_reformatter_payload(
        {},
        markdown_content=markdown_content,
        doc_name=doc_name,
        optimization_prep=optimization_prep,
    )


def _build_default_reformatter_options(vlm_options: VLMOptions | None) -> VLMOptions:
    """Return initialized text reformatter options."""
    if vlm_options is not None:
        return vlm_options

    default_options = VLMOptions.get_default("quality")
    default_options.model_id = get_text_model_id()
    default_options.max_new_tokens = 8000
    default_options.do_sample = False
    default_options.generation_timeout_seconds = get_generation_timeout_seconds()
    return default_options


def _trim_optimization_prep_payload(optimization_prep: dict | None) -> dict | None:
    """Remove duplicated large markdown fields from optimization prep payloads."""
    if not optimization_prep:
        return None

    import copy as _copy

    trimmed_prep = _copy.deepcopy(optimization_prep)
    trimmed_prep.pop("combined_markdown", None)
    for page in trimmed_prep.get("pages", []):
        if isinstance(page, dict):
            page.pop("authoritative_markdown", None)
    return trimmed_prep


def _trim_validation_payload(validation_report: dict) -> dict:
    """Keep only the lightweight validation summary needed at inference time."""
    if not validation_report:
        return {}
    return {
        key: value
        for key, value in validation_report.items()
        if key not in ("page_validations",)
    }


def _prepare_reformatter_generation_inputs(
    *,
    markdown_content: str,
    validation_report: dict,
    optimization_prep: dict | None,
) -> tuple[dict | None, dict, str, list[dict[str, Any]]]:
    """Prepare trimmed payloads and generation segments for Stage 10."""
    trimmed_prep = _trim_optimization_prep_payload(optimization_prep)
    trimmed_validation = _trim_validation_payload(validation_report)
    validation_payload = json.dumps(trimmed_validation, indent=2) if trimmed_validation else "null"
    generation_segments = _build_generation_segments(markdown_content, optimization_prep)
    return trimmed_prep, trimmed_validation, validation_payload, generation_segments


def _load_reformatter_model_resources(vlm_options: VLMOptions) -> tuple[Any, Any, Any, Any]:
    """Load tokenizer/model resources for generation."""
    from transformers import AutoModelForCausalLM, AutoTokenizer
    import torch
    import gc

    model_source = resolve_model_reference(vlm_options.model_id)
    local_model_only = Path(model_source).expanduser().exists()

    gc.collect()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()

    with log_operation("Load Tokenizer"):
        tokenizer = AutoTokenizer.from_pretrained(
            model_source,
            trust_remote_code=vlm_options.trust_remote_code,
            local_files_only=local_model_only,
        )

    with log_operation("Load Model"):
        model = AutoModelForCausalLM.from_pretrained(
            model_source,
            dtype=torch.float16,
            device_map=vlm_options.device_map,
            trust_remote_code=vlm_options.trust_remote_code,
            local_files_only=local_model_only,
            max_memory={
                0: f"{int(vlm_options.gpu_memory_fraction * 22)}GiB",
                "cpu": "100GiB"
            },
            offload_folder="/tmp/offload"
        )

    return tokenizer, model, torch, gc


def _get_reformatter_fallback_reason(torch_module: Any) -> str | None:
    """Return a fallback reason when free CUDA memory is too low."""
    free_memory_gib = _get_cuda_free_memory_gib(torch_module)
    if free_memory_gib is None or free_memory_gib >= 0.75:
        return None
    return (
        f"Insufficient free GPU memory after model load ({free_memory_gib:.2f} GiB available); "
        "using deterministic optimization-prep synthesis"
    )


def _build_segment_optimization_prep(
    *,
    doc_name: str,
    trimmed_validation: dict,
    segment: dict[str, Any],
) -> dict[str, Any]:
    """Build the minimal optimization-prep payload for one generation segment."""
    return {
        "document_name": doc_name,
        "validation_summary": trimmed_validation,
        "pages": segment.get("pages") or [],
    }


def _generate_segment_payloads(
    *,
    tokenizer: Any,
    model: Any,
    torch_module: Any,
    vlm_options: VLMOptions,
    system_prompt: str,
    doc_name: str,
    validation_payload: str,
    trimmed_validation: dict,
    generation_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate and parse one response payload per optimization segment."""
    total_segments = len(generation_segments)
    logger.info(
        "Stage 10 using %s optimization segment(s) instead of one monolithic prompt",
        total_segments,
    )

    segment_payloads: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(generation_segments, start=1):
        segment_markdown = _stringify(segment.get("authoritative_markdown"))
        segment_label = f"segment {segment_index}/{total_segments}"
        segment_prep = _build_segment_optimization_prep(
            doc_name=doc_name,
            trimmed_validation=trimmed_validation,
            segment=segment,
        )
        messages = _build_reformatter_messages(
            doc_name=doc_name,
            system_prompt=system_prompt,
            segment=segment,
            validation_payload=validation_payload,
            total_segments=total_segments,
            segment_index=segment_index,
        )

        with log_operation("Generate Response", chars=len(segment_markdown), segment=segment_label):
            try:
                response = _generate_segment_response(
                    tokenizer=tokenizer,
                    model=model,
                    torch=torch_module,
                    messages=messages,
                    vlm_options=vlm_options,
                    segment_label=segment_label,
                )
                segment_payloads.append(
                    parse_reformatter_response(
                        response,
                        markdown_content=segment_markdown,
                        doc_name=doc_name,
                        optimization_prep=segment_prep,
                    )
                )
            except Exception as exc:
                error_detail = _describe_generation_exception(exc)
                log_level = logging.ERROR if isinstance(exc, queue.Empty) else logging.INFO
                logger.log(
                    log_level,
                    "Text generation failed for %s; switching to deterministic synthesis (%s: %s)",
                    segment_label,
                    type(exc).__name__,
                    error_detail,
                )
                segment_payloads.append(
                    normalize_reformatter_payload(
                        {},
                        markdown_content=segment_markdown,
                        doc_name=doc_name,
                        optimization_prep=segment_prep,
                    )
                )

    return segment_payloads


def _build_generation_response(
    *,
    tokenizer: Any,
    model: Any,
    torch_module: Any,
    vlm_options: VLMOptions,
    markdown_content: str,
    doc_name: str,
    system_prompt: str,
    validation_payload: str,
    trimmed_validation: dict,
    trimmed_prep: dict | None,
    generation_segments: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Attempt model generation and return either a response or a fallback reason."""
    fallback_reason = _get_reformatter_fallback_reason(torch_module)
    if fallback_reason:
        return None, fallback_reason

    segment_payloads = _generate_segment_payloads(
        tokenizer=tokenizer,
        model=model,
        torch_module=torch_module,
        vlm_options=vlm_options,
        system_prompt=system_prompt,
        doc_name=doc_name,
        validation_payload=validation_payload,
        trimmed_validation=trimmed_validation,
        generation_segments=generation_segments,
    )
    merged_payload = _merge_segment_payloads(
        segment_payloads,
        markdown_content=markdown_content,
        doc_name=doc_name,
        optimization_prep=trimmed_prep,
    )
    return json.dumps(merged_payload), None


def reformat_with_qwen(
    markdown_content: str,
    validation_report: dict,
    _pdf_path: str,
    doc_name: str,
    vlm_options: VLMOptions = None,
    optimization_prep: dict | None = None,
) -> dict:
    """
    Use the configured shared text model to reformat markdown for RAG
    
    Args:
        markdown_content: Markdown content to reformat
        validation_report: Validation feedback from VLM comparison
        pdf_path: Path to source PDF
        doc_name: Document name
        vlm_options: VLM configuration (uses default if None)
        
    Returns:
        Reformatted JSON with chunks
    """
    vlm_options = _build_default_reformatter_options(vlm_options)
    
    try:
        with log_operation("Text Reformatting", model=vlm_options.model_id, doc=doc_name):
            response: str | None = None
            fallback_reason: str | None = None
            model = None
            tokenizer = None
            torch = None
            gc = None

            system_prompt = load_reformatter_prompt()
            trimmed_prep, trimmed_validation, validation_payload, generation_segments = _prepare_reformatter_generation_inputs(
                markdown_content=markdown_content,
                validation_report=validation_report,
                optimization_prep=optimization_prep,
            )

            try:
                tokenizer, model, torch, gc = _load_reformatter_model_resources(vlm_options)
                response, fallback_reason = _build_generation_response(
                    tokenizer=tokenizer,
                    model=model,
                    torch_module=torch,
                    vlm_options=vlm_options,
                    markdown_content=markdown_content,
                    doc_name=doc_name,
                    system_prompt=system_prompt,
                    validation_payload=validation_payload,
                    trimmed_validation=trimmed_validation,
                    trimmed_prep=trimmed_prep,
                    generation_segments=generation_segments,
                )
            except Exception as exc:
                error_detail = _describe_generation_exception(exc)
                logger.error(
                    "Model initialization or generation setup failed; switching to deterministic synthesis (%s: %s)",
                    type(exc).__name__,
                    error_detail,
                )
                fallback_reason = f"Generation unavailable; using deterministic optimization-prep synthesis: {error_detail}"
            finally:
                _safe_cleanup_model_resources(model, tokenizer, torch, gc)
            
            with log_operation("Parse Response"):
                if fallback_reason:
                    logger.info(fallback_reason)
                    result = normalize_reformatter_payload(
                        {},
                        markdown_content=markdown_content,
                        doc_name=doc_name,
                        optimization_prep=optimization_prep,
                    )
                else:
                    result = parse_reformatter_response(
                        response or "",
                        markdown_content=markdown_content,
                        doc_name=doc_name,
                        optimization_prep=trimmed_prep or optimization_prep,
                    )
                logger.info(f"✅ JSON parsed and normalized successfully")
                return result
    
    except Exception as e:
        logger.error(f"❌ Reformatting failed: {e}")
        import traceback
        traceback.print_exc()
        raise


def save_output(reformatted_json: dict, output_path: str):
    """Save RAG-optimized output"""
    output_path = Path(output_path)
    save_started_at = time.monotonic()
    logger.info("Saving optimization artifacts")
    
    # Save JSON
    with open(output_path.with_suffix('.json'), 'w') as f:
        json.dump(reformatted_json, f, indent=2)
    
    # Convert to markdown
    markdown_content = _stringify(reformatted_json.get("markdown"))
    if not markdown_content:
        markdown_content = _build_markdown_from_chunks(
            reformatted_json.get('document_name', 'Document'),
            reformatted_json.get("chunks") or [],
        )
    
    with open(output_path.with_suffix('.md'), 'w') as f:
        f.write(markdown_content)

    logger.info("Optimized artifacts written in %s", _format_elapsed_seconds(save_started_at))


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="RAG text reformatter")
    parser.add_argument("pdf", help="Path to PDF")
    parser.add_argument("--markdown", default="output.md", help="Markdown file")
    parser.add_argument("--validation", default="validation_report.json", help="Validation report")
    parser.add_argument("--optimization-prep", help="Structured optimization prep artifact")
    parser.add_argument("--output", default="output_rag_optimized", help="Output base path")
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
        vlm_options.model_id = get_text_model_id()
        vlm_options.max_new_tokens = 8000
        vlm_options.do_sample = False
    
    logger.info(f"Using VLM configuration: {args.preset if not args.config else args.config}")
    
    logger.info("=" * 80)
    logger.info("✨ Step 2c: RAG Text Reformatter")
    logger.info("=" * 80)
    
    # Load markdown
    logger.info("\n[1/4] Loading markdown...")
    with open(args.markdown, 'r') as f:
        markdown_content = f.read()
    logger.info(f"✅ Loaded {len(markdown_content)} characters")
    
    # Load validation report
    logger.info("\n[2/4] Loading validation report...")
    with open(args.validation, 'r') as f:
        validation_report = json.load(f)
    logger.info("✅ Validation report loaded")

    optimization_prep = None
    if args.optimization_prep:
        with open(args.optimization_prep, 'r', encoding='utf-8') as f:
            optimization_prep = json.load(f)
        logger.info("✅ Optimization prep loaded")
    
    # Reformat with Qwen
    logger.info(f"\n[3/4] Reformatting with {vlm_options.model_id}...")
    result = reformat_with_qwen(
        markdown_content,
        validation_report,
        args.pdf,
        Path(args.pdf).stem,
        vlm_options,
        optimization_prep=optimization_prep,
    )
    
    # Save output
    logger.info("\n[4/4] Saving output...")
    save_output(result, args.output)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ RAG optimization complete!")
    logger.info("=" * 80)
    
    if "validation_summary" in result:
        logger.info(f"Summary: {result['validation_summary']}")


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
