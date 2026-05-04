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

import fcntl
import json
import logging
import sys
import subprocess
import os
import re
from time import perf_counter
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

_VLM_LOCK_PATH = "/tmp/vlm_worker.lock"
_VLM_MIN_FREE_VRAM_BYTES = 9 * 1024 * 1024 * 1024  # 9 GiB — VLM requires ~8.5 GiB
_VLM_GPU_INDEX = 1  # Physical GPU index used by CUDA_VISIBLE_DEVICES=1

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
from ..utils.vlm_options import (
    build_gpu1_constrained_subprocess_env,
    gather_gpu_preflight_info,
    get_text_model_id,
    get_vision_model_id,
)
from ..utils.docling_lifecycle import DoclingLifecycleManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')  # NOSONAR: Safe basic logging format
logger = logging.getLogger(__name__)  # NOSONAR: Standard logger initialization


def _emit_event(
    event_type: str,
    stage: str,
    message: str,
    progress: int,
    step: Optional[str] = None,
    **extra: Any,
) -> None:
    """Emit a structured JSON event to stdout so the backend can stream it as an SSE event.

    event_type: "stage_start" | "stage_done" | "progress" | "runtime.gpu.*" | "model.lifecycle.*" | …
    stage:      backend stage name (extraction, validation, preflight, …)
    message:    human-readable detail line
    progress:   0-100 integer
    step:       optional display label shown as a section header on the frontend
    **extra:    optional structured metadata merged into the event payload
    """
    payload: dict = {
        "event": event_type,
        "stage": stage,
        "message": message,
        "progress": progress,
    }
    if step is not None:
        payload["step"] = step
    if extra:
        payload.update(extra)
    print(f"PIPELINE_EVENT:{json.dumps(payload)}", flush=True)


def _emit_gpu_runtime_events(environ: Optional[dict] = None) -> dict:
    """Probe GPU runtime and emit structured transparency events.

    Emits (in order):
      runtime.gpu.discovered → runtime.gpu.selected + runtime.gpu.validated
      OR runtime.gpu.discovered → pipeline.failfast.preflight_failed

    Returns the preflight info dict.
    """
    torch_module = None
    try:
        import torch as _torch
        torch_module = _torch
    except ImportError:
        pass

    info = gather_gpu_preflight_info(torch_module=torch_module, environ=environ)

    visible_raw = info["cuda_visible_devices_raw"]
    required_idx = info["required_gpu_physical_index"]

    # --- runtime.gpu.discovered ---
    _emit_event(
        "runtime.gpu.discovered",
        "preflight",
        f"Checking CUDA devices... CUDA_VISIBLE_DEVICES={visible_raw!r}, "
        f"cuda_available={info['cuda_available']}, device_count={info['cuda_device_count_visible']}",
        1,
        step="GPU Preflight",
        event_name="runtime.gpu.discovered",
        stage_id="preflight",
        status="probing",
        severity="info",
        cuda_available=info["cuda_available"],
        cuda_device_count_visible=info["cuda_device_count_visible"],
        cuda_visible_devices_raw=visible_raw,
        required_gpu_physical_index=required_idx,
    )

    if not info["preflight_passed"]:
        logger.error(
            "GPU preflight failed [%s]: %s",
            info["error_code"],
            info["failure_reason"],
        )
        _emit_event(
            "pipeline.failfast.preflight_failed",
            "preflight",
            f"Required GPU not available - {info['failure_reason']}. "
            f"Action: {info['recommended_action']}",
            1,
            step="GPU Preflight",
            event_name="pipeline.failfast.preflight_failed",
            stage_id="preflight",
            status="failed",
            severity="critical",
            message_user=(
                f"Pipeline cannot start: required GPU (physical index {required_idx}) is not available. "
                f"{info['recommended_action']}"
            ),
            cuda_available=info["cuda_available"],
            cuda_device_count_visible=info["cuda_device_count_visible"],
            cuda_visible_devices_raw=visible_raw,
            required_gpu_physical_index=required_idx,
            resolved_runtime_index=info["resolved_runtime_index"],
            error_code=info["error_code"],
            reason_code=info["failure_reason"],
            retryable=info["retryable"],
            recommended_action=info["recommended_action"],
        )
        return info

    resolved_idx = info["resolved_runtime_index"]
    selected_device = info["selected_device"]
    device_name = info["device_name"]

    # --- runtime.gpu.selected ---
    remap_note = (
        f" (remapped by CUDA_VISIBLE_DEVICES={visible_raw!r})"
        if visible_raw is not None
        else ""
    )
    _emit_event(
        "runtime.gpu.selected",
        "preflight",
        f"Required GPU found, using {selected_device}{remap_note}",
        2,
        step="GPU Preflight",
        event_name="runtime.gpu.selected",
        stage_id="preflight",
        status="selected",
        severity="info",
        message_user=f"Required GPU found, using {selected_device}{remap_note}",
        cuda_available=True,
        cuda_device_count_visible=info["cuda_device_count_visible"],
        cuda_visible_devices_raw=visible_raw,
        required_gpu_physical_index=required_idx,
        resolved_runtime_index=resolved_idx,
        selected_device=selected_device,
        device_name=device_name,
    )

    # --- runtime.gpu.validated ---
    _emit_event(
        "runtime.gpu.validated",
        "preflight",
        f"GPU validated: {device_name} at {selected_device}",
        3,
        step="GPU Preflight",
        event_name="runtime.gpu.validated",
        stage_id="preflight",
        status="validated",
        severity="info",
        message_user=f"GPU validated: {device_name} at {selected_device}",
        required_gpu_physical_index=required_idx,
        resolved_runtime_index=resolved_idx,
        selected_device=selected_device,
        device_name=device_name,
    )

    return info


def _emit_model_lifecycle_event(
    event_name: str,
    *,
    model_role: str,
    model_id: str,
    stage_id: str,
    status: str,
    message_user: str,
    progress: int,
    device: Optional[str] = None,
    dtype: Optional[str] = None,
    device_map: Optional[Any] = None,
    error_code: Optional[str] = None,
    reason_code: Optional[str] = None,
    retryable: bool = False,
    recommended_action: Optional[str] = None,
) -> None:
    """Emit a model lifecycle transparency event (load_started / load_completed / load_failed)."""
    extra: dict = {
        "event_name": event_name,
        "stage_id": stage_id,
        "status": status,
        "severity": "error" if status == "failed" else "info",
        "message_user": message_user,
        "model_role": model_role,
        "model_id_resolved": model_id,
    }
    if device is not None:
        extra["device_map"] = device_map if device_map is not None else device
        extra["selected_device"] = device
    if dtype is not None:
        extra["dtype"] = dtype
    if error_code is not None:
        extra["error_code"] = error_code
        extra["reason_code"] = reason_code
        extra["retryable"] = retryable
    if recommended_action is not None:
        extra["recommended_action"] = recommended_action

    _emit_event(event_name, stage_id, message_user, progress, **extra)



PLACEHOLDER_MARKDOWN_SENTINELS = (
    "Initial placeholder markdown created by backend upload workflow.",
    "Replace with Docling-extracted markdown for full-quality pipeline results.",
)

# Use "placeholder" mode instead of "descriptions" to avoid expensive VLM inference on every image
# This significantly speeds up Docling PDF conversion. Images are replaced with simple [Figure N: alt-text]
# Future enhancement: implement async/batch VLM description generation as an optional post-processing step
DOCLING_IMAGE_MODE = "placeholder"
CE_EXTRACTION_FLAG_ENV = "PIPELINE_CE_EXTRACTION_ENABLED"
CE_RETRIEVAL_FLAG_ENV = "PIPELINE_CE_RETRIEVAL_ENABLED"
_UUID_SEGMENT_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_feature_flag_enabled(env_name: str, *, default: bool = False) -> bool:
    """Resolve bool feature flags from environment with conservative defaults."""
    raw_value = os.getenv(env_name)
    if raw_value is None:
        return default
    return str(raw_value).strip().lower() in {"1", "true", "yes", "on"}


def _is_ce_extraction_enabled() -> bool:
    """Return whether CE structured extraction is enabled (default OFF)."""
    return _is_feature_flag_enabled(CE_EXTRACTION_FLAG_ENV, default=False)


def _is_ce_retrieval_enabled() -> bool:
    """Return whether CE retrieval route is enabled (default OFF scaffold)."""
    return _is_feature_flag_enabled(CE_RETRIEVAL_FLAG_ENV, default=False)


def _resolve_source_type(*, source_path: str, explicit_source_type: Optional[str] = None) -> str:
    """Resolve canonical pipeline source type for the current document."""
    if explicit_source_type in {"pdf", "xlsx"}:
        return str(explicit_source_type)
    return "xlsx" if Path(source_path).suffix.lower() in {".xlsx", ".xls"} else "pdf"


def _infer_document_id_from_markdown_path(markdown_path: Path) -> Optional[str]:
    """Infer UUID-like document id from path segments when available."""
    for segment in reversed(markdown_path.parts):
        if _UUID_SEGMENT_RE.fullmatch(segment):
            return segment
    return None


def _resolve_ce_artifact_path(markdown_path: Path) -> Path:
    """Return CE structured artifact path associated with canonical markdown."""
    return markdown_path.with_name(f"{markdown_path.stem}_ce_relations.json")


def _build_xlsx_page_markdown_map(markdown_path: str) -> Dict[int, str]:
    """Map page numbers to their full ## sheet section in the xlsx markdown.

    The xlsx extractor writes one ``## SheetName`` section per sheet.  This
    function splits on those headings and returns a 1-based page → section map
    so that ``validate_page_against_markdown`` uses the complete GFM table
    (including header and separator rows) rather than an anchor-based slice.
    """
    content = Path(markdown_path).read_text(encoding="utf-8")
    parts = re.split(r"(?=^## )", content.strip(), flags=re.MULTILINE)
    result: Dict[int, str] = {}
    page_num = 1
    for part in parts:
        stripped = part.strip()
        if stripped:
            result[page_num] = stripped
            page_num += 1
    return result


def _parse_xlsx_sheet_sections(markdown_content: str) -> list[dict[str, Any]]:
    """Parse sheet sections and retain page/line boundaries for lineage-aware chunking."""
    lines = markdown_content.splitlines()
    sections: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    for line_number, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if stripped.startswith("## "):
            if current is not None:
                current["line_end"] = line_number - 1
                current["markdown"] = "\n".join(
                    lines[current["line_start"] - 1 : current["line_end"]]
                ).strip()
                sections.append(current)
            current = {
                "sheet_name": stripped[3:].strip(),
                "page_number": len(sections) + 1,
                "line_start": line_number,
            }

    if current is not None:
        current["line_end"] = len(lines)
        current["markdown"] = "\n".join(lines[current["line_start"] - 1 :]).strip()
        sections.append(current)

    if sections:
        return sections

    fallback_markdown = markdown_content.strip()
    if not fallback_markdown:
        return []
    return [
        {
            "sheet_name": "Sheet1",
            "page_number": 1,
            "line_start": 1,
            "line_end": max(len(lines), 1),
            "markdown": fallback_markdown,
        }
    ]


def _sheet_section_for_line(
    line_number: Optional[int], sheet_sections: list[dict[str, Any]]
) -> Optional[dict[str, Any]]:
    """Return the sheet section containing the given line number."""
    if not sheet_sections:
        return None
    if line_number is None:
        return sheet_sections[0]

    for section in sheet_sections:
        if int(section["line_start"]) <= int(line_number) <= int(section["line_end"]):
            return section
    return sheet_sections[0]


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _load_xlsx_structured_relations_artifact(
    optimization_prep: Optional[dict[str, Any]],
) -> dict[str, Any] | None:
    """Load the authoritative XLSX structured relations artifact when present."""
    artifact_path = str(
        ((optimization_prep or {}).get("ce_structured_artifact") or {}).get("artifact_path") or ""
    ).strip()
    if not artifact_path:
        return None

    path = Path(artifact_path)
    if not path.exists() or not path.is_file():
        return None

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _build_xlsx_sheet_lookup(
    *,
    optimization_prep: Optional[dict[str, Any]],
    sheet_sections: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Resolve sheet-level page numbers and extracted table facts."""
    lookup: dict[str, dict[str, Any]] = {}
    for section in sheet_sections:
        lookup[str(section["sheet_name"]).lower()] = {
            "sheet_name": section["sheet_name"],
            "page_number": int(section["page_number"]),
            "markdown": section.get("markdown") or "",
            "table_facts": [],
        }

    for page in (optimization_prep or {}).get("pages") or []:
        headings = page.get("heading_candidates") or []
        table_facts = [str(fact).strip() for fact in (page.get("table_facts") or []) if str(fact).strip()]
        for heading in headings:
            key = str(heading).strip().lower()
            if not key:
                continue
            sheet_entry = lookup.setdefault(
                key,
                {
                    "sheet_name": str(heading).strip(),
                    "page_number": int(page.get("page_number") or len(lookup) + 1),
                    "markdown": str(page.get("authoritative_markdown") or ""),
                    "table_facts": [],
                },
            )
            if not sheet_entry.get("markdown"):
                sheet_entry["markdown"] = str(page.get("authoritative_markdown") or "")
            sheet_entry["page_number"] = int(sheet_entry.get("page_number") or page.get("page_number") or 1)
            sheet_entry["table_facts"] = _dedupe_preserving_order(
                list(sheet_entry.get("table_facts") or []) + table_facts
            )

    return lookup


def _build_xlsx_chunk_payload(
    *,
    chunk_id: str,
    chunk_type: str,
    heading: str,
    text: str,
    sheet_name: str,
    source_pages: list[int],
    row_refs: list[int],
    entity_refs: list[str],
    relation_refs: list[str],
    source_lineage: dict[str, Any],
    retrieval_hints: dict[str, Any],
    table_facts: Optional[list[str]] = None,
    ambiguity_flags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build one XLSX retrieval chunk with compatibility aliases for existing consumers."""
    normalized_text = text.strip()
    return {
        "chunk_id": chunk_id,
        "id": chunk_id,
        "chunk_type": chunk_type,
        "heading": heading,
        "title": heading,
        "text": normalized_text,
        "content": normalized_text,
        "sheet_name": sheet_name,
        "source_pages": source_pages,
        "row_refs": row_refs,
        "entity_refs": entity_refs,
        "relation_refs": relation_refs,
        "source_lineage": source_lineage,
        "retrieval_hints": retrieval_hints,
        "table_facts": table_facts or [],
        "ambiguity_flags": ambiguity_flags or [],
    }


def _build_xlsx_relation_optimized_output(
    markdown_content: str,
    doc_name: str,
    optimization_prep: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build JSON-first XLSX retrieval output from structured relations + reviewed headings."""
    structured_payload = _load_xlsx_structured_relations_artifact(optimization_prep)
    sheet_sections = _parse_xlsx_sheet_sections(markdown_content)
    sheet_lookup = _build_xlsx_sheet_lookup(
        optimization_prep=optimization_prep,
        sheet_sections=sheet_sections,
    )
    source_lineage = dict((structured_payload or {}).get("source_lineage") or {})
    warnings: list[str] = list((structured_payload or {}).get("warnings") or [])
    chunks: list[dict[str, Any]] = []

    for section in sheet_sections:
        sheet_name = str(section["sheet_name"])
        lookup_entry = sheet_lookup.get(sheet_name.lower(), {})
        page_number = int(lookup_entry.get("page_number") or section["page_number"])
        section_relations = [
            relation
            for relation in (structured_payload or {}).get("relations") or []
            if str((relation.get("origin") or {}).get("sheet") or sheet_name).strip().lower()
            == sheet_name.lower()
        ]
        chunks.append(
            _build_xlsx_chunk_payload(
                chunk_id=f"question_heading_{page_number:03d}",
                chunk_type="question_heading_chunk",
                heading=f"What data does the {sheet_name} sheet contain?",
                text=(
                    f"What data does the {sheet_name} sheet contain? "
                    f"This sheet contributes {len(section_relations)} structured relations and "
                    f"{len(lookup_entry.get('table_facts') or [])} extracted table facts for retrieval."
                ),
                sheet_name=sheet_name,
                source_pages=[page_number],
                row_refs=[],
                entity_refs=[],
                relation_refs=[
                    str(relation.get("relation_id") or "")
                    for relation in section_relations
                    if relation.get("relation_id")
                ],
                source_lineage=source_lineage,
                retrieval_hints={
                    "keywords": _dedupe_preserving_order(
                        [sheet_name]
                        + list(lookup_entry.get("table_facts") or [])
                        + [str(relation.get("marker_semantic") or "") for relation in section_relations]
                    ),
                    "heading_aliases": [sheet_name],
                    "marker_semantics": _dedupe_preserving_order(
                        [str(relation.get("marker_semantic") or "") for relation in section_relations]
                    ),
                },
                table_facts=list(lookup_entry.get("table_facts") or []),
            )
        )

    if structured_payload:
        causes_by_id = {
            str(cause.get("cause_id") or ""): cause
            for cause in structured_payload.get("causes") or []
        }
        effects_by_id = {
            str(effect.get("effect_id") or ""): effect
            for effect in structured_payload.get("effects") or []
        }

        relations_by_cause: dict[str, list[dict[str, Any]]] = {}
        for relation in structured_payload.get("relations") or []:
            relations_by_cause.setdefault(str(relation.get("cause_id") or ""), []).append(relation)

        for cause_id, cause in causes_by_id.items():
            related_relations = relations_by_cause.get(cause_id, [])
            cause_origin = cause.get("origin") or {}
            cause_line = int(cause_origin.get("line_number") or 0)
            sheet_section = _sheet_section_for_line(cause_line, sheet_sections)
            sheet_name = str((cause_origin.get("sheet") or (sheet_section or {}).get("sheet_name") or "Sheet1")).strip()
            page_number = int(
                (cause_origin.get("page_number") or 0)
                or ((sheet_section or {}).get("page_number") or 1)
            )
            related_effects = [
                effects_by_id.get(str(relation.get("effect_id") or ""), {})
                for relation in related_relations
            ]
            effect_summaries = [
                f"{effect.get('effect_label')} ({relation.get('marker_semantic')})"
                for relation, effect in zip(related_relations, related_effects)
                if effect.get("effect_label")
            ]
            cause_text = " ".join(
                part
                for part in [
                    f"Cause {cause.get('cause_ref') or cause_id}",
                    str(cause.get("cause_tag") or "").strip(),
                    str(cause.get("cause_description") or "").strip(),
                ]
                if str(part).strip()
            )
            row_fact_text = cause_text
            if effect_summaries:
                row_fact_text += f". Related effects: {'; '.join(effect_summaries)}."

            chunks.append(
                _build_xlsx_chunk_payload(
                    chunk_id=f"row_fact_{cause_id}",
                    chunk_type="row_fact_chunk",
                    heading=f"What does {cause.get('cause_ref') or cause_id} indicate?",
                    text=row_fact_text,
                    sheet_name=sheet_name,
                    source_pages=[page_number],
                    row_refs=[cause_line] if cause_line else [],
                    entity_refs=_dedupe_preserving_order(
                        [cause_id]
                        + [
                            str(effect.get("effect_id") or "")
                            for effect in related_effects
                            if effect.get("effect_id")
                        ]
                    ),
                    relation_refs=[
                        str(relation.get("relation_id") or "")
                        for relation in related_relations
                        if relation.get("relation_id")
                    ],
                    source_lineage=source_lineage,
                    retrieval_hints={
                        "keywords": _dedupe_preserving_order(
                            [
                                str(cause.get("cause_ref") or ""),
                                str(cause.get("cause_tag") or ""),
                                str(cause.get("cause_description") or ""),
                            ]
                            + [str(effect.get("effect_label") or "") for effect in related_effects]
                        ),
                        "heading_aliases": [sheet_name, str(cause.get("cause_ref") or cause_id)],
                        "marker_semantics": _dedupe_preserving_order(
                            [str(relation.get("marker_semantic") or "") for relation in related_relations]
                        ),
                    },
                )
            )

        for relation in structured_payload.get("relations") or []:
            relation_origin = relation.get("origin") or {}
            relation_line = int(relation_origin.get("line_number") or 0)
            sheet_section = _sheet_section_for_line(relation_line, sheet_sections)
            sheet_name = str((relation_origin.get("sheet") or (sheet_section or {}).get("sheet_name") or "Sheet1")).strip()
            page_number = int(
                (relation_origin.get("page_number") or 0)
                or ((sheet_section or {}).get("page_number") or 1)
            )
            cause = causes_by_id.get(str(relation.get("cause_id") or ""), {})
            effect = effects_by_id.get(str(relation.get("effect_id") or ""), {})
            cause_label = str(cause.get("cause_description") or cause.get("cause_ref") or relation.get("cause_id") or "Unknown cause")
            effect_label = str(effect.get("effect_label") or relation.get("effect_id") or "Unknown effect")
            marker = str(relation.get("marker") or "")
            marker_description = str(relation.get("marker_description") or relation.get("marker_semantic") or "")

            chunks.append(
                _build_xlsx_chunk_payload(
                    chunk_id=f"relation_edge_{relation.get('relation_id')}",
                    chunk_type="relation_edge_chunk",
                    heading=f"How does {cause_label} affect {effect_label}?",
                    text=(
                        f"Cause-effect relation on {sheet_name}: {cause_label} -> {effect_label}. "
                        f"Marker {marker or '?'} means {marker_description}."
                    ),
                    sheet_name=sheet_name,
                    source_pages=[page_number],
                    row_refs=[relation_line] if relation_line else [],
                    entity_refs=_dedupe_preserving_order(
                        [str(relation.get("cause_id") or ""), str(relation.get("effect_id") or "")]
                    ),
                    relation_refs=[str(relation.get("relation_id") or "")],
                    source_lineage=source_lineage,
                    retrieval_hints={
                        "keywords": _dedupe_preserving_order(
                            [cause_label, effect_label, marker, marker_description, sheet_name]
                        ),
                        "heading_aliases": [sheet_name, effect_label],
                        "marker_semantics": _dedupe_preserving_order(
                            [str(relation.get("marker_semantic") or "")]
                        ),
                    },
                )
            )
    else:
        warnings.append(
            "Structured relations artifact missing; XLSX retrieval output fell back to sheet-heading chunks only."
        )

    return {
        "document_name": doc_name,
        "source_type": "xlsx",
        "markdown": markdown_content,
        "chunks": chunks,
        "skip_reformatting": True,
        "structured_relations_artifact_path": str(
            ((optimization_prep or {}).get("ce_structured_artifact") or {}).get("artifact_path") or ""
        ).strip() or None,
        "retrieval_artifact_contract": {
            "json_first": True,
            "authoritative_source": "structured_relations" if structured_payload else "sheet_headings_fallback",
            "chunk_classes": ["question_heading_chunk", "row_fact_chunk", "relation_edge_chunk"],
        },
        "warnings": warnings,
    }


def _extract_xlsx_table_facts(section_markdown: str, sheet_name: str) -> list[str]:
    """Extract column headers and row count from a GFM table as table_facts strings."""
    lines = section_markdown.splitlines()
    header_line: Optional[str] = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 2:
            header_line = stripped
            break

    if not header_line:
        return [f"Sheet: {sheet_name}"]

    columns = [col.strip() for col in header_line.split("|") if col.strip()]
    facts: list[str] = []
    if columns:
        # Filter out generic auto-generated column names (Col0, Col1, …)
        real_columns = [c for c in columns if not re.match(r"^Col\d+$", c)]
        display_columns = real_columns if real_columns else columns
        facts.append(f"Columns: {', '.join(display_columns)}")

    data_rows = 0
    past_separator = False
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        if not stripped.replace("|", "").replace("-", "").replace(":", "").replace(" ", ""):
            past_separator = True
            continue
        if past_separator:
            data_rows += 1

    if data_rows > 0:
        facts.append(f"Contains {data_rows} data rows")

    return facts


def _build_xlsx_rag_chunks(
    markdown_content: str,
    doc_name: str,
    optimization_prep: Optional[Dict[str, Any]] = None,
) -> list[Dict[str, Any]]:
    """Build RAG-optimized chunks from xlsx GFM markdown (rule-based, no LLM).

    Each ``## SheetName`` section becomes one retrieval chunk with:
    - A question-format heading ("What data does the <sheet> sheet contain?")
    - Full table content with an appended source citation
    - ``table_facts`` listing column headers and row count
    - ``source_pages`` mapped from the optimization-prep page index
    - Empty ``ambiguity_flags``

    This replaces the LLM reformatting stage for spreadsheet documents so that
    RAG retrieval gets structured, semantically annotated chunks rather than raw
    GFM table text.
    """
    # Build sheet-name → page-number lookup from optimization_prep when available.
    page_num_by_heading: Dict[str, int] = {}
    if optimization_prep:
        for page in (optimization_prep.get("pages") or []):
            page_num = int(page.get("page_number") or 0)
            for heading in (page.get("heading_candidates") or []):
                page_num_by_heading[str(heading).lower().strip()] = page_num

    parts = re.split(r"(?=^## )", markdown_content.strip(), flags=re.MULTILINE)
    chunks: list[Dict[str, Any]] = []
    chunk_index = 1

    for part in parts:
        section = part.strip()
        if not section:
            continue

        lines = section.splitlines()
        heading_line = lines[0].strip() if lines else ""
        sheet_name = re.sub(r"^#+\s*", "", heading_line).strip()
        if not sheet_name:
            continue

        source_page = page_num_by_heading.get(sheet_name.lower(), chunk_index)
        citation = f"\n\n[Source: {doc_name}, Sheet {chunk_index}]"
        content_with_citation = section + citation

        chunks.append(
            {
                "heading": f"What data does the {sheet_name} sheet contain?",
                "content": content_with_citation,
                "source_pages": [source_page],
                "table_facts": _extract_xlsx_table_facts(section, sheet_name),
                "ambiguity_flags": [],
            }
        )
        chunk_index += 1

    return chunks


def _load_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_review_markdown(review_dir: Path, page_entry: dict[str, Any]) -> str:
    page_file = review_dir / str(page_entry.get("file") or "")
    if page_file.exists() and page_file.is_file():
        return page_file.read_text(encoding="utf-8").strip()
    return str(page_entry.get("markdown_content") or "").strip()


def _load_review_checklist(review_dir: Path, page_entry: dict[str, Any]) -> dict[str, Any]:
    checklist_path = review_dir / str(page_entry.get("checklist") or "")
    if checklist_path.exists() and checklist_path.is_file():
        return _load_json_file(checklist_path)
    return {}


def _extract_heading_candidates(markdown_content: str) -> list[str]:
    headings: list[str] = []
    for line in markdown_content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return headings


def _extract_checklist_notes(checklist_payload: dict[str, Any]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    for checklist_key, checklist_item in checklist_payload.items():
        if not isinstance(checklist_item, dict):
            continue
        note = checklist_item.get("notes")
        if note:
            notes.append(
                {
                    "checklist_item": checklist_key,
                    "checked": bool(checklist_item.get("checked")),
                    "note": str(note),
                }
            )
    return notes


def _checklist_ambiguity_flags(checklist_payload: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    for key, item in checklist_payload.items():
        if isinstance(item, dict) and not item.get("checked") and item.get("notes"):
            flags.append(f"{key}: {item['notes']}")
    return flags


def _validation_ambiguity_flags(validation_issues: list[dict[str, Any]]) -> list[str]:
    return [
        str(issue.get("description") or issue.get("evidence") or "")
        for issue in validation_issues
        if issue.get("severity") in {"critical", "major"}
    ]


def _extract_ambiguity_flags(checklist_payload: dict[str, Any], validation_issues: list[dict[str, Any]]) -> list[str]:
    raw = _checklist_ambiguity_flags(checklist_payload) + _validation_ambiguity_flags(validation_issues)
    return [flag for flag in raw if flag]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        cleaned = str(value).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _collect_page_numbers(current_pages: list[dict[str, Any]]) -> list[int]:
    return [int(page.get("page_number") or 0) for page in current_pages]


def _collect_title_candidates(current_pages: list[dict[str, Any]]) -> list[str]:
    return _dedupe_strings(
        [
            heading
            for page in current_pages
            for heading in (page.get("heading_candidates") or [])
        ]
    )


def _collect_string_field_values(current_pages: list[dict[str, Any]], field_name: str) -> list[str]:
    return _dedupe_strings(
        [value for page in current_pages for value in (page.get(field_name) or [])]
    )


def _collect_dict_field_values(current_pages: list[dict[str, Any]], field_name: str) -> list[dict[str, Any]]:
    return [
        item
        for page in current_pages
        for item in (page.get(field_name) or [])
        if isinstance(item, dict)
    ]


def _build_authoritative_markdown(current_pages: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        str(page.get("authoritative_markdown") or "").strip()
        for page in current_pages
        if str(page.get("authoritative_markdown") or "").strip()
    ).strip()


def _build_segment_payload(
    current_pages: list[dict[str, Any]], segment_index: int, source_type: str = "pdf"
) -> dict[str, Any]:
    """Build one optimization segment payload from grouped pages."""
    page_numbers = _collect_page_numbers(current_pages)
    title_candidates = _collect_title_candidates(current_pages)
    segment_title = title_candidates[0] if title_candidates else f"Pages {page_numbers[0]}-{page_numbers[-1]}"

    return {
        "segment_id": f"segment_{segment_index:03d}",
        "title": segment_title,
        "page_numbers": page_numbers,
        "page_range": {"start": page_numbers[0], "end": page_numbers[-1]},
        "heading_candidates": title_candidates,
        "table_facts": _collect_string_field_values(current_pages, "table_facts"),
        "ambiguity_flags": _collect_string_field_values(current_pages, "ambiguity_flags"),
        "citations": _collect_dict_field_values(current_pages, "citations"),
        "reviewer_notes": _collect_dict_field_values(current_pages, "reviewer_notes"),
        "pages": current_pages.copy(),
        "authoritative_markdown": _build_authoritative_markdown(current_pages),
        "skip_reformatting": False,
    }


def _should_flush_segment(
    *,
    current_pages: list[dict[str, Any]],
    current_chars: int,
    page_chars: int,
    introduces_heading: bool,
    max_pages_per_segment: int,
    target_chars: int,
    min_chars_before_split: int,
) -> bool:
    """Determine whether a segment boundary should be emitted before adding a page."""
    if not current_pages:
        return False

    exceeds_page_budget = len(current_pages) >= max_pages_per_segment
    exceeds_char_budget = current_chars + page_chars > target_chars
    natural_heading_break = introduces_heading and current_chars >= min_chars_before_split
    return exceeds_page_budget or exceeds_char_budget or natural_heading_break


def _build_optimization_segments(
    structured_pages: list[dict[str, Any]],
    *,
    source_type: str = "pdf",
    target_chars: int = 18_000,
    min_chars_before_split: int = 6_000,
    max_pages_per_segment: int = 4,
) -> list[dict[str, Any]]:
    """Group reviewed pages into section-aware optimization batches.

    Stage 10 prompt quality drops sharply when the full reviewed document is sent in a
    single request. These segments keep the model input bounded while still preserving
    page-local provenance, tables, figures, and ambiguity flags.
    """

    segments: list[dict[str, Any]] = []
    current_pages: list[dict[str, Any]] = []
    current_chars = 0

    for page in structured_pages:
        page_markdown = str(page.get("authoritative_markdown") or page.get("text_preview") or "")
        page_chars = max(len(page_markdown), 1)
        introduces_heading = bool(page.get("heading_candidates"))

        if _should_flush_segment(
            current_pages=current_pages,
            current_chars=current_chars,
            page_chars=page_chars,
            introduces_heading=introduces_heading,
            max_pages_per_segment=max_pages_per_segment,
            target_chars=target_chars,
            min_chars_before_split=min_chars_before_split,
        ):
            segments.append(_build_segment_payload(current_pages, len(segments) + 1, source_type))
            current_pages = []
            current_chars = 0

        current_pages.append(page)
        current_chars += page_chars

    if current_pages:
        segments.append(_build_segment_payload(current_pages, len(segments) + 1, source_type))

    return segments


def _build_validation_page_lookup(validation_report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        int(page.get("page_number") or 0): page
        for page in validation_report.get("page_validations", [])
    }


def _select_page_records(records: list[dict[str, Any]], page_number: int) -> list[dict[str, Any]]:
    return [record for record in records if int(record.get("page_number") or 0) == page_number]


def _count_image_loss_pages(validation_report: Any) -> int:
    return sum(
        1 for pv in validation_report.page_validations
        for issue in pv.issues
        if issue.issue_type == "image_loss"
    )


def _get_validation_issues(
    page_entry: dict[str, Any], validation_page: dict[str, Any]
) -> list[dict[str, Any]]:
    return page_entry.get("validation_issues") or validation_page.get("issues") or []


def _get_text_preview(page_entry: dict[str, Any]) -> str:
    return (
        page_entry.get("text_preview")
        or (page_entry.get("evidence") or {}).get("text_preview")
        or ""
    )


def _get_source_mapping(
    page_entry: dict[str, Any], page_number: int, document_name: str
) -> dict[str, Any]:
    return {
        "validation_page_number": page_number,
        "thumbnail_path": (page_entry.get("evidence") or {}).get("thumbnail_path"),
        "citation_reference": f"{document_name}, Page {page_number}",
    }


def _build_table_facts(page_tables: list[dict[str, Any]]) -> list[str]:
    return [fact for table in page_tables for fact in table.get("key_facts", [])]


def _build_structured_page_record(
    *,
    page_entry: dict[str, Any],
    review_root: Path,
    validation_page: dict[str, Any],
    all_tables: list[dict[str, Any]],
    all_figures: list[dict[str, Any]],
    document_name: str,
) -> tuple[dict[str, Any], list[str]]:
    page_number = int(page_entry.get("page_number") or 0)
    authoritative_markdown = _load_review_markdown(review_root, page_entry)
    checklist_payload = _load_review_checklist(review_root, page_entry)
    validation_issues = _get_validation_issues(page_entry, validation_page)
    checklist_notes = _extract_checklist_notes(checklist_payload)
    ambiguity_flags = _extract_ambiguity_flags(checklist_payload, validation_issues)
    page_tables = _select_page_records(all_tables, page_number)
    page_figures = _select_page_records(all_figures, page_number)

    return {
        "page_id": page_entry.get("page_id", f"page_{page_number:03d}"),
        "page_number": page_number,
        "authoritative_markdown": authoritative_markdown,
        "heading_candidates": _extract_heading_candidates(authoritative_markdown),
        "text_preview": _get_text_preview(page_entry),
        "review_checklist": checklist_payload,
        "reviewer_notes": checklist_notes,
        "ambiguity_flags": ambiguity_flags,
        "validation_issues": validation_issues,
        "source_mapping": _get_source_mapping(page_entry, page_number, document_name),
        "table_records": page_tables,
        "table_facts": _build_table_facts(page_tables),
        "figure_records": page_figures,
        "citations": [
            {
                "document_name": document_name,
                "page_number": page_number,
                "label": f"[Source: {document_name}, Page {page_number}]",
            }
        ],
    }, ambiguity_flags


def _build_structured_pages_and_ambiguities(
    *,
    page_manifest: dict[str, Any],
    review_root: Path,
    validation_pages: dict[int, dict[str, Any]],
    all_tables: list[dict[str, Any]],
    all_figures: list[dict[str, Any]],
    document_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    structured_pages: list[dict[str, Any]] = []
    unresolved_ambiguities: list[dict[str, Any]] = []

    for page_entry in page_manifest.get("pages", []):
        page_number = int(page_entry.get("page_number") or 0)
        page_record, ambiguity_flags = _build_structured_page_record(
            page_entry=page_entry,
            review_root=review_root,
            validation_page=validation_pages.get(page_number, {}),
            all_tables=all_tables,
            all_figures=all_figures,
            document_name=document_name,
        )
        structured_pages.append(page_record)

        if ambiguity_flags:
            unresolved_ambiguities.append(
                {
                    "page_number": page_number,
                    "page_id": page_record["page_id"],
                    "flags": ambiguity_flags,
                }
            )

    return structured_pages, unresolved_ambiguities


def _build_source_artifacts_payload(
    *,
    page_manifest_path: Path,
    validation_report: dict[str, Any],
    document_name: str,
    table_figure_report: dict[str, Any],
    ce_structured_artifact: Optional[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "page_review_manifest": str(page_manifest_path),
        "validation_report": validation_report.get("document_name") or document_name,
        "table_figure_report_present": bool(table_figure_report),
        "ce_structured_artifact_present": bool(ce_structured_artifact),
        "ce_structured_artifact_path": (ce_structured_artifact or {}).get("artifact_path"),
    }


def _build_ce_retrieval_extension(ce_structured_artifact: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Build additive CE retrieval extension metadata for downstream routing."""
    ce_structured_artifact = ce_structured_artifact or {}
    relation_count = int(ce_structured_artifact.get("relations_count") or 0)
    artifact_available = bool(ce_structured_artifact.get("artifact_path")) and relation_count > 0
    ce_retrieval_enabled = _is_ce_retrieval_enabled()

    return {
        "ce_retrieval": {
            "enabled": ce_retrieval_enabled,
            "artifact_available": artifact_available,
            "artifact_path": ce_structured_artifact.get("artifact_path"),
            "artifact_schema_version": ce_structured_artifact.get("schema_version"),
            "route": "ce_relations" if ce_retrieval_enabled and artifact_available else "markdown_default",
            "diagnostics": {
                "causes_count": int(ce_structured_artifact.get("causes_count") or 0),
                "effects_count": int(ce_structured_artifact.get("effects_count") or 0),
                "relations_count": relation_count,
                "fallback_reason": None if (ce_retrieval_enabled and artifact_available) else "ce_route_disabled_or_artifact_unavailable",
            },
        }
    }


def build_optimization_prep(
    *,
    document_id: str,
    document_name: str,
    review_dir: str,
    validation_report: dict[str, Any],
    table_figure_report: Optional[dict[str, Any]] = None,
    ce_structured_artifact: Optional[dict[str, Any]] = None,
    source_path: Optional[str] = None,
) -> dict[str, Any]:
    """Create the structured optimization-prep artifact from reviewed page assets."""
    review_root = Path(review_dir)
    page_manifest_path = review_root / "page_review_manifest.json"
    page_manifest = _load_json_file(page_manifest_path)
    validation_pages = _build_validation_page_lookup(validation_report)
    table_figure_report = table_figure_report or {}
    all_tables = table_figure_report.get("tables", []) or []
    all_figures = table_figure_report.get("figures", []) or []
    structured_pages, unresolved_ambiguities = _build_structured_pages_and_ambiguities(
        page_manifest=page_manifest,
        review_root=review_root,
        validation_pages=validation_pages,
        all_tables=all_tables,
        all_figures=all_figures,
        document_name=document_name,
    )

    _source_suffix = Path(source_path).suffix.lower() if source_path else ""
    _source_type = "xlsx" if _source_suffix in {".xlsx", ".xls"} else "pdf"

    return {
        "schema_version": "1.0",
        "document_id": document_id,
        "document_name": document_name,
        "source_type": _source_type,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_workspace": str(review_root),
        "source_artifacts": _build_source_artifacts_payload(
            page_manifest_path=page_manifest_path,
            validation_report=validation_report,
            document_name=document_name,
            table_figure_report=table_figure_report,
            ce_structured_artifact=ce_structured_artifact,
        ),
        "validation_summary": validation_report.get("metadata", {}),
        "pages": structured_pages,
        "segments": _build_optimization_segments(structured_pages, source_type=_source_type),
        "tables": all_tables,
        "figures": all_figures,
        "ce_structured_artifact": ce_structured_artifact or {},
        "retrieval_extensions": _build_ce_retrieval_extension(ce_structured_artifact),
        "unresolved_ambiguities": unresolved_ambiguities,
        "combined_markdown": "\n\n".join(
            page["authoritative_markdown"]
            for page in structured_pages
            if page.get("authoritative_markdown")
        ).strip(),
    }


def _convert_pdf_to_markdown(
    *,
    pdf_path: str,
    output_path: str,
    image_mode: str,
    docling_url: str,
    ce_output_path: Optional[str] = None,
    ce_extraction_enabled: Optional[bool] = None,
    lineage_context: Optional[dict[str, Any]] = None,
) -> None:
    from ..ingestion.docling_converter import convert_pdf_with_qwen

    convert_pdf_with_qwen(
        pdf_path=pdf_path,
        output_path=output_path,
        image_mode=image_mode,
        docling_url=docling_url,
        ce_output_path=ce_output_path,
        ce_extraction_enabled=ce_extraction_enabled,
        lineage_context=lineage_context,
    )


_CHUNK_CONTENT_KEYS = ("content", "markdown", "body", "text")


def _chunk_has_content(chunk: Any) -> bool:
    if isinstance(chunk, str):
        return bool(chunk.strip())
    if isinstance(chunk, dict):
        return any(str(chunk.get(k) or "").strip() for k in _CHUNK_CONTENT_KEYS)
    return False


def _has_structurally_valid_optimized_output(result: dict[str, Any]) -> bool:
    chunks = result.get("chunks")
    if isinstance(chunks, list) and any(_chunk_has_content(c) for c in chunks):
        return True
    markdown_content = result.get("markdown")
    return isinstance(markdown_content, str) and bool(markdown_content.strip())


def _prepare_reformat_content(
    optimization_prep_path: Optional[str],
    markdown_path: Optional[str],
) -> tuple[Optional[dict[str, Any]], str]:
    """Load and return (optimization_prep, markdown_content) from available inputs."""
    optimization_prep = None
    markdown_content = ""

    if optimization_prep_path:
        with open(optimization_prep_path, 'r', encoding='utf-8') as f:
            optimization_prep = json.load(f)
        markdown_content = str(optimization_prep.get("combined_markdown") or "")

    if not markdown_content and markdown_path:
        with open(markdown_path, 'r', encoding='utf-8') as f:
            markdown_content = f.read()

    if not markdown_content:
        raise ValueError("No authoritative reviewed markdown available for optimization")

    return optimization_prep, markdown_content


def _build_qa_input_dicts(
    sections: Any,
    validation_report: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build input dictionaries for QA metrics computation."""
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
        ],
    }
    return sections_for_qa, validation_dict


class HITLPipeline:
    """
    Enhanced HITL Pipeline for Document Optimization
    Implements all suggested improvements
    """
    
    def __init__(self, work_dir: str = "hitl_workspace"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(exist_ok=True, parents=True)
        logger.info(f"[INFO] HITL workspace: {self.work_dir}")

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
            logger.info(f"[OK] Using existing markdown: {markdown_file}")
            return str(markdown_file)

        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 0: Docling Document -> Markdown Extraction")
        logger.info("=" * 80)
        logger.info(f"[INFO] Generating markdown from document: {Path(pdf_path).name}")

        ce_artifact_path = _resolve_ce_artifact_path(markdown_file)
        lineage_context = {
            "document_id": _infer_document_id_from_markdown_path(markdown_file),
            "run_id": os.getenv("PIPELINE_RUN_ID"),
        }

        # Direct pandas extraction path for xlsx — skips Docling lifecycle entirely.
        if Path(pdf_path).suffix.lower() in {".xlsx", ".xls"}:
            _emit_event(
                "progress",
                "extraction",
                "XLSX detected — extracting directly via pandas (no Docling required).",
                6,
                step="Stage 0: Document → Markdown Extraction",
            )
            from ..ingestion.docling_converter import extract_xlsx_to_markdown
            extract_xlsx_to_markdown(
                xlsx_path=pdf_path,
                output_path=str(markdown_file),
                ce_output_path=str(ce_artifact_path),
                ce_extraction_enabled=_is_ce_extraction_enabled(),
                lineage_context=lineage_context,
            )
            if ce_artifact_path.exists() and ce_artifact_path.is_file():
                logger.info("[OK] CE relation artifact saved: %s", ce_artifact_path)
            logger.info("[OK] XLSX markdown saved (pandas direct path): %s", markdown_file)
            _emit_event(
                "progress",
                "extraction",
                "XLSX extraction complete.",
                12,
            )
            return str(markdown_file)

        docling_url = os.getenv("DOCLING_URL", "http://localhost:5001")
        temp_output = markdown_file.with_suffix(".docling.tmp.md")
        temp_ce_artifact_path = ce_artifact_path.with_suffix(".tmp.json")

        lifecycle = DoclingLifecycleManager(docling_url=docling_url)
        _lifecycle_started = False
        try:
            _emit_event(
                "lifecycle.docling.starting",
                "extraction",
                "Starting Docling service (on-demand)…" if lifecycle.is_on_demand
                else "Waiting for Docling service…",
                5,
                step="Stage 0: Document → Markdown Extraction",
                on_demand=lifecycle.is_on_demand,
            )
            lifecycle.start()
            _lifecycle_started = True
            _emit_event(
                "lifecycle.docling.ready",
                "extraction",
                "Docling service is ready; starting document extraction.",
                6,
                on_demand=lifecycle.is_on_demand,
            )
            _convert_pdf_to_markdown(
                pdf_path=pdf_path,
                output_path=str(temp_output),
                image_mode=DOCLING_IMAGE_MODE,
                docling_url=docling_url,
                ce_output_path=str(temp_ce_artifact_path),
                ce_extraction_enabled=_is_ce_extraction_enabled(),
                lineage_context=lineage_context,
            )

            generated_content = temp_output.read_text(encoding="utf-8")
            if not generated_content.strip():
                raise ValueError("Docling generated empty markdown output")
            if any(sentinel in generated_content for sentinel in PLACEHOLDER_MARKDOWN_SENTINELS):
                raise ValueError("Docling output still contains placeholder markdown sentinel text")

            markdown_file.write_text(generated_content, encoding="utf-8")
            if temp_ce_artifact_path.exists() and temp_ce_artifact_path.is_file():
                ce_artifact_path.write_text(temp_ce_artifact_path.read_text(encoding="utf-8"), encoding="utf-8")
                logger.info("[OK] CE relation artifact saved: %s", ce_artifact_path)
            logger.info(f"[OK] Docling markdown saved: {markdown_file}")
            return str(markdown_file)
        finally:
            # stop() never raises — guaranteed release attempt on both success and failure paths.
            lifecycle.stop()
            if lifecycle.is_on_demand and _lifecycle_started:
                _emit_event(
                    "lifecycle.docling.stopped",
                    "extraction",
                    "Docling service stopped; GPU memory released for VLM stage.",
                    12,
                    on_demand=True,
                )
            temp_output.unlink(missing_ok=True)
            temp_ce_artifact_path.unlink(missing_ok=True)

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

    def _build_validation_page_markdown_map(self, pdf_path: str) -> Optional[Dict[int, str]]:
        """Return page markdown overrides for validation when a cheaper source exists.

        The primary ingestion path intentionally avoids rebuilding the document page by
        page with a second Docling conversion pass. Validation can derive page-aligned
        review slices from the authoritative full-document markdown, which removes the
        duplicate conversion/image-description loop that was saturating CPU.
        """
        del pdf_path
        return None

    @staticmethod
    def _read_markdown_content(markdown_path: str) -> str:
        with open(markdown_path, 'r', encoding='utf-8') as file_handle:
            return file_handle.read()

    def _run_optional_vlm_comparison(self, *, markdown_path: str, pdf_path: str, validation_report) -> None:
        logger.info("\n[INFO] Step 2b: Running VLM deep comparison...")
        logger.info("[WARNING] Note: You can skip VLM comparison by pressing Ctrl+C")
        logger.info("         Basic validation is already complete.")
        _emit_event(
            "progress",
            "validation",
            "Running VLM deep comparison (duration varies by document size)...",
            40,
        )

        try:
            from ..validation.vlm_comparison import compare_with_vlm

            markdown_content = self._read_markdown_content(markdown_path)
            started_at = perf_counter()
            vlm_result = compare_with_vlm(markdown_content, pdf_path)
            elapsed_seconds = max(perf_counter() - started_at, 0.0)
            if vlm_result and 'format_issues' in vlm_result:
                validation_report.metadata['vlm_validation'] = vlm_result
                logger.info("[OK] VLM validation complete")

            confidence = None
            if isinstance(vlm_result, dict):
                try:
                    confidence = float(vlm_result.get("confidence"))
                except (TypeError, ValueError):
                    confidence = None

            if confidence is not None and confidence <= 0.0:
                _emit_event(
                    "progress",
                    "validation",
                    f"VLM comparison finished in {elapsed_seconds:.1f}s with low-confidence fallback.",
                    55,
                )
            else:
                _emit_event(
                    "progress",
                    "validation",
                    f"VLM deep comparison complete in {elapsed_seconds:.1f}s.",
                    55,
                )
        except KeyboardInterrupt:
            logger.warning("[WARNING] VLM comparison skipped by user")
            _emit_event("progress", "validation", "VLM comparison skipped by user.", 55)
        except Exception as exc:
            logger.warning(f"[WARNING] VLM comparison failed (continuing with basic validation): {exc}")
            _emit_event("progress", "validation", f"VLM comparison skipped: {exc}", 55)

    def _write_image_description_failure_log(
        self,
        *,
        return_code: int | str,
        command: list[str],
        stdout_text: str,
        stderr_text: str,
    ) -> Path:
        """Persist full subprocess diagnostics for image-description failures."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        failure_log_path = self.work_dir / f"image_description_failure_{timestamp}.log"
        failure_report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "returncode": return_code,
            "command": command,
            "stdout": stdout_text,
            "stderr": stderr_text,
        }
        with open(failure_log_path, "w", encoding="utf-8") as f:
            json.dump(failure_report, f, indent=2)
        return failure_log_path

    @staticmethod
    def _coerce_subprocess_stream(output: Any) -> str:
        """Convert subprocess output payloads to text for JSON-safe diagnostics."""
        if output is None:
            return ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return str(output)

    def _read_image_description_progress_metrics(
        self,
        *,
        pdf_path: str,
        pages_requested: int,
    ) -> dict[str, int]:
        """Read persisted page-level completion metrics for image-description stage."""
        requested = max(int(pages_requested), 0)
        metrics = {
            "pages_requested": requested,
            "pages_succeeded": 0,
            "pages_failed": requested,
        }

        progress_path = self.work_dir / f"{Path(pdf_path).stem}_progress.json"
        if not progress_path.exists():
            return metrics

        try:
            progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not parse image-description progress file %s: %s", progress_path, exc)
            return metrics

        completed_items = progress_payload.get("completed_items")
        failed_items = progress_payload.get("failed_items")
        total_items = progress_payload.get("total_items")

        pages_succeeded = len(completed_items) if isinstance(completed_items, list) else 0
        pages_failed = len(failed_items) if isinstance(failed_items, list) else 0

        if isinstance(total_items, int) and total_items >= 0:
            requested = total_items
        elif requested == 0:
            requested = pages_succeeded + pages_failed

        # Normalize for consistency in user-facing reporting.
        # Treat missing coverage as failed so "complete" reflects full requested-page coverage.
        if requested > 0:
            pages_succeeded = min(max(pages_succeeded, 0), requested)
            inferred_failed = max(requested - pages_succeeded, 0)
            pages_failed = max(pages_failed, inferred_failed)

            if pages_succeeded + pages_failed > requested:
                pages_failed = max(requested - pages_succeeded, 0)

        return {
            "pages_requested": max(requested, 0),
            "pages_succeeded": max(pages_succeeded, 0),
            "pages_failed": max(pages_failed, 0),
        }

    @staticmethod
    def _summarize_subprocess_failure(stderr_text: str, stdout_text: str) -> str:
        """Return a concise error summary without dropping full diagnostics."""
        stderr_lines = [line.strip() for line in stderr_text.splitlines() if line.strip()]
        if stderr_lines:
            return stderr_lines[-1]
        stdout_lines = [line.strip() for line in stdout_text.splitlines() if line.strip()]
        if stdout_lines:
            return stdout_lines[-1]
        return "Image description subprocess exited with no output"

    def _execute_image_description_subprocess(
        self,
        *,
        image_description_cmd: list[str],
        image_loss_count: int,
        markdown_path: str,
        markdown_enhanced_path: Path,
        pdf_path: str,
        vlm_model: str,
        docling_version: str,
        validation_path: Path,
        validation_report: Any,
        manifest: Any,
        manifest_path: Path,
        reviewer: str,
        page_markdown_map: Optional[Dict[int, str]],
    ) -> tuple[str, dict[str, Any], Any, Any]:
        """Execute the image description subprocess and return updated pipeline state."""
        updated_markdown_path = markdown_path
        stage_result: dict[str, Any]

        # Resolve vision model id for lifecycle events
        vision_model_id = vlm_model
        selected_device_hint: Optional[str] = None
        try:
            _info = gather_gpu_preflight_info()
            if _info.get("selected_device"):
                selected_device_hint = _info["selected_device"]
        except Exception:
            pass

        # ── Layer 2: Preflight VRAM gate ───────────────────────────────────────
        # Check before acquiring the lock so we fail fast without blocking other jobs.
        # Raised outside the try/except so VRAM errors propagate cleanly as RuntimeError.
        _free_vram_bytes: Optional[int] = None
        try:
            smi_result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                    "-i",
                    str(_VLM_GPU_INDEX),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            _free_vram_bytes = int(smi_result.stdout.strip()) * 1024 * 1024
        except Exception as smi_exc:
            logger.warning(f"[WARNING] VRAM preflight check failed (proceeding anyway): {smi_exc}")

        if _free_vram_bytes is not None and _free_vram_bytes < _VLM_MIN_FREE_VRAM_BYTES:
            free_gib = _free_vram_bytes / (1024 ** 3)
            required_gib = _VLM_MIN_FREE_VRAM_BYTES / (1024 ** 3)
            msg = (
                f"Insufficient VRAM on GPU {_VLM_GPU_INDEX}: "
                f"{free_gib:.2f} GiB free, {required_gib:.1f} GiB required. "
                "Aborting VLM stage to prevent CUDA OOM."
            )
            logger.warning(f"[WARNING] {msg}")
            _emit_event("progress", "validation", msg, 56)
            raise RuntimeError(msg)

        # ── Layer 1: File-based VLM worker lock ──────────────────────────────────
        # Ensures only one VLM subprocess runs at a time system-wide, preventing
        # concurrent processes from exhausting GPU memory.
        logger.info(f"[INFO] Acquiring VLM worker lock ({_VLM_LOCK_PATH})...")
        _emit_event("progress", "validation", "Waiting for VLM worker slot (serializing GPU access)...", 56)
        lock_file = open(_VLM_LOCK_PATH, "w")  # noqa: WPS515
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX)  # blocking exclusive lock
            logger.info("[INFO] VLM worker lock acquired.")
        except Exception as lock_exc:
            lock_file.close()
            raise RuntimeError(f"Failed to acquire VLM worker lock: {lock_exc}") from lock_exc

        try:
            _emit_model_lifecycle_event(
                "model.lifecycle.load_started",
                model_role="vision",
                model_id=vision_model_id,
                stage_id="validation",
                status="loading",
                message_user=(
                    f"Loading {vision_model_id} on required GPU"
                    + (f" ({selected_device_hint})" if selected_device_hint else "")
                    + "..."
                ),
                progress=56,
                device=selected_device_hint,
            )
            result = subprocess.run(
                image_description_cmd,
                capture_output=True,
                text=True,
                timeout=2400,
                cwd=str(Path(__file__).resolve().parents[3]),
                env=build_gpu1_constrained_subprocess_env(os.environ),
            )

            if result.returncode == 0:
                logger.info("[OK] Image descriptions generated")
                _emit_model_lifecycle_event(
                    "model.lifecycle.load_completed",
                    model_role="vision",
                    model_id=vision_model_id,
                    stage_id="validation",
                    status="completed",
                    message_user=f"Vision model inference complete on {selected_device_hint or 'cuda:?'}.",
                    progress=60,
                    device=selected_device_hint,
                )
                updated_markdown_path = str(markdown_enhanced_path)
                validation_report, manifest = self._run_validation_stage(
                    pdf_path=pdf_path,
                    markdown_path=updated_markdown_path,
                    vlm_model=vlm_model,
                    docling_version=docling_version,
                    validation_path=validation_path,
                    manifest=manifest,
                    manifest_path=manifest_path,
                    reviewer=reviewer,
                    page_markdown_map=page_markdown_map,
                )

                metrics = self._read_image_description_progress_metrics(
                    pdf_path=pdf_path,
                    pages_requested=image_loss_count,
                )
                pages_requested = metrics["pages_requested"]
                pages_succeeded = metrics["pages_succeeded"]
                pages_failed = metrics["pages_failed"]

                if pages_requested > 0 and pages_succeeded == pages_requested and pages_failed == 0:
                    status = "complete"
                elif pages_succeeded > 0:
                    status = "partial"
                else:
                    status = "failed"

                summary_message = (
                    f"Image descriptions generated for {pages_succeeded} pages "
                    f"({pages_failed} failed)."
                )

                stage_result = {
                    "status": status,
                    "output": str(markdown_enhanced_path),
                    "pages_processed": pages_succeeded,
                    "pages_requested": pages_requested,
                    "pages_succeeded": pages_succeeded,
                    "pages_failed": pages_failed,
                }
                _emit_event("progress", "validation", summary_message, 64)
            else:
                stderr_text = self._coerce_subprocess_stream(result.stderr)
                stdout_text = self._coerce_subprocess_stream(result.stdout)
                failure_log_path = self._write_image_description_failure_log(
                    return_code=result.returncode,
                    command=image_description_cmd,
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                )
                failure_summary = self._summarize_subprocess_failure(stderr_text, stdout_text)
                logger.warning(f"[WARNING] Image description failed: {failure_summary}")
                logger.info(f"   Full diagnostics saved: {failure_log_path}")
                logger.info("   Continuing with original markdown...")
                stage_result = {
                    "status": "failed",
                    "error": failure_summary,
                    "returncode": result.returncode,
                    "stdout": stdout_text,
                    "stderr": stderr_text,
                    "diagnostics_log": str(failure_log_path),
                    "pages_processed": 0,
                    "pages_requested": image_loss_count,
                    "pages_succeeded": 0,
                    "pages_failed": image_loss_count,
                }
                _emit_model_lifecycle_event(
                    "model.lifecycle.load_failed",
                    model_role="vision",
                    model_id=vision_model_id,
                    stage_id="validation",
                    status="failed",
                    message_user=f"Vision model load/inference failed: {failure_summary}",
                    progress=64,
                    device=selected_device_hint,
                    error_code="SUBPROCESS_NONZERO_EXIT",
                    reason_code=failure_summary,
                    recommended_action=(
                        f"Check diagnostics log at {failure_log_path.name}. "
                        "Verify required GPU is available and model weights are accessible."
                    ),
                )
                _emit_event("progress", "validation", "Image description failed, using original markdown.", 64)
        except subprocess.TimeoutExpired:
            logger.warning("[WARNING] Image description timed out - continuing with original markdown")
            stage_result = {
                "status": "timeout",
                "pages_processed": 0,
                "pages_requested": image_loss_count,
                "pages_succeeded": 0,
                "pages_failed": image_loss_count,
            }
            _emit_model_lifecycle_event(
                "model.lifecycle.load_failed",
                model_role="vision",
                model_id=vision_model_id,
                stage_id="validation",
                status="failed",
                message_user="Vision model inference timed out (>2400 s).",
                progress=64,
                device=selected_device_hint,
                error_code="SUBPROCESS_TIMEOUT",
                reason_code="Image description subprocess exceeded 2400 s timeout.",
                retryable=True,
                recommended_action="Consider reducing image count or increasing GENERATION_TIMEOUT_SECONDS.",
            )
            _emit_event("progress", "validation", "Image description timed out, continuing.", 64)
        except Exception as exc:
            logger.warning(f"[WARNING] Image description error: {exc}")
            stage_result = {
                "status": "error",
                "error": str(exc),
                "pages_processed": 0,
                "pages_requested": image_loss_count,
                "pages_succeeded": 0,
                "pages_failed": image_loss_count,
            }
            _emit_model_lifecycle_event(
                "model.lifecycle.load_failed",
                model_role="vision",
                model_id=vision_model_id,
                stage_id="validation",
                status="failed",
                message_user=f"Vision model error: {exc}",
                progress=64,
                device=selected_device_hint,
                error_code="SUBPROCESS_EXCEPTION",
                reason_code=str(exc),
            )
            _emit_event("progress", "validation", f"Image description error: {exc}", 64)

        finally:
            # ── Release VLM worker lock ──────────────────────────────────────────
            try:
                fcntl.flock(lock_file, fcntl.LOCK_UN)
                lock_file.close()
                logger.info("[INFO] VLM worker lock released.")
            except Exception:
                pass

        return updated_markdown_path, stage_result, validation_report, manifest

    def _run_image_description_stage(
        self,
        *,
        doc_name: str,
        pdf_path: str,
        markdown_path: str,
        validation_path: Path,
        validation_report,
        manifest,
        manifest_path: Path,
        reviewer: str,
        page_markdown_map: Optional[Dict[int, str]],
        vlm_model: str,
        docling_version: str,
    ) -> tuple[str, str, dict[str, Any], Any, Any]:
        image_loss_count = _count_image_loss_pages(validation_report)

        if image_loss_count <= 0:
            logger.info("[OK] No image loss detected - skipping image description")
            _emit_event("progress", "validation", "No image loss detected, skipping description generation.", 64)
            markdown_content = self._read_markdown_content(markdown_path)
            return (
                markdown_path,
                markdown_content,
                {
                    "status": "skipped",
                    "reason": "no_image_loss",
                    "pages_processed": 0,
                    "pages_requested": 0,
                    "pages_succeeded": 0,
                    "pages_failed": 0,
                },
                validation_report,
                manifest,
            )

        logger.info(f"[INFO] Detected {image_loss_count} pages with image loss")
        logger.info(f"[INFO] Generating image descriptions with {vlm_model}...")
        logger.info("   This takes ~20-30 min...")
        _emit_event("progress", "validation",
                    f"Detected {image_loss_count} pages with image loss. Generating descriptions (~20-30 min)...", 56)

        markdown_enhanced_path = self.work_dir / f"{doc_name}_with_images.md"
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
        updated_markdown_path, stage_result, validation_report, manifest = (
            self._execute_image_description_subprocess(
                image_description_cmd=image_description_cmd,
                image_loss_count=image_loss_count,
                markdown_path=markdown_path,
                markdown_enhanced_path=markdown_enhanced_path,
                pdf_path=pdf_path,
                vlm_model=vlm_model,
                docling_version=docling_version,
                validation_path=validation_path,
                validation_report=validation_report,
                manifest=manifest,
                manifest_path=manifest_path,
                reviewer=reviewer,
                page_markdown_map=page_markdown_map,
            )
        )

        markdown_content = self._read_markdown_content(updated_markdown_path)
        return updated_markdown_path, markdown_content, stage_result, validation_report, manifest
    
    def run_full_pipeline(
        self,
        pdf_path: str,
        markdown_path: str,
        reviewer: str,
        docling_version: str = "1.0.0",
        vlm_model: Optional[str] = None,
        reformatter_model: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> Dict:
        """
        Run complete HITL pipeline with all improvements
        
        Returns pipeline result summary
        """
        logger.info("=" * 80)
        logger.info("[START] ENHANCED HITL PIPELINE - START")
        logger.info("=" * 80)

        vlm_model = vlm_model or get_vision_model_id()
        reformatter_model = reformatter_model or get_text_model_id()
        resolved_source_type = _resolve_source_type(
            source_path=pdf_path,
            explicit_source_type=source_type,
        )

        # GPU preflight transparency events (before any stage begins)
        # If required GPU is not available, fail immediately — CPU fallback is disabled.
        _gpu_preflight = _emit_gpu_runtime_events()
        if not _gpu_preflight.get("preflight_passed"):
            return {
                "document": Path(pdf_path).stem,
                "stages": {},
                "summary": {
                    "pipeline_status": "failed",
                    "review_required": False,
                    "error_code": _gpu_preflight.get("error_code", "GPU_PREFLIGHT_FAILED"),
                    "failure_reason": _gpu_preflight.get("failure_reason", "Required GPU not available"),
                    "recommended_action": _gpu_preflight.get(
                        "recommended_action", "Ensure the required GPU index is present and visible to this process."
                    ),
                    "next_action": "fix_gpu_configuration",
                },
            }

        _emit_event("stage_start", "extraction", "Stage 0: PDF → Markdown Extraction", 5,
                    step="Stage 0: PDF → Markdown Extraction")
        _emit_event("progress", "extraction", "Stage 0a: Sending PDF to Docling for conversion...", 6)
        markdown_path = self._ensure_docling_markdown(pdf_path, markdown_path)
        _emit_event(
            "progress",
            "extraction",
            "PDF extracted. Reusing canonical markdown for page-aligned validation slices.",
            14,
        )
        _emit_event("progress", "extraction", "Stage 0b: Building per-page markdown alignment map...", 16)
        page_markdown_map = self._build_validation_page_markdown_map(pdf_path)
        # For xlsx: bypass anchor-based matching; map each page directly to its ## sheet section.
        if resolved_source_type == "xlsx":
            page_markdown_map = _build_xlsx_page_markdown_map(markdown_path)
        _emit_event("progress", "extraction", "Stage 0c: Per-page markdown map ready.", 18)
        
        doc_name = Path(pdf_path).stem
        results = {"document": doc_name, "stages": {}}
        ce_artifact_path = _resolve_ce_artifact_path(Path(markdown_path))
        ce_artifact_exists = ce_artifact_path.exists() and ce_artifact_path.is_file()
        results["stages"]["docling_extraction"] = {
            "status": "complete",
            "output": str(markdown_path),
            "source_type": resolved_source_type,
            "image_mode": DOCLING_IMAGE_MODE,
            "ce_structured_artifact": str(ce_artifact_path) if ce_artifact_exists else None,
            "ce_extraction_enabled": _is_ce_extraction_enabled(),
        }
        
        # Stage 1: Create lineage manifest
        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 1: Create Document Manifest")
        logger.info("=" * 80)
        _emit_event("stage_start", "extraction", "Stage 1: Document Manifest", 20,
                    step="Stage 1: Document Manifest")
        
        manifest = create_document_manifest(
            pdf_path,
            docling_version,
            vlm_model,
            reformatter_model
        )
        manifest.primary_reviewer = reviewer
        manifest_path = self.work_dir / f"{doc_name}_manifest.json"
        save_manifest(manifest, str(manifest_path))
        _emit_event("progress", "extraction", f"Document manifest created for {doc_name}.", 23)
        
        results["stages"]["manifest"] = {
            "status": "complete",
            "output": str(manifest_path)
        }
        
        # Stage 2: Enhanced validation with the configured vision model
        logger.info("\n" + "=" * 80)
        logger.info(f"[STAGE] STAGE 2: VLM-Powered Validation ({vlm_model})")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 2: VLM-Powered Validation", 25,
                    step="Stage 2: VLM-Powered Validation")
        
        # First: Basic per-page evidence extraction
        logger.info("[INFO] Step 2a: Extracting per-page evidence...")
        _emit_event("progress", "validation", "Extracting per-page content evidence...", 26)
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
        _emit_event("progress", "validation",
                    f"Per-page evidence extracted "
                    f"({validation_report.metadata.get('total_issues', 0)} issues found).", 38)

        # Second: Deep VLM comparison (optional - can be skipped for speed)
        # Skip for xlsx — VLM comparison requires renderable page images; xlsx has none.
        if resolved_source_type != "xlsx":
            self._run_optional_vlm_comparison(
                markdown_path=markdown_path,
                pdf_path=pdf_path,
                validation_report=validation_report,
            )
        else:
            _emit_event("progress", "validation", "VLM deep comparison skipped (xlsx — no page images).", 55)
        
        results["stages"]["validation"] = {
            "status": "complete",
            "output": str(validation_path),
            "confidence": validation_report.overall_confidence,
            "total_issues": validation_report.metadata["total_issues"],
            "critical_issues": validation_report.metadata["critical_issues"]
        }
        
        # Stage 2b: VLM Image Description (if image loss detected)
        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 2b: VLM Image Description Generation")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 2b: VLM Image Description Generation", 55,
                    step="Stage 2b: VLM Image Description Generation")

        # Skip image description stage for xlsx — spreadsheets have no embedded images to describe.
        if resolved_source_type == "xlsx":
            markdown_content = self._read_markdown_content(markdown_path)
            image_stage_result = {
                "status": "skipped",
                "reason": "xlsx_no_images",
                "pages_processed": 0,
                "pages_requested": 0,
                "pages_succeeded": 0,
                "pages_failed": 0,
            }
            _emit_event("progress", "validation", "Image description skipped (xlsx — no embedded images).", 64)
        else:
            markdown_path, markdown_content, image_stage_result, validation_report, manifest = self._run_image_description_stage(
                doc_name=doc_name,
                pdf_path=pdf_path,
                markdown_path=markdown_path,
                validation_path=validation_path,
                validation_report=validation_report,
                manifest=manifest,
                manifest_path=manifest_path,
                reviewer=reviewer,
                page_markdown_map=page_markdown_map,
                vlm_model=vlm_model,
                docling_version=docling_version,
            )

        if image_stage_result.get("status") in {"complete", "partial"}:
            results["stages"]["validation"] = {
                "status": "complete",
                "output": str(validation_path),
                "confidence": validation_report.overall_confidence,
                "total_issues": validation_report.metadata["total_issues"],
                "critical_issues": validation_report.metadata["critical_issues"],
                "validated_markdown": image_stage_result.get("output"),
            }

        results["stages"]["image_descriptions"] = image_stage_result
        
        # Stage 3: Table and figure extraction
        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 3: Table and Figure Analysis")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 3: Table & Figure Analysis", 65,
                    step="Stage 3: Table & Figure Analysis")
        
        tables = extract_tables_from_pdf(pdf_path)
        figures = extract_figures_from_markdown(markdown_content)
        _emit_event("progress", "validation",
                    f"Extracted {len(tables)} table(s) and {len(figures)} figure(s).", 71)
        
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
        logger.info("[STAGE] STAGE 4: Create Page-Based Review Workspace")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 4: Building Review Workspace", 72,
                    step="Stage 4: Building Review Workspace")

        pages = extract_pages_from_validation(validation_report, doc_name)
        sections = extract_sections_from_markdown(markdown_content, doc_name)

        review_workspace = self.work_dir / f"{doc_name}_review"
        create_page_review_workspace(pages, str(review_workspace))
        create_review_workspace(sections, str(review_workspace))
        _emit_event("progress", "validation",
                    f"Review workspace ready: {pages.total_pages} pages, "
                    f"{sections.total_sections} sections.", 79)
        
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
        logger.info("[STAGE] STAGE 5: Create Initial Version")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 5: Versioning", 80,
                    step="Stage 5: Versioning")
        
        versions_dir = self.work_dir / f"{doc_name}_versions"
        manifest = create_version(
            manifest,
            markdown_content,
            str(versions_dir),
            version_notes="Initial extraction from Docling"
        )
        save_manifest(manifest, str(manifest_path))
        _emit_event("progress", "validation", "Initial v1 snapshot created.", 84)
        
        results["stages"]["versioning"] = {
            "status": "complete",
            "version": 1,
            "versions_dir": str(versions_dir)
        }
        
        # Stage 6: Compute QA metrics (pre-review)
        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 6: Compute Pre-Review QA Metrics")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 6: Pre-Review QA Metrics", 85,
                    step="Stage 6: Pre-Review QA Metrics")
        
        sections_for_qa, validation_dict = _build_qa_input_dicts(sections, validation_report)
        
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
        _emit_event("progress", "validation",
                    f"QA gate: {qa_result.decision} "
                    f"({len(qa_result.passed_criteria)} passed, "
                    f"{len(qa_result.failed_criteria)} failed).", 92)
        
        # Stage 7: Generate audit report
        logger.info("\n" + "=" * 80)
        logger.info("[STAGE] STAGE 7: Generate Audit Report")
        logger.info("=" * 80)
        _emit_event("stage_start", "validation", "Stage 7: Audit Report", 92,
                    step="Stage 7: Audit Report")
        
        audit_report = generate_audit_report(manifest)
        audit_path = self.work_dir / f"{doc_name}_audit.txt"
        
        with open(audit_path, 'w') as f:
            f.write(audit_report)
        
        logger.info(f"[INFO] Audit report: {audit_path}")
        _emit_event("progress", "validation", f"Audit trail written to {audit_path.name}.", 98)
        
        results["stages"]["audit"] = {
            "status": "complete",
            "output": str(audit_path)
        }
        
        # Pipeline summary
        logger.info("\n" + "=" * 80)
        logger.info("[OK] HITL PIPELINE COMPLETE")
        logger.info("=" * 80)
        logger.info("\n[SUMMARY] PIPELINE SUMMARY:")
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
        logger.info("\n[OUTPUTS]")
        logger.info(f"   Workspace: {self.work_dir}")
        logger.info(f"   Review Sections: {review_workspace}")
        logger.info(f"   Manifest: {manifest_path}")
        logger.info(f"   Audit: {audit_path}")
        
        # Next steps
        logger.info("\n[NEXT STEPS FOR REVIEWER]")
        logger.info(f"   1. Review pages in: {review_workspace}")
        logger.info(f"   2. Fill out checklists for each page")
        logger.info(f"   3. Address {len(qa_result.failed_criteria)} failed QA criteria")
        logger.info(f"   4. Focus on {validation_report.metadata['critical_issues']} critical issues")
        
        if qa_result.recommendations:
            logger.info("\n[RECOMMENDATIONS]")
            for rec in qa_result.recommendations[:5]:
                logger.info(f"   - {rec}")
        
        results["summary"] = {
            "pipeline_status": "complete",
            "review_required": True,
            "workspace": str(self.work_dir),
            "source_type": resolved_source_type,
            "next_action": "manual_review",
            "qa_decision": qa_result.decision
        }
        
        # Save pipeline results
        results_path = self.work_dir / f"{doc_name}_pipeline_results.json"
        with open(results_path, 'w') as f:
            json.dump(results, f, indent=2)
        
        logger.info(f"\n[INFO] Pipeline results saved: {results_path}")
        
        return results
    
    def run_post_approval_reformatting(
        self,
        doc_name: str,
        pdf_path: str,
        validation_report_path: str,
        markdown_path: Optional[str] = None,
        optimization_prep_path: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> Dict:
        """
        Run shared text-model reformatting AFTER manual review approval
        This is Stage 10 - final AI-powered optimization
        """
        try:
            # Import reformatter
            from ..cli.text_reformatter import reformat_with_qwen, save_output
            optimization_prep, markdown_content = _prepare_reformat_content(
                optimization_prep_path, markdown_path
            )

            # Load validation report
            with open(validation_report_path, 'r') as f:
                validation_data = json.load(f)

            # xlsx sources must not be sent through the LLM reformatter — it can corrupt
            # the matrix structure.  Check both the source file extension and the segment
            # flag set at optimization-prep build time.
            resolved_source_type = _resolve_source_type(
                source_path=pdf_path,
                explicit_source_type=source_type
                or str((optimization_prep or {}).get("source_type") or "").strip()
                or None,
            )
            # Run reformatting
            result = reformat_with_qwen(
                markdown_content,
                validation_data,
                pdf_path,
                doc_name,
                optimization_prep=optimization_prep,
            )
            
            if not result:
                logger.error("Reformatting returned no result")
                return {"status": "failed"}

            if not _has_structurally_valid_optimized_output(result):
                logger.error("Reformatting produced incomplete optimized output")
                return {
                    "status": "error",
                    "message": "Optimization output is incomplete and not suitable for QA",
                }

            output_base = self.work_dir / f"{doc_name}_rag_optimized"
            save_output(result, str(output_base))
            output_json = output_base.with_suffix('.json')
            output_md = output_base.with_suffix('.md')

            logger.info("Reformatting complete")

            return {
                "status": "complete",
                "json_output": str(output_json),
                "markdown_output": str(output_md)
            }
                
        except Exception as e:
            logger.error(f"Reformatting failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}
    
    def get_review_status(self, doc_name: str) -> Dict:
        """Get current review status for a document"""
        review_workspace = self.work_dir / f"{doc_name}_review"
        
        if not review_workspace.exists():
            return {"error": "Review workspace not found"}
        
        progress = get_review_progress(str(review_workspace))
        
        logger.info(f"[INFO] Review Progress for {doc_name}:")
        logger.info(f"   Total sections: {progress['total_sections']}")
        logger.info(f"   Completion: {progress['completion_percentage']:.1f}%")
        logger.info(f"   By status:")
        for status, count in progress['by_status'].items():
            logger.info(f"     {status}: {count}")
        
        return progress


def _log_pipeline_banner() -> None:
    logger.info("=" * 80)
    logger.info("[START] ENHANCED HITL PIPELINE ORCHESTRATOR")
    logger.info("=" * 80)


def _handle_run_action(args, pipeline: HITLPipeline) -> int:
    if not args.pdf or not args.markdown:
        logger.error("[ERROR] --pdf and --markdown required for run action")
        return 1

    try:
        results = pipeline.run_full_pipeline(
            args.pdf,
            args.markdown,
            args.reviewer,
            args.docling_version,
            args.vlm_model,
            args.reformatter_model,
            args.source_type,
        )
        logger.info("\n[OK] Pipeline execution complete")

        pipeline_status = results.get("summary", {}).get("pipeline_status", "unknown")
        if pipeline_status == "failed":
            error_code = results["summary"].get("error_code", "UNKNOWN")
            reason = results["summary"].get("failure_reason", "unknown failure")
            action = results["summary"].get("recommended_action", "")
            logger.error(f"\n[ERROR] Pipeline failed [{error_code}]: {reason}")
            if action:
                logger.error(f"   Action: {action}")
            return 1

        qa_decision = results.get("summary", {}).get("qa_decision")
        if qa_decision == "approved":
            logger.info("\n[OK] Document APPROVED")
            logger.info("   Next step: Run reformatting")
            logger.info(f"   Command: python3 rag_hitl_pipeline.py reformat --doc-name \"{Path(args.pdf).stem}\"")
        else:
            logger.info("\n[WARNING] Document needs review")
            review_output = results.get("stages", {}).get("review_workspace", {}).get("output", "N/A")
            logger.info(f"   Review workspace: {review_output}")

        return 0
    except Exception as exc:
        logger.error(f"[ERROR] Pipeline failed: {exc}", exc_info=True)
        return 1


def _handle_status_action(args, pipeline: HITLPipeline) -> int:
    if not args.doc_name:
        logger.error("[ERROR] --doc-name required for status action")
        return 1

    try:
        status = pipeline.get_review_status(args.doc_name)
        if "error" in status:
            logger.error(f"[ERROR] {status['error']}")
            return 1
        return 0
    except Exception as exc:
        logger.error(f"[ERROR] Status check failed: {exc}")
        return 1


def _resolve_reformat_inputs(args) -> tuple[str | None, str | None, str | None]:
    doc_name = args.doc_name or (Path(args.pdf).stem if args.pdf else None)
    if not doc_name:
        logger.error("[ERROR] --doc-name or --pdf required for reformat action")
        return None, None, None

    workspace = Path(args.workspace)
    validation_path = workspace / f"{doc_name}_validation.json"

    markdown_path = args.markdown
    if not markdown_path:
        version_path = workspace / f"{doc_name}_versions" / f"{doc_name}_v1.md"
        if version_path.exists():
            markdown_path = str(version_path)
        else:
            logger.error("[ERROR] --markdown required and could not auto-detect")
            return None, None, None

    return doc_name, str(validation_path), markdown_path


def _handle_reformat_action(args, pipeline: HITLPipeline) -> int:
    doc_name, validation_path, markdown_path = _resolve_reformat_inputs(args)
    if not doc_name or not validation_path or not markdown_path:
        return 1

    if not args.pdf:
        logger.error("[ERROR] --pdf required for reformat action")
        return 1

    try:
        logger.info(f"[INFO] Reformatting: {doc_name}")
        logger.info(f"   File: {args.pdf}")
        logger.info(f"   Markdown: {markdown_path}")
        logger.info(f"   Validation: {validation_path}")

        result = pipeline.run_post_approval_reformatting(
            doc_name,
            args.pdf,
            validation_path,
            markdown_path=markdown_path,
            source_type=args.source_type,
        )

        if result["status"] == "complete":
            logger.info("\n[OK] Reformatting complete")
            logger.info("   Ready for vector DB ingestion")
            return 0

        logger.error(f"\n[ERROR] Reformatting failed: {result.get('message', 'Unknown error')}")
        return 1
    except Exception as exc:
        logger.error(f"[ERROR] Reformat failed: {exc}", exc_info=True)
        return 1


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Enhanced HITL Pipeline Orchestrator"
    )
    parser.add_argument("action", choices=["run", "status", "reformat"],
                       help="Action to perform")
    parser.add_argument("--pdf", help="PDF or XLSX path (for run/reformat)")
    parser.add_argument("--markdown", help="Markdown path (for run/reformat)")
    parser.add_argument("--source-type", choices=["pdf", "xlsx"], help="Explicit source type override")
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
    _log_pipeline_banner()
    pipeline = HITLPipeline(args.workspace)

    if args.action == "run":
        return _handle_run_action(args, pipeline)
    if args.action == "status":
        return _handle_status_action(args, pipeline)
    return _handle_reformat_action(args, pipeline)


if __name__ == "__main__":
    sys.exit(main())
