"use client";

/**
 * PipelineJobLog — Collapsible step-grouped log viewer
 *
 * Renders a live or completed pipeline execution log as a series of
 * collapsible step rows. Each step shows its run status, name, and
 * optional duration. Expanding a step reveals its individual log lines
 * with sequential line numbers and per-line severity colouring.
 *
 * Design principles:
 * - Running and failed steps auto-expand; pending/success steps start collapsed.
 * - Line numbers are cumulative across all steps (matches editor convention).
 * - Error lines receive a distinct background highlight for immediate triage.
 * - The component is scroll-agnostic: the caller wraps it in an overflow container.
 */

import React, { useState, useEffect, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  ChevronRight,
  ChevronDown,
  Loader2,
  AlertTriangle,
  Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type StepStatus = "pending" | "running" | "success" | "failed" | "warning";

export interface StepLogLine {
  text: string;
  level?: "info" | "warning" | "error";
  progress?: {
    /** 0-100 */
    percent: number;
    /** e.g. Segment 3/29 */
    label?: string;
    /** e.g. 4329/8000 tokens, 01:10 elapsed */
    detail?: string;
  };
}

export interface PipelineStep {
  id: string;
  name: string;
  status: StepStatus;
  /** Human-readable duration shown right-aligned in the step row. e.g. "3s", "1m 4s" */
  durationLabel?: string;
  lines: StepLogLine[];
}

interface PipelineJobLogProps {
  steps: PipelineStep[];
  /**
   * When true, a blinking cursor is rendered inside the last running step,
   * signalling that output is still being received.
   */
  isActive?: boolean;
  className?: string;
  "aria-label"?: string;
}

// ---------------------------------------------------------------------------
// Step status icon
// ---------------------------------------------------------------------------

function StepStatusIcon({ status }: { status: StepStatus }) {
  if (status === "success") {
    return <CheckCircle2 className="h-4 w-4 text-[#3fb950] shrink-0" aria-label="Success" />;
  }
  if (status === "failed") {
    return <XCircle className="h-4 w-4 text-[#f85149] shrink-0" aria-label="Failed" />;
  }
  if (status === "warning") {
    return <AlertTriangle className="h-4 w-4 text-[#d29922] shrink-0" aria-label="Warning" />;
  }
  if (status === "running") {
    return (
      <Loader2 className="h-4 w-4 text-[#58a6ff] shrink-0 animate-spin" aria-label="Running" />
    );
  }
  // pending
  return (
    <span aria-label="Pending" className="h-4 w-4 shrink-0 flex items-center justify-center">
      <Minus className="h-3 w-3 text-[#484f58]" />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Duration helper
// ---------------------------------------------------------------------------

function computeDurationLabel(startIso?: string, endIso?: string): string | undefined {
  if (!startIso || !endIso) return undefined;
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (isNaN(ms) || ms < 0) return undefined;
  const s = Math.round(ms / 1000);
  if (s === 0) return "< 1s";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

export { computeDurationLabel };

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PipelineJobLog({
  steps,
  isActive = false,
  className,
  "aria-label": ariaLabel = "Pipeline log",
}: PipelineJobLogProps) {
  // --- Expand/collapse state ---
  // Running and failed steps open automatically; everything else starts closed.
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const init = new Set<string>();
    for (const s of steps) {
      if (s.status === "running" || s.status === "failed") init.add(s.id);
    }
    return init;
  });

  // When a step transitions to running or failed, auto-expand it.
  useEffect(() => {
    setExpanded((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const s of steps) {
        if ((s.status === "running" || s.status === "failed") && !next.has(s.id)) {
          next.add(s.id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [steps]);

  const toggle = useCallback((id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Cumulative line number offsets (1-based, continuous across all steps).
  const lineOffsets: number[] = [];
  let cursor = 1;
  for (const step of steps) {
    lineOffsets.push(cursor);
    cursor += step.lines.length;
  }

  // --- Render ---
  return (
    <div
      role="log"
      aria-live="polite"
      aria-label={ariaLabel}
      className={cn("font-mono text-xs bg-[#0d1117]", className)}
    >
      {/* Empty state */}
      {steps.length === 0 && (
        <div className="px-6 py-10 text-center text-[#6e7681] text-xs italic">
          {isActive ? "Waiting for runner output…" : "No log output available."}
        </div>
      )}

      {steps.map((step, si) => {
        const isExpanded = expanded.has(step.id);
        const isLast = si === steps.length - 1;
        const hasLines = step.lines.length > 0;
        const baseLineNum = lineOffsets[si];

        const rowBg =
          step.status === "running"
            ? "bg-[#0f2744]"
            : step.status === "failed"
              ? "bg-[#1c0a0a]"
              : step.status === "warning"
                ? "bg-[#1c1507]"
                : "";

        const nameColor =
          step.status === "running"
            ? "text-[#58a6ff]"
            : step.status === "failed"
              ? "text-[#f85149]"
              : step.status === "warning"
                ? "text-[#d29922]"
                : step.status === "pending"
                  ? "text-[#8b949e]"
                  : "text-[#e6edf3]";

        return (
          <div key={step.id} className="border-b border-[#21262d] last:border-b-0">
            {/* Step header row */}
            <button
              type="button"
              className={cn(
                "w-full flex items-center gap-2 px-3 py-[7px] text-left transition-colors hover:bg-[#161b22]",
                rowBg,
                !hasLines && "cursor-default",
              )}
              onClick={hasLines ? () => toggle(step.id) : undefined}
              aria-expanded={hasLines ? isExpanded : undefined}
              disabled={!hasLines && step.status === "pending"}
            >
              {/* Expand chevron */}
              <span className="w-4 shrink-0 flex items-center justify-center text-[#484f58]">
                {hasLines ? (
                  isExpanded ? (
                    <ChevronDown className="h-3 w-3" />
                  ) : (
                    <ChevronRight className="h-3 w-3" />
                  )
                ) : (
                  <span className="h-3 w-3 block" />
                )}
              </span>

              <StepStatusIcon status={step.status} />

              <span className={cn("flex-1 text-[13px] font-medium truncate", nameColor)}>
                {step.name}
              </span>

              {step.durationLabel && (
                <span className="shrink-0 text-[#6e7681] text-[11px] tabular-nums ml-2">
                  {step.durationLabel}
                </span>
              )}
            </button>

            {/* Expanded log lines */}
            {isExpanded && hasLines && (
              <div className="bg-[#010409]">
                {step.lines.map((line, li) => {
                  const lineNum = baseLineNum + li;
                  const isErr = line.level === "error";
                  const isWarn = line.level === "warning";

                  return (
                    <div
                      key={li}
                      className={cn(
                        "flex items-start min-w-0",
                        isErr && "bg-[#3d1212]",
                        isWarn && "bg-[#201b05]",
                      )}
                    >
                      {/* Line number */}
                      <span className="select-none text-[#6e7681] text-right shrink-0 w-10 px-2 py-[2px] text-[11px] leading-5 border-r border-[#21262d] bg-[#010409] sticky left-0">
                        {lineNum}
                      </span>
                      {/* Log text / structured progress */}
                      <div className="flex-1 px-4 py-[2px] min-w-0">
                        {line.progress ? (
                          <div className="py-[2px]">
                            {(() => {
                              const progressPercent = Math.max(0, Math.min(100, line.progress!.percent));
                              const isComplete = progressPercent >= 100;
                              const percentColor = isComplete ? "text-[#3fb950]" : "text-[#58a6ff]";
                              const barColor = isComplete ? "bg-[#3fb950]" : "bg-[#2f81f7]";

                              return (
                                <>
                                  <div className="flex items-center justify-between gap-3 text-[11px] leading-4">
                                    <span className="text-[#8b949e] truncate">
                                      {line.progress.label ?? line.text}
                                    </span>
                                    <span className={cn("tabular-nums shrink-0", percentColor)}>
                                      {progressPercent}%
                                    </span>
                                  </div>
                                  <div className="mt-1 h-1.5 w-full rounded bg-[#21262d] overflow-hidden">
                                    <div
                                      className={cn("h-full transition-[width] duration-300 ease-out", barColor)}
                                      style={{ width: `${progressPercent}%` }}
                                    />
                                  </div>
                                  {line.progress.detail && (
                                    <p className="mt-1 text-[11px] leading-4 text-[#6e7681] break-all whitespace-pre-wrap">
                                      {line.progress.detail}
                                    </p>
                                  )}
                                </>
                              );
                            })()}
                          </div>
                        ) : (
                          <span
                            className={cn(
                              "text-[12px] leading-5 break-all whitespace-pre-wrap",
                              isErr
                                ? "text-[#ffa198]"
                                : isWarn
                                  ? "text-[#e3b341]"
                                  : "text-[#e6edf3]",
                            )}
                          >
                            {line.text}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })}

                {/* Blinking cursor — shown only inside the last actively running step */}
                {isActive && isLast && step.status === "running" && (
                  <div className="flex items-start">
                    <span className="select-none w-10 px-2 py-[2px] border-r border-[#21262d] bg-[#010409]" />
                    <span className="px-4 py-[2px] text-[#6e7681] text-[12px] leading-5 animate-pulse">
                      █
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
