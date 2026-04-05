"use client";

/**
 * Document Upload & Ingestion Monitoring Interface
 *
 * Accepts PDF uploads with metadata, streams ingestion progress via SSE,
 * displays pipeline stage progression with terminal logs, and supports
 * artifact browsing upon completion.
 */

import { useState, useRef, useEffect, useCallback } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, Loader2, ArrowLeft, AlertCircle, XCircle, Terminal, FileText, Upload } from "lucide-react";
import { useRouter } from "next/navigation";
import { getPipelineStatus, uploadDocument, streamIngestionEvents, type PipelineStatus, type IngestionSSEEvent } from "@/lib/api";
import {
  PIPELINE_STAGES,
  MAX_UPLOAD_BYTES,
  ALLOWED_UPLOAD_EXTENSION,
  toUIStage,
} from "./_constants";
import { IngestionLogEntry, toLogLine, type PipelineLogLine } from "./_components/IngestionLogEntry";
import { UploadForm } from "./_components/UploadForm";

// ---------------------------------------------------------------------------
// Local types
// ---------------------------------------------------------------------------

type StageStatus = "pending" | "active" | "complete" | "error";

function isReviewReadyStatus(status: PipelineStatus): boolean {
  return [
    "validation-complete",
    "in-review",
    "review-complete",
    "approved-for-optimization",
    "optimizing",
    "optimization-complete",
    "qa-review",
    "qa-passed",
    "final-approved",
    "approved",
    "rejected",
  ].includes(status);
}

// ---------------------------------------------------------------------------
// Upload Page
// ---------------------------------------------------------------------------

export default function UploadPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  // Form state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("");
  const [system, setSystem] = useState("");
  const [docType, setDocType] = useState("");

  // Transfer + pipeline state
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadWarning, setUploadWarning] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [stageStatuses, setStageStatuses] = useState<Record<string, StageStatus>>({});
  const [done, setDone] = useState(false);
  const [logLines, setLogLines] = useState<PipelineLogLine[]>([]);
  const [logScrolledUp, setLogScrolledUp] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const sawTerminalEventRef = useRef(false);
  const pollingCancelledRef = useRef(false);
  const terminalRef = useRef<HTMLDivElement>(null);

  function isIngestionProcessingStatus(status: PipelineStatus): boolean {
    return status === "uploading" || status === "extracting" || status === "vlm-validating";
  }

  async function wait(ms: number): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function monitorPipelineUntilTerminal(documentId: string): Promise<void> {
    setUploadWarning("Live progress stream disconnected. Monitoring pipeline status in the background...");

    for (let attempt = 0; attempt < 240; attempt += 1) {
      if (pollingCancelledRef.current) return;

      try {
        const latest = await getPipelineStatus(documentId);
        setProgress(latest.progress);
        setStatusMessage(latest.message ?? "Pipeline is still processing...");

        if (latest.status === "failed") {
          setUploadWarning(null);
          setUploadError(latest.error || "Pipeline failed before completion.");
          setDone(false);
          setUploading(false);
          return;
        }

        if (isReviewReadyStatus(latest.status)) {
          setUploadWarning(null);
          setDone(true);
          setUploading(false);
          setStageStatuses(() => {
            const allComplete: Record<string, StageStatus> = {};
            PIPELINE_STAGES.forEach((s) => { allComplete[s.id] = "complete"; });
            return allComplete;
          });
          return;
        }

        if (!isIngestionProcessingStatus(latest.status)) {
          setUploadWarning(null);
          setUploadError(`Unexpected pipeline status: ${latest.status}`);
          setDone(false); setUploading(false);
          return;
        }
      } catch { /* keep polling on transient failures */ }

      await wait(3000);
    }

    setUploading(false);
    setDone(false);
    setUploadWarning(null);
    setUploadError("Lost connection to live progress updates and status polling timed out. Please check the document list and retry if needed.");
  }

  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
      pollingCancelledRef.current = true;
    };
  }, []);

  useEffect(() => {
    if (!logScrolledUp && terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [logLines, logScrolledUp]);

  const handleTerminalScroll = useCallback(() => {
    const el = terminalRef.current;
    if (!el) return;
    setLogScrolledUp(el.scrollHeight - el.scrollTop - el.clientHeight > 48);
  }, []);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setSelectedFile(f);
    setUploadError(null);
    if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
    if (f && !f.name.toLowerCase().endsWith(ALLOWED_UPLOAD_EXTENSION)) {
      setUploadError("Only PDF files are supported");
      setSelectedFile(null);
      return;
    }
    if (f && f.size > MAX_UPLOAD_BYTES) {
      setUploadError("File size exceeds maximum of 100MB");
      setSelectedFile(null);
    }
  }

  function handleIngestionSSEEvent(event: IngestionSSEEvent) {
    setLogLines((prev) => [...prev, toLogLine(event)]);
    const uiStage = toUIStage(event.stage);

    switch (event.type) {
      case "job.accepted":
        setStatusMessage(event.message);
        setProgress(event.progress);
        setStageStatuses((prev) => ({ ...prev, [uiStage]: "active" }));
        break;
      case "progress":
        setProgress(event.progress);
        setStatusMessage(event.message);
        setStageStatuses((prev) => {
          const updated = { ...prev };
          updated[uiStage] = "active";
          const activeIdx = PIPELINE_STAGES.findIndex((s) => s.id === uiStage);
          PIPELINE_STAGES.forEach((stage, idx) => {
            if (idx < activeIdx && updated[stage.id] !== "complete") updated[stage.id] = "complete";
          });
          return updated;
        });
        break;
      case "stage.complete":
        setStageStatuses((prev) => ({ ...prev, [uiStage]: "complete" }));
        setProgress(event.progress);
        setStatusMessage(event.message);
        break;
      case "complete":
        sawTerminalEventRef.current = true;
        setProgress(100);
        setStatusMessage(event.message);
        setDone(true);
        setUploading(false);
        setStageStatuses(() => {
          const allComplete: Record<string, StageStatus> = {};
          PIPELINE_STAGES.forEach((stage) => { allComplete[stage.id] = "complete"; });
          return allComplete;
        });
        break;
      case "error":
        sawTerminalEventRef.current = true;
        setUploadError(`Pipeline error: ${event.error}`);
        setUploading(false); setDone(false);
        if (uiStage) setStageStatuses((prev) => ({ ...prev, [uiStage]: "error" }));
        break;
    }
  }

  async function handleUpload() {
    if (!selectedFile || !title.trim()) {
      setUploadError("File and title are required");
      return;
    }
    setUploading(true);
    setUploadError(null);
    setUploadWarning(null);
    setDone(false);
    pollingCancelledRef.current = false;
    sawTerminalEventRef.current = false;

    const init: Record<string, StageStatus> = {};
    PIPELINE_STAGES.forEach((s) => (init[s.id] = "pending"));
    setStageStatuses(init);

    try {
      const response = await uploadDocument({
        file: selectedFile,
        title: title.trim(),
        version: version.trim() || undefined,
        system: system || undefined,
        documentType: docType || undefined,
      });

      setDocumentId(response.document_id);
      setStatusMessage(response.message);

      if (typeof window !== "undefined") {
        localStorage.setItem(
          `plantiq-upload-preview-${response.document_id}`,
          JSON.stringify({ title: title.trim(), version: version.trim() || "1.0", system: system || "—", docType: docType || "PDF" })
        );
      }

      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        for await (const event of streamIngestionEvents(response.document_id, abortController.signal)) {
          if (abortController.signal.aborted) break;
          handleIngestionSSEEvent(event);
        }
      } catch (streamErr) {
        if (!abortController.signal.aborted) {
          setUploadError(streamErr instanceof Error ? streamErr.message : "SSE stream error");
          setUploading(false);
        }
      } finally {
        abortControllerRef.current = null;
        if (!abortController.signal.aborted && !sawTerminalEventRef.current) {
          await monitorPipelineUntilTerminal(response.document_id);
        }
      }
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
      setUploading(false);
    }
  }

  function handleReset() {
    setSelectedFile(null); setTitle(""); setVersion(""); setSystem(""); setDocType("");
    setUploading(false); setUploadError(null); setUploadWarning(null);
    setDocumentId(null); setProgress(0);
    setStatusMessage(""); setStageStatuses({});
    setDone(false); setLogLines([]); setLogScrolledUp(false);
    if (abortControllerRef.current) { abortControllerRef.current.abort(); abortControllerRef.current = null; }
    pollingCancelledRef.current = true;
  }

  const canSubmit = selectedFile && title.trim() && system && docType && !uploading;
  const totalProgress = progress;

  return (
    <AppLayout>
      <div className="flex-1 flex flex-col h-full min-h-0">
        {/* Header */}
        <div className="border-b border-border px-6 py-5 flex items-center gap-4 bg-card/50">
          <Button variant="ghost" size="sm" className="gap-1.5 -ml-2" onClick={() => router.back()}>
            <ArrowLeft className="h-4 w-4" />
            Back
          </Button>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Upload Document</h1>
            <p className="text-sm text-muted-foreground">Add a new technical document to the ingestion pipeline</p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto">

            {/* Upload form (pre-processing) */}
            {!uploading && !done && !uploadError && (
              <UploadForm
                fileRef={fileRef}
                selectedFile={selectedFile}
                title={title}
                version={version}
                system={system}
                docType={docType}
                canSubmit={!!canSubmit}
                onFileChange={handleFileChange}
                onTitleChange={setTitle}
                onVersionChange={setVersion}
                onSystemChange={setSystem}
                onDocTypeChange={setDocType}
                onSubmit={() => void handleUpload()}
              />
            )}

            {/* Processing / done: pipeline stages + terminal log */}
            {(uploading || done || logLines.length > 0) && (
              <div className="flex flex-col lg:flex-row gap-6 items-stretch">

                {/* Left — Pipeline stages */}
                <div className="lg:w-[420px] shrink-0">
                  <Card className="overflow-hidden border-border flex flex-col h-full">
                    <div className="px-5 py-4 border-b border-border bg-muted/40 flex items-center justify-between shrink-0">
                      <div>
                        <h2 className="font-semibold text-sm">Ingestion Pipeline</h2>
                        <p className="text-xs text-muted-foreground mt-0.5">{statusMessage || "Preparing..."}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold tabular-nums text-sm">{progress}%</span>
                        {done ? (
                          <Badge variant="outline" className="gap-1 text-green-400 bg-green-400/10 border-green-400/30">
                            <CheckCircle2 className="h-3 w-3" />Complete
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="gap-1 text-amber-400 bg-amber-400/10 border-amber-400/30">
                            <Loader2 className="h-3 w-3 animate-spin" />Running
                          </Badge>
                        )}
                      </div>
                    </div>
                    <div className="px-5 py-3 border-b border-border shrink-0">
                      <Progress value={totalProgress} className="h-1.5" />
                    </div>
                    <div className="divide-y divide-border flex-1">
                      {PIPELINE_STAGES.map((stage, idx) => {
                        const status = stageStatuses[stage.id] ?? "pending";
                        return (
                          <div key={stage.id} className={`flex items-center gap-4 px-6 py-4 transition-all ${status === "active" ? "bg-primary/8" : status === "complete" ? "bg-green-400/5" : ""}`}>
                            <div className="w-8 h-8 flex items-center justify-center shrink-0">
                              {status === "complete" ? <CheckCircle2 className="h-5 w-5 text-green-400" />
                                : status === "active" ? <Loader2 className="h-5 w-5 text-primary animate-spin" />
                                : <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border text-xs text-muted-foreground font-medium">{idx + 1}</span>}
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

                {/* Right — Terminal log */}
                <div className="flex-1 min-w-0 flex flex-col">
                  <div className="flex items-center gap-2 px-4 py-2 rounded-t-lg bg-zinc-800 border border-zinc-700 border-b-0 shrink-0">
                    <div className="flex gap-1.5" aria-hidden="true">
                      <span className="h-3 w-3 rounded-full bg-red-500/50" />
                      <span className="h-3 w-3 rounded-full bg-yellow-500/50" />
                      <span className="h-3 w-3 rounded-full bg-green-500/50" />
                    </div>
                    <Terminal className="h-3.5 w-3.5 text-zinc-500 ml-1" aria-hidden="true" />
                    <span className="text-xs text-zinc-500 font-mono flex-1 ml-1">ingestion pipeline &middot; stages 1&ndash;4</span>
                    <span className="text-[10px] text-zinc-600 font-mono tabular-nums">{logLines.length} lines</span>
                    {logScrolledUp && (
                      <button className="ml-2 text-[11px] text-zinc-300 bg-zinc-700 hover:bg-zinc-600 px-2 py-0.5 rounded transition-colors" onClick={() => { setLogScrolledUp(false); if (terminalRef.current) terminalRef.current.scrollTop = terminalRef.current.scrollHeight; }}>
                        &#8595; Jump to bottom
                      </button>
                    )}
                  </div>
                  <div
                    ref={terminalRef}
                    onScroll={handleTerminalScroll}
                    className="flex-1 overflow-y-auto py-3 font-mono bg-zinc-950 rounded-b-lg border border-zinc-700"
                    style={{ minHeight: "260px", maxHeight: "560px" }}
                    role="log"
                    aria-live="polite"
                    aria-label="Pipeline log output"
                  >
                    {logLines.length === 0 && <p className="pl-4 text-xs text-zinc-600 italic">Waiting for runner output...</p>}
                    {logLines.map((line, idx) => <IngestionLogEntry key={idx} line={line} />)}
                    {uploading && (
                      <div className="flex gap-2 pl-3 mt-1">
                        <span className="text-zinc-700 text-[10px] font-mono w-[60px] select-none shrink-0" />
                        <span className="text-zinc-500 font-mono text-xs animate-pulse">&#9608;</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Connection-interrupted warning */}
            {uploadWarning && uploading && (
              <Card className="overflow-hidden border-border mt-4">
                <div className="px-6 py-4 bg-amber-400/5 border border-amber-400/20 rounded-md">
                  <div className="flex items-start gap-3">
                    <AlertCircle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-amber-400">Connection interrupted</p>
                      <p className="text-sm text-muted-foreground mt-1">{uploadWarning}</p>
                    </div>
                  </div>
                </div>
              </Card>
            )}

            {/* Error display */}
            {uploadError && !uploading && (
              <Card className="overflow-hidden border-border">
                <div className="px-6 py-5 border-t border-border bg-red-400/5">
                  <div className="flex items-start gap-3 mb-3">
                    <XCircle className="h-5 w-5 text-red-400 shrink-0 mt-0.5" />
                    <div>
                      <p className="font-semibold text-red-400">Pipeline Failed</p>
                      <p className="text-sm text-muted-foreground mt-1">{uploadError}</p>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <Button variant="outline" onClick={handleReset} className="flex-1">Try Again</Button>
                    <Button variant="outline" onClick={() => router.push("/admin/documents")} className="flex-1">Return to Dashboard</Button>
                  </div>
                </div>
              </Card>
            )}

            {/* Success display */}
            {done && !uploadError && documentId && (
              <Card className="overflow-hidden border-border mt-4">
                <div className="px-6 py-5 bg-green-400/5 border-b border-green-400/10">
                  <div className="flex items-center gap-3 mb-1">
                    <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
                    <p className="font-semibold text-green-400">Processing complete</p>
                  </div>
                  <p className="text-xs text-muted-foreground ml-8">Validation finished · ready for fidelity review</p>
                </div>
                <div className="px-6 py-5">
                  <div className="mb-4 rounded-lg border border-border bg-muted/50 px-4 py-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-muted-foreground mb-0.5">Document ID</p>
                      <p className="text-sm font-mono font-bold tracking-wider text-foreground select-all truncate">{documentId}</p>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <Button className="flex-1 gap-2 font-semibold" onClick={() => router.push(`/admin/documents/${documentId}/review`)}>
                      <FileText className="h-4 w-4" />
                      Start Fidelity Review
                    </Button>
                    <Button variant="outline" className="flex-1" onClick={handleReset}>Upload Another</Button>
                  </div>
                </div>
              </Card>
            )}

          </div>
        </div>
      </div>
    </AppLayout>
  );
}
