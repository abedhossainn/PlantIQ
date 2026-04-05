"use client";

/**
 * Terminal log entry component for the document ingestion pipeline.
 * Renders structured pipeline log lines with colour-coded categories.
 */

import type { IngestionSSEEvent } from "@/lib/api";

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

export function toLogLine(event: IngestionSSEEvent): PipelineLogLine {
  const stage = STAGE_LABEL[event.stage] ?? event.stage;
  const ts = event.timestamp;
  switch (event.type) {
    case "job.accepted":
      return { timestamp: ts, level: "INFO", category: "init", stage, message: event.message || "Pipeline job accepted" };
    case "progress": {
      const isStepHeader = /^Stage \d+:/.test(event.message);
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
