"""
Filesystem helpers: workspace discovery, artifact path resolution, and storage cleanup.

All file-system operations (finding work directories, loading JSON artifacts,
collecting and deleting document storage) live here so that route handlers and
service modules have a single, tested surface for I/O.
"""
import json
import shutil
from pathlib import Path
from typing import Optional

from fastapi import HTTPException, status

from ...core.config import REPO_ROOT, settings
from ._constants import _FLAT_ARTIFACT_SUFFIXES, _FLAT_ARTIFACT_DIRECTORIES


# ---------------------------------------------------------------------------
# Workspace discovery
# ---------------------------------------------------------------------------

def _candidate_work_roots() -> list[Path]:
    configured_root = Path(settings.PIPELINE_WORK_DIR).expanduser()
    roots = [configured_root]

    if not configured_root.is_absolute():
        relative_root = Path(str(configured_root).lstrip("./"))
        roots.extend(
            [
                REPO_ROOT / relative_root,
                REPO_ROOT / "backend" / relative_root,
            ]
        )
    elif (
        configured_root.name == "hitl_workspace"
        and configured_root.parent.name == "artifacts"
        and configured_root.parent.parent.name == "data"
    ):
        absolute_base = configured_root.parent.parent.parent
        roots.extend(
            [
                absolute_base / "backend" / "data" / "artifacts" / "hitl_workspace",
                absolute_base.parent / "data" / "artifacts" / "hitl_workspace"
                if absolute_base.name == "backend"
                else absolute_base / "data" / "artifacts" / "hitl_workspace",
            ]
        )

    roots.extend(
        [
            REPO_ROOT / "data" / "artifacts" / "hitl_workspace",
            REPO_ROOT / "backend" / "data" / "artifacts" / "hitl_workspace",
        ]
    )

    unique_roots: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved not in seen:
            seen.add(resolved)
            unique_roots.append(resolved)

    return unique_roots


def _find_document_workspace(document_id, *, require_document_dir: bool = False) -> Path:
    for root in _candidate_work_roots():
        document_dir = root / str(document_id)
        if document_dir.exists():
            return document_dir

    if require_document_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review workspace not found for this document",
        )

    for root in _candidate_work_roots():
        if root.exists():
            return root

    return _candidate_work_roots()[0]


def _find_review_workspace(document_id) -> Path:
    work_dir = _find_document_workspace(document_id)
    review_dirs = sorted(work_dir.glob("*_review"))
    if review_dirs:
        return review_dirs[0]

    if work_dir not in _candidate_work_roots():
        for root in _candidate_work_roots():
            root_review_dirs = sorted(root.glob("*_review"))
            if root_review_dirs:
                return root_review_dirs[0]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Review workspace not found for this document",
    )


def _find_validation_report(work_dir: Path) -> Path:
    validation_files = sorted(work_dir.glob("*_validation.json"))
    if validation_files:
        return validation_files[0]

    for root in _candidate_work_roots():
        root_validation_files = sorted(root.glob("*_validation.json"))
        if root_validation_files:
            return root_validation_files[0]

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Validation report not found for this document",
    )


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def _load_json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional_json(path: Optional[Path]) -> dict:
    if path is None or not path.exists() or not path.is_file():
        return {}
    return _load_json_file(path)


def _load_artifact_manifest(path: Path) -> dict:
    try:
        return _load_json_file(path)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Artifact path helpers
# ---------------------------------------------------------------------------

def _find_manifest_path(work_dir: Path) -> Optional[Path]:
    manifest_files = sorted(work_dir.glob("*_manifest.json"))
    return manifest_files[0] if manifest_files else None


def _find_table_figure_report_path(work_dir: Path) -> Optional[Path]:
    report_files = sorted(work_dir.glob("*_tables_figures.json"))
    return report_files[0] if report_files else None


def _find_optimized_artifact_paths(work_dir: Path) -> tuple[Optional[Path], Optional[Path]]:
    optimized_json = sorted(work_dir.glob("*_rag_optimized.json"))
    optimized_markdown = sorted(work_dir.glob("*_rag_optimized.md"))
    return (
        optimized_json[0] if optimized_json else None,
        optimized_markdown[0] if optimized_markdown else None,
    )


# ---------------------------------------------------------------------------
# Storage cleanup
# ---------------------------------------------------------------------------

def _collect_document_cleanup_paths(
    *,
    document_id,
    document_title: Optional[str],
    file_path: Optional[str],
) -> list[Path]:
    seen: set[Path] = set()
    paths: list[Path] = []

    def _add(candidate: Path) -> None:
        resolved = candidate.resolve(strict=False)
        if resolved in seen or not candidate.exists():
            return
        seen.add(resolved)
        paths.append(candidate)

    document_id_str = str(document_id)
    normalized_file_path = str(file_path or "").strip()
    normalized_title = str(document_title or "").strip()

    if normalized_file_path:
        _add(Path(normalized_file_path))

    cleanup_roots: list[Path] = []
    for root in [*_candidate_work_roots(), Path(settings.ARTIFACTS_DIR).expanduser().resolve()]:
        resolved = root.resolve(strict=False)
        if resolved not in cleanup_roots:
            cleanup_roots.append(resolved)

    for root in cleanup_roots:
        _add(root / document_id_str)

        for manifest_path in sorted(root.glob("*_manifest.json")):
            manifest_payload = _load_artifact_manifest(manifest_path)
            manifest_pdf_path = str(manifest_payload.get("pdf_path") or "").strip()
            manifest_document_id = str(manifest_payload.get("document_id") or "").strip()
            manifest_document_name = str(manifest_payload.get("document_name") or "").strip()

            if not any(
                [
                    manifest_document_id == document_id_str,
                    normalized_file_path and manifest_pdf_path == normalized_file_path,
                    normalized_title and manifest_document_name == normalized_title,
                ]
            ):
                continue

            stem = manifest_path.name[: -len("_manifest.json")]
            for suffix in _FLAT_ARTIFACT_SUFFIXES:
                _add(root / f"{stem}{suffix}")
            for directory_suffix in _FLAT_ARTIFACT_DIRECTORIES:
                _add(root / f"{stem}{directory_suffix}")

    return paths


def _delete_document_storage(
    *,
    document_id,
    document_title: Optional[str],
    file_path: Optional[str],
) -> list[str]:
    deleted_paths: list[str] = []
    for path in _collect_document_cleanup_paths(
        document_id=document_id,
        document_title=document_title,
        file_path=file_path,
    ):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted_paths.append(str(path))
    return deleted_paths
