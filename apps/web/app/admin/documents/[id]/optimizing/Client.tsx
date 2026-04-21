"use client";

/**
 * Document Optimization Stage - LLM-Powered Enhancement Monitoring
 *
 * Monitors real-time optimization progress via SSE streaming, shows a
 * step-grouped log viewer, and provides retry/abort controls for the
 * optimization pipeline stage.
 *
 * Input:  Document in APPROVED_FOR_OPTIMIZATION status
 * Output: Document transitions to OPTIMIZATION_COMPLETE (ready for QA)
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  RefreshCw,
  Terminal,
  Loader2,
  XCircle,
} from "lucide-react";

import { AppLayout } from "@/components/shared/AppLayout";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { fastapiFetch, getPipelineStatus, streamOptimizationLogs } from "@/lib/api";
import type { OptimizationProgressEvent } from "@/lib/api";
import { isQAReadyStatus } from "@/lib/document-status";
import {
  StatusPill,
  formatElapsed,
  groupOptimizationLines,
  type LogLine,
  type OptimizationStatus,
} from "./_components/LogEntry";
import { PipelineJobLog } from "@/components/shared/PipelineJobLog";

type StageRailStatus = "pending" | "active" | "complete" | "failed";

const OPTIMIZATION_STAGES: Array<{ id: string; label: string; description: string }> = [
  {
    id: "model-initialization",
    label: "Model Bootstrapping",
    description: "Load tokenizer/model and verify generation readiness",
  },
  {
    id: "segmentation-plan",
    label: "Segmentation Planning",
    description: "Determine segment count and optimization boundaries",
  },
  {
    id: "segment-generation",
    label: "Segment Generation",
    description: "Generate optimized output for each segment",
  },
  {
    id: "output-validation",
    label: "Output Validation",
    description: "Finalize and validate generated structured output",
  },
  {
    id: "artifact-export",
    label: "Artifact Export",
    description: "Write artifacts and persist optimization completion",
  },
  {
    id: "completion",
    label: "Completion",
    description: "Finalize stage and hand off to optimized review",
  },
];

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
  const [latestProgress, setLatestProgress] = useState<OptimizationProgressEvent | null>(null);

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
  // SSE stream — with automatic reconnection
  //
  // The backend optimization SSE generator may close early (e.g. before the
  // BackgroundTask has called OptimizationLogManager.start, or if the proxy
  // resets the connection). When the stream ends without a "done" event and
  // the job is not yet terminal, reconnect after SSE_RECONNECT_DELAY_MS so
  // logs begin flowing once the backend has registered the running job.
  // -------------------------------------------------------------------------

  const SSE_RECONNECT_DELAY_MS = 3000;

  useEffect(() => {
    const controller = new AbortController();
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let receivedDone = false;

    async function run() {
      receivedDone = false;
      try {
        for await (const event of streamOptimizationLogs(docId, controller.signal)) {
          if (controller.signal.aborted) return;

          if (event.type === "log") {
            setLogLines((prev) => [
              ...prev,
              { timestamp: event.timestamp, level: event.level, message: event.message },
            ]);
            if (event.level === "ERROR") {
              setLastError(event.message);
              setHasLogErrors(true);
            }
          } else if (event.type === "progress") {
            setLatestProgress(event);
          } else if (event.type === "done") {
            receivedDone = true;
            setDoneStatus(event.status);
            setOptStatus(
              event.status === "optimization-complete" ? "optimization-complete" : "failed"
            );
          }
        }
      } catch {
        if (controller.signal.aborted) return;
      }

      // Stream ended. If we received a proper "done" event or the job is known
      // to be terminal, do not reconnect. Otherwise schedule a reconnect so we
      // pick up events once the backend has registered the running job.
      if (!controller.signal.aborted && !receivedDone) {
        reconnectTimer = setTimeout(() => {
          if (!controller.signal.aborted) {
            void run();
          }
        }, SSE_RECONNECT_DELAY_MS);
      }
    }

    void run();
    return () => {
      controller.abort();
      if (reconnectTimer !== null) {
        clearTimeout(reconnectTimer);
      }
    };
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
      setLatestProgress(null);
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

  // Derive collapsible step groups from the flat SSE log stream.
  const pipelineSteps = useMemo(
    () => groupOptimizationLines(logLines, doneStatus, latestProgress),
    [logLines, doneStatus, latestProgress],
  );

  const stageStatuses = useMemo<Record<string, StageRailStatus>>(() => {
    const initial: Record<string, StageRailStatus> = Object.fromEntries(
      OPTIMIZATION_STAGES.map((s) => [s.id, "pending" as StageRailStatus]),
    );

    if (doneStatus === "optimization-complete" && logLines.length === 0) {
      for (const s of OPTIMIZATION_STAGES) initial[s.id] = "complete";
      return initial;
    }

    const orderedIds = OPTIMIZATION_STAGES.map((s) => s.id);
    const stageIndexById = new Map<string, number>(orderedIds.map((id, idx) => [id, idx]));
    let maxSeenIdx = -1;
    let failedAtIdx: number | null = null;

    for (const line of logLines) {
      const msg = line.message.trim();
      const lower = msg.toLowerCase();

      let stageId: string | null = null;
      if (
        lower.includes("optimization started")
        || lower.includes("initialize tokenizer")
        || lower.includes("initialize model")
        || lower.includes("tokenizer ready")
        || lower.includes("model ready")
      ) {
        stageId = "model-initialization";
      } else if (lower.includes("optimization segment")) {
        stageId = "segmentation-plan";
      } else if (
        lower.startsWith("prepare generation request")
        || lower.startsWith("generating output for segment")
        || lower.startsWith("generate output:")
        || lower.startsWith("generation complete for segment")
        || lower.startsWith("generation finished")
      ) {
        stageId = "segment-generation";
      } else if (
        lower.startsWith("finalize output")
        || lower.startsWith("validate output")
        || lower.startsWith("validation finished")
        || lower.startsWith("output validated")
        || lower.includes("fallback output")
      ) {
        stageId = "output-validation";
      } else if (
        lower.startsWith("write artifacts")
        || lower.startsWith("artifacts written")
        || lower.startsWith("artifacts ready")
      ) {
        stageId = "artifact-export";
      } else if (lower.startsWith("job completed")) {
        stageId = "completion";
      }

      if (stageId) {
        const idx = stageIndexById.get(stageId) ?? -1;
        if (idx > maxSeenIdx) maxSeenIdx = idx;
        if (line.level === "ERROR" && failedAtIdx === null) {
          failedAtIdx = idx >= 0 ? idx : Math.max(maxSeenIdx, 0);
        }
      } else if (line.level === "ERROR" && failedAtIdx === null) {
        failedAtIdx = Math.max(maxSeenIdx, 0);
      }
    }

    if (doneStatus === "optimization-complete") {
      maxSeenIdx = Math.max(maxSeenIdx, orderedIds.length - 1);
    }

    for (let i = 0; i <= maxSeenIdx; i += 1) {
      initial[orderedIds[i]] = "complete";
    }

    if (doneStatus === null && maxSeenIdx >= 0) {
      initial[orderedIds[maxSeenIdx]] = "active";
    }

    if (doneStatus === "failed") {
      const failIdx = failedAtIdx ?? Math.max(maxSeenIdx, 0);
      for (let i = 0; i < failIdx; i += 1) {
        initial[orderedIds[i]] = "complete";
      }
      if (failIdx >= 0) {
        initial[orderedIds[failIdx]] = "failed";
      }
    }

    if (doneStatus === "optimization-complete") {
      initial["completion"] = "complete";
    }

    return initial;
  }, [logLines, doneStatus]);

  const activeStageId = useMemo(() => {
    return OPTIMIZATION_STAGES.find((s) => stageStatuses[s.id] === "active")?.id ?? null;
  }, [stageStatuses]);

  const stageProgress = useMemo(() => {
    if (latestProgress && doneStatus === null) {
      return Math.max(0, Math.min(100, latestProgress.overall_progress_percent));
    }
    const total = OPTIMIZATION_STAGES.length;
    const completeCount = OPTIMIZATION_STAGES.filter((s) => stageStatuses[s.id] === "complete").length;
    const failedCount = OPTIMIZATION_STAGES.filter((s) => stageStatuses[s.id] === "failed").length;
    const activeCount = OPTIMIZATION_STAGES.filter((s) => stageStatuses[s.id] === "active").length;
    const blended = completeCount + failedCount + (activeCount > 0 ? 0.5 : 0);
    return Math.round((blended / total) * 100);
  }, [stageStatuses, latestProgress, doneStatus]);

  const stageStatusMessage = useMemo(() => {
    if (doneStatus === "optimization-complete") return "Optimization complete";
    if (doneStatus === "failed") return "Optimization failed";
    const active = OPTIMIZATION_STAGES.find((s) => s.id === activeStageId);
    return active ? `Running: ${active.label}` : "Preparing optimization...";
  }, [activeStageId, doneStatus]);

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
                  <span className="text-xs text-muted-foreground">RAG Optimization</span>
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

        {/* Stages + step-grouped log viewer */}
        <div className="flex-1 min-h-0 mx-6 my-4">
          <div className="flex flex-col lg:flex-row gap-6 items-stretch h-full min-h-0">

            {/* Left — Optimization stages */}
            <div className="lg:w-[420px] shrink-0">
              <Card className="overflow-hidden border-border flex flex-col h-full">
                <div className="px-5 py-4 border-b border-border bg-muted/40 flex items-center justify-between shrink-0">
                  <div>
                    <h2 className="font-semibold text-sm">Optimization Pipeline</h2>
                    <p className="text-xs text-muted-foreground mt-0.5">{stageStatusMessage}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold tabular-nums text-sm">{stageProgress}%</span>
                    {doneStatus === "optimization-complete" ? (
                      <Badge variant="outline" className="gap-1 text-green-400 bg-green-400/10 border-green-400/30">
                        <CheckCircle2 className="h-3 w-3" />Complete
                      </Badge>
                    ) : doneStatus === "failed" ? (
                      <Badge variant="outline" className="gap-1 text-red-400 bg-red-400/10 border-red-400/30">
                        <XCircle className="h-3 w-3" />Failed
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="gap-1 text-amber-400 bg-amber-400/10 border-amber-400/30">
                        <Loader2 className="h-3 w-3 animate-spin" />Running
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="px-5 py-3 border-b border-border shrink-0">
                  <Progress value={stageProgress} className="h-1.5" />
                </div>

                <div className="divide-y divide-border flex-1">
                  {OPTIMIZATION_STAGES.map((stage) => {
                    const status = stageStatuses[stage.id] ?? "pending";
                    return (
                      <div
                        key={stage.id}
                        className={`flex items-center gap-4 px-6 py-4 transition-all ${
                          status === "active"
                            ? "bg-primary/8"
                            : status === "complete"
                              ? "bg-green-400/5"
                              : status === "failed"
                                ? "bg-red-400/5"
                                : ""
                        }`}
                      >
                        <div className="w-8 h-8 flex items-center justify-center shrink-0">
                          {status === "complete" ? (
                            <CheckCircle2 className="h-5 w-5 text-green-400" />
                          ) : status === "failed" ? (
                            <XCircle className="h-5 w-5 text-red-400" />
                          ) : status === "active" ? (
                            <Loader2 className="h-5 w-5 text-primary animate-spin" />
                          ) : (
                            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border text-xs text-muted-foreground font-medium">
                              •
                            </span>
                          )}
                        </div>
                        <div className="flex-1">
                          <p className="font-semibold text-sm">{stage.label}</p>
                          <p className="text-xs text-muted-foreground">{stage.description}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </Card>
            </div>

            {/* Right — Optimization log */}
            <div className="flex-1 min-w-0 flex flex-col min-h-0">
              <div className="flex items-center gap-3 px-4 py-2 bg-[#161b22] border border-[#21262d] rounded-t-lg border-b-0 shrink-0">
                <span className="text-xs text-[#8b949e] font-medium flex-1">Optimization Log</span>
                {logLines.length > 0 && (
                  <span className="text-[10px] text-[#6e7681] tabular-nums">{logLines.length} lines</span>
                )}
                {userScrolledUp && (
                  <button
                    type="button"
                    className="text-[11px] text-[#e6edf3] bg-[#21262d] hover:bg-[#30363d] px-2 py-0.5 rounded transition-colors"
                    onClick={() => {
                      setUserScrolledUp(false);
                      if (terminalRef.current) {
                        terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
                      }
                    }}
                  >
                    ↓ Jump to latest
                  </button>
                )}
              </div>

              <div
                ref={terminalRef}
                onScroll={handleTerminalScroll}
                className="flex-1 overflow-y-auto min-h-0 border border-[#21262d] border-t-0 rounded-b-lg"
              >
                {logLines.length === 0 ? (
                  isAlreadyComplete ? (
                    <div className="flex flex-col items-center justify-center h-32 gap-2 px-6 text-center bg-[#0d1117]">
                      <CheckCircle2 className="h-5 w-5 text-green-400" aria-hidden="true" />
                      <p className="text-sm text-[#8b949e]">Optimization already completed.</p>
                      <p className="text-xs text-[#6e7681]">
                        Live log output is only available for active runs. Proceed to review the optimized output.
                      </p>
                    </div>
                  ) : statusError !== null && doneStatus === null ? (
                    <div className="bg-[#0d1117] px-4 py-4">
                      <p className="text-xs text-[#ffa198] italic">Unable to load status: {statusError}</p>
                    </div>
                  ) : (
                    <PipelineJobLog steps={[]} isActive={doneStatus === null} className="rounded-none" />
                  )
                ) : (
                  <PipelineJobLog
                    steps={pipelineSteps}
                    isActive={doneStatus === null}
                    className="rounded-none"
                  />
                )}
              </div>
            </div>
          </div>
        </div>

      </div>
    </AppLayout>
  );
}
