"use client";

/**
 * Document Optimization Stage - LLM-Powered Enhancement Monitoring
 *
 * Monitors real-time optimization progress via SSE streaming, shows terminal
 * logs, and provides retry/abort controls for the optimization pipeline stage.
 *
 * Input:  Document in APPROVED_FOR_OPTIMIZATION status
 * Output: Document transitions to OPTIMIZATION_COMPLETE (ready for QA)
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
import { Button } from "@/components/ui/button";
import { fastapiFetch, getPipelineStatus, streamOptimizationLogs } from "@/lib/api";
import { isQAReadyStatus } from "@/lib/document-status";
import {
  LogEntry,
  StatusPill,
  formatElapsed,
  type LogLine,
  type OptimizationStatus,
} from "./_components/LogEntry";

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
  const [hasLogErrors, setHasLogErrors] = useState(false);
  const [isAlreadyComplete, setIsAlreadyComplete] = useState(false);
  const [statusError, setStatusError] = useState<string | null>(null);

  const terminalRef = useRef<HTMLDivElement>(null);

  // -------------------------------------------------------------------------
  // Document title + initial status check
  // -------------------------------------------------------------------------

  useEffect(() => {
    let cancelled = false;
    async function loadTitleAndInitialStatus() {
      try {
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
        const st = await getPipelineStatus(docId);
        if (cancelled) return;
        if (!title) {
          title = `Document ${String(st.document_id).slice(0, 8)}…`;
        }
        setDocTitle(title);
        if (st.started_at) setStartedAt(st.started_at);
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
              { timestamp: event.timestamp, level: event.level, message: event.message },
            ]);
            if (event.level === "ERROR") {
              setLastError(event.message);
              setHasLogErrors(true);
            }
          } else if (event.type === "done") {
            setDoneStatus(event.status);
            setOptStatus(
              event.status === "optimization-complete" ? "optimization-complete" : "failed"
            );
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        throw error;
      }
    }

    void run();
    return () => { controller.abort(); };
    // retryCount triggers stream restart on retry
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
      await fastapiFetch(`/api/v1/documents/${docId}/approve-for-optimization`, { method: "POST" });
      setLogLines([]);
      setDoneStatus(null);
      setLastError(null);
      setElapsedSeconds(0);
      setStartedAt(null);
      setOptStatus("approved-for-optimization");
      setUserScrolledUp(false);
      setRetryCount((c) => c + 1);
    } catch {
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

        {/* Header */}
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
                <Button size="sm" variant="outline" className="gap-1.5" disabled={isRetrying} onClick={() => void handleRetry()}>
                  <RefreshCw className={`h-3.5 w-3.5 ${isRetrying ? "animate-spin" : ""}`} />
                  {isRetrying ? "Retrying…" : "Retry"}
                </Button>
                <Button size="sm" variant="outline" className="gap-1.5" onClick={() => router.push(`/admin/documents/${docId}/review`)}>
                  <ArrowLeft className="h-3.5 w-3.5" />
                  Back to Review
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Completion banner */}
        {doneStatus === "optimization-complete" && (
          <div className="mx-6 mt-4 shrink-0 rounded-lg border border-green-400/30 bg-green-400/5 px-5 py-3 flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
            <div className="flex-1">
              <p className="font-semibold text-green-400">Optimization complete</p>
              <p className="text-sm text-muted-foreground">Review and edit the optimized chunks before running QA scoring.</p>
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

        {/* Degraded completion banner */}
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

        {/* Failure banner */}
        {doneStatus === "failed" && (
          <div className="mx-6 mt-4 shrink-0 rounded-lg border border-red-400/30 bg-red-400/5 px-5 py-3 flex items-start gap-3">
            <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-red-400">Optimization failed</p>
              {lastError && (
                <p className="text-sm text-muted-foreground mt-0.5 font-mono truncate">{lastError}</p>
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

        {/* Terminal log pane */}
        <div className="flex-1 flex flex-col min-h-0 mx-6 my-4">
          <div className="flex items-center gap-2 px-4 py-2 rounded-t-lg bg-zinc-800 border border-zinc-700 border-b-0 shrink-0">
            <div className="flex gap-1.5" aria-hidden="true">
              <span className="h-3 w-3 rounded-full bg-red-500/50" />
              <span className="h-3 w-3 rounded-full bg-yellow-500/50" />
              <span className="h-3 w-3 rounded-full bg-green-500/50" />
            </div>
            <span className="text-xs text-zinc-500 font-mono ml-2 flex-1">optimization · stage 10</span>
            {logLines.length > 0 && (
              <span className="text-[10px] text-zinc-600 font-mono tabular-nums">{logLines.length} lines</span>
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

          <div
            ref={terminalRef}
            onScroll={handleTerminalScroll}
            className="flex-1 overflow-y-auto min-h-0 py-3 font-mono bg-zinc-950 rounded-b-lg border border-zinc-700"
          >
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
                <p className="pl-4 text-xs text-red-400 italic">Unable to load status: {statusError}</p>
              ) : doneStatus === null ? (
                <p className="pl-4 text-xs text-zinc-600 italic">Waiting for runner output...</p>
              ) : null
            )}

            {logLines.map((line, idx) => (
              <LogEntry key={idx} line={line} />
            ))}

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
