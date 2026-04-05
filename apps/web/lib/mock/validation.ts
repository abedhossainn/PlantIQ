import type { ValidationReport, ValidationIssue } from "@/types";

/**
 * Mock VLM validation reports for document quality assessment
 *
 * Purpose:
 * - Supplies deterministic validation artifacts for the validation UI.
 * - Exercises severity sorting, category badges, and confidence summaries.
 * - Simulates common extraction defects (table fidelity, missing text, image loss).
 *
 * Design intent:
 * - Includes both low-risk and critical findings for triage workflows.
 * - Embeds evidence image links and context text for detail drawers.
 * - Mirrors backend artifact shape to simplify future swap to live data.
 */

// Sample issues for doc-3 (Emergency Shutdown System P&ID)
const doc3Issues: ValidationIssue[] = [
  {
    id: "issue-1",
    page: 2,
    category: "table-fidelity",
    severity: "medium",
    description: "Valve specification table has merged cells that may affect readability",
    evidenceImageUrl: "/mock-evidence/doc3-page2.png",
    context: "Table 2-1: Emergency Valve Specifications",
  },
  {
    id: "issue-2",
    page: 5,
    category: "image-loss",
    severity: "low",
    description: "Minor legend icon quality degradation in P&ID diagram",
    evidenceImageUrl: "/mock-evidence/doc3-page5.png",
    context: "Figure 5-1: Main P&ID Schematic",
  },
  {
    id: "issue-3",
    page: 7,
    category: "formatting",
    severity: "low",
    description: "Footnote superscripts not properly preserved",
    evidenceImageUrl: "/mock-evidence/doc3-page7.png",
    context: "Section 7: Operating Conditions",
  },
];

// Sample issues for doc-2 (Cryogenic Pump System)
const doc2Issues: ValidationIssue[] = [
  {
    id: "issue-4",
    page: 15,
    category: "missing-text",
    severity: "high",
    description: "Safety warning callout box text not fully extracted",
    evidenceImageUrl: "/mock-evidence/doc2-page15.png",
    context: "WARNING: Low Temperature Hazards",
  },
  {
    id: "issue-5",
    page: 23,
    category: "table-fidelity",
    severity: "critical",
    description: "Multi-column pump specification table structure lost",
    evidenceImageUrl: "/mock-evidence/doc2-page23.png",
    context: "Table 3-2: Pump Performance Characteristics",
  },
  {
    id: "issue-6",
    page: 45,
    category: "table-fidelity",
    severity: "medium",
    description: "Troubleshooting matrix alignment issues",
    evidenceImageUrl: "/mock-evidence/doc2-page45.png",
    context: "Table 5-4: Troubleshooting Guide",
  },
  {
    id: "issue-7",
    page: 67,
    category: "image-loss",
    severity: "medium",
    description: "Cross-sectional diagram detail reduced",
    evidenceImageUrl: "/mock-evidence/doc2-page67.png",
    context: "Figure 7-3: Pump Assembly Cross-Section",
  },
  {
    id: "issue-8",
    page: 89,
    category: "formatting",
    severity: "low",
    description: "Numbered list indentation not preserved",
    evidenceImageUrl: "/mock-evidence/doc2-page89.png",
    context: "Section 9: Maintenance Procedures",
  },
  {
    id: "issue-9",
    page: 102,
    category: "missing-text",
    severity: "medium",
    description: "Chemical compatibility chart legend incomplete",
    evidenceImageUrl: "/mock-evidence/doc2-page102.png",
    context: "Appendix B: Material Compatibility",
  },
];

export const mockValidationReports: Record<string, ValidationReport> = {
  "doc-3": {
    documentId: "doc-3",
    totalIssues: 3,
    criticalIssues: 0,
    highIssues: 0,
    mediumIssues: 1,
    lowIssues: 2,
    overallConfidence: 94,
    issues: doc3Issues,
    generatedAt: "2026-02-19T06:50:00Z",
  },
  "doc-2": {
    documentId: "doc-2",
    totalIssues: 6,
    criticalIssues: 1,
    highIssues: 1,
    mediumIssues: 3,
    lowIssues: 1,
    overallConfidence: 82,
    issues: doc2Issues,
    generatedAt: "2026-02-18T08:30:00Z",
  },
};

/**
 * Helper function to get validation report by document ID
 */
export function getValidationReportByDocId(documentId: string): ValidationReport | undefined {
  return mockValidationReports[documentId];
}

/**
 * Helper function to get issues by severity
 */
export function getIssuesBySeverity(
  report: ValidationReport,
  severity: ValidationIssue["severity"]
): ValidationIssue[] {
  return report.issues.filter((issue) => issue.severity === severity);
}
