from __future__ import annotations

import queue
from pathlib import Path

from pipeline.src.cli.text_reformatter import (
    _build_segment_prompt_context,
    DEFAULT_REFORMATTER_PROMPT,
    _build_generation_segments,
    _coerce_chunk,
    _describe_generation_exception,
    _synthesize_chunks_from_optimization_prep,
    load_reformatter_prompt,
    normalize_reformatter_payload,
    parse_reformatter_response,
)
from pipeline.src.utils.vlm_options import VLMOptions, get_generation_timeout_seconds


def _sample_optimization_prep() -> dict:
    return {
        "document_name": "Sample LNG Document",
        "pages": [
            {
                "page_number": 1,
                "heading_candidates": ["Introduction to LNG"],
                "authoritative_markdown": "<!-- comment -->\n## Introduction to LNG\n\nLNG is stored at cryogenic temperature.",
                "table_facts": ["LNG is cryogenic"],
                "ambiguity_flags": ["Image caption incomplete"],
                "citations": [{"page_number": 1}],
            }
        ],
    }


def test_load_reformatter_prompt_uses_fallback_when_file_missing(tmp_path: Path):
    prompt = load_reformatter_prompt(tmp_path / "missing_prompt.md")

    assert prompt == DEFAULT_REFORMATTER_PROMPT
    assert "Return valid JSON only" in prompt


def test_parse_reformatter_response_recovers_partial_json():
    response = '''The user wants me to output JSON.
    {
      "document_name": "Sample LNG Document",
      "chunks": [
        {
          "heading": "Introduction to LNG",
          "content": "## What is LNG?\n\nLNG is stored at cryogenic temperature.\n\n[Source: Sample LNG Document, Page 1]",
          "source_pages": [1]
        }
      ]
    '''

    parsed = parse_reformatter_response(
        response,
        markdown_content="## Introduction to LNG\n\nLNG is stored at cryogenic temperature.",
        doc_name="Sample LNG Document",
        optimization_prep=_sample_optimization_prep(),
    )

    assert parsed["document_name"] == "Sample LNG Document"
    assert parsed["chunks"]
    assert parsed["chunks"][0]["source_pages"] == [1]
    assert "[Source: Sample LNG Document, Page 1]" in parsed["markdown"]


def test_normalize_reformatter_payload_synthesizes_chunks_when_missing_fields():
    normalized = normalize_reformatter_payload(
        {"summary": "done"},
        markdown_content="## Introduction to LNG\n\nLNG is stored at cryogenic temperature.",
        doc_name="Sample LNG Document",
        optimization_prep=_sample_optimization_prep(),
    )

    assert normalized["document_name"] == "Sample LNG Document"
    assert len(normalized["chunks"]) == 1
    assert normalized["chunks"][0]["heading"].endswith("?")
    assert normalized["chunks"][0]["table_facts"] == ["LNG is cryogenic"]
    assert normalized["chunks"][0]["ambiguity_flags"] == ["Image caption incomplete"]
    assert "[Source: Sample LNG Document, Page 1]" in normalized["chunks"][0]["content"]


def test_describe_generation_exception_uses_exception_type_for_empty_message():
    assert _describe_generation_exception(queue.Empty()) == "Empty"


def test_vlm_options_reads_generation_timeout_from_environment(monkeypatch):
    monkeypatch.setenv("GENERATION_TIMEOUT_SECONDS", "450")

    timeout_seconds = get_generation_timeout_seconds()
    options = VLMOptions()

    assert timeout_seconds == 450
    assert options.generation_timeout_seconds == 450


def test_build_generation_segments_prefers_segmented_optimization_prep():
    optimization_prep = {
        "segments": [
            {
                "segment_id": "segment_001",
                "title": "Introduction",
                "page_numbers": [1],
                "pages": _sample_optimization_prep()["pages"],
                "authoritative_markdown": "## Introduction to LNG\n\nLNG is cryogenic.",
            }
        ]
    }

    segments = _build_generation_segments("unused markdown", optimization_prep)

    assert len(segments) == 1
    assert segments[0]["title"] == "Introduction"


def test_build_generation_segments_collapses_page_metadata_into_full_document_segment():
    optimization_prep = {
        "pages": [
            {
                "page_number": 1,
                "heading_candidates": ["Introduction to LNG"],
                "table_facts": ["LNG is cryogenic"],
                "ambiguity_flags": ["Image caption incomplete"],
                "citations": [{"page_number": 1}],
            },
            {
                "page_number": 2,
                "heading_candidates": ["Storage"],
                "table_facts": ["Stored in tanks"],
                "ambiguity_flags": ["Unit label unclear"],
                "citations": [{"page_number": 2}],
            },
        ]
    }

    segments = _build_generation_segments("## Combined markdown", optimization_prep)

    assert len(segments) == 1
    assert segments[0]["page_numbers"] == [1, 2]
    assert segments[0]["heading_candidates"] == ["Introduction to LNG", "Storage"]
    assert segments[0]["table_facts"] == ["LNG is cryogenic", "Stored in tanks"]


def test_synthesize_chunks_from_optimization_prep_uses_text_preview_fallback():
    chunks = _synthesize_chunks_from_optimization_prep(
        markdown_content="",
        doc_name="Sample LNG Document",
        optimization_prep={
            "pages": [
                {
                    "page_number": 3,
                    "heading_candidates": ["Storage Overview"],
                    "text_preview": "Storage details are summarized here.",
                    "citations": [{"page_number": 3}],
                }
            ]
        },
    )

    assert len(chunks) == 1
    assert chunks[0]["source_pages"] == [3]
    assert "Storage details are summarized here." in chunks[0]["content"]
    assert "[Source: Sample LNG Document, Page 3]" in chunks[0]["content"]


def test_coerce_chunk_backfills_content_from_optimization_prep_page_markdown():
    coerced = _coerce_chunk(
        {
            "heading": "Overview",
            "source_pages": [1],
        },
        "Sample LNG Document",
        1,
        _sample_optimization_prep(),
    )

    assert coerced is not None
    assert coerced["source_pages"] == [1]
    assert "LNG is stored at cryogenic temperature." in coerced["content"]
    assert "[Source: Sample LNG Document, Page 1]" in coerced["content"]


def test_build_segment_prompt_context_includes_filtered_ce_relations_for_xlsx_segment():
    optimization_prep = {
        "ce_relations": {
            "schema_version": "1.0",
            "path_notation": {"relation": "<sheet>.rows[line:<n>].effects[column:<n>]"},
            "marker_semantics": {
                "X": {"semantic": "active_interlock", "description": "Active cause/effect linkage."}
            },
            "sheets": [
                {"sheet_name": "Area 200-1", "page_number": 3},
                {"sheet_name": "Area 300-1", "page_number": 4},
            ],
            "causes": [
                {"cause_id": "cause_001", "path_ref": "Area 200-1.rows[line:82].cause", "origin": {"sheet": "Area 200-1", "page_number": 3}},
                {"cause_id": "cause_999", "path_ref": "Area 300-1.rows[line:90].cause", "origin": {"sheet": "Area 300-1", "page_number": 4}},
            ],
            "effects": [
                {"effect_id": "effect_001", "path_ref": "Area 200-1.effects[column:7]", "origin": {"sheet": "Area 200-1", "page_number": 3}},
                {"effect_id": "effect_999", "path_ref": "Area 300-1.effects[column:8]", "origin": {"sheet": "Area 300-1", "page_number": 4}},
            ],
            "relations": [
                {"relation_id": "rel_0001", "cause_id": "cause_001", "effect_id": "effect_001", "path_ref": "Area 200-1.rows[line:82].effects[column:7]", "origin": {"sheet": "Area 200-1", "page_number": 3}},
                {"relation_id": "rel_9999", "cause_id": "cause_999", "effect_id": "effect_999", "path_ref": "Area 300-1.rows[line:90].effects[column:8]", "origin": {"sheet": "Area 300-1", "page_number": 4}},
            ],
        }
    }

    context = _build_segment_prompt_context(
        {
            "segment_id": "segment_003",
            "title": "Area 200-1",
            "page_numbers": [3],
            "pages": [
                {
                    "page_number": 3,
                    "heading_candidates": ["Area 200-1", "Reviewer summary"],
                    "text_preview": "Cause/effect review",
                    "table_facts": [],
                    "ambiguity_flags": [],
                    "citations": [{"page_number": 3}],
                }
            ],
        },
        "Sample XLSX",
        optimization_prep,
    )

    ce_context = context["ce_relations"]
    assert ce_context["filtered_counts"] == {"sheets": 1, "causes": 1, "effects": 1, "relations": 1}
    assert ce_context["relations"][0]["relation_id"] == "rel_0001"
    assert ce_context["causes"][0]["cause_id"] == "cause_001"
    assert ce_context["effects"][0]["effect_id"] == "effect_001"