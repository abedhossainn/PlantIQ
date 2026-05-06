"""
Optimized chunk helpers: extraction, coercion, serialization, and rebuild from markdown.

Handles everything related to the *_rag_optimized.json / *_rag_optimized.md
artifacts produced by Stage 10.
"""
import json
import re
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from ._filesystem import _find_optimized_artifact_paths, _load_optional_json
from ._review import _extract_page_heading, _strip_embedded_html_comments


_OPTIONAL_CHUNK_PASSTHROUGH_KEYS = (
    "chunk_type",
    "sheet_name",
    "row_refs",
    "entity_refs",
    "relation_refs",
    "source_lineage",
    "retrieval_hints",
    "path_ref",
    "parent_path_ref",
    "node_type",
    "value_type",
    "value_state",
    "path_depth",
)


# ---------------------------------------------------------------------------
# Page number extraction from chunk content
# ---------------------------------------------------------------------------

def _extract_page_numbers_from_chunk(chunk: dict, content: str) -> list[int]:
    source_pages = chunk.get("source_pages")
    if isinstance(source_pages, list):
        normalized_pages: list[int] = []
        for page_number in source_pages:
            if isinstance(page_number, int) and page_number not in normalized_pages:
                normalized_pages.append(page_number)
        if normalized_pages:
            return normalized_pages

    return [
        page_number
        for page_number in dict.fromkeys(
            int(match)
            for match in re.findall(r"Page\s+(\d+)", content or "", flags=re.IGNORECASE)
        )
    ]


# ---------------------------------------------------------------------------
# Text preview
# ---------------------------------------------------------------------------

def _preview_text(content: str, *, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", _strip_embedded_html_comments(content or "")).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------
# Chunk coercion
# ---------------------------------------------------------------------------

def _optimized_chunk_id(chunk: dict, index: int) -> str:
    explicit_id = str(chunk.get("chunk_id") or chunk.get("id") or "").strip()
    if explicit_id:
        return explicit_id
    return f"chunk_{index:03d}"


def _extract_chunk_markdown_content(chunk: dict) -> str:
    return str(
        chunk.get("content") or chunk.get("markdown") or chunk.get("body") or chunk.get("text") or ""
    ).strip()


def _extract_chunk_heading(chunk: dict, index: int) -> str:
    return str(
        chunk.get("heading")
        or chunk.get("title")
        or chunk.get("question")
        or f"Chunk {index}"
    ).strip()


def _extract_non_empty_string_list(values: list[object]) -> list[str]:
    return [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]


def _build_ce_id_label_map(ce_payload: dict | None) -> dict[str, str]:
    if not isinstance(ce_payload, dict):
        return {}

    mapping: dict[str, str] = {}

    for cause in ce_payload.get("causes") or []:
        if not isinstance(cause, dict):
            continue
        cause_id = str(cause.get("cause_id") or "").strip()
        if not cause_id:
            continue
        cause_tag = str(cause.get("cause_tag") or "").strip()
        cause_description = str(cause.get("cause_description") or "").strip()
        replacement = cause_tag or cause_description
        if replacement:
            mapping[cause_id] = replacement

    for effect in ce_payload.get("effects") or []:
        if not isinstance(effect, dict):
            continue
        effect_id = str(effect.get("effect_id") or "").strip()
        if not effect_id:
            continue
        required_fields = effect.get("required_fields") if isinstance(effect.get("required_fields"), dict) else {}
        effect_label = str(effect.get("effect_label") or "").strip()
        effect_description = str(required_fields.get("description") or "").strip()
        replacement = effect_label or effect_description
        if replacement:
            mapping[effect_id] = replacement

    return mapping


def _load_ce_id_label_map(
    *,
    work_dir: Path,
    document_name: str,
    optimized_payload: dict,
) -> dict[str, str]:
    embedded_ce = optimized_payload.get("ce_relations")
    embedded_map = _build_ce_id_label_map(embedded_ce if isinstance(embedded_ce, dict) else None)
    if embedded_map:
        return embedded_map

    ce_candidates = [
        work_dir / f"{document_name}_ce_relations.json",
        work_dir / "ce_relations.json",
    ]
    for candidate in ce_candidates:
        if not candidate.exists() or not candidate.is_file():
            continue
        ce_payload = _load_optional_json(candidate)
        ce_map = _build_ce_id_label_map(ce_payload)
        if ce_map:
            return ce_map

    return {}


def _apply_ce_id_substitutions(text: str, id_label_map: dict[str, str] | None) -> str:
    if not text or not id_label_map:
        return text

    substituted = text
    for token in sorted(id_label_map.keys(), key=len, reverse=True):
        replacement = str(id_label_map.get(token) or "").strip()
        if not replacement:
            continue
        substituted = re.sub(rf"\b{re.escape(token)}\b", replacement, substituted)
    return substituted


def _coerce_optimized_chunk(chunk: dict, index: int, id_label_map: dict[str, str] | None = None) -> dict:
    content = _extract_chunk_markdown_content(chunk)
    heading = _extract_chunk_heading(chunk, index)
    content = _apply_ce_id_substitutions(content, id_label_map)
    heading = _apply_ce_id_substitutions(heading, id_label_map)
    table_facts = _extract_non_empty_string_list(chunk.get("table_facts") or chunk.get("facts") or [])
    ambiguity_flags = _extract_non_empty_string_list(chunk.get("ambiguity_flags") or chunk.get("ambiguities") or [])

    normalized_chunk = {
        "id": _optimized_chunk_id(chunk, index),
        "heading": heading,
        "markdown_content": content,
        "source_pages": _extract_page_numbers_from_chunk(chunk, content),
        "table_facts": table_facts,
        "ambiguity_flags": ambiguity_flags,
    }

    for key in _OPTIONAL_CHUNK_PASSTHROUGH_KEYS:
        if key in chunk:
            normalized_chunk[key] = chunk.get(key)

    return normalized_chunk


def _copy_optional_chunk_fields(chunk: dict) -> dict:
    """Copy additive optional chunk metadata fields for persistence."""
    copied: dict = {}
    for key in _OPTIONAL_CHUNK_PASSTHROUGH_KEYS:
        if key in chunk:
            copied[key] = chunk.get(key)
    return copied


# ---------------------------------------------------------------------------
# Optimized artifact loading
# ---------------------------------------------------------------------------

def _has_usable_optimized_chunks(optimized_payload: dict) -> bool:
    chunks = optimized_payload.get("chunks")
    if not isinstance(chunks, list):
        return False

    for chunk in chunks:
        if isinstance(chunk, str) and chunk.strip():
            return True
        if not isinstance(chunk, dict):
            continue
        for key in ("content", "markdown", "body", "text"):
            if str(chunk.get(key) or "").strip():
                return True
    return False


def _extract_optimized_markdown(optimized_payload: dict, optimized_markdown_path: Optional[Path]) -> str:
    payload_markdown = optimized_payload.get("markdown")
    if isinstance(payload_markdown, str) and payload_markdown.strip():
        return payload_markdown.strip()

    if optimized_markdown_path and optimized_markdown_path.exists() and optimized_markdown_path.is_file():
        markdown_content = optimized_markdown_path.read_text(encoding="utf-8").strip()
        if markdown_content:
            return markdown_content

    return ""


def _load_validated_optimized_output(work_dir: Path) -> tuple[dict, str]:
    optimized_json_path, optimized_markdown_path = _find_optimized_artifact_paths(work_dir)
    optimized_payload = _load_optional_json(optimized_json_path)
    markdown_content = _extract_optimized_markdown(optimized_payload, optimized_markdown_path)

    if not _has_usable_optimized_chunks(optimized_payload) and not markdown_content:
        raise ValueError(
            "Optimization output is incomplete; rerun optimization before QA or finalization"
        )

    return optimized_payload, markdown_content


# ---------------------------------------------------------------------------
# Markdown section splitting
# ---------------------------------------------------------------------------

def _split_markdown_into_sections(markdown_content: str) -> list[dict]:
    stripped_content = markdown_content.strip()
    if not stripped_content:
        return []

    heading_matches = list(re.finditer(r"^##\s+(.+)$", stripped_content, flags=re.MULTILINE))
    if not heading_matches:
        first_heading = _extract_page_heading(stripped_content, 1)
        return [{"heading": first_heading, "content": stripped_content, "has_tables": "|" in stripped_content}]

    sections: list[dict] = []
    for index, match in enumerate(heading_matches):
        start = match.start()
        end = heading_matches[index + 1].start() if index + 1 < len(heading_matches) else len(stripped_content)
        section_content = stripped_content[start:end].strip()
        sections.append(
            {
                "heading": match.group(1).strip(),
                "content": section_content,
                "has_tables": "|" in section_content,
            }
        )
    return sections


def _iter_dict_chunks(raw_chunks: list[object]) -> list[dict]:
    """Return only dictionary chunk entries from a mixed chunk list."""
    return [chunk for chunk in raw_chunks if isinstance(chunk, dict)]


def _build_chunk_from_markdown_section(section: dict, index: int) -> dict | None:
    """Build normalized editable chunk from a markdown section payload."""
    content = str(section.get("content") or "").strip()
    if not content:
        return None

    return {
        "id": f"chunk_{index:03d}",
        "heading": str(section.get("heading") or f"Chunk {index}").strip(),
        "markdown_content": content,
        "source_pages": _extract_page_numbers_from_chunk({}, content),
        "table_facts": [],
        "ambiguity_flags": [],
    }


def _append_chunks_from_markdown_sections(
    *,
    chunks: list[dict],
    markdown_content: str,
) -> None:
    """Append fallback chunks derived from markdown sections when needed."""
    for index, section in enumerate(_split_markdown_into_sections(markdown_content), start=1):
        section_chunk = _build_chunk_from_markdown_section(section, index)
        if section_chunk is not None:
            chunks.append(section_chunk)


# ---------------------------------------------------------------------------
# Editable chunk building and persistence
# ---------------------------------------------------------------------------

def _build_markdown_from_optimized_chunks(document_name: str, chunks: list[dict]) -> str:
    sections: list[str] = [f"# {document_name}"]
    for chunk in chunks:
        content = str(chunk.get("markdown_content") or chunk.get("content") or "").strip()
        if content:
            sections.append(content)
    return "\n\n".join(section for section in sections if section.strip()).strip() + "\n"


def _build_editable_optimized_chunks(
    work_dir: Path,
) -> tuple[dict, str, list[dict], Optional[Path], Optional[Path]]:
    optimized_json_path, optimized_markdown_path = _find_optimized_artifact_paths(work_dir)
    optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)
    document_name = str(optimized_payload.get("document_name") or work_dir.name).strip() or work_dir.name
    id_label_map = _load_ce_id_label_map(
        work_dir=work_dir,
        document_name=document_name,
        optimized_payload=optimized_payload,
    )

    editable_chunks: list[dict] = []
    raw_chunks = optimized_payload.get("chunks") or []
    if isinstance(raw_chunks, list) and raw_chunks:
        for index, raw_chunk in enumerate(_iter_dict_chunks(raw_chunks), start=1):
            editable_chunks.append(_coerce_optimized_chunk(raw_chunk, index, id_label_map=id_label_map))

    if not editable_chunks and markdown_content:
        _append_chunks_from_markdown_sections(
            chunks=editable_chunks,
            markdown_content=markdown_content,
        )

    if not editable_chunks:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Optimization output is incomplete; rerun optimization before editing",
        )

    return optimized_payload, document_name, editable_chunks, optimized_json_path, optimized_markdown_path


def _save_optimized_chunks(
    *,
    optimized_payload: dict,
    document_name: str,
    editable_chunks: list[dict],
    optimized_json_path: Optional[Path],
    optimized_markdown_path: Optional[Path],
    work_dir: Path,
) -> None:
    json_path = optimized_json_path or (work_dir / f"{document_name}_rag_optimized.json")
    markdown_path = optimized_markdown_path or (work_dir / f"{document_name}_rag_optimized.md")

    persisted_chunks = []
    for chunk in editable_chunks:
        persisted_chunk = {
            "heading": chunk["heading"],
            "content": chunk["markdown_content"],
            "source_pages": chunk.get("source_pages") or [],
            "table_facts": chunk.get("table_facts") or [],
            "ambiguity_flags": chunk.get("ambiguity_flags") or [],
        }
        persisted_chunk.update(_copy_optional_chunk_fields(chunk))
        persisted_chunks.append(persisted_chunk)

    optimized_payload = dict(optimized_payload or {})
    optimized_payload["document_name"] = document_name
    optimized_payload["chunks"] = persisted_chunks
    optimized_payload["markdown"] = _build_markdown_from_optimized_chunks(document_name, persisted_chunks)

    json_path.write_text(json.dumps(optimized_payload, indent=2), encoding="utf-8")
    markdown_path.write_text(str(optimized_payload["markdown"]), encoding="utf-8")


# ---------------------------------------------------------------------------
# Publishable chunk assembly
# ---------------------------------------------------------------------------

def _build_publishable_chunks(work_dir: Path) -> list[dict]:
    optimized_payload, markdown_content = _load_validated_optimized_output(work_dir)
    document_name = str(optimized_payload.get("document_name") or work_dir.name).strip() or work_dir.name
    id_label_map = _load_ce_id_label_map(
        work_dir=work_dir,
        document_name=document_name,
        optimized_payload=optimized_payload,
    )

    publishable_chunks: list[dict] = []
    raw_chunks = optimized_payload.get("chunks") or []
    if isinstance(raw_chunks, list) and raw_chunks:
        for index, raw_chunk in enumerate(_iter_dict_chunks(raw_chunks), start=1):
            normalized_chunk = _coerce_optimized_chunk(raw_chunk, index, id_label_map=id_label_map)
            if normalized_chunk["markdown_content"]:
                publishable_chunks.append(normalized_chunk)

    if not publishable_chunks and markdown_content:
        _append_chunks_from_markdown_sections(
            chunks=publishable_chunks,
            markdown_content=markdown_content,
        )

    if not publishable_chunks:
        raise ValueError("Optimization output is incomplete; nothing is available to publish")

    return publishable_chunks
