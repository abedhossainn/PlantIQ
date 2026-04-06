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
from typing import Optional
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
    _find_document_workspace,
    _find_manifest_path,
    _find_review_workspace,
    _find_table_figure_report_path,
    _load_json_file,
    _load_optional_json,
)
from ._review import _ensure_page_review_manifest

logger = logging.getLogger(__name__)


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
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))

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

        logger.info("Starting Stage 10 reformatting for %s in thread pool", document_id)
        pipeline_runner = HITLPipeline(str(work_root))

        _loop = asyncio.get_event_loop()
        _opt_handler = OptimizationLogHandler(document_id, _loop)
        _opt_logger_names = [
            "pipeline.src.cli.hitl_pipeline",
            "pipeline.src.cli.text_reformatter",
            "pipeline.src.utils.progress_tracker",
        ]
        for _lname in _opt_logger_names:
            logging.getLogger(_lname).addHandler(_opt_handler)

        result = None
        try:
            result = await asyncio.to_thread(
                pipeline_runner.run_post_approval_reformatting,
                doc_name=document_name,
                pdf_path=str(pdf_path),
                validation_report_path=str(validation_path),
                optimization_prep_path=optimization_prep_path,
            )
        finally:
            for _lname in _opt_logger_names:
                logging.getLogger(_lname).removeHandler(_opt_handler)

        if result.get("status") != "complete":
            _emit_optimization_log(
                document_id,
                "ERROR",
                result.get("message") or "Optimization stage failed",
            )
            OptimizationLogManager.close(document_id, "failed")
            closed_stream = True
            raise RuntimeError(result.get("message") or "Optimization stage failed")

        from ._chunks import _load_validated_optimized_output  # local import to avoid top-level cycle

        _load_validated_optimized_output(work_root)

        duration_seconds = int(time.monotonic() - started_monotonic)
        _emit_optimization_log(
            document_id,
            "INFO",
            f"Optimization completed in {duration_seconds}s",
        )

        if manifest_path and manifest_path.exists():
            manifest_record = load_manifest(str(manifest_path))
            manifest_record = update_manifest_timestamp(manifest_record, "reformatting", reviewer)
            save_manifest(manifest_record, str(manifest_path))

        async with _pipeline_pkg().AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.OPTIMIZATION_COMPLETE.value,
                review_progress=100,
                optimization_completed_at=_SET_NOW,
                optimization_error=_CLEAR,
            )

        OptimizationLogManager.close(document_id, "optimization-complete")
        closed_stream = True

    except Exception as exc:
        _emit_optimization_log(document_id, "ERROR", f"Optimization failed: {exc}")
        if not closed_stream:
            OptimizationLogManager.close(document_id, "failed")
        logger.error("Optimization stage failed for %s: %s", document_id, exc, exc_info=True)
        async with _pipeline_pkg().AsyncSessionLocal() as db:
            await _set_document_status(
                db,
                document_id,
                PipelineStatus.FAILED.value,
                review_progress=100,
                notes=str(exc),
                optimization_completed_at=_SET_NOW,
                optimization_error=str(exc),
            )


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
        optimization_prep = build_optimization_prep(
            document_id=str(document_id),
            document_name=document_name,
            review_dir=str(review_dir),
            validation_report=validation_report,
            table_figure_report=table_figure_report,
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
    import glob as _glob
    import json as _json
    from sqlalchemy import text as _text

    root = Path(settings.PIPELINE_WORK_DIR)
    index: dict[str, dict] = {}

    for m_path in _glob.glob(str(root / "*_manifest.json")):
        try:
            data = _json.loads(Path(m_path).read_text())
            name = data.get("document_name") or data.get("document", "")
            if name:
                index.setdefault(name, {})["total_pages"] = data.get("pdf_page_count")
        except Exception:
            pass

    for pr_path in _glob.glob(str(root / "*_pipeline_results.json")):
        try:
            data = _json.loads(Path(pr_path).read_text())
            name = data.get("document", "")
            if name:
                total_sections = (data.get("stages", {}).get("review_workspace") or {}).get("total_sections")
                if total_sections is not None:
                    index.setdefault(name, {})["total_sections"] = total_sections
        except Exception:
            pass

    for qa_pattern in ("*_qa_report.json", "*_qa_pre_review.json"):
        for qa_path in _glob.glob(str(root / qa_pattern)):
            try:
                data = _json.loads(Path(qa_path).read_text())
                name = data.get("document_name") or data.get("document", "")
                if name:
                    score = (data.get("metrics") or {}).get("overall_confidence_score")
                    if score is not None and (
                        "qa_score" not in index.setdefault(name, {})
                        or qa_pattern == "*_qa_report.json"
                    ):
                        index.setdefault(name, {})["qa_score"] = score
            except Exception:
                pass

    if not index:
        return docs

    enriched = []
    updates: list[dict] = []
    for doc in docs:
        title = doc["title"]
        meta = index.get(title, {})
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

    for u in updates:
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
                u,
            )
        except Exception as exc:
            logger.warning("Failed to persist metadata for %s: %s", u["doc_id"], exc)
    try:
        await db.commit()
    except Exception as exc:
        logger.warning("Failed to commit metadata updates: %s", exc)

    return enriched
