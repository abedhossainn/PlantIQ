"""Pipeline artifact helpers - pure functions for artifact metadata reading."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..core.config import settings

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


def _utc_iso_from_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _optimized_output_has_usable_content(payload: dict[str, Any]) -> bool:
    chunks = payload.get("chunks")
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


def _resolve_document_work_dir(document_id: str) -> Path | None:
    if not _UUID_RE.match(document_id):
        return None
    work_dir = Path(settings.PIPELINE_WORK_DIR).expanduser().resolve() / document_id
    if not work_dir.exists():
        return None
    return work_dir


def _first_candidate_path(candidates: list[Path]) -> Path | None:
    return candidates[0] if candidates else None


def _read_markdown_content(markdown_path: Path | None) -> str:
    if markdown_path and markdown_path.is_file():
        return markdown_path.read_text(encoding="utf-8").strip()
    return ""


def _read_optimized_json_payload(json_path: Path | None) -> dict[str, Any]:
    if not json_path or not json_path.is_file():
        return {}
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _collect_mtime_sources(paths: tuple[Path | None, ...]) -> list[float]:
    return [path.stat().st_mtime for path in paths if path is not None and path.exists()]


def _read_valid_optimized_artifact_metadata(document_id: str) -> dict[str, Optional[str]] | None:
    work_dir = _resolve_document_work_dir(document_id)
    if work_dir is None:
        return None

    optimized_json_candidates = sorted(work_dir.glob("*_rag_optimized.json"))
    optimized_markdown_candidates = sorted(work_dir.glob("*_rag_optimized.md"))
    optimization_prep_candidates = sorted(work_dir.glob("*_optimization_prep.json"))

    optimized_json_path = _first_candidate_path(optimized_json_candidates)
    optimized_markdown_path = _first_candidate_path(optimized_markdown_candidates)
    optimization_prep_path = _first_candidate_path(optimization_prep_candidates)

    markdown_content = _read_markdown_content(optimized_markdown_path)

    payload = _read_optimized_json_payload(optimized_json_path)

    payload_markdown = payload.get("markdown")
    if isinstance(payload_markdown, str) and payload_markdown.strip():
        markdown_content = payload_markdown.strip()

    if not _optimized_output_has_usable_content(payload) and not markdown_content:
        return None

    completion_sources = _collect_mtime_sources((optimized_json_path, optimized_markdown_path))
    started_sources = _collect_mtime_sources((optimization_prep_path, optimized_json_path, optimized_markdown_path))
    if not completion_sources:
        return None

    return {
        "started_at": _utc_iso_from_timestamp(min(started_sources)) if started_sources else None,
        "completed_at": _utc_iso_from_timestamp(max(completion_sources)),
    }
