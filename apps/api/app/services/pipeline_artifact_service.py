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


def _read_valid_optimized_artifact_metadata(document_id: str) -> dict[str, Optional[str]] | None:
    if not _UUID_RE.match(document_id):
        return None
    work_dir = Path(settings.PIPELINE_WORK_DIR).expanduser().resolve() / document_id
    if not work_dir.exists():
        return None

    optimized_json_candidates = sorted(work_dir.glob("*_rag_optimized.json"))
    optimized_markdown_candidates = sorted(work_dir.glob("*_rag_optimized.md"))
    optimization_prep_candidates = sorted(work_dir.glob("*_optimization_prep.json"))

    optimized_json_path = optimized_json_candidates[0] if optimized_json_candidates else None
    optimized_markdown_path = optimized_markdown_candidates[0] if optimized_markdown_candidates else None
    optimization_prep_path = optimization_prep_candidates[0] if optimization_prep_candidates else None

    markdown_content = ""
    if optimized_markdown_path and optimized_markdown_path.is_file():
        markdown_content = optimized_markdown_path.read_text(encoding="utf-8").strip()

    payload: dict[str, Any] = {}
    if optimized_json_path and optimized_json_path.is_file():
        try:
            payload = json.loads(optimized_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}

        payload_markdown = payload.get("markdown")
        if isinstance(payload_markdown, str) and payload_markdown.strip():
            markdown_content = payload_markdown.strip()

    if not _optimized_output_has_usable_content(payload) and not markdown_content:
        return None

    completion_sources = [
        path.stat().st_mtime
        for path in (optimized_json_path, optimized_markdown_path)
        if path is not None and path.exists()
    ]
    started_sources = [
        path.stat().st_mtime
        for path in (optimization_prep_path, optimized_json_path, optimized_markdown_path)
        if path is not None and path.exists()
    ]
    if not completion_sources:
        return None

    return {
        "started_at": _utc_iso_from_timestamp(min(started_sources)) if started_sources else None,
        "completed_at": _utc_iso_from_timestamp(max(completion_sources)),
    }
