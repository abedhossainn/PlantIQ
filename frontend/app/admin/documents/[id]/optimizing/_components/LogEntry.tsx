"use client";

/**
 * Optimization Terminal Log Components
 *
 * LogEntry renders a single classified log line in the terminal pane.
 * StatusPill renders the current optimization lifecycle status badge.
 */

import { CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getOptimizationLifecycleLabel } from "@/lib/document-status";
import type { DocumentStatus } from "@/types";

// ---------------------------------------------------------------------------
// Types shared between LogEntry and OptimizingClient
// ---------------------------------------------------------------------------

export type OptimizationStatus = Extract<
  DocumentStatus,
  "approved-for-optimization" | "optimizing" | "optimization-complete" | "failed"
>;

export interface LogLine {
  timestamp: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
}

// ---------------------------------------------------------------------------
// Log classification helpers
// ---------------------------------------------------------------------------

type LineKind =
  | "separator"
  | "stage"
  | "step-start"
  | "step-complete"
  | "step-progress"
  | "warning"
  | "error"
  | "detail";

function toHHMMSS(isoTimestamp: string): string {
  try {
    return new Date(isoTimestamp).toTimeString().slice(0, 8);
  } catch {
    return "--:--:--";
  }
}

/** Strip leading pipeline sigil emoji from a log message before display. */
function stripPrefix(msg: string): string {
  return msg
    .replace(/^▶️\s*/u, "")
    .replace(/^✅\s*/u, "")
    .replace(/^🔄\s*/u, "")
    .replace(/^🤖\s*/u, "")
    .replace(/^⚠️\s*/u, "")
    .replace(/^🗑️\s*/u, "")
    .replace(/^📨\s*/u, "")
    .replace(/^⏱️\s*/u, "")
    .trim();
}

function classifyLine(line: LogLine): LineKind {
  const msg = line.message;
  if (line.level === "ERROR") return "error";
  if (/^={3,}/.test(msg)) return "separator";
  if (/^🤖/u.test(msg)) return "stage";
  if (/^▶️/u.test(msg)) return "step-start";
  if (/^✅/u.test(msg)) return "step-complete";
  if (/^🔄/u.test(msg)) return "step-progress";
  if (line.level === "WARNING") return "warning";
  return "detail";
}

// ---------------------------------------------------------------------------
// Log entry component
// ---------------------------------------------------------------------------

export function LogEntry({ line }: { line: LogLine }) {
  const timeStr = toHHMMSS(line.timestamp);
  const kind = classifyLine(line);
  const clean = stripPrefix(line.message);

  if (kind === "separator") {
    return (
      <div className="py-2 px-3" role="separator">
        <div className="border-t border-zinc-800" />
      </div>
    );
  }

  if (kind === "stage") {
    return (
      <div className="mt-3 mb-0.5 px-3 py-1.5 bg-zinc-900/80 border-l-2 border-sky-500 flex items-center">
        <span className="text-sky-400 font-bold text-[11px] tracking-wide">{clean}</span>
      </div>
    );
  }

  const borderClass =
    kind === "step-complete" ? "border-l-2 border-green-600/70"
    : kind === "step-start"  ? "border-l-2 border-zinc-600"
    : kind === "warning"     ? "border-l-2 border-amber-500"
    : kind === "error"       ? "border-l-2 border-red-500"
    : "";

  const bgClass =
    kind === "warning" ? "bg-amber-950/20"
    : kind === "error" ? "bg-red-950/20"
    : "";

  const badge =
    kind === "step-complete" ? (
      <span className="text-[10px] text-green-400 font-mono shrink-0 w-8">OK</span>
    ) : kind === "step-start" ? (
      <span className="text-[10px] text-sky-400 font-mono shrink-0 w-8">RUN</span>
    ) : kind === "step-progress" ? (
      <span className="text-[10px] text-zinc-600 font-mono shrink-0 w-8">···</span>
    ) : kind === "warning" ? (
      <span className="text-[10px] text-amber-400 font-mono font-semibold shrink-0 w-8">WARN</span>
    ) : kind === "error" ? (
      <span className="text-[10px] text-red-400 font-mono font-semibold shrink-0 w-8">ERR</span>
    ) : (
      <span className="text-[10px] text-zinc-700 font-mono shrink-0 w-8">—</span>
    );

  const msgClass =
    kind === "step-complete"  ? "text-green-300"
    : kind === "step-start"   ? "text-zinc-200 font-medium"
    : kind === "step-progress"? "text-zinc-400 italic"
    : kind === "warning"      ? "text-amber-300"
    : kind === "error"        ? "text-red-300 font-medium"
    : "text-zinc-500";

  return (
    <div className={`flex gap-2 items-baseline py-0.5 pl-3 pr-2 ${borderClass} ${bgClass}`}>
      <span className="text-zinc-600 text-[10px] font-mono shrink-0 w-[60px] select-none tabular-nums">
        {timeStr}
      </span>
      {badge}
      <span className={`flex-1 break-words text-xs leading-relaxed ${msgClass}`}>
        {clean}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status pill component
// ---------------------------------------------------------------------------

export function StatusPill({ status }: { status: OptimizationStatus }) {
  if (status === "approved-for-optimization") {
    return (
      <Badge
        variant="outline"
        className="text-yellow-400 border-yellow-400/30 bg-yellow-400/10 gap-1.5 text-xs font-semibold"
      >
        {getOptimizationLifecycleLabel(status)}
      </Badge>
    );
  }
  if (status === "optimizing") {
    return (
      <Badge
        variant="outline"
        className="text-blue-400 border-blue-400/30 bg-blue-400/10 gap-1.5 text-xs font-semibold"
      >
        <span className="inline-block h-2 w-2 rounded-full bg-blue-400 animate-pulse shrink-0" />
        {getOptimizationLifecycleLabel(status)}
      </Badge>
    );
  }
  if (status === "optimization-complete") {
    return (
      <Badge
        variant="outline"
        className="text-green-400 border-green-400/30 bg-green-400/10 gap-1.5 text-xs font-semibold"
      >
        <CheckCircle2 className="h-3.5 w-3.5" />
        {getOptimizationLifecycleLabel(status)}
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="text-red-400 border-red-400/30 bg-red-400/10 gap-1.5 text-xs font-semibold"
    >
      <XCircle className="h-3.5 w-3.5" />
      {getOptimizationLifecycleLabel(status)}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Elapsed time formatter (used by OptimizingClient)
// ---------------------------------------------------------------------------

export function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
