"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Upload, FileText, CheckCircle2, Loader2, ArrowLeft, AlertCircle, XCircle, Terminal } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadDocument, streamIngestionEvents, type PipelineStatus, type IngestionSSEEvent } from "@/lib/api";

// Backend pipeline stages mapped to UI display
type Stage = {
  id: string;
  label: string;
  description: string;
};

const PIPELINE_STAGES: Stage[] = [
  { id: "uploading", label: "File Upload", description: "Transferring document to server" },
  { id: "extracting", label: "Document Extraction", description: "Extracting text, tables, and figures with Docling" },
  { id: "vlm-validating", label: "VLM Validation", description: "AI validation of content fidelity" },
  { id: "validation-complete", label: "Validation Complete", description: "Ready for fidelity review" },
];

// Map backend SSE stage strings → UI PIPELINE_STAGES id.
// Backend emits: queued, upload, extraction, validation, completed, startup, monitoring.
// Also maps sub-stages emitted by the pipeline CLI structured events.
const BACKEND_TO_UI_STAGE: Record<string, string> = {
  queued: "uploading",
  upload: "uploading",
  extraction: "extracting",
  docling: "extracting",
  manifest: "extracting",
  validation: "vlm-validating",
  tables: "vlm-validating",
  review: "vlm-validating",
  version: "vlm-validating",
  qa: "vlm-validating",
  audit: "vlm-validating",
  completed: "validation-complete",
  // Fallback: startup / monitoring errors map to the first stage.
  startup: "uploading",
  monitoring: "vlm-validating",
};

/** Resolve a backend stage string to a UI PIPELINE_STAGES id, falling back to the raw value. */
function toUIStage(backendStage: string): string {
  return BACKEND_TO_UI_STAGE[backendStage] ?? backendStage;
}

// ---------------------------------------------------------------------------
// Terminal log types + helpers
// ---------------------------------------------------------------------------

type LogCategory = "init" | "step-start" | "progress" | "stage-done" | "done" | "error";

interface PipelineLogLine {
  timestamp: string;
  level: "INFO" | "ERROR";
  category: LogCategory;
  stage: string;
  message: string;
}

const STAGE_LABEL: Record<string, string> = {
  queued: "queue",
  upload: "upload",
  extraction: "extract",
  validation: "validate",
  completed: "pipeline",
  startup: "system",
  monitoring: "monitor",
};

function toLogLine(event: IngestionSSEEvent): PipelineLogLine {
  const stage = STAGE_LABEL[event.stage] ?? event.stage;
  const ts = event.timestamp;
  switch (event.type) {
    case "job.accepted":
      return { timestamp: ts, level: "INFO", category: "init", stage, message: event.message || "Pipeline job accepted" };
    case "progress": {
      // Stage header lines start with "Stage N:" — show as visual step separator.
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

function IngestionLogEntry({ line }: { line: PipelineLogLine }) {
  const timeStr = toHHMMSS(line.timestamp);

  // Stage header row — rendered as a visual section separator.
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

type StageStatus = "pending" | "active" | "complete" | "error";

export default function UploadPage() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [version, setVersion] = useState("");
  const [system, setSystem] = useState("");
  const [docType, setDocType] = useState("");

  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus | null>(null);
  const [progress, setProgress] = useState(0);
  const [currentStage, setCurrentStage] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string>("");
  const [stageStatuses, setStageStatuses] = useState<Record<string, StageStatus>>({});
  const [done, setDone] = useState(false);
  const [logLines, setLogLines] = useState<PipelineLogLine[]>([]);
  const [logScrolledUp, setLogScrolledUp] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const terminalRef = useRef<HTMLDivElement>(null);

  // Abort any in-flight SSE stream on unmount.
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  // Auto-scroll terminal to bottom when new lines arrive.
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
    
    // Auto-populate title from filename
    if (f && !title) {
      setTitle(f.name.replace(/\.[^.]+$/, ""));
    }

    // Validate file type
    if (f && !f.name.endsWith('.pdf')) {
      setUploadError("Only PDF files are supported");
      setSelectedFile(null);
      return;
    }

    // Validate file size (100MB max)
    if (f && f.size > 100 * 1024 * 1024) {
      setUploadError("File size exceeds maximum of 100MB");
      setSelectedFile(null);
      return;
    }
  }

  function handleIngestionSSEEvent(event: IngestionSSEEvent) {
    setLogLines((prev) => [...prev, toLogLine(event)]);
    const uiStage = toUIStage(event.stage);

    switch (event.type) {
      case 'job.accepted':
        setStatusMessage(event.message);
        setProgress(event.progress);
        setCurrentStage(uiStage);
        setStageStatuses((prev) => ({ ...prev, [uiStage]: 'active' }));
        break;

      case 'progress':
        setCurrentStage(uiStage);
        setProgress(event.progress);
        setStatusMessage(event.message);
        setStageStatuses((prev) => {
          const updated = { ...prev };
          updated[uiStage] = 'active';
          // Mark all UI stages that appear before the current one as complete.
          const activeIdx = PIPELINE_STAGES.findIndex((s) => s.id === uiStage);
          PIPELINE_STAGES.forEach((stage, idx) => {
            if (idx < activeIdx && updated[stage.id] !== 'complete') {
              updated[stage.id] = 'complete';
            }
          });
          return updated;
        });
        break;

      case 'stage.complete':
        setStageStatuses((prev) => ({
          ...prev,
          [uiStage]: 'complete',
        }));
        setProgress(event.progress);
        setStatusMessage(event.message);
        break;

      case 'complete':
        setProgress(100);
        setStatusMessage(event.message);
        setDone(true);
        setUploading(false);
        // Mark all stages complete.
        setStageStatuses(() => {
          const allComplete: Record<string, StageStatus> = {};
          PIPELINE_STAGES.forEach((stage) => {
            allComplete[stage.id] = 'complete';
          });
          return allComplete;
        });
        break;

      case 'error':
        setUploadError(`Pipeline error: ${event.error}`);
        setPipelineStatus('failed');
        setUploading(false);
        setDone(false);
        if (uiStage) {
          setStageStatuses((prev) => ({
            ...prev,
            [uiStage]: 'error',
          }));
        }
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
    setDone(false);

    // Initialize stage statuses
    const init: Record<string, StageStatus> = {};
    PIPELINE_STAGES.forEach((s) => (init[s.id] = "pending"));
    setStageStatuses(init);

    try {
      // Upload document via real API
      const response = await uploadDocument({
        file: selectedFile,
        title: title.trim(),
        version: version.trim() || undefined,
        system: system || undefined,
        documentType: docType || undefined,
      });

      console.log('Upload successful:', response);

      setDocumentId(response.document_id);
      setPipelineStatus(response.status);
      setStatusMessage(response.message);

      // Persist form metadata so document detail pages can show human-readable
      // info without PostgREST (core stack has FastAPI only).
      if (typeof window !== 'undefined') {
        localStorage.setItem(
          `plantiq-upload-preview-${response.document_id}`,
          JSON.stringify({
            title: title.trim(),
            version: version.trim() || '1.0',
            system: system || '—',
            docType: docType || 'PDF',
          })
        );
      }

      // Stream ingestion progress via SSE.
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      try {
        for await (const event of streamIngestionEvents(
          response.document_id,
          abortController.signal
        )) {
          if (abortController.signal.aborted) break;
          handleIngestionSSEEvent(event);
        }
      } catch (streamErr) {
        if (!abortController.signal.aborted) {
          console.error('Ingestion SSE stream error:', streamErr);
          setUploadError(streamErr instanceof Error ? streamErr.message : 'SSE stream error');
          setUploading(false);
        }
      } finally {
        abortControllerRef.current = null;
        // Guard: if the stream closed without emitting a terminal event and the
        // UI is still in the loading state, resolve it gracefully so the page
        // does not hang forever.
        setUploading((prev) => {
          if (prev && !abortController.signal.aborted) {
            // Stream ended with no explicit complete/error — treat as complete
            // because the backend closes the SSE connection after the last event.
            setDone(true);
            setStageStatuses(() => {
              const allComplete: Record<string, StageStatus> = {};
              PIPELINE_STAGES.forEach((s) => { allComplete[s.id] = 'complete'; });
              return allComplete;
            });
            setProgress(100);
            setStatusMessage('Processing complete.');
            return false; // clear uploading
          }
          return prev;
        });
      }

    } catch (err) {
      console.error('Upload failed:', err);
      setUploadError(err instanceof Error ? err.message : 'Upload failed');
      setUploading(false);
    }
  }

  function handleReset() {
    setSelectedFile(null);
    setTitle("");
    setVersion("");
    setSystem("");
    setDocType("");
    setUploading(false);
    setUploadError(null);
    setDocumentId(null);
    setPipelineStatus(null);
    setProgress(0);
    setCurrentStage(null);
    setStatusMessage("");
    setStageStatuses({});
    setDone(false);
    setLogLines([]);
    setLogScrolledUp(false);

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }

  const canSubmit = selectedFile && title.trim() && system && docType && !uploading;
  const completedCount = Object.values(stageStatuses).filter((s) => s === "complete").length;
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
            <p className="text-sm text-muted-foreground">
              Add a new technical document to the ingestion pipeline
            </p>
          </div>
        </div>

        {/* Main content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto">

            {/* ── Pre-processing: upload form centred, full width ── */}
            {!uploading && !done && !uploadError && (
              <div className="max-w-2xl mx-auto space-y-4">
              <Card className="overflow-hidden border-border">
                {/* Step 1 — File */}
                <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center gap-3">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold shrink-0">1</span>
                  <span className="font-semibold text-sm">Select File</span>
                </div>
                <div className="p-6">
                  <div
                    className="flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border p-8 cursor-pointer hover:border-primary/60 hover:bg-primary/5 transition-colors"
                    onClick={() => fileRef.current?.click()}
                  >
                    {selectedFile ? (
                      <>
                        <FileText className="h-10 w-10 text-primary" />
                        <p className="font-medium">{selectedFile.name}</p>
                        <p className="text-xs text-muted-foreground">
                          {(selectedFile.size / 1024 / 1024).toFixed(2)} MB · Click to change
                        </p>
                      </>
                    ) : (
                      <>
                        <Upload className="h-10 w-10 text-muted-foreground/40" />
                        <p className="text-sm text-muted-foreground">
                          Click or drag-and-drop a PDF document
                        </p>
                      </>
                    )}
                  </div>
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".pdf,.docx,.md,.txt"
                    className="hidden"
                    onChange={handleFileChange}
                  />
                </div>

                {/* Step 2 — Metadata */}
                <div className="border-t border-border">
                  <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center gap-3">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold shrink-0">2</span>
                    <span className="font-semibold text-sm">Document Metadata</span>
                  </div>
                  <div className="p-6 space-y-4">
                  <div>
                    <Label htmlFor="title" className="mb-1.5 block">Document Title</Label>
                    <Input
                      id="title"
                      value={title}
                      onChange={(e) => setTitle(e.target.value)}
                      placeholder="e.g., Gas Turbine Maintenance Guide"
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <Label htmlFor="version" className="mb-1.5 block">Version</Label>
                      <Input
                        id="version"
                        value={version}
                        onChange={(e) => setVersion(e.target.value)}
                        placeholder="e.g., Rev 3.0"
                      />
                    </div>
                    <div>
                      <Label className="mb-1.5 block">System / Area</Label>
                      <Select onValueChange={setSystem}>
                        <SelectTrigger>
                          <SelectValue placeholder="Select system" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="LNG Processing">LNG Processing</SelectItem>
                          <SelectItem value="Liquefaction Train">Liquefaction Train</SelectItem>
                          <SelectItem value="Safety Systems">Safety Systems</SelectItem>
                          <SelectItem value="Compression System">Compression System</SelectItem>
                          <SelectItem value="Heat Transfer">Heat Transfer</SelectItem>
                          <SelectItem value="Instrumentation">Instrumentation</SelectItem>
                          <SelectItem value="Electrical">Electrical</SelectItem>
                          <SelectItem value="General">General</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <div>
                    <Label className="mb-1.5 block">Document Type</Label>
                    <Select onValueChange={setDocType}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select document type" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="Operating Manual">Operating Manual</SelectItem>
                        <SelectItem value="Maintenance Manual">Maintenance Manual</SelectItem>
                        <SelectItem value="Troubleshooting Guide">Troubleshooting Guide</SelectItem>
                        <SelectItem value="Technical Manual">Technical Manual</SelectItem>
                        <SelectItem value="Technical Standard">Technical Standard</SelectItem>
                        <SelectItem value="P&ID Diagram">P&ID Diagram</SelectItem>
                        <SelectItem value="Procedure">Procedure</SelectItem>
                        <SelectItem value="Other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  </div>
                </div>

                {/* Step 3 — Submit */}
                <div className="border-t border-border">
                  <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center gap-3">
                    <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold shrink-0 ${
                      canSubmit ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground border border-border"
                    }`}>3</span>
                    <span className="font-semibold text-sm">Start Pipeline</span>
                  </div>
                  <div className="p-6">
                    <div className="rounded-lg border border-border bg-muted/20 p-4 mb-4">
                      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Pipeline Stages</p>
                      <div className="space-y-2">
                        {PIPELINE_STAGES.map((stage, idx) => (
                          <div key={stage.id} className="flex items-center gap-3 text-sm">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full border border-border text-xs text-muted-foreground shrink-0 font-medium">
                              {idx + 1}
                            </span>
                            <span className="font-medium">{stage.label}</span>
                            <span className="text-muted-foreground text-xs">— {stage.description}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <Button disabled={!canSubmit} className="w-full gap-2 font-semibold h-11" onClick={handleUpload}>
                      <Upload className="h-4 w-4" />
                      Start Ingestion Pipeline
                    </Button>
                    {!canSubmit && (
                      <p className="text-xs text-muted-foreground text-center mt-2">
                        Complete steps 1 and 2 to continue
                      </p>
                    )}
                  </div>
                </div>
              </Card>
              </div>
            )}

            {/* ── Processing/done: pipeline stages + log terminal side by side ── */}
            {(uploading || done || logLines.length > 0) && (
              <div className="flex flex-col lg:flex-row gap-6 items-stretch">

                {/* Left — Ingestion Pipeline stages (fixed width) */}
                <div className="lg:w-[420px] shrink-0">
                <Card className="overflow-hidden border-border flex flex-col h-full">
                <div className="px-5 py-4 border-b border-border bg-muted/40 flex items-center justify-between shrink-0">
                  <div>
                    <h2 className="font-semibold text-sm">Ingestion Pipeline</h2>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {statusMessage || (currentStage ? `Stage: ${currentStage}` : 'Preparing...')}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold tabular-nums text-sm">{progress}%</span>
                    {done ? (
                      <Badge variant="outline" className="gap-1 text-green-400 bg-green-400/10 border-green-400/30">
                        <CheckCircle2 className="h-3 w-3" />
                        Complete
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="gap-1 text-amber-400 bg-amber-400/10 border-amber-400/30">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Running
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
                      <div
                        key={stage.id}
                        className={`flex items-center gap-4 px-6 py-4 transition-all ${
                          status === "active"
                            ? "bg-primary/8"
                            : status === "complete"
                            ? "bg-green-400/5"
                            : ""
                        }`}
                      >
                        <div className="w-8 h-8 flex items-center justify-center shrink-0">
                          {status === "complete" ? (
                            <CheckCircle2 className="h-5 w-5 text-green-400" />
                          ) : status === "active" ? (
                            <Loader2 className="h-5 w-5 text-primary animate-spin" />
                          ) : (
                            <span className="flex h-6 w-6 items-center justify-center rounded-full border border-border text-xs text-muted-foreground font-medium">
                              {idx + 1}
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
                </div>{/* end left col */}

                {/* Right — Live log terminal */}
                <div className="flex-1 min-w-0 flex flex-col">
                  {/* Chrome bar */}
                  <div className="flex items-center gap-2 px-4 py-2 rounded-t-lg bg-zinc-800 border border-zinc-700 border-b-0 shrink-0">
                    <div className="flex gap-1.5" aria-hidden="true">
                      <span className="h-3 w-3 rounded-full bg-red-500/50" />
                      <span className="h-3 w-3 rounded-full bg-yellow-500/50" />
                      <span className="h-3 w-3 rounded-full bg-green-500/50" />
                    </div>
                    <Terminal className="h-3.5 w-3.5 text-zinc-500 ml-1" aria-hidden="true" />
                    <span className="text-xs text-zinc-500 font-mono flex-1 ml-1">
                      ingestion pipeline &middot; stages 1&ndash;4
                    </span>
                    <span className="text-[10px] text-zinc-600 font-mono tabular-nums">
                      {logLines.length} lines
                    </span>
                    {logScrolledUp && (
                      <button
                        className="ml-2 text-[11px] text-zinc-300 bg-zinc-700 hover:bg-zinc-600 px-2 py-0.5 rounded transition-colors"
                        onClick={() => {
                          setLogScrolledUp(false);
                          if (terminalRef.current) {
                            terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
                          }
                        }}
                      >
                        &#8595; Jump to bottom
                      </button>
                    )}
                  </div>

                  {/* Log output — flex-1 so height matches left pipeline card */}
                  <div
                    ref={terminalRef}
                    onScroll={handleTerminalScroll}
                    className="flex-1 overflow-y-auto py-3 font-mono bg-zinc-950 rounded-b-lg border border-zinc-700"
                    style={{ minHeight: "260px", maxHeight: "560px" }}
                    role="log"
                    aria-live="polite"
                    aria-label="Pipeline log output"
                  >
                    {logLines.length === 0 && (
                      <p className="pl-4 text-xs text-zinc-600 italic">Waiting for runner output...</p>
                    )}
                    {logLines.map((line, idx) => (
                      <IngestionLogEntry key={idx} line={line} />
                    ))}

                    {/* Blinking cursor while running */}
                    {uploading && (
                      <div className="flex gap-2 pl-3 mt-1">
                        <span className="text-zinc-700 text-[10px] font-mono w-[60px] select-none shrink-0" />
                        <span className="text-zinc-500 font-mono text-xs animate-pulse">&#9608;</span>
                      </div>
                    )}
                  </div>
                </div>{/* end right col */}

              </div>
            )}

            {/* Error / Success cards — full width below side-by-side */}
            {/* Error Display */}
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
                    <Button variant="outline" onClick={handleReset} className="flex-1">
                      Try Again
                    </Button>
                    <Button variant="outline" onClick={() => router.push("/admin/documents")} className="flex-1">
                      Return to Dashboard
                    </Button>
                  </div>
                </div>
              </Card>
            )}

            {/* Success Display */}
            {done && !uploadError && documentId && (
              <Card className="overflow-hidden border-border mt-4">
                <div className="px-6 py-5 bg-green-400/5 border-b border-green-400/10">
                  <div className="flex items-center gap-3 mb-1">
                    <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
                    <p className="font-semibold text-green-400">Processing complete</p>
                  </div>
                  <p className="text-xs text-muted-foreground ml-8">
                    Validation finished · ready for fidelity review
                  </p>
                </div>
                <div className="px-6 py-5">
                  <div className="mb-4 rounded-lg border border-border bg-muted/50 px-4 py-3 flex items-start gap-3">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-muted-foreground mb-0.5">Document ID</p>
                      <p className="text-sm font-mono font-bold tracking-wider text-foreground select-all truncate">{documentId}</p>
                    </div>
                  </div>
                  <div className="flex gap-3">
                    <Button
                      className="flex-1 gap-2 font-semibold"
                      onClick={() => router.push(`/admin/documents/${documentId}/review`)}
                    >
                      <FileText className="h-4 w-4" />
                      Start Fidelity Review
                    </Button>
                    <Button
                      variant="outline"
                      className="flex-1"
                      onClick={handleReset}
                    >
                      Upload Another
                    </Button>
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
