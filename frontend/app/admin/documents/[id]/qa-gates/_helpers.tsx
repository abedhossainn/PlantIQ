import { CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import type { QAMetric } from "@/types";

// ---------- Backend types --------------------------------------------------

export interface QAPreReviewMetrics {
  citation_coverage_percent: number;
  question_heading_compliance_percent: number;
  table_to_bullets_ratio: number;
  figure_description_coverage_percent: number;
  overall_confidence_score: number;
  critical_issues_count: number;
  total_issues_count: number;
  hallucination_risk_score: number;
}

export interface QAPreReviewArtifact {
  timestamp?: string;
  decision: "approved" | "rejected" | "review";
  metrics: QAPreReviewMetrics;
  passed_criteria: string[];
  failed_criteria: string[];
  recommendations: string[];
}

export interface QARescoreResponse {
  document_id: string;
  decision: string;
  passed_criteria: string[];
  failed_criteria: string[];
  recommendations: string[];
  metrics: QAPreReviewMetrics;
  timestamp: string;
}

// Map backend metric key → display label and default threshold
export const METRIC_DISPLAY: Record<
  keyof Omit<QAPreReviewMetrics, "critical_issues_count" | "total_issues_count" | "hallucination_risk_score">,
  { name: string; threshold: number }
> = {
  citation_coverage_percent:            { name: "Citation Coverage",             threshold: 90 },
  question_heading_compliance_percent:  { name: "Question Heading Compliance",   threshold: 85 },
  table_to_bullets_ratio:               { name: "Table Facts Extraction",        threshold: 95 },
  figure_description_coverage_percent:  { name: "Figure Description Coverage",   threshold: 100 },
  overall_confidence_score:             { name: "Overall Confidence Score",      threshold: 80 },
};

// Map metric name keywords → which criteria strings to look for
export const METRIC_CRITERIA_KEYWORDS: Record<string, string[]> = {
  citation_coverage_percent:            ["citation coverage", "citation"],
  question_heading_compliance_percent:  ["question heading", "question headings"],
  table_to_bullets_ratio:               ["table facts", "table"],
  figure_description_coverage_percent:  ["figure", "figures described"],
  overall_confidence_score:             ["confidence score", "confidence"],
};

export function findCriterionDescription(key: string, passed: string[], failed: string[]): string | undefined {
  const keywords = METRIC_CRITERIA_KEYWORDS[key] ?? [];
  const allCriteria = [...passed, ...failed];
  for (const criterion of allCriteria) {
    if (keywords.some((kw) => criterion.toLowerCase().includes(kw))) {
      return criterion;
    }
  }
  return undefined;
}

export function mapBackendMetrics(report: QAPreReviewArtifact): QAMetric[] {
  return (Object.entries(METRIC_DISPLAY) as Array<[keyof typeof METRIC_DISPLAY, { name: string; threshold: number }]>).map(
    ([key, { name, threshold }]) => {
      const score = Math.round(report.metrics[key] ?? 0);
      const status: QAMetric["status"] =
        score >= threshold ? "pass" : score >= threshold * 0.85 ? "warning" : "fail";
      const details = findCriterionDescription(key, report.passed_criteria ?? [], report.failed_criteria ?? []);
      return { name, score, threshold, status, details };
    }
  );
}

export function decisionToRecommendation(d: string): "accept" | "reject" | "review" {
  if (d === "approved" || d === "conditional_approval") return "accept";
  if (d === "rejected") return "reject";
  return "review";
}

export const STATUS_CONFIG = {
  pass:    { badgeClass: "text-green-400 bg-green-400/10 border-green-400/30", icon: <CheckCircle2 className="h-4 w-4" />, label: "PASS",    barClass: "[&>div]:bg-green-400" },
  warning: { badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30", icon: <AlertTriangle className="h-4 w-4" />, label: "WARNING", barClass: "[&>div]:bg-amber-400" },
  fail:    { badgeClass: "text-red-400 bg-red-400/10 border-red-400/30",       icon: <XCircle className="h-4 w-4" />,       label: "FAIL",    barClass: "[&>div]:bg-red-400" },
};
