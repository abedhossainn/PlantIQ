import type { DocumentStatus } from "@/types";

export type OptimizationLifecycleStatus = Extract<
  DocumentStatus,
  "approved-for-optimization" | "optimizing" | "optimization-complete" | "failed"
>;

export const REVIEW_QUEUE_STATUSES: DocumentStatus[] = [
  "validation-complete",
  "in-review",
];

export const QA_QUEUE_STATUSES: DocumentStatus[] = [
  "approved-for-optimization",
  "optimizing",
  "optimization-complete",
  "qa-review",
  "qa-passed",
  "review-complete",
];

export const FINALIZED_DOCUMENT_STATUSES: DocumentStatus[] = [
  "final-approved",
  "approved",
  "rejected",
];

export const OPTIMIZATION_PENDING_STATUSES: DocumentStatus[] = [
  "approved-for-optimization",
  "optimizing",
];

export const QA_READY_STATUSES: DocumentStatus[] = [
  "optimization-complete",
  "qa-review",
  "qa-passed",
  "final-approved",
  "approved",
];

export function isReviewQueueStatus(status: DocumentStatus): boolean {
  return REVIEW_QUEUE_STATUSES.includes(status);
}

export function isQAQueueStatus(status: DocumentStatus): boolean {
  return QA_QUEUE_STATUSES.includes(status);
}

export function isFinalizedDocumentStatus(status: DocumentStatus): boolean {
  return FINALIZED_DOCUMENT_STATUSES.includes(status);
}

export function isOptimizationPendingStatus(status: DocumentStatus): boolean {
  return OPTIMIZATION_PENDING_STATUSES.includes(status);
}

export function isQAReadyStatus(status: DocumentStatus): boolean {
  return QA_READY_STATUSES.includes(status);
}

export function canStartFinalApproval(status: DocumentStatus): boolean {
  return status === "qa-passed" || status === "final-approved" || status === "approved";
}

/**
 * Returns true for statuses where the optimized-review screen should be shown
 * (editor is writable) rather than bypassed.
 * qa-review is included so users can revisit edits before rescoring.
 */
export function canOpenOptimizedReview(status: DocumentStatus): boolean {
  return status === "optimization-complete" || status === "qa-review";
}

/**
 * Returns true for statuses where the optimized-review screen should be shown
 * in read-only mode (content already progressed past editable stage).
 */
export function isOptimizedReviewReadOnly(status: DocumentStatus): boolean {
  return status === "qa-passed" || status === "final-approved" || status === "approved";
}

export function getOptimizationLifecycleLabel(status: OptimizationLifecycleStatus): string {
  switch (status) {
    case "approved-for-optimization":
      return "Ready for Optimization";
    case "optimizing":
      return "Running";
    case "optimization-complete":
      return "Complete";
    case "failed":
      return "Failed";
  }
}