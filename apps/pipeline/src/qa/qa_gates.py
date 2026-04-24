#!/usr/bin/env python3
"""
QA Gates and Metrics Module
Implements improvement #3: Explicit QA gates with acceptance criteria
- Acceptance gate with minimum criteria
- Sampling policy (100% for critical, 10-20% for low-risk)
- QA metrics: citation coverage, question-heading compliance, table-to-bullets ratio
"""

import json
import logging
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


NON_DATA_TABLE_HEADING_MARKERS = (
    "contents",
    "list of figures",
    "list of tables",
)


class RiskLevel(Enum):
    """Risk classification for sampling policy"""
    CRITICAL = "critical"  # Safety-critical, 100% review
    HIGH = "high"          # Important content, 100% review
    MEDIUM = "medium"      # Standard content, 50% review
    LOW = "low"            # Low-risk content, 10-20% review


class QADecision(Enum):
    """QA gate decision"""
    APPROVED = "approved"
    CONDITIONAL_APPROVAL = "conditional_approval"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


@dataclass
class AcceptanceCriteria:
    """Minimum acceptance criteria for QA gate"""
    min_citation_coverage: float = 0.90  # 90% of chunks must have citations
    min_question_heading_compliance: float = 0.85  # 85% headings as questions
    min_table_facts_extraction: float = 0.95  # 95% of tables must have bullet facts
    min_confidence_score: float = 0.80  # 80% overall confidence
    max_critical_issues: int = 0  # Zero critical issues allowed
    require_all_figures_described: bool = True


@dataclass
class QAMetrics:
    """Comprehensive QA metrics for document validation"""
    citation_coverage_percent: float
    question_heading_compliance_percent: float
    table_to_bullets_ratio: float
    figure_description_coverage_percent: float
    overall_confidence_score: float
    critical_issues_count: int
    total_issues_count: int
    hallucination_risk_score: float  # 0.0-1.0, lower is better
    
    # Section-level metrics
    sections_approved: int
    sections_rejected: int
    sections_pending: int
    
    # Reviewer metrics
    avg_review_time_minutes: Optional[float] = None
    reviewer_agreement_score: Optional[float] = None


@dataclass
class SamplingPolicy:
    """Sampling rules based on risk level"""
    critical_sample_rate: float = 1.0   # 100%
    high_sample_rate: float = 1.0        # 100%
    medium_sample_rate: float = 0.5      # 50%
    low_sample_rate: float = 0.15        # 15%
    
    def get_sample_rate(self, risk_level: RiskLevel) -> float:
        """Get sampling rate for risk level"""
        rates = {
            RiskLevel.CRITICAL: self.critical_sample_rate,
            RiskLevel.HIGH: self.high_sample_rate,
            RiskLevel.MEDIUM: self.medium_sample_rate,
            RiskLevel.LOW: self.low_sample_rate
        }
        return rates.get(risk_level, 1.0)


@dataclass
class QAGateResult:
    """Result from QA gate evaluation"""
    document_name: str
    timestamp: str
    decision: str  # QADecision enum value
    metrics: QAMetrics
    acceptance_criteria: AcceptanceCriteria
    passed_criteria: List[str]
    failed_criteria: List[str]
    recommendations: List[str]
    reviewer_notes: Optional[str] = None


def calculate_citation_coverage(sections: List[Dict]) -> float:
    """
    Calculate percentage of sections with proper source citations
    Citation format: [Source: <document>, Page X]
    """
    if not sections:
        return 0.0
    
    sections_with_citations = 0
    
    for section in sections:
        content = section.get('content', '')
        # Check for citation patterns
        if '[Source:' in content or '(Page ' in content or '[p.' in content.lower():
            sections_with_citations += 1
    
    coverage = (sections_with_citations / len(sections)) * 100
    logger.info(f"📊 Citation coverage: {coverage:.1f}% ({sections_with_citations}/{len(sections)} sections)")
    return coverage


def calculate_question_heading_compliance(sections: List[Dict]) -> float:
    """
    Calculate percentage of headings formatted as questions
    Questions should end with '?' or contain question words
    """
    if not sections:
        return 0.0
    
    question_headings = 0
    question_words = ['what', 'why', 'how', 'when', 'where', 'which', 'who']
    
    for section in sections:
        heading = section.get('heading', '').lower()
        
        if heading.endswith('?'):
            question_headings += 1
        elif any(word in heading for word in question_words):
            question_headings += 1
    
    compliance = (question_headings / len(sections)) * 100
    logger.info(f"📊 Question heading compliance: {compliance:.1f}% ({question_headings}/{len(sections)} sections)")
    return compliance


def _section_has_markdown_table(content: str) -> bool:
    return '|' in content and '---' in content


def _section_has_structured_table_facts(section: Dict) -> bool:
    table_facts = section.get('table_facts') or []
    return any(str(fact).strip() for fact in table_facts)


def _is_non_data_table_section(section: Dict) -> bool:
    heading = str(section.get('heading', '')).strip().lower()
    if any(marker in heading for marker in NON_DATA_TABLE_HEADING_MARKERS):
        return True

    content = str(section.get('content', '')).strip().lower()
    first_lines = '\n'.join(content.splitlines()[:5])
    return any(marker in first_lines for marker in NON_DATA_TABLE_HEADING_MARKERS)


def _has_bullets_near_markdown_table(content: str) -> bool:
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if '|' not in line:
            continue

        context = '\n'.join(lines[max(0, i - 5):min(len(lines), i + 10)])
        if '- ' in context or '* ' in context:
            return True

    return False


def calculate_table_to_bullets_ratio(sections: List[Dict]) -> float:
    """
    Calculate ratio of tables with extracted bullet facts
    Table facts should appear as bullet points before or after table
    """
    if not sections:
        return 0.0
    
    sections_with_tables = []
    sections_with_table_facts = 0
    
    for section in sections:
        content = str(section.get('content', ''))
        has_table = bool(section.get('has_tables')) or _section_has_markdown_table(content)

        if not has_table or _is_non_data_table_section(section):
            continue

        sections_with_tables.append(section)

        if _section_has_structured_table_facts(section) or _has_bullets_near_markdown_table(content):
            sections_with_table_facts += 1
    
    if not sections_with_tables:
        return 100.0  # No tables = perfect compliance
    
    ratio = (sections_with_table_facts / len(sections_with_tables)) * 100
    logger.info(f"📊 Table-to-bullets ratio: {ratio:.1f}% ({sections_with_table_facts}/{len(sections_with_tables)} tables)")
    return ratio


def calculate_figure_description_coverage(sections: List[Dict]) -> float:
    """
    Calculate percentage of figures with text descriptions
    Figures should have ![Description](path) format
    """
    if not sections:
        return 0.0
    
    total_figures = 0
    described_figures = 0
    
    for section in sections:
        content = section.get('content', '')
        
        # Find all image references
        import re
        image_pattern = r'!\[(.*?)\]\((.*?)\)'
        matches = re.findall(image_pattern, content)
        
        total_figures += len(matches)
        
        for alt_text, path in matches:
            # Check if description is meaningful (not empty or just filename)
            if alt_text and len(alt_text) > 10 and alt_text.lower() != 'image':
                described_figures += 1
    
    if total_figures == 0:
        return 100.0  # No figures = perfect compliance
    
    coverage = (described_figures / total_figures) * 100
    logger.info(f"📊 Figure description coverage: {coverage:.1f}% ({described_figures}/{total_figures} figures)")
    return coverage


def calculate_hallucination_risk(sections: List[Dict], validation_issues: List[Dict]) -> float:
    """
    Calculate hallucination risk score based on semantic mismatches
    Lower score is better (0.0 = no risk, 1.0 = high risk)
    """
    if not sections:
        return 0.0
    
    semantic_mismatch_count = 0
    
    for issue in validation_issues:
        if issue.get('issue_type') == 'semantic_mismatch':
            semantic_mismatch_count += 1
    
    # Risk score based on mismatch frequency
    risk_score = min(1.0, semantic_mismatch_count / len(sections))
    
    logger.info(f"📊 Hallucination risk: {risk_score:.2f} ({semantic_mismatch_count} semantic mismatches)")
    return risk_score


def calculate_overall_confidence_score(
    citation_coverage: float,
    question_heading_compliance: float,
    table_to_bullets_ratio: float,
    figure_description_coverage: float,
    hallucination_risk: float,
) -> float:
    """Calculate QA confidence from current post-optimization quality signals.

    This intentionally avoids inheriting the ingestion-time validation artifact's
    `overall_confidence`, because QA rescoring should reflect the current optimized
    output rather than the pre-optimization markdown snapshot.
    """

    weighted_score = (
        (citation_coverage * 0.30)
        + (question_heading_compliance * 0.15)
        + (table_to_bullets_ratio * 0.25)
        + (figure_description_coverage * 0.30)
    )
    hallucination_penalty = max(0.0, min(10.0, hallucination_risk * 10.0))
    return max(0.0, min(100.0, weighted_score - hallucination_penalty))


def filter_unresolved_validation_issues(
    validation_issues: List[Dict],
    *,
    citation_coverage: float,
    question_heading_compliance: float,
    table_to_bullets_ratio: float,
    figure_description_coverage: float,
    hallucination_risk: float,
) -> List[Dict]:
    """Return only validation issues that are still unresolved in optimized output."""

    unresolved: List[Dict] = []

    for issue in validation_issues:
        issue_type = str(issue.get('issue_type') or '').strip().lower()

        if issue_type == 'image_loss' and figure_description_coverage >= 100.0:
            continue
        if issue_type == 'table_fidelity' and table_to_bullets_ratio >= 100.0:
            continue
        if issue_type == 'semantic_mismatch' and hallucination_risk <= 0.0:
            continue
        if issue_type == 'missing_content' and citation_coverage >= 100.0:
            continue
        if issue_type == 'formatting' and question_heading_compliance >= 100.0:
            continue

        unresolved.append(issue)

    return unresolved


def compute_qa_metrics(
    sections: List[Dict],
    validation_report: Dict,
    review_data: Optional[Dict] = None
) -> QAMetrics:
    """
    Compute comprehensive QA metrics for document
    """
    logger.info("📊 Computing QA metrics...")
    
    # Extract validation data
    validation_issues = []
    if 'page_validations' in validation_report:
        for page_val in validation_report['page_validations']:
            validation_issues.extend(page_val.get('issues', []))
    
    # Calculate metrics
    citation_coverage = calculate_citation_coverage(sections)
    question_compliance = calculate_question_heading_compliance(sections)
    table_ratio = calculate_table_to_bullets_ratio(sections)
    figure_coverage = calculate_figure_description_coverage(sections)
    hallucination_risk = calculate_hallucination_risk(sections, validation_issues)
    unresolved_validation_issues = filter_unresolved_validation_issues(
        validation_issues,
        citation_coverage=citation_coverage,
        question_heading_compliance=question_compliance,
        table_to_bullets_ratio=table_ratio,
        figure_description_coverage=figure_coverage,
        hallucination_risk=hallucination_risk,
    )
    critical_issues = sum(1 for issue in unresolved_validation_issues if issue.get('severity') == 'critical')
    
    overall_confidence = calculate_overall_confidence_score(
        citation_coverage,
        question_compliance,
        table_ratio,
        figure_coverage,
        hallucination_risk,
    )
    
    # Section status counts
    sections_approved, sections_rejected, sections_pending = _summarize_review_section_statuses(review_data)
    
    metrics = QAMetrics(
        citation_coverage_percent=citation_coverage,
        question_heading_compliance_percent=question_compliance,
        table_to_bullets_ratio=table_ratio,
        figure_description_coverage_percent=figure_coverage,
        overall_confidence_score=overall_confidence,
        critical_issues_count=critical_issues,
        total_issues_count=len(unresolved_validation_issues),
        hallucination_risk_score=hallucination_risk,
        sections_approved=sections_approved,
        sections_rejected=sections_rejected,
        sections_pending=sections_pending
    )
    
    logger.info("✅ QA metrics computed")
    return metrics


def _summarize_review_section_statuses(review_data: Optional[Dict]) -> tuple[int, int, int]:
    """Return approved/rejected/pending section counts from optional review data."""
    sections_approved = 0
    sections_rejected = 0
    sections_pending = 0

    if not review_data or 'sections' not in review_data:
        return sections_approved, sections_rejected, sections_pending

    for section in review_data['sections']:
        status = section.get('status', 'PENDING')
        if status == 'APPROVED':
            sections_approved += 1
        elif status == 'REJECTED' or status == 'NEEDS_REWORK':
            sections_rejected += 1
        else:
            sections_pending += 1

    return sections_approved, sections_rejected, sections_pending


def _evaluate_gate_criterion(
    *,
    passed: List[str],
    failed: List[str],
    recommendations: List[str],
    value: float,
    threshold: float,
    label: str,
    recommendation: str,
    formatter: str = "{value:.1f}%",
    threshold_formatter: str = "{threshold:.1f}%",
) -> None:
    """Evaluate one threshold-based criterion and append messaging."""
    if value >= threshold:
        passed.append(f"{label}: {formatter.format(value=value, threshold=threshold)}")
        return

    failed.append(
        f"{label}: {formatter.format(value=value, threshold=threshold)} < "
        f"{threshold_formatter.format(value=value, threshold=threshold)}"
    )
    recommendations.append(recommendation)


def _evaluate_critical_issue_criterion(
    *,
    passed: List[str],
    failed: List[str],
    recommendations: List[str],
    current_count: int,
    max_allowed: int,
) -> None:
    """Evaluate zero/low critical issue tolerance criterion."""
    if current_count <= max_allowed:
        passed.append(f"Critical issues: {current_count}")
        return

    failed.append(f"Critical issues: {current_count} > {max_allowed}")
    recommendations.append("Resolve all critical issues before approval")


def _evaluate_figure_description_criterion(
    *,
    passed: List[str],
    failed: List[str],
    recommendations: List[str],
    require_all_figures_described: bool,
    figure_description_coverage_percent: float,
) -> None:
    """Evaluate the optional all-figures-described gate."""
    if not require_all_figures_described:
        return

    if figure_description_coverage_percent >= 100.0:
        passed.append("All figures described")
        return

    failed.append(f"Figure descriptions: {figure_description_coverage_percent:.1f}% < 100%")
    recommendations.append("Add text descriptions for all figures")


def evaluate_qa_gate(
    metrics: QAMetrics,
    criteria: AcceptanceCriteria
) -> QAGateResult:
    """
    Evaluate document against acceptance criteria
    Returns QA gate decision
    """
    logger.info("🚦 Evaluating QA gate...")
    
    passed = []
    failed = []
    recommendations = []
    
    _evaluate_gate_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        value=metrics.citation_coverage_percent,
        threshold=criteria.min_citation_coverage * 100,
        label="Citation coverage",
        recommendation="Add source citations to more sections",
    )

    _evaluate_gate_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        value=metrics.question_heading_compliance_percent,
        threshold=criteria.min_question_heading_compliance * 100,
        label="Question headings",
        recommendation="Reformat more headings as questions",
    )

    _evaluate_gate_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        value=metrics.table_to_bullets_ratio,
        threshold=criteria.min_table_facts_extraction * 100,
        label="Table facts extraction",
        recommendation="Extract key facts from tables as bullet points",
    )

    _evaluate_gate_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        value=metrics.overall_confidence_score,
        threshold=criteria.min_confidence_score * 100,
        label="Confidence score",
        recommendation="Review and correct low-confidence sections",
    )

    _evaluate_critical_issue_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        current_count=metrics.critical_issues_count,
        max_allowed=criteria.max_critical_issues,
    )

    _evaluate_figure_description_criterion(
        passed=passed,
        failed=failed,
        recommendations=recommendations,
        require_all_figures_described=criteria.require_all_figures_described,
        figure_description_coverage_percent=metrics.figure_description_coverage_percent,
    )
    
    # Determine decision
    if not failed:
        decision = QADecision.APPROVED
    elif len(failed) <= 2 and metrics.critical_issues_count == 0:
        decision = QADecision.CONDITIONAL_APPROVAL
        recommendations.insert(0, "Approved with conditions - address failed criteria")
    else:
        decision = QADecision.REJECTED
        recommendations.insert(0, "Rejected - must address failed criteria")
    
    result = QAGateResult(
        document_name="unknown",  # Will be set by caller
        timestamp=datetime.now(timezone.utc).isoformat(),
        decision=decision.value,
        metrics=metrics,
        acceptance_criteria=criteria,
        passed_criteria=passed,
        failed_criteria=failed,
        recommendations=recommendations
    )
    
    logger.info(f"🚦 QA Gate Decision: {decision.value}")
    logger.info(f"   Passed: {len(passed)} criteria")
    logger.info(f"   Failed: {len(failed)} criteria")
    
    return result


def apply_sampling_policy(
    sections: List[Dict],
    policy: SamplingPolicy
) -> List[Dict]:
    """
    Apply risk-based sampling policy to sections
    Returns sections selected for review
    """
    import random
    
    logger.info("🎯 Applying sampling policy...")
    
    selected_sections = []
    
    for section in sections:
        # Determine risk level (simplified heuristic)
        risk_level = RiskLevel.MEDIUM
        
        heading = section.get('heading', '').lower()
        content = section.get('content', '')
        
        # Critical: safety, warnings, specifications
        if any(word in heading for word in ['safety', 'warning', 'critical', 'specification']):
            risk_level = RiskLevel.CRITICAL
        # High: tables, technical data
        elif section.get('has_tables', False) or 'specification' in content.lower():
            risk_level = RiskLevel.HIGH
        # Low: introduction, overview
        elif any(word in heading for word in ['introduction', 'overview', 'summary']):
            risk_level = RiskLevel.LOW
        
        # Apply sampling
        sample_rate = policy.get_sample_rate(risk_level)
        
        if random.random() < sample_rate:
            section['risk_level'] = risk_level.value
            section['sampled'] = True
            selected_sections.append(section)
        else:
            section['sampled'] = False
    
    logger.info(f"✅ Sampling complete: {len(selected_sections)}/{len(sections)} sections selected")
    logger.info(f"   Sampling rate: {len(selected_sections)/len(sections)*100:.1f}%")
    
    return selected_sections


def save_qa_report(result: QAGateResult, output_path: str):
    """Save QA gate result as JSON"""
    output_file = Path(output_path)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(asdict(result), f, indent=2)
    
    logger.info(f"💾 QA report saved: {output_file}")


def main():
    """CLI entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="QA Gates and Metrics Module"
    )
    parser.add_argument("--validation-report", required=True, help="Validation report JSON")
    parser.add_argument("--sections", required=True, help="Sections JSON")
    parser.add_argument("--output", default="qa_gate_result.json", help="Output path")
    parser.add_argument("--review-data", help="Optional review data JSON")
    
    args = parser.parse_args()
    
    logger.info("=" * 80)
    logger.info("🚦 QA Gates and Metrics")
    logger.info("=" * 80)
    
    # Load data
    with open(args.validation_report, 'r') as f:
        validation_report = json.load(f)
    
    with open(args.sections, 'r') as f:
        sections_data = json.load(f)
        sections = sections_data.get('sections', [])
    
    review_data = None
    if args.review_data:
        with open(args.review_data, 'r') as f:
            review_data = json.load(f)
    
    # Compute metrics
    metrics = compute_qa_metrics(sections, validation_report, review_data)
    
    # Evaluate gate
    criteria = AcceptanceCriteria()
    result = evaluate_qa_gate(metrics, criteria)
    result.document_name = sections_data.get('document_name', 'unknown')
    
    # Save report
    save_qa_report(result, args.output)
    
    logger.info("✅ QA evaluation complete")
    return 0 if result.decision == QADecision.APPROVED.value else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
