from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from pipeline.src.review import section_review as mod


def test_section_has_images_recognizes_markdown_and_figure_text():
    assert mod._section_has_images("![alt](img.png)") is True
    assert mod._section_has_images("**[Figure 2: LNG tank]**") is True
    assert mod._section_has_images("No image") is False


def test_checklist_create_empty_complete_and_failed_items():
    checklist = mod.SectionChecklist.create_empty()
    assert checklist.is_complete() is False
    failed = checklist.get_failed_items()
    assert "Question headings" in failed

    checklist.question_headings.checked = True
    checklist.table_facts_extracted.checked = True
    checklist.figure_descriptions.checked = True
    checklist.citations_present.checked = True
    checklist.no_hallucinations.checked = True
    checklist.rag_optimized.checked = True
    assert checklist.is_complete() is True
    assert checklist.get_failed_items() == []


def test_extract_validation_report_context_for_dict_and_object():
    report_dict = {
        "document_name": "docA",
        "page_validations": [1, 2],
        "metadata": {"m": 1},
    }
    name, pages, meta = mod._extract_validation_report_context(report_dict)
    assert (name, pages, meta) == ("docA", [1, 2], {"m": 1})

    class _Obj:
        document_name = "docB"
        page_validations = [3]
        metadata = {"k": 2}

    name2, pages2, meta2 = mod._extract_validation_report_context(_Obj())
    assert (name2, pages2, meta2) == ("docB", [3], {"k": 2})


def test_extract_page_validation_fields_for_dict_and_object():
    d = {
        "page_number": 5,
        "markdown_section": "## H",
        "evidence": {"text_preview": "p"},
        "issues": [{"issue_type": "x"}],
    }
    assert mod._extract_page_validation_fields(d)[0] == 5

    class _Obj:
        page_number = 6
        markdown_section = "## J"
        evidence = {"text_preview": "q"}
        issues = [{"issue_type": "y"}]

    assert mod._extract_page_validation_fields(_Obj())[0] == 6


@dataclass
class _EvidenceDC:
    text_preview: str
    thumbnail_path: str


@dataclass
class _IssueDC:
    issue_type: str
    severity: str


def test_coerce_helpers_and_build_review_page():
    evidence = mod._coerce_evidence_dict(_EvidenceDC(text_preview="pv", thumbnail_path="a.png"))
    assert evidence["thumbnail_path"] == "a.png"

    issues = mod._coerce_issue_dicts([_IssueDC(issue_type="x", severity="major")])
    assert issues[0]["issue_type"] == "x"

    page = mod._build_review_page(
        page_number=1,
        markdown_content="## P1",
        evidence_dict=evidence,
        issue_dicts=issues,
    )
    assert page.page_id == "page_001"
    assert page.evidence_images == ["a.png"]


def test_extract_pages_from_validation_with_dict_payload():
    payload = {
        "document_name": "doc",
        "page_validations": [
            {
                "page_number": 1,
                "markdown_section": "## Page 1",
                "evidence": {"text_preview": "hello", "thumbnail_path": "t1.png"},
                "issues": [{"issue_type": "table_fidelity", "severity": "major"}],
            }
        ],
        "metadata": {"version": "v1"},
    }

    pages = mod.extract_pages_from_validation(payload)
    assert pages.document_name == "doc"
    assert pages.total_pages == 1
    assert pages.metadata["total_issues"] == 1
    assert pages.pages[0].evidence_images == ["t1.png"]


def test_create_page_review_workspace_writes_files(tmp_path: Path):
    pages = mod.DocumentPages(
        document_name="doc",
        total_pages=1,
        pages=[
            mod.ReviewPage(
                page_id="page_001",
                page_number=1,
                markdown_content="## P1\n\ncontent",
                text_preview="preview",
                validation_issues=[{"issue_type": "x"}],
                evidence_images=["img1.png"],
                evidence={"text_preview": "preview", "thumbnail_path": "img1.png"},
            )
        ],
        metadata={"meta": True},
    )

    workspace = mod.create_page_review_workspace(pages, str(tmp_path / "page_review"))
    assert (workspace / "page_001.md").exists()
    assert (workspace / "page_001_checklist.json").exists()

    manifest = json.loads((workspace / "page_review_manifest.json").read_text(encoding="utf-8"))
    assert manifest["review_unit"] == "page"
    assert manifest["pages"][0]["status"] == "pending"


def test_extract_sections_from_markdown_splits_by_heading():
    text = "intro\n## What is LNG?\ntext a\n## How stored?\ntext b"
    sections = mod.extract_sections_from_markdown(text, "doc")
    assert sections.total_sections == 2
    assert sections.sections[0].heading == "What is LNG?"
    assert sections.sections[1].has_tables is False


def test_create_markdown_section_and_append_helper():
    sec = mod._create_markdown_section(index=1, heading="H", content="C", start_line=0, end_line=1)
    assert sec.section_id == "section_001"

    out = []
    mod._append_current_section_if_any(out, "H", ["## H", "x"], 0, 1)
    assert len(out) == 1


def test_create_review_workspace_and_submit_review(tmp_path: Path):
    sections = mod.DocumentSections(
        document_name="doc",
        total_sections=1,
        sections=[
            mod.MarkdownSection(
                section_id="section_001",
                heading="What is LNG?",
                content="## What is LNG?\n\ntext",
                start_line=0,
                end_line=2,
                page_numbers=[1],
                word_count=4,
                has_tables=False,
                has_images=False,
            )
        ],
        metadata={},
    )

    workspace = mod.create_review_workspace(sections, str(tmp_path / "review"))
    checklist = mod.SectionChecklist.create_empty()
    checklist.question_headings.checked = True

    review = mod.submit_section_review(
        section_id="section_001",
        reviewer="qa",
        checklist=checklist,
        workspace_path=str(workspace),
    )

    assert review.status == mod.ReviewStatus.NEEDS_REWORK.value
    manifest = json.loads((workspace / "review_manifest.json").read_text(encoding="utf-8"))
    assert manifest["sections"][0]["status"] == mod.ReviewStatus.NEEDS_REWORK.value


def test_submit_section_review_approved_when_checklist_complete(tmp_path: Path):
    sections = mod.DocumentSections(
        document_name="doc",
        total_sections=1,
        sections=[
            mod.MarkdownSection(
                section_id="section_001",
                heading="H",
                content="## H",
                start_line=0,
                end_line=0,
                page_numbers=[],
                word_count=2,
                has_tables=False,
                has_images=False,
            )
        ],
        metadata={},
    )
    workspace = mod.create_review_workspace(sections, str(tmp_path / "review2"))

    c = mod.SectionChecklist.create_empty()
    c.question_headings.checked = True
    c.table_facts_extracted.checked = True
    c.figure_descriptions.checked = True
    c.citations_present.checked = True
    c.no_hallucinations.checked = True
    c.rag_optimized.checked = True

    r = mod.submit_section_review("section_001", "qa", c, workspace_path=str(workspace))
    assert r.status == mod.ReviewStatus.APPROVED.value


def test_reprocess_section_success_and_failure(tmp_path: Path):
    workspace = tmp_path / "rw"
    workspace.mkdir()
    section_file = workspace / "section_001.md"
    section_file.write_text("hello", encoding="utf-8")

    ok = mod.reprocess_section(
        "section_001",
        str(workspace),
        reformatter_func=lambda content: content.upper(),
    )
    assert ok is True
    assert (workspace / "section_001_reformatted.md").read_text(encoding="utf-8") == "HELLO"

    bad = mod.reprocess_section(
        "section_001",
        str(workspace),
        reformatter_func=lambda _content: (_ for _ in ()).throw(RuntimeError("x")),
    )
    assert bad is False


def test_get_review_progress_for_section_and_page_manifest(tmp_path: Path):
    ws1 = tmp_path / "s"
    ws1.mkdir()
    (ws1 / "review_manifest.json").write_text(
        json.dumps(
            {
                "sections": [
                    {"section_id": "a", "status": "APPROVED"},
                    {"section_id": "b", "status": "PENDING"},
                ]
            }
        ),
        encoding="utf-8",
    )
    p1 = mod.get_review_progress(str(ws1))
    assert p1["total_sections"] == 2
    assert p1["completion_percentage"] == 50.0

    ws2 = tmp_path / "p"
    ws2.mkdir()
    (ws2 / "page_review_manifest.json").write_text(
        json.dumps(
            {
                "pages": [
                    {"page_id": "p1", "status": "reviewed"},
                    {"page_id": "p2", "status": "pending"},
                ]
            }
        ),
        encoding="utf-8",
    )
    p2 = mod.get_review_progress(str(ws2))
    assert p2["completion_percentage"] == 50.0


def test_main_extract_progress_review_and_missing_markdown(monkeypatch, tmp_path: Path):
    import sys

    md = tmp_path / "doc.md"
    md.write_text("## Q\nA", encoding="utf-8")
    workspace = tmp_path / "ws"

    # extract success
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "section_review.py",
            "extract",
            "--markdown",
            str(md),
            "--workspace",
            str(workspace),
        ],
    )
    assert mod.main() == 0

    # progress success
    monkeypatch.setattr(sys, "argv", ["section_review.py", "progress", "--workspace", str(workspace)])
    assert mod.main() == 0

    # review action no-op success
    monkeypatch.setattr(sys, "argv", ["section_review.py", "review", "--workspace", str(workspace)])
    assert mod.main() == 0

    # extract missing markdown
    monkeypatch.setattr(sys, "argv", ["section_review.py", "extract", "--workspace", str(workspace)])
    assert mod.main() == 1
