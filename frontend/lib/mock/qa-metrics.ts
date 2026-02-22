import type { QAGateReport, QAMetric } from "@/types";

/**
 * Mock QA gate metrics for document quality assessment
 */

// Helper to create metric
const createMetric = (
  name: string,
  score: number,
  threshold: number,
  details?: string
): QAMetric => {
  let status: "pass" | "fail" | "warning";
  if (score >= threshold) {
    status = "pass";
  } else if (score >= threshold - 5) {
    status = "warning";
  } else {
    status = "fail";
  }

  return { name, score, threshold, status, details };
};

export const mockQAGateReports: Record<string, QAGateReport> = {
  "doc-1": {
    documentId: "doc-1",
    metrics: {
      textAccuracy: createMetric(
        "Text Accuracy",
        98,
        95,
        "Character-level accuracy from OCR validation"
      ),
      tableStructure: createMetric(
        "Table Structure Preservation",
        96,
        90,
        "Column/row structure integrity maintained"
      ),
      imageCoverage: createMetric(
        "Image Description Coverage",
        94,
        90,
        "VLM-generated descriptions for all figures"
      ),
      overallScore: createMetric("Overall Quality Score", 96, 92, "Weighted average of all metrics"),
    },
    recommendation: "accept",
    failingCriteria: [],
    generatedAt: "2026-02-17T14:15:00Z",
  },
  "doc-2": {
    documentId: "doc-2",
    metrics: {
      textAccuracy: createMetric(
        "Text Accuracy",
        89,
        95,
        "Missing text in safety callout boxes (pages 15, 34)"
      ),
      tableStructure: createMetric(
        "Table Structure Preservation",
        78,
        90,
        "Critical issue: Table 3-2 structure lost"
      ),
      imageCoverage: createMetric(
        "Image Description Coverage",
        88,
        90,
        "Cross-sectional diagram detail reduced"
      ),
      overallScore: createMetric(
        "Overall Quality Score",
        85,
        92,
        "Below threshold - requires remediation"
      ),
    },
    recommendation: "reject",
    failingCriteria: [
      "Text accuracy below 95% threshold (89% actual)",
      "Table structure preservation below 90% threshold (78% actual)",
      "Overall quality score below 92% threshold (85% actual)",
    ],
    generatedAt: "2026-02-18T09:00:00Z",
  },
  "doc-5": {
    documentId: "doc-5",
    metrics: {
      textAccuracy: createMetric("Text Accuracy", 92, 95, "Acceptable but below target"),
      tableStructure: createMetric(
        "Table Structure Preservation",
        72,
        90,
        "Significant table extraction failures"
      ),
      imageCoverage: createMetric("Image Description Coverage", 81, 90, "Incomplete coverage"),
      overallScore: createMetric(
        "Overall Quality Score",
        82,
        92,
        "Rejected - multiple failing criteria"
      ),
    },
    recommendation: "reject",
    failingCriteria: [
      "Text accuracy below 95% threshold (92% actual)",
      "Table structure preservation below 90% threshold (72% actual)",
      "Image coverage below 90% threshold (81% actual)",
      "Overall quality score below 92% threshold (82% actual)",
    ],
    generatedAt: "2026-02-16T14:00:00Z",
  },
  "doc-6": {
    documentId: "doc-6",
    metrics: {
      textAccuracy: createMetric("Text Accuracy", 99, 95, "Exceptional OCR quality"),
      tableStructure: createMetric(
        "Table Structure Preservation",
        97,
        90,
        "All tables correctly structured"
      ),
      imageCoverage: createMetric(
        "Image Description Coverage",
        96,
        90,
        "Comprehensive figure descriptions"
      ),
      overallScore: createMetric(
        "Overall Quality Score",
        98,
        92,
        "Excellent quality - approved for ingestion"
      ),
    },
    recommendation: "accept",
    failingCriteria: [],
    generatedAt: "2026-02-16T09:25:00Z",
  },
  "doc-3": {
    documentId: "doc-3",
    metrics: {
      textAccuracy: createMetric(
        "Text Accuracy",
        97,
        95,
        "High OCR confidence scores throughout document"
      ),
      tableStructure: createMetric(
        "Table Structure Preservation",
        91,
        90,
        "Minor cell merge in Table 2-1 — acceptable for this document type"
      ),
      imageCoverage: createMetric(
        "Image Description Coverage",
        92,
        90,
        "P&ID diagrams adequately described by VLM pipeline"
      ),
      overallScore: createMetric(
        "Overall Quality Score",
        93,
        92,
        "Above acceptance threshold — document is ready for approval"
      ),
    },
    recommendation: "accept",
    failingCriteria: [],
    generatedAt: "2026-02-19T08:00:00Z",
  },
  "doc-7": {
    documentId: "doc-7",
    metrics: {
      textAccuracy: createMetric(
        "Text Accuracy",
        96,
        95,
        "Clean extraction from well-structured technical specification"
      ),
      tableStructure: createMetric(
        "Table Structure Preservation",
        94,
        90,
        "Switchgear specification tables preserved accurately"
      ),
      imageCoverage: createMetric(
        "Image Description Coverage",
        87,
        90,
        "Single-line diagram descriptions partially incomplete — within warning range"
      ),
      overallScore: createMetric(
        "Overall Quality Score",
        93,
        92,
        "Passes overall threshold despite image coverage warning"
      ),
    },
    recommendation: "accept",
    failingCriteria: [],
    generatedAt: "2026-02-19T11:00:00Z",
  },
};

/**
 * Helper function to get QA gate report by document ID
 */
export function getQAGateReportByDocId(documentId: string): QAGateReport | undefined {
  return mockQAGateReports[documentId];
}

/**
 * Helper to check if document passes all QA gates
 */
export function passesQAGates(report: QAGateReport): boolean {
  return report.recommendation === "accept";
}

/**
 * Helper to get failing metrics
 */
export function getFailingMetrics(report: QAGateReport): QAMetric[] {
  return Object.values(report.metrics).filter((m) => m.status === "fail");
}
