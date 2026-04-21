"use client";

/**
 * Ingestion pipeline log processing utilities.
 *
 * toLogLine   — converts a raw SSE event into a structured PipelineLogLine.
 * groupIngestionLines — groups a flat PipelineLogLine[] into PipelineStep[]
 *                       suitable for the PipelineJobLog viewer.
 * IngestionLogEntry   — legacy per-line renderer (kept for reference).
 */

import type { IngestionSSEEvent } from "@/lib/api";
import type { PipelineStep, StepLogLine } from "@/components/shared/PipelineJobLog";
import { computeDurationLabel } from "@/components/shared/PipelineJobLog";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LogCategory = "init" | "step-start" | "progress" | "stage-done" | "done" | "error";

export interface PipelineLogLine {
  timestamp: string;
  level: "INFO" | "ERROR";
  category: LogCategory;
  stage: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STAGE_LABEL: Record<string, string> = {
  queued:     "queue",
  upload:     "upload",
  extraction: "extract",
  validation: "validate",
  completed:  "pipeline",
  startup:    "system",
  monitoring: "monitor",
};

function stripStageNumberingPrefix(message: string): string {
  return message.replace(/^Stage\s+\d+[a-z]?:\s*/i, "").trim();
}

export function toLogLine(event: IngestionSSEEvent): PipelineLogLine {
  const stage = STAGE_LABEL[event.stage] ?? event.stage;
  const ts = event.timestamp;
  switch (event.type) {
    case "ping":
      return { timestamp: ts, level: "INFO", category: "progress", stage, message: event.message || "Waiting for runner output..." };
    case "job.accepted":
      return { timestamp: ts, level: "INFO", category: "init", stage, message: event.message || "Pipeline job accepted" };
    case "progress": {
      const isStepHeader = /^Stage \d+[a-z]?:/i.test(event.message);
      return { timestamp: ts, level: "INFO", category: isStepHeader ? "step-start" : "progress", stage, message: event.message };
    }
    case "stage.complete":
      return { timestamp: ts, level: "INFO", category: "stage-done", stage, message: event.message };
    case "complete":
      return { timestamp: ts, level: "INFO", category: "done", stage: "pipeline", message: event.message || "Pipeline complete" };
    case "error":
      return { timestamp: ts, level: "ERROR", category: "error", stage, message: event.error || event.message };
  }
}

function toHHMMSS(isoTs: string): string {
  try { return new Date(isoTs).toTimeString().slice(0, 8); } catch { return "--:--:--"; }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function IngestionLogEntry({ line }: { line: PipelineLogLine }) {
  const timeStr = toHHMMSS(line.timestamp);

  if (line.category === "step-start") {
    return (
      <div className="flex items-center gap-2 pl-3 pr-3 py-1.5 mt-2 mb-0.5 border-l-2 border-amber-500/50 bg-amber-500/5">
        <span className="text-[10px] text-zinc-700 font-mono shrink-0 w-[60px] select-none tabular-nums">{timeStr}</span>
        <span className="text-[10px] text-amber-500 font-mono shrink-0">▶</span>
        <span className="flex-1 text-[11px] text-amber-300/90 font-semibold tracking-wide">{line.message}</span>
      </div>
    );
  }

  const borderClass =
    line.category === "stage-done" ? "border-l-2 border-green-600/70"
    : line.category === "done"     ? "border-l-2 border-green-500"
    : line.category === "init"     ? "border-l-2 border-sky-500/80"
    : line.category === "error"    ? "border-l-2 border-red-500"
    : "";

  const bgClass = line.category === "error" ? "bg-red-950/20" : "";

  const badge =
    line.category === "init"         ? <span className="text-[10px] text-sky-400 font-mono font-semibold shrink-0 w-12">INIT</span>
    : line.category === "progress"   ? <span className="text-[10px] text-zinc-600 font-mono shrink-0 w-12">···</span>
    : line.category === "stage-done" ? <span className="text-[10px] text-green-400 font-mono shrink-0 w-12">OK</span>
    : line.category === "done"       ? <span className="text-[10px] text-green-400 font-mono font-bold shrink-0 w-12">DONE</span>
    : line.category === "error"      ? <span className="text-[10px] text-red-400 font-mono font-bold shrink-0 w-12">ERR</span>
    :                                  <span className="text-[10px] text-zinc-700 font-mono shrink-0 w-12">—</span>;

  const msgClass =
    line.category === "stage-done" ? "text-green-300"
    : line.category === "done"     ? "text-green-300 font-medium"
    : line.category === "error"    ? "text-red-300 font-medium"
    : line.category === "init"     ? "text-zinc-200 font-medium"
    : line.category === "progress" ? "text-zinc-400"
    : "text-zinc-500";

  return (
    <div className={`flex gap-2 items-baseline py-0.5 pl-3 pr-2 ${borderClass} ${bgClass}`}>
      <span className="text-zinc-600 text-[10px] font-mono shrink-0 w-[60px] select-none tabular-nums">
        {timeStr}
      </span>
      {badge}
      <span className="text-zinc-600 text-[10px] font-mono shrink-0 w-[52px] truncate">
        [{line.stage}]
      </span>
      <span className={`flex-1 break-words text-xs leading-relaxed ${msgClass}`}>
        {line.message}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step grouping — converts flat log lines into collapsible PipelineStep[]
// ---------------------------------------------------------------------------

/**
 * Groups a flat PipelineLogLine array into PipelineStep[] for the
 * PipelineJobLog viewer. Grouping rules:
 *
 * - "init"       → implicit "Initialize" step (first lines before any stage opens)
 * - "step-start" → opens a new named step (message is the step title)
 * - "progress"   → appended to the current open step
 * - "stage-done" → appends the completion message and closes the step as success
 * - "done"       → closes the current step as success
 * - "error"      → closes the current step as failed
 */
export function groupIngestionLines(lines: PipelineLogLine[]): PipelineStep[] {
  const steps: PipelineStep[] = [];

  // Internal mutable build state
  let curName = "";
  let curStatus: PipelineStep["status"] = "running";
  let curLines: StepLogLine[] = [];
  let curId = "";
  let curFirstTs: string | undefined;
  let stepIdx = 0;
  let isOpen = false;

  function openStep(id: string, name: string, ts?: string) {
    curId = id;
    curName = name;
    curStatus = "running";
    curLines = [];
    curFirstTs = ts;
    isOpen = true;
  }

  function closeStep(status: PipelineStep["status"], lastTs?: string) {
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
    switch (line.category) {
      case "init": {
        if (!isOpen) openStep(`step-${stepIdx++}`, "Initialize", line.timestamp);
        curLines.push({ text: line.message, level: "info" });
        break;
      }
      case "step-start": {
        if (isOpen) closeStep("success", line.timestamp);
        openStep(`step-${stepIdx++}`, stripStageNumberingPrefix(line.message), line.timestamp);
        break;
      }
      case "progress": {
        if (!isOpen) openStep(`step-${stepIdx++}`, "Running", line.timestamp);
        curLines.push({ text: line.message, level: "info" });
        break;
      }
      case "stage-done": {
        if (isOpen) {
          curLines.push({ text: line.message, level: "info" });
          closeStep("success", line.timestamp);
        }
        break;
      }
      case "done": {
        if (isOpen) {
          curLines.push({ text: line.message, level: "info" });
          closeStep("success", line.timestamp);
        } else {
          steps.push({
            id: `step-${stepIdx++}`,
            name: "Complete",
            status: "success",
            lines: [{ text: line.message, level: "info" }],
          });
        }
        break;
      }
      case "error": {
        if (isOpen) {
          curLines.push({ text: line.message, level: "error" });
          closeStep("failed", line.timestamp);
        } else {
          steps.push({
            id: `step-${stepIdx++}`,
            name: "Pipeline Error",
            status: "failed",
            lines: [{ text: line.message, level: "error" }],
          });
        }
        break;
      }
    }
  }

  // Flush any step still open (pipeline still running)
  if (isOpen) {
    steps.push({
      id: curId,
      name: curName,
      status: "running",
      lines: [...curLines],
    });
  }

  return steps;
}
