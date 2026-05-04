"""Unit tests for app.api.pipeline._document_ops CE artifact summary helpers."""

from __future__ import annotations

import json
from pathlib import Path

import app.api.pipeline._document_ops as mod


def test_summarize_ce_structured_artifact_returns_expected_counts_and_schema(tmp_path: Path):
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    document_name = "testdoc"
    artifact_path = work_dir / f"{document_name}_ce_relations.json"

    artifact_payload = {
        "schema_version": "1.0",
        "causes": [{"cause_id": "cause_001"}],
        "effects": [{"effect_id": "effect_001"}, {"effect_id": "effect_002"}],
        "relations": [{"cause_id": "cause_001", "effect_id": "effect_001"}],
    }
    artifact_path.write_text(json.dumps(artifact_payload), encoding="utf-8")

    summary = mod._summarize_ce_structured_artifact(work_dir=work_dir, document_name=document_name)

    assert summary["schema_version"] == "1.0"
    assert summary["causes_count"] == 1
    assert summary["effects_count"] == 2
    assert summary["relations_count"] == 1
    assert summary["artifact_path"] == str(artifact_path)
