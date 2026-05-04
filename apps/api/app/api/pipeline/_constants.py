"""
Pipeline status constants, sentinel values, SQL queries, and artifact naming conventions.

All modules in the pipeline package import constants from here instead of
defining them locally, to ensure a single source of truth.
"""
from datetime import datetime, timezone

from ...models.pipeline import PipelineStatus, PublicationStatus  # noqa: F401 — re-exported for convenience

# ---------------------------------------------------------------------------
# Sentinel objects used by _set_document_status to distinguish between
# "leave unchanged", "set to NOW()", and "set to NULL".
# ---------------------------------------------------------------------------
_UNCHANGED = object()
_SET_NOW = object()
_CLEAR = object()

# ---------------------------------------------------------------------------
# SQL — complete list of columns returned by the documents listing query.
# Centralised here so any module reading documents gets the same projection.
# ---------------------------------------------------------------------------
_LIST_DOCUMENTS_SQL = """
    SELECT
        id, title, version, system, document_type,
        status, file_path, uploaded_by, notes,
        uploaded_at, updated_at,
        total_pages, total_sections, review_progress, qa_score,
        approved_by, approved_at,
        publication_status, published_at, publication_error,
        indexed_chunk_count, qdrant_collection
    FROM documents
    ORDER BY uploaded_at DESC
"""

# ---------------------------------------------------------------------------
# Pipeline status transition guard sets
# ---------------------------------------------------------------------------

# Any status occurring AFTER optimization decision initiated.
_POST_OPTIMIZATION_LIFECYCLE_STATUSES: set[str] = {
    PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    PipelineStatus.OPTIMIZING.value,
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
    PipelineStatus.QA_PASSED.value,
    PipelineStatus.FINAL_APPROVED.value,
}

# Statuses where document deletion is BLOCKED.
_DELETE_BLOCKED_STATUSES: set[str] = {
    PipelineStatus.UPLOADING.value,
    PipelineStatus.EXTRACTING.value,
    PipelineStatus.VLM_VALIDATING.value,
    PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    PipelineStatus.OPTIMIZING.value,
}

# Terminal states: no further status transitions allowed.
_FINALIZED_STATUSES: set[str] = {
    PipelineStatus.APPROVED.value,
    PipelineStatus.FINAL_APPROVED.value,
    PipelineStatus.REJECTED.value,
}

# Statuses where optimized RAG chunks are available for retrieval.
_OPTIMIZED_OUTPUT_AVAILABLE_STATUSES: set[str] = {
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
    PipelineStatus.QA_PASSED.value,
    PipelineStatus.FINAL_APPROVED.value,
}

# Statuses where optimized chunks can be edited by QA team.
_OPTIMIZED_OUTPUT_EDITABLE_STATUSES: set[str] = {
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
}

# Statuses that BLOCK the transition to APPROVED_FOR_OPTIMIZATION.
_APPROVE_FOR_OPTIMIZATION_BLOCKED_STATUSES: set[str] = {
    PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
    PipelineStatus.OPTIMIZING.value,
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
    PipelineStatus.QA_PASSED.value,
    PipelineStatus.FINAL_APPROVED.value,
    PipelineStatus.APPROVED.value,
    PipelineStatus.REJECTED.value,
}

# Statuses from which APPROVED_FOR_OPTIMIZATION is ALLOWED.
_APPROVE_FOR_OPTIMIZATION_ALLOWED_STATUSES: set[str] = {
    PipelineStatus.VALIDATION_COMPLETE.value,
    PipelineStatus.IN_REVIEW.value,
    PipelineStatus.REVIEW_COMPLETE.value,
    PipelineStatus.FAILED.value,
}

# Statuses eligible for QA rescoring and report auto-generation.
_QA_RESCORE_ALLOWED_STATUSES: set[str] = {
    PipelineStatus.OPTIMIZATION_COMPLETE.value,
    PipelineStatus.QA_REVIEW.value,
    PipelineStatus.QA_PASSED.value,
}

# Alias for clarity (same set as QA_RESCORE_ALLOWED).
_QA_REPORT_AUTOGEN_ELIGIBLE_STATUSES: set[str] = _QA_RESCORE_ALLOWED_STATUSES

# ---------------------------------------------------------------------------
# Artifact file naming conventions
# ---------------------------------------------------------------------------
_FLAT_ARTIFACT_SUFFIXES: list[str] = [
    "_validation.json",
    "_manifest.json",
    "_pipeline_results.json",
    "_qa_report.json",
    "_qa_pre_review.json",
    "_tables_figures.json",
    "_ce_relations.json",
    "_optimization_prep.json",
    "_rag_optimized.json",
    "_rag_optimized.md",
    "_audit.txt",
]

_FLAT_ARTIFACT_DIRECTORIES: list[str] = ["_review"]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def pipeline_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string ending with 'Z'."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def is_post_optimization_lifecycle(status_value: str | None) -> bool:
    """Return True when the status belongs to the post-optimization lifecycle."""
    return status_value in _POST_OPTIMIZATION_LIFECYCLE_STATUSES
