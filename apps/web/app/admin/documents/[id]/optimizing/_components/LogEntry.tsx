"use client";

/**
 * Optimization Terminal Log Components
 *
 * LogEntry             — single classified log line renderer (legacy terminal style).
 * StatusPill           — lifecycle status badge for the optimizing page header.
 * formatElapsed        — seconds → MM:SS / H:MM:SS formatter.
 * groupOptimizationLines — groups flat LogLine[] into PipelineStep[] for
 *                          the PipelineJobLog viewer.
 */

import { CheckCircle2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { OptimizationProgressEvent } from "@/lib/api";
import { getOptimizationLifecycleLabel } from "@/lib/document-status";
import type { DocumentStatus } from "@/types";
import type { PipelineStep, StepLogLine } from "@/components/shared/PipelineJobLog";
import { computeDurationLabel } from "@/components/shared/PipelineJobLog";

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

function stripStageNumberingPrefix(message: string): string {
  return message.replace(/^Stage\s+\d+[a-z]?:\s*/i, "").trim();
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

// ---------------------------------------------------------------------------
// Step grouping — converts flat log lines into collapsible PipelineStep[]
// ---------------------------------------------------------------------------

/**
 * Natural semantic stage boundaries used when the backend emits no explicit
 * `Stage N:` or `🤖`-prefixed stage markers.  Evaluated top-to-bottom; first
 * matching trigger wins.
 *
 * Trigger messages correspond to the normalized log output produced by
 * `normalize_optimization_message` in the backend `optimization_log.py`.
 */
const SEMANTIC_STAGE_TRIGGERS: Array<{ trigger: RegExp; name: string }> = [
  { trigger: /^Optimization started$/i,                          name: "Model Initialization" },
  { trigger: /^Prepare generation request|^Generate output /i,  name: "Content Generation" },
  { trigger: /^Finalize output/i,                                name: "Output Finalization" },
  { trigger: /^Write artifacts/i,                                name: "Artifact Export" },
];

/**
 * Groups a flat LogLine array into PipelineStep[] for the PipelineJobLog viewer.
 *
 * Grouping priority (highest to lowest):
 *  1. Explicit `Stage N: Name` prefix — added by the backend optimizer when
 *     structural stage markers are available.
 *  2. Legacy `🤖`-prefixed stage header.
 *  3. Keyword-based semantic detection via SEMANTIC_STAGE_TRIGGERS — provides
 *     natural stage grouping from the normalized log output even when the
 *     backend emits no structural markers.
 *
 * - "separator" lines are discarded.
 * - ERROR-level lines mark the current step as "failed".
 * - WARNING-level lines are appended with the "warning" level label.
 *
 * @param lines       Flat stream of log lines from the SSE feed.
 * @param doneStatus  Terminal pipeline status used to set the final step's
 *                    status once the stream ends. Pass null while streaming.
 */
export function groupOptimizationLines(
  lines: LogLine[],
  doneStatus: "optimization-complete" | "failed" | null,
  progressSnapshot?: OptimizationProgressEvent | null,
): PipelineStep[] {
  const steps: PipelineStep[] = [];

  let curId = "";
  let curName = "";
  let curStatus: PipelineStep["status"] = "running";
  let curLines: StepLogLine[] = [];
  let curFirstTs: string | undefined;
  let stepIdx = 0;
  let isOpen = false;
  let currentSegmentLabel: string | null = null;
  let currentSegmentIndex: number | null = null;
  let totalSegments: number | null = null;
  let segmentProgressLineIdxByLabel = new Map<string, number>();
  const hasStructuredProgress = !!progressSnapshot;

  function openStep(id: string, name: string, ts?: string) {
    curId = id;
    curName = name;
    curStatus = "running";
    curLines = [];
    curFirstTs = ts;
    isOpen = true;
    currentSegmentLabel = null;
    currentSegmentIndex = null;
    totalSegments = null;
    segmentProgressLineIdxByLabel = new Map();
  }

  function flushStep(status: PipelineStep["status"], lastTs?: string) {
    if (!isOpen) return;
    steps.push({
      id: curId,
      name: curName,
      status,
      durationLabel: computeDurationLabel(curFirstTs, lastTs),
      lines: [...curLines],
    });
    isOpen = false;
  }

  for (const line of lines) {
    const kind = classifyLine(line);
    const msg = line.message;
    if (kind === "separator") continue;

    // 1. Explicit `Stage N: Name` structural marker — highest priority.
    //    Step name is derived from the header text; the line itself is not
    //    added as a log entry (it serves as a section divider).
    const stageMatch = /^Stage \d+[a-z]?:\s*(.+)$/i.exec(msg);
    if (stageMatch) {
      if (isOpen) flushStep(curStatus === "failed" ? "failed" : "success", line.timestamp);
      openStep(`step-${stepIdx++}`, stripStageNumberingPrefix(stageMatch[1].trim()), line.timestamp);
      continue;
    }

    // 2. Legacy `🤖`-prefixed stage marker.
    if (kind === "stage") {
      if (isOpen) flushStep(curStatus === "failed" ? "failed" : "success", line.timestamp);
      openStep(`step-${stepIdx++}`, stripStageNumberingPrefix(stripPrefix(msg)), line.timestamp);
      continue;
    }

    // 3. Keyword-based semantic stage detection.
    //    Opens a new step when a trigger message is seen, unless the same
    //    named step is already open (prevents duplicate opening on re-render).
    const semanticStage = SEMANTIC_STAGE_TRIGGERS.find((s) => s.trigger.test(msg));
    if (semanticStage && (!isOpen || curName !== semanticStage.name)) {
      if (isOpen) flushStep(curStatus === "failed" ? "failed" : "success", line.timestamp);
      openStep(`step-${stepIdx++}`, semanticStage.name, line.timestamp);
      // Fall through — the trigger line is a real log message; add it to the
      // newly opened step below.
    } else if (!isOpen) {
      // No trigger matched and no step is open — absorb into a generic preamble.
      openStep(`step-${stepIdx++}`, "Initialization", line.timestamp);
    }

    const level: StepLogLine["level"] =
      line.level === "ERROR" ? "error" : line.level === "WARNING" ? "warning" : "info";

    const clean = stripPrefix(msg);

    // Track segment context so progress updates can collapse into a single line.
    const segmentStartMatch = /^Generating output for segment\s+(\d+)\/(\d+)\b/i.exec(clean)
      || /^Prepare generation request \(.+segment=segment\s+(\d+)\/(\d+)\s+chars\)$/i.exec(clean)
      || /^Generation complete for segment\s+(\d+)\/(\d+)\b/i.exec(clean);
    if (segmentStartMatch) {
      currentSegmentIndex = Number(segmentStartMatch[1]);
      totalSegments = Number(segmentStartMatch[2]);
      currentSegmentLabel = `Segment ${segmentStartMatch[1]}/${segmentStartMatch[2]}`;
    }

    // Also detect total segment count from planning logs.
    const totalSegmentCountMatch = /using\s+(\d+)\s+optimization segment\(s\)/i.exec(clean);
    if (totalSegmentCountMatch) {
      const parsed = Number(totalSegmentCountMatch[1]);
      if (Number.isFinite(parsed) && parsed > 0) totalSegments = parsed;
    }

    function upsertSegmentProgress(percent: number, detail: string, explicitLabel?: string) {
      const clamped = Math.max(0, Math.min(100, percent));
      const label = explicitLabel ?? (
        totalSegments && currentSegmentIndex
          ? `Segment ${currentSegmentIndex}/${totalSegments}`
          : "Current segment"
      );
      const lineEntry: StepLogLine = {
        text: label,
        level,
        progress: {
          percent: clamped,
          label,
          detail,
        },
      };

      const existingIdx = segmentProgressLineIdxByLabel.get(label);
      if (existingIdx !== undefined) {
        curLines[existingIdx] = lineEntry;
      } else {
        segmentProgressLineIdxByLabel.set(label, curLines.length);
        curLines.push(lineEntry);
      }
    }

    // Replace noisy per-percent lines with one live CURRENT-SEGMENT progress entry.
    const progressMatch = /^Generate output:\s*(\d+)%\s*\((.+)\)$/i.exec(clean);
    if (progressMatch && !hasStructuredProgress) {
      const segmentPercent = Number(progressMatch[1]);
      const tokenDetail = progressMatch[2]?.trim() ?? "";
      const segmentProgressPercent = Number.isFinite(segmentPercent)
        ? Math.max(0, Math.min(100, segmentPercent))
        : 0;

      const detail = tokenDetail;
      upsertSegmentProgress(segmentProgressPercent, detail, currentSegmentLabel ?? undefined);
    } else {
      // Keep current-segment progress in sync on segment completion in case the
      // final 100% token-progress line is not emitted before completion log.
      const segmentDoneMatch = /^Generation complete for segment\s+(\d+)\/(\d+)\b/i.exec(clean);
      if (segmentDoneMatch) {
        const segIdx = Number(segmentDoneMatch[1]);
        const segTotal = Number(segmentDoneMatch[2]);
        if (Number.isFinite(segIdx) && Number.isFinite(segTotal) && segTotal > 0) {
          currentSegmentIndex = segIdx;
          totalSegments = segTotal;
          currentSegmentLabel = `Segment ${segIdx}/${segTotal}`;
          upsertSegmentProgress(100, `${currentSegmentLabel} complete`);
        }
        curLines.push({ text: clean, level });
      } else {
        // With structured progress enabled, skip noisy per-percent text lines.
        if (hasStructuredProgress && /^Generate output:\s*\d+%\s*\(/i.test(clean)) {
          continue;
        }
        curLines.push({ text: clean, level });
      }
    }

    if (line.level === "ERROR") {
      curStatus = "failed";
    }
  }

  // Flush the last open step.
  if (isOpen) {
    flushStep(curStatus);
  }

  if (progressSnapshot && steps.length > 0) {
    const generationStep =
      [...steps].reverse().find((s) => /generation/i.test(s.name))
      ?? steps[steps.length - 1];

    const tokens =
      progressSnapshot.tokens_generated !== null && progressSnapshot.tokens_target !== null
        ? `${progressSnapshot.tokens_generated}/${progressSnapshot.tokens_target} tokens`
        : null;

    const elapsed =
      progressSnapshot.elapsed_seconds !== null
        ? `${Math.floor(progressSnapshot.elapsed_seconds / 60)}:${String(progressSnapshot.elapsed_seconds % 60).padStart(2, "0")} elapsed`
        : null;

    const detail = [tokens, elapsed].filter(Boolean).join(" · ");

    const progressLine: StepLogLine = {
      text: progressSnapshot.label || "Current segment",
      level: "info",
      progress: {
        percent: Math.max(0, Math.min(100, progressSnapshot.segment_progress_percent)),
        label: progressSnapshot.label || "Current segment",
        detail,
      },
    };

    const progressLabel = progressSnapshot.label || "Current segment";
    const existingIdx = generationStep.lines.findIndex(
      (line) => line.progress?.label === progressLabel,
    );

    if (existingIdx >= 0) {
      generationStep.lines[existingIdx] = progressLine;
    } else {
      generationStep.lines.push(progressLine);
    }
  }

  // Apply terminal status once the stream is complete.
  if (doneStatus !== null && steps.length > 0) {
    const last = steps[steps.length - 1];
    if (last.status !== "failed") {
      last.status = doneStatus === "optimization-complete" ? "success" : "failed";
    }
  }

  return steps;
}
