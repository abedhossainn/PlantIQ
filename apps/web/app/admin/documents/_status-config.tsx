/**
 * Status taxonomy mapping for the document pipeline.
 * Maps every known backend status string to its UI label, badge styling, icon, and action route.
 *
 * Importing this file requires React for JSX icon nodes.
 */

import {
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  AlertCircle,
  ShieldCheck,
} from "lucide-react";

export const STATUS_CONFIG: Record<
  string,
  { label: string; badgeClass: string; icon: React.ReactNode; action?: string; actionLabel?: string }
> = {
  pending: {
    label: "Queued",
    badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    icon: <Clock className="h-3 w-3" />,
    action: "ingestion",
    actionLabel: "Track Ingestion",
  },
  uploading: {
    label: "Uploading",
    badgeClass: "text-sky-400 bg-sky-400/10 border-sky-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    action: "ingestion",
    actionLabel: "Track Ingestion",
  },
  extracting: {
    label: "Extracting",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    action: "ingestion",
    actionLabel: "Track Ingestion",
  },
  approved: {
    label: "Approved",
    badgeClass: "text-green-400 bg-green-400/10 border-green-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Approval",
  },
  rejected: {
    label: "Rejected",
    badgeClass: "text-red-400 bg-red-400/10 border-red-400/30",
    icon: <XCircle className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Details",
  },
  "final-approved": {
    label: "Final Approved",
    badgeClass: "text-green-400 bg-green-400/10 border-green-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "View Approval",
  },
  "review-complete": {
    label: "Review Complete",
    badgeClass: "text-blue-400 bg-blue-400/10 border-blue-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Open QA Gates",
  },
  "approved-for-optimization": {
    label: "Approved for Optimization",
    badgeClass: "text-sky-400 bg-sky-400/10 border-sky-400/30",
    icon: <Clock className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Track Optimization",
  },
  optimizing: {
    label: "Optimizing",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    action: "optimizing",
    actionLabel: "Track Optimization",
  },
  "optimization-complete": {
    label: "Optimization Complete",
    badgeClass: "text-blue-400 bg-blue-400/10 border-blue-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "optimized-review",
    actionLabel: "Review Optimized Output",
  },
  "qa-review": {
    label: "QA Review",
    badgeClass: "text-indigo-400 bg-indigo-400/10 border-indigo-400/30",
    icon: <ShieldCheck className="h-3 w-3" />,
    action: "qa-gates",
    actionLabel: "Continue QA",
  },
  "qa-passed": {
    label: "QA Passed",
    badgeClass: "text-emerald-400 bg-emerald-400/10 border-emerald-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "approve",
    actionLabel: "Final Approval",
  },
  "in-review": {
    label: "In Review",
    badgeClass: "text-amber-400 bg-amber-400/10 border-amber-400/30",
    icon: <Clock className="h-3 w-3" />,
    action: "review",
    actionLabel: "Continue Review",
  },
  "validation-complete": {
    label: "Validation Complete",
    badgeClass: "text-cyan-400 bg-cyan-400/10 border-cyan-400/30",
    icon: <CheckCircle2 className="h-3 w-3" />,
    action: "review",
    actionLabel: "Start Review",
  },
  "vlm-validating": {
    label: "Validating",
    badgeClass: "text-purple-400 bg-purple-400/10 border-purple-400/30",
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    action: "ingestion",
    actionLabel: "Track Ingestion",
  },
  uploaded: {
    label: "Uploaded",
    badgeClass: "text-zinc-400 bg-zinc-400/10 border-zinc-400/30",
    icon: <AlertCircle className="h-3 w-3" />,
    action: "ingestion",
    actionLabel: "Track Ingestion",
  },
  failed: {
    label: "Failed",
    badgeClass: "text-red-400 bg-red-400/10 border-red-400/30",
    icon: <XCircle className="h-3 w-3" />,
    action: "optimizing",
    actionLabel: "View Failure",
  },
};
