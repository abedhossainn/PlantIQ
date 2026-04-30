from pipeline.src.qa.qa_gates import calculate_overall_confidence_score, calculate_table_to_bullets_ratio, compute_qa_metrics


def test_table_ratio_uses_structured_table_facts_without_markdown_bullets():
    sections = [
        {
            "heading": "What does the table show about LNG properties?",
            "content": (
                "## LNG Properties\n\n"
                "| Parameter | Methane | Ethane |\n"
                "| --- | --- | --- |\n"
                "| Molecular Weight | 16 | 30 |\n"
                "| Specific Gravity | 0.3 | 0.36 |\n"
                "\n[Source: sample_document, Page 1]"
            ),
            "has_tables": True,
            "table_facts": [
                "Molecular Weight: Methane = 16",
                "Specific Gravity: Methane = 0.3",
            ],
        }
    ]

    assert calculate_table_to_bullets_ratio(sections) == 100.0


def test_table_ratio_excludes_contents_and_list_of_figures_from_denominator():
    sections = [
        {
            "heading": "What does this section explain about CONTENTS?",
            "content": (
                "## CONTENTS\n\n"
                "| Chapter | Page |\n"
                "| --- | --- |\n"
                "| Overview | 1 |\n"
            ),
            "has_tables": True,
            "table_facts": [],
        },
        {
            "heading": "What does this section explain about LIST OF FIGURES?",
            "content": (
                "## LIST OF FIGURES\n\n"
                "| Figure | Page |\n"
                "| --- | --- |\n"
                "| Figure 1 | 5 |\n"
            ),
            "has_tables": True,
            "table_facts": [],
        },
        {
            "heading": "What does the table show about LNG properties?",
            "content": (
                "## LNG Properties\n\n"
                "| Parameter | Methane | Ethane |\n"
                "| --- | --- | --- |\n"
                "| Molecular Weight | 16 | 30 |\n"
                "\n[Source: sample_document, Page 8]"
            ),
            "has_tables": True,
            "table_facts": ["Molecular Weight: Methane = 16"],
        },
    ]

    assert calculate_table_to_bullets_ratio(sections) == 100.0


def test_table_ratio_falls_back_to_markdown_bullets_when_structured_facts_absent():
    sections = [
        {
            "heading": "What does the table show about LNG properties?",
            "content": (
                "## LNG Properties\n\n"
                "- Methane molecular weight is 16.\n"
                "- Ethane molecular weight is 30.\n\n"
                "| Parameter | Methane | Ethane |\n"
                "| --- | --- | --- |\n"
                "| Molecular Weight | 16 | 30 |\n"
            ),
            "has_tables": True,
            "table_facts": [],
        }
    ]

    assert calculate_table_to_bullets_ratio(sections) == 100.0


def test_overall_confidence_uses_current_qa_metrics_not_validation_artifact_confidence():
    sections = [
        {
            "heading": "What is LNG?",
            "content": "## What is LNG?\n\n- LNG is cryogenic.\n\n[Source: sample_document, Page 1]",
            "has_tables": False,
            "table_facts": [],
        }
    ]
    validation_report = {
        "overall_confidence": 0.12,
        "page_validations": [],
    }

    metrics = compute_qa_metrics(sections, validation_report)

    assert metrics.overall_confidence_score == 100.0


def test_overall_confidence_applies_small_hallucination_penalty_to_current_metrics():
    score = calculate_overall_confidence_score(
        citation_coverage=100.0,
        question_heading_compliance=100.0,
        table_to_bullets_ratio=100.0,
        figure_description_coverage=100.0,
        hallucination_risk=0.5,
    )

    assert score == 95.0


def test_compute_qa_metrics_drops_resolved_image_loss_and_table_fidelity_issues():
    sections = [
        {
            "heading": "What is shown in the figure?",
            "content": (
                "## What is shown in the figure?\n\n"
                "**[Figure 1: LNG storage tank schematic with inlet and outlet flow paths.]**\n\n"
                "- Tank capacity is listed in the table below.\n\n"
                "| Parameter | Value |\n"
                "| --- | --- |\n"
                "| Capacity | 1000 |\n"
                "\n[Source: sample_document, Page 1]"
            ),
            "has_tables": True,
            "table_facts": ["Capacity = 1000"],
        }
    ]
    validation_report = {
        "overall_confidence": 0.12,
        "page_validations": [
            {
                "page_number": 1,
                "issues": [
                    {"issue_type": "image_loss", "severity": "critical"},
                    {"issue_type": "table_fidelity", "severity": "major"},
                ],
            }
        ],
    }

    metrics = compute_qa_metrics(sections, validation_report)

    assert metrics.figure_description_coverage_percent == 100.0
    assert metrics.table_to_bullets_ratio == 100.0
    assert metrics.critical_issues_count == 0
    assert metrics.total_issues_count == 0