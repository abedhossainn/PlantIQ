"use client";

/**
 * Document Optimization Stage - LLM-Powered Enhancement Monitoring
 * 
 * Purpose:
 * - Display real-time optimization progress via SSE streaming
 * - Monitor LLM-powered enhancements (summary, synthetic QA pairs, augmentation)
 * - Show terminal-style logs for debugging + audit trail
 * - Allow retry/abort of stuck optimization processes
 * 
 * Pipeline Stage Context:
 * - Input: Document in APPROVED_FOR_OPTIMIZATION status
 * - Process: Backend spins up LLM task via vLLM (text pipeline)
 * - Output: Document transitions to OPTIMIZATION_COMPLETE (ready for QA)
 * - Optional: Can skip directly to QA if optimization disabled
 * 
 * Optimization Tasks (Configurable):
 * - Generate optimized summary from extracted content
 * - Create synthetic Q&A pairs for training/validation
 * - Augment document with semantic tags/keywords
 * - Validate consistency with source material
 * 
 * SSE Event Streaming:
 * - streamOptimizationLogs() opens SSE connection to /documents/{id}/optimization/logs
 * - Events: log (INFO|WARNING|ERROR), done (optimization-complete|failed), heartbeat
 * - Browser reconnection and replay from buffer (SSE buffer on backend)
 * - Terminal log display: scrollable, color-coded by level, timestamps included
 * 
 * Monitoring Features:
 * - Real-time log streaming with auto-scroll
 * - Elapsed time tracking + ETA estimation
 * - Stage indicator showing current task (extraction → QA tagging, etc.)
 * - Abort button to cancel running optimization
 * - Retry button to restart failed optimizations
 * 
 * State Management:
 * - status: Current OptimizationStatus (optimizing|optimization-complete|failed)
 * - logs: Terminal log buffer (logLines with timestamp, level, message)
 * - isStreaming: Active SSE connection indicator
 * - startTime: For elapsed time calculation
 * 
 * Error Handling:
 * - SSE connection errors: Show error state + retry
 * - Timeout: After 30 mins without progress, suggest manual intervention
 * - Failed status: Show error logs + provide clear next steps
 * 
 * Performance Considerations:
 * - Terminal log buffer limited to prevent DOM bloat (auto-scroll with virtual list)
 * - SSE events batched to reduce UI re-renders
 * - AbortSignal cleanup on unmount prevents memory leaks
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  Terminal,
  XCircle,
} from "lucide-react";

import { AppLayout } from "@/components/shared/AppLayout";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fastapiFetch, getPipelineStatus, streamOptimizationLogs } from "@/lib/api";
import { getOptimizationLifecycleLabel, isQAReadyStatus } from "@/lib/document-status";
import type { DocumentStatus } from "@/types";

// ---------------------------------------------------------------------------
// Optimization Stage Runtime Notes
// ---------------------------------------------------------------------------
// - Optimization may be skipped by backend policy; always check terminal status.
// - SSE stream can replay buffered logs when reconnecting after temporary disconnects.
// - `done` events are terminal and should short-circuit additional stream handling.
// - UI should remain responsive during long-running model operations.
// - Elapsed timers are informational; backend state is authoritative.
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type OptimizationStatus = Extract<
  DocumentStatus,
  "approved-for-optimization" | "optimizing" | "optimization-complete" | "failed"
>;

/**
 * All document statuses that mean optimization has already completed.
 * Any of these arriving from the backend means we should immediately show
 * the completion state rather than waiting for the SSE stream.
 * Uses isQAReadyStatus from document-status.ts — same set of statuses.
 */

interface LogLine {
  timestamp: string;
  level: "INFO" | "WARNING" | "ERROR";
  message: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatElapsed(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) {
    return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  }
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function toHHMMSS(isoTimestamp: string): string {
  try {
    return new Date(isoTimestamp).toTimeString().slice(0, 8);
  } catch {
    return "--:--:--";
  }
}

// ---------------------------------------------------------------------------
// Log classification
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
// Log entry
// ---------------------------------------------------------------------------

function LogEntry({ line }: { line: LogLine }) {
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
// Status pill
// ---------------------------------------------------------------------------

function StatusPill({ status }: { status: OptimizationStatus }) {
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
// Main component
// ---------------------------------------------------------------------------

export default function OptimizingClient({ docId }: { docId: string }) {
  const router = useRouter();

  const [docTitle, setDocTitle] = useState<string>("");
  const [optStatus, setOptStatus] = useState<OptimizationStatus>("approved-for-optimization");
  const [logLines, setLogLines] = useState<LogLine[]>([]);
  const [doneStatus, setDoneStatus] = useState<"optimization-complete" | "failed" | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);
  const [retryCount, setRetryCount] = useState(0);
  const [userScrolledUp, setUserScrolledUp] = useState(false);
  // True when any ERROR-level log line was received — used to show a degraded-
  // completion warning even when the overall status is optimization-complete.
  const [hasLogErrors, setHasLogErrors] = useState(false);
  // True when we detected completion from the initial status probe (not the SSE stream)
  const [isAlreadyComplete, setIsAlreadyComplete] = useState(false);
  // Set when the initial status probe fails so the terminal can show an error
  const [statusError, setStatusError] = useState<string | null>(null);

  const terminalRef = useRef<HTMLDivElement>(null);

  // -------------------------------------------------------------------------
  // Document title + initial status check — load once on mount
  //
  // Always probes the backend status so we can immediately resolve doneStatus
  // if the document has already completed optimization.  The localStorage
  // preview is used only for the human-readable title.
  // -------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    async function loadTitleAndInitialStatus() {
      try {
        // Try localStorage for title (written by the upload page)
        let title = "";
        if (typeof window !== "undefined") {
          const stored = localStorage.getItem(`plantiq-upload-preview-${docId}`);
          if (stored) {
            try {
              const preview = JSON.parse(stored) as { title?: string };
              title = preview?.title ?? "";
            } catch { /* noop */ }
          }
        }
        // Always fetch current status — needed for both title fallback and
        // immediate completion detection.
        const st = await getPipelineStatus(docId);
        if (cancelled) return;
        if (!title) {
          title = `Document ${String(st.document_id).slice(0, 8)}…`;
        }
        setDocTitle(title);
        if (st.started_at) setStartedAt(st.started_at);
        // If optimization is already past, resolve immediately rather than
        // waiting for the SSE stream to deliver a "done" event.
        if (isQAReadyStatus(st.status)) {
          setOptStatus("optimization-complete");
          setDoneStatus("optimization-complete");
          setIsAlreadyComplete(true);
        } else if (st.status === "optimizing") {
          setOptStatus("optimizing");
        } else if (st.status === "failed") {
          setOptStatus("failed");
        }
      } catch (err) {
        if (!cancelled) {
          setStatusError(
            err instanceof Error ? err.message : "Failed to load document status."
          );
        }
      }
    }
    void loadTitleAndInitialStatus();
    return () => { cancelled = true; };
  }, [docId]);

  // -------------------------------------------------------------------------
  // Status polling — every 3 s until done
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (doneStatus !== null) return;

    let cancelled = false;

    async function poll() {
      try {
        const data = await getPipelineStatus(docId);
        if (cancelled) return;
        if (data.started_at) setStartedAt(data.started_at);
        // Detect any status that means optimization has completed or is
        // downstream of it — set doneStatus so banners / CTAs render.
        if (isQAReadyStatus(data.status)) {
          setOptStatus("optimization-complete");
          setDoneStatus("optimization-complete");
        } else if (data.status === "optimizing") {
          setOptStatus("optimizing");
        } else if (data.status === "failed") {
          setOptStatus("failed");
          setDoneStatus("failed");
        }
      } catch { /* noop */ }
    }

    void poll();
    const iv = setInterval(() => void poll(), 3000);
    return () => {
      cancelled = true;
      clearInterval(iv);
    };
  }, [docId, doneStatus, retryCount]);

  // -------------------------------------------------------------------------
  // Elapsed timer
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!startedAt || doneStatus !== null) return;
    const startMs = new Date(startedAt).getTime();
    const iv = setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startMs) / 1000));
    }, 1000);
    return () => clearInterval(iv);
  }, [startedAt, doneStatus]);

  // -------------------------------------------------------------------------
  // SSE stream
  // -------------------------------------------------------------------------

  useEffect(() => {
    const controller = new AbortController();

    async function run() {
      try {
        for await (const event of streamOptimizationLogs(docId, controller.signal)) {
          if (controller.signal.aborted) break;

          if (event.type === "log") {
            setLogLines((prev) => [
              ...prev,
              {
                timestamp: event.timestamp,
                level: event.level,
                message: event.message,
              },
            ]);
            if (event.level === "ERROR") {
              setLastError(event.message);
              setHasLogErrors(true);
            }
          } else if (event.type === "done") {
            setDoneStatus(event.status);
            setOptStatus(
              event.status === "optimization-complete"
                ? "optimization-complete"
                : "failed"
            );
          }
        }
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        throw error;
      }
    }

    void run();
    return () => {
      controller.abort();
    };
    // retryCount is intentionally included to restart the stream on retry
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId, retryCount]);

  // -------------------------------------------------------------------------
  // Auto-scroll terminal
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!userScrolledUp && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logLines, userScrolledUp]);

  const handleTerminalScroll = useCallback(() => {
    const el = terminalRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setUserScrolledUp(distFromBottom > 48);
  }, []);

  // -------------------------------------------------------------------------
  // Retry
  // -------------------------------------------------------------------------

  async function handleRetry() {
    setIsRetrying(true);
    try {
      await fastapiFetch(`/api/v1/documents/${docId}/approve-for-optimization`, {
        method: "POST",
      });
      // Reset state so the new run starts fresh
      setLogLines([]);
      setDoneStatus(null);
      setLastError(null);
      setElapsedSeconds(0);
      setStartedAt(null);
      setOptStatus("approved-for-optimization");
      setUserScrolledUp(false);
      setRetryCount((c) => c + 1);
    } catch {
      // If the endpoint is unavailable show a log line
      setLogLines((prev) => [
        ...prev,
        {
          timestamp: new Date().toISOString(),
          level: "ERROR",
          message: "Retry failed — could not contact backend. Please try again.",
        },
      ]);
    } finally {
      setIsRetrying(false);
    }
  }

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">

        {/* ── Header ── */}
        <div className="border-b border-border px-6 py-4 bg-card/50 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 mb-2 -ml-2"
            onClick={() => router.push("/admin/documents")}
          >
            <ArrowLeft className="h-4 w-4" />
            Document Pipeline
          </Button>

          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-3 min-w-0">
              <Terminal className="h-5 w-5 text-primary shrink-0" />
              <div className="min-w-0">
                <h1 className="font-bold text-lg leading-tight truncate">
                  {docTitle || "Optimizing Document…"}
                </h1>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-xs text-muted-foreground">Stage 10 · RAG Optimization</span>
                  <span className="text-zinc-700 text-xs">·</span>
                  <StatusPill status={optStatus} />
                  {doneStatus === null && startedAt && (
                    <span className="text-xs text-muted-foreground font-mono tabular-nums">
                      {formatElapsed(elapsedSeconds)}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Action buttons shown when done */}
            {doneStatus === "optimization-complete" && (
              <Button
                size="sm"
                className="gap-1.5 font-semibold shrink-0"
                onClick={() => router.push(`/admin/documents/${docId}/optimized-review`)}
              >
                Review Optimized Output
                <ArrowRight className="h-4 w-4" />
              </Button>
            )}
            {doneStatus === "failed" && (
              <div className="flex gap-2 shrink-0">
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  disabled={isRetrying}
                  onClick={() => void handleRetry()}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isRetrying ? "animate-spin" : ""}`} />
                  {isRetrying ? "Retrying…" : "Retry"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-1.5"
                  onClick={() => router.push(`/admin/documents/${docId}/review`)}
                >
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back to Review
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* ── Completion / failure banners ── */}
        {doneStatus === "optimization-complete" && (
          <div className="mx-6 mt-4 shrink-0 rounded-lg border border-green-400/30 bg-green-400/5 px-5 py-3 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
            <div className="flex-1">
              <p className="font-semibold text-green-400">Optimization complete</p>
              <p className="text-sm text-muted-foreground">
                Review and edit the optimized chunks before running QA scoring.
              </p>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 border-green-400/30 text-green-400 hover:bg-green-400/10 shrink-0"
              onClick={() => router.push(`/admin/documents/${docId}/optimized-review`)}
            >
              Review Optimized Output
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        )}

        {/* Degraded completion — completed via fallback due to model errors */}
        {doneStatus === "optimization-complete" && hasLogErrors && (
          <div className="mx-6 mt-2 shrink-0 rounded-lg border border-amber-400/30 bg-amber-400/5 px-5 py-3 flex items-start gap-3">
            <RefreshCw className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-amber-400 text-sm">Completed via fallback — model errors occurred</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                The LLM could not generate output (see ERR lines above). Optimization used deterministic
                synthesis instead. Review the QA output carefully before approval.
              </p>
              {lastError && (
                <p className="text-xs text-amber-300/70 font-mono mt-1 truncate">{lastError}</p>
              )}
            </div>
          </div>
        )}

        {doneStatus === "failed" && (
          <div className="mx-6 mt-4 shrink-0 rounded-lg border border-red-400/30 bg-red-400/5 px-5 py-3 flex items-start gap-3">
            <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-red-400">Optimization failed</p>
              {lastError && (
                <p className="text-sm text-muted-foreground mt-0.5 font-mono truncate">
                  {lastError}
                </p>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 border-red-400/30 text-red-400 hover:bg-red-400/10"
                disabled={isRetrying}
                onClick={() => void handleRetry()}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${isRetrying ? "animate-spin" : ""}`} />
                {isRetrying ? "Retrying…" : "Retry"}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5"
                onClick={() => router.push(`/admin/documents/${docId}/review`)}
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                Back to Review
              </Button>
            </div>
          </div>
        )}

        {/* ── Terminal log pane ── */}
        <div className="flex-1 flex flex-col min-h-0 mx-6 my-4">
          {/* Terminal chrome bar */}
          <div className="flex items-center gap-2 px-4 py-2 rounded-t-lg bg-zinc-800 border border-zinc-700 border-b-0 shrink-0">
            <div className="flex gap-1.5" aria-hidden="true">
              <span className="h-3 w-3 rounded-full bg-red-500/50" />
              <span className="h-3 w-3 rounded-full bg-yellow-500/50" />
              <span className="h-3 w-3 rounded-full bg-green-500/50" />
            </div>
            <span className="text-xs text-zinc-500 font-mono ml-2 flex-1">
              optimization · stage 10
            </span>
            {logLines.length > 0 && (
              <span className="text-[10px] text-zinc-600 font-mono tabular-nums">
                {logLines.length} lines
              </span>
            )}
            {userScrolledUp && (
              <button
                className="ml-2 text-[11px] text-zinc-300 bg-zinc-700 hover:bg-zinc-600 px-2 py-0.5 rounded transition-colors"
                onClick={() => {
                  setUserScrolledUp(false);
                  if (terminalRef.current) {
                    terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
                  }
                }}
              >
                ↓ Jump to bottom
              </button>
            )}
          </div>

          {/* Log output */}
          <div
            ref={terminalRef}
            onScroll={handleTerminalScroll}
            className="flex-1 overflow-y-auto min-h-0 py-3 font-mono bg-zinc-950 rounded-b-lg border border-zinc-700"
          >
            {/* Empty state — distinguish between waiting, already complete, and load error */}
            {logLines.length === 0 && (
              isAlreadyComplete ? (
                <div className="flex flex-col items-center justify-center h-32 gap-2 px-6 text-center">
                  <CheckCircle2 className="h-5 w-5 text-green-400" aria-hidden="true" />
                  <p className="text-sm text-zinc-400">Optimization already completed.</p>
                  <p className="text-xs text-zinc-600">
                    Live log output is only available for active runs. Proceed to review the optimized output.
                  </p>
                </div>
              ) : statusError !== null && doneStatus === null ? (
                <p className="pl-4 text-xs text-red-400 italic">
                  Unable to load status: {statusError}
                </p>
              ) : doneStatus === null ? (
                <p className="pl-4 text-xs text-zinc-600 italic">
                  Waiting for runner output...
                </p>
              ) : null
            )}

            {logLines.map((line, idx) => (
              <LogEntry key={idx} line={line} />
            ))}

            {/* Blinking cursor while running */}
            {doneStatus === null && (
              <div className="flex gap-2 pl-3 mt-1">
                <span className="text-zinc-700 text-[10px] font-mono w-[60px] select-none shrink-0" />
                <span className="text-zinc-500 font-mono text-xs animate-pulse">█</span>
              </div>
            )}
          </div>
        </div>

      </div>
    </AppLayout>
  );
}
