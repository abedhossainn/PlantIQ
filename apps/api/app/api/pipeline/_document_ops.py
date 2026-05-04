"""
Document operation helpers: optimization stage execution, RAG publishing,
approval orchestration, metadata enrichment, and publication status normalization.
"""
import asyncio
import importlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Optional
from uuid import NAMESPACE_URL, uuid5

from fastapi import BackgroundTasks, HTTPException, status
from pydantic import UUID4
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import REPO_ROOT, get_artifacts_path, settings
from ...core.optimization_log import OptimizationLogHandler, OptimizationLogManager
from ...models.pipeline import PipelineStatus, PublicationStatus
from ...services.embedding_service import EmbeddingService
from ...services.qdrant_service import QdrantService


def _pipeline_pkg():
    """Late-bound import of the pipeline package to allow test monkeypatching."""
    return importlib.import_module(__package__)


from ._chunks import _build_publishable_chunks
from ._constants import _CLEAR, _SET_NOW, _UNCHANGED, pipeline_timestamp
from ._constants import _APPROVE_FOR_OPTIMIZATION_ALLOWED_STATUSES, _APPROVE_FOR_OPTIMIZATION_BLOCKED_STATUSES
from ._db_ops import (
    _ensure_status_in,
    _ensure_status_not_in,
    _require_document_status,
    _set_document_status,
)
from ._filesystem import (
    _candidate_work_roots,
    _find_document_workspace,
    _find_manifest_path,
    _find_review_workspace,
    _find_table_figure_report_path,
    _load_json_file,
    _load_optional_json,
)
from ._review import _ensure_page_review_manifest

logger = logging.getLogger(__name__)


def _summarize_ce_structured_artifact(work_dir: Path, document_name: str) -> dict[str, Any] | None:
    """Return lightweight CE artifact summary if a structured relations file exists."""
    candidates = [
        work_dir / f"{document_name}_ce_relations.json",
        work_dir / "ce_relations.json",
    ]
    artifact_path = next((path for path in candidates if path.exists() and path.is_file()), None)
    if artifact_path is None:
        return None

    payload = _load_optional_json(artifact_path)
    if not payload:
        return {
            "artifact_path": str(artifact_path),
            "schema_version": None,
            "causes_count": 0,
            "effects_count": 0,
            "relations_count": 0,
        }

    return {
        "artifact_path": str(artifact_path),
        "schema_version": payload.get("schema_version"),
        "causes_count": len(payload.get("causes") or []),
        "effects_count": len(payload.get("effects") or []),
        "relations_count": len(payload.get("relations") or []),
    }


def _ensure_repo_root_on_syspath() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _resolve_optimization_context(
    *,
    work_root: Path,
    document_id: str,
) -> tuple[Path | None, Path, str, str]:
    manifest_path = _find_manifest_path(work_root)
    validation_path = get_artifacts_path(document_id, "validation")
    if not validation_path.exists():
        raise FileNotFoundError("Validation artifact not found for optimization")

    manifest = _load_optional_json(manifest_path)
    document_name = str(
        manifest.get("document_name")
        or validation_path.name.replace("_validation.json", "")
    )
    pdf_path = manifest.get("pdf_path")
    if not pdf_path:
        raise FileNotFoundError("Manifest is missing source PDF path")

    return manifest_path, validation_path, document_name, str(pdf_path)


def _attach_optimization_log_handler(document_id: str, loop: asyncio.AbstractEventLoop) -> OptimizationLogHandler:
    handler = OptimizationLogHandler(document_id, loop)
    for logger_name in (
        "pipeline.src.cli.hitl_pipeline",
        "pipeline.src.cli.text_reformatter",
        "pipeline.src.utils.progress_tracker",
    ):
        logging.getLogger(logger_name).addHandler(handler)
    return handler


def _detach_optimization_log_handler(handler: OptimizationLogHandler) -> None:
    for logger_name in (
        "pipeline.src.cli.hitl_pipeline",
        "pipeline.src.cli.text_reformatter",
        "pipeline.src.utils.progress_tracker",
    ):
        logging.getLogger(logger_name).removeHandler(handler)


async def _set_optimization_completed_status(document_id: str) -> None:
    async with _pipeline_pkg().AsyncSessionLocal() as db:
        await _set_document_status(
            db,
            document_id,
            PipelineStatus.OPTIMIZATION_COMPLETE.value,
            review_progress=100,
            optimization_completed_at=_SET_NOW,
            optimization_error=_CLEAR,
        )


async def _set_optimization_failed_status(document_id: str, message: str) -> None:
    async with _pipeline_pkg().AsyncSessionLocal() as db:
        await _set_document_status(
            db,
            document_id,
            PipelineStatus.FAILED.value,
            review_progress=100,
            notes=message,
            optimization_completed_at=_SET_NOW,
            optimization_error=message,
        )


def _build_qdrant_chunks(
    *,
    document_id: str,
    document_title: str,
    system: Optional[str],
    document_type: Optional[str],
    publishable_chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> list[dict[str, object]]:
    workspace = str(system or "").strip()
    normalized_workspace = workspace.lower() if workspace else None
    is_shared_document = normalized_workspace in {"shared", "global", "cross-functional"}

    qdrant_chunks: list[dict[str, object]] = []
    for index, (chunk, vector) in enumerate(zip(publishable_chunks, embeddings, strict=True), start=1):
        source_pages = [int(page) for page in chunk.get("source_pages") or []]
        point_id = str(uuid5(NAMESPACE_URL, f"{document_id}:{chunk['id'] or index}"))
        qdrant_chunks.append(
            {
                "id": point_id,
                "vector": vector,
                "payload": {
                    "chunk_id": chunk["id"],
                    "document_id": document_id,
                    "document_title": document_title,
                    "system": system,
                    "workspace": normalized_workspace,
                    "document_type": document_type,
                    "is_shared": is_shared_document,
                    "content": chunk["markdown_content"],
                    "section_heading": chunk["heading"],
                    "page_number": source_pages[0] if source_pages else None,
                    "source_pages": source_pages,
                    "table_facts": chunk.get("table_facts") or [],
                    "ambiguity_flags": chunk.get("ambiguity_flags") or [],
                },
            }
        )
    return qdrant_chunks


def _iter_artifact_paths(pattern: str):
    seen: set[Path] = set()
    for root in _candidate_work_roots():
        if not root.exists():
            continue
        for path in sorted(root.rglob(pattern)):
            if not path.is_file():
                continue
            resolved = path.resolve(strict=False)
            if resolved in seen:
                continue
            seen.add(resolved)
            yield path


def _index_total_pages(index: dict[str, dict[str, Any]]) -> None:
    for manifest_path in _iter_artifact_paths("*_manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        name = data.get("document_name") or data.get("document", "")
        if name:
            index.setdefault(name, {})["total_pages"] = data.get("pdf_page_count")


def _index_total_sections(index: dict[str, dict[str, Any]]) -> None:
    for pipeline_results_path in _iter_artifact_paths("*_pipeline_results.json"):
        try:
            data = json.loads(pipeline_results_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        name = data.get("document", "")
        if not name:
            continue

        total_sections = (data.get("stages", {}).get("review_workspace") or {}).get("total_sections")
        if total_sections is not None:
            index.setdefault(name, {})["total_sections"] = total_sections


def _index_qa_scores(index: dict[str, dict[str, Any]]) -> None:
    for qa_pattern in ("*_qa_report.json", "*_qa_pre_review.json"):
        for qa_path in _iter_artifact_paths(qa_pattern):
            _index_qa_score_from_path(index, qa_pattern, qa_path)


def _index_qa_score_from_path(
    index: dict[str, dict[str, Any]],
    qa_pattern: str,
    qa_path: Path,
) -> None:
    try:
        data = json.loads(qa_path.read_text(encoding="utf-8"))
    except Exception:
        return

    name = data.get("document_name") or data.get("document", "")
    if not name:
        return

    score = (data.get("metrics") or {}).get("overall_confidence_score")
    if score is None:
        return

    should_set_score = (
        "qa_score" not in index.setdefault(name, {})
        or qa_pattern == "*_qa_report.json"
    )
    if should_set_score:
        index.setdefault(name, {})["qa_score"] = score


def _apply_metadata_enrichment(
    docs: list[dict[str, Any]],
    index: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    for doc in docs:
        meta = index.get(doc["title"], {})
        new_doc = dict(doc)
        changed = False

        if doc["totalPages"] is None and "total_pages" in meta:
            new_doc["totalPages"] = meta["total_pages"]
            changed = True
        if doc["totalSections"] is None and "total_sections" in meta:
            new_doc["totalSections"] = meta["total_sections"]
            changed = True
        if doc["qaScore"] is None and "qa_score" in meta:
            new_doc["qaScore"] = float(meta["qa_score"])
            changed = True

        if changed:
            updates.append(
                {
                    "doc_id": doc["id"],
                    "tp": new_doc["totalPages"],
                    "ts": new_doc["totalSections"],
                    "qs": new_doc["qaScore"],
                }
            )

        enriched.append(new_doc)

    return enriched, updates


async def _persist_metadata_updates(db: AsyncSession, updates: list[dict[str, Any]]) -> None:
    if not updates:
        return

    from sqlalchemy import text as _text

    for update_payload in updates:
        try:
            await db.execute(
                _text(
                    """
                    UPDATE documents
                    SET total_pages    = COALESCE(total_pages,    :tp),
                        total_sections = COALESCE(total_sections, :ts),
                        qa_score       = COALESCE(qa_score,       :qs),
                        updated_at     = NOW()
                    WHERE id = :doc_id
                    """
                ),
                update_payload,
            )
        except Exception as exc:
            logger.warning("Failed to persist metadata for %s: %s", update_payload["doc_id"], exc)

    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to commit metadata updates: %s", exc)


# ---------------------------------------------------------------------------
# Publication status normalization
# ---------------------------------------------------------------------------

def _normalize_publication_status(
    document_status: Optional[str],
    publication_status: Optional[str],
) -> Optional[str]:
    if publication_status:
        return publication_status
    if document_status == PipelineStatus.FINAL_APPROVED.value:
        return PublicationStatus.PENDING.value
    return None


# ---------------------------------------------------------------------------
# Optimization log emission
# ---------------------------------------------------------------------------

def _emit_optimization_log(document_id: str, level: str, message: str) -> None:
    normalized_level = level.upper()
    if normalized_level not in {"INFO", "WARNING", "ERROR"}:
        normalized_level = "INFO"
    OptimizationLogManager.publish_line(
        document_id,
        {
            "timestamp": pipeline_timestamp(),
            "level": normalized_level,
            "message": message,
        },
    )


# ---------------------------------------------------------------------------
# Stage 10 optimization runner
# ---------------------------------------------------------------------------

async def _execute_optimization_stage(
    *,
    document_id: str,
    reviewer: str,
    work_dir: str,
    optimization_prep_path: str,
) -> None:
    work_root = Path(work_dir)
    OptimizationLogManager.start(document_id)
    closed_stream = False
    started_monotonic = time.monotonic()
    try:
        _ensure_repo_root_on_syspath()
        manifest_path, validation_path, document_name, pdf_path = _resolve_optimization_context(
            work_root=work_root,
            document_id=document_id,
        )

        from pipeline.src.cli.hitl_pipeline import HITLPipeline  # noqa: WPS433
        from pipeline.src.lineage.lineage_tracker import (  # noqa: WPS433
            load_manifest,
            save_manifest,
            update_manifest_timestamp,
        )

        async with _pipeline_pkg().AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.OPTIMIZING.value,
                review_progress=100,
                optimization_started_at=_SET_NOW,
                optimization_completed_at=_CLEAR,
                optimization_error=_CLEAR,
            )

        _emit_optimization_log(document_id, "INFO", "Optimization started")
        _emit_optimization_log(document_id, "INFO", "Stage 1: Model Initialization")

        logger.info("Starting Stage 10 reformatting for %s in thread pool", document_id)
        pipeline_runner = HITLPipeline(str(work_root))

        _loop = asyncio.get_event_loop()
        _opt_handler = _attach_optimization_log_handler(document_id, _loop)

        _emit_optimization_log(document_id, "INFO", "Stage 2: Text Generation")
        result = None
        try:
            result = await asyncio.to_thread(
                pipeline_runner.run_post_approval_reformatting,
                doc_name=document_name,
                pdf_path=pdf_path,
                validation_report_path=str(validation_path),
                optimization_prep_path=optimization_prep_path,
            )
        finally:
            _detach_optimization_log_handler(_opt_handler)

        if result.get("status") != "complete":
            _emit_optimization_log(
                document_id,
                "ERROR",
                result.get("message") or "Optimization stage failed",
            )
            OptimizationLogManager.close(document_id, "failed")
            closed_stream = True
            raise RuntimeError(result.get("message") or "Optimization stage failed")

        _emit_optimization_log(document_id, "INFO", "Stage 3: Output Validation")
        from ._chunks import _load_validated_optimized_output  # local import to avoid top-level cycle

        _load_validated_optimized_output(work_root)

        duration_seconds = int(time.monotonic() - started_monotonic)
        _emit_optimization_log(
            document_id,
            "INFO",
            f"Optimization completed in {duration_seconds}s",
        )

        _emit_optimization_log(document_id, "INFO", "Stage 4: Artifact Export")
        if manifest_path and manifest_path.exists():
            manifest_record = load_manifest(str(manifest_path))
            manifest_record = update_manifest_timestamp(manifest_record, "reformatting", reviewer)
            save_manifest(manifest_record, str(manifest_path))

        await _set_optimization_completed_status(document_id)

        OptimizationLogManager.close(document_id, "optimization-complete")
        closed_stream = True

    except Exception as exc:
        _emit_optimization_log(document_id, "ERROR", f"Optimization failed: {exc}")
        if not closed_stream:
            OptimizationLogManager.close(document_id, "failed")
        logger.error("Optimization stage failed for %s: %s", document_id, exc, exc_info=True)
        await _set_optimization_failed_status(document_id, str(exc))


# ---------------------------------------------------------------------------
# RAG publishing
# ---------------------------------------------------------------------------

async def _publish_document_to_rag(
    *,
    document_id: str,
    document_title: str,
    system: Optional[str],
    document_type: Optional[str],
    work_dir: Path,
) -> dict[str, object]:
    publishable_chunks = _build_publishable_chunks(work_dir)
    chunk_contents = [chunk["markdown_content"] for chunk in publishable_chunks]

    if not await QdrantService.ensure_collection():
        raise RuntimeError("Failed to ensure Qdrant collection exists")

    embeddings = await EmbeddingService.embed_batch(chunk_contents)
    if len(embeddings) != len(publishable_chunks):
        raise RuntimeError("Embedding generation returned an unexpected number of vectors")

    if not await QdrantService.delete_document_chunks(document_id):
        raise RuntimeError("Failed to clear existing Qdrant chunks for this document")

    qdrant_chunks = _build_qdrant_chunks(
        document_id=document_id,
        document_title=document_title,
        system=system,
        document_type=document_type,
        publishable_chunks=publishable_chunks,
        embeddings=embeddings,
    )

    if not await QdrantService.upsert_chunks(qdrant_chunks):
        raise RuntimeError("Failed to upsert optimized chunks into Qdrant")

    return {
        "indexed_chunk_count": len(qdrant_chunks),
        "qdrant_collection": settings.QDRANT_COLLECTION,
    }


# ---------------------------------------------------------------------------
# Approve-for-optimization orchestration
# ---------------------------------------------------------------------------

async def _approve_for_optimization(
    document_id: UUID4,
    background_tasks: BackgroundTasks,
    current_user_id: str,
    db: AsyncSession,
) -> dict:
    """Generate optimization-prep artifacts and trigger Stage 10 after fidelity review."""
    try:
        document_status = await _require_document_status(document_id, db)
        _ensure_status_not_in(
            current_status=document_status,
            blocked_statuses=_APPROVE_FOR_OPTIMIZATION_BLOCKED_STATUSES,
            detail=f"Cannot approve document in {document_status} status",
        )
        _ensure_status_in(
            current_status=document_status,
            allowed_statuses=_APPROVE_FOR_OPTIMIZATION_ALLOWED_STATUSES,
            detail=(
                "Approve for optimization is only available for documents in "
                "validation-complete, in-review, review-complete, or failed status"
            ),
            error_status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

        work_dir = _find_document_workspace(document_id, require_document_dir=True)
        review_dir = _find_review_workspace(document_id)
        page_manifest = _ensure_page_review_manifest(review_dir, work_dir)

        validation_path = get_artifacts_path(str(document_id), "validation")
        if not validation_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Validation artifact not found for this document",
            )

        _manifest_path, _resolved_validation_path, _resolved_document_name, source_path = _resolve_optimization_context(
            work_root=work_dir,
            document_id=str(document_id),
        )

        validation_report = _load_json_file(validation_path)
        table_figure_report = _load_optional_json(_find_table_figure_report_path(work_dir))

        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

        from pipeline.src.cli.hitl_pipeline import build_optimization_prep  # noqa: WPS433

        document_name = (
            page_manifest.get("document_name")
            or validation_report.get("document_name")
            or str(document_id)
        )
        ce_structured_artifact = _summarize_ce_structured_artifact(work_dir, document_name)
        optimization_prep = build_optimization_prep(
            document_id=str(document_id),
            document_name=document_name,
            review_dir=str(review_dir),
            validation_report=validation_report,
            table_figure_report=table_figure_report,
            ce_structured_artifact=ce_structured_artifact,
            source_path=source_path,
        )

        optimization_prep_path = work_dir / f"{document_name}_optimization_prep.json"
        optimization_prep_path.write_text(
            json.dumps(optimization_prep, indent=2), encoding="utf-8"
        )

        await _set_document_status(
            db,
            document_id,
            PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            review_progress=100,
            optimization_started_at=_CLEAR,
            optimization_completed_at=_CLEAR,
            optimization_error=_CLEAR,
        )
        background_tasks.add_task(
            _pipeline_pkg()._execute_optimization_stage,
            document_id=str(document_id),
            reviewer=str(current_user_id),
            work_dir=str(work_dir),
            optimization_prep_path=str(optimization_prep_path),
        )

        return {
            "document_id": str(document_id),
            "status": PipelineStatus.APPROVED_FOR_OPTIMIZATION.value,
            "optimization_triggered": True,
            "optimization_prep_path": str(optimization_prep_path),
            "ce_structured_artifact_path": (ce_structured_artifact or {}).get("artifact_path"),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Error approving optimization for %s: %s", document_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve document for optimization",
        )


# ---------------------------------------------------------------------------
# Metadata enrichment
# ---------------------------------------------------------------------------

async def _enrich_metadata_from_artifacts(docs: list, db: AsyncSession) -> list:
    """Read pipeline artifact files to populate totalPages/totalSections/qaScore for docs with NULL metadata."""
    index: dict[str, dict[str, Any]] = {}
    _index_total_pages(index)
    _index_total_sections(index)
    _index_qa_scores(index)

    if not index:
        return docs
    enriched, updates = _apply_metadata_enrichment(docs, index)
    await _persist_metadata_updates(db, updates)

    return enriched
