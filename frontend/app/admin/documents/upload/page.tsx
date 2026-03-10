"use client";

import { useState, useRef, useEffect } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Upload, FileText, CheckCircle2, Loader2, ArrowLeft, AlertCircle, XCircle } from "lucide-react";
import { useRouter } from "next/navigation";
import { uploadDocument, type PipelineStatus } from "@/lib/api";
import { PipelineWebSocketClient, type PipelineMessage } from "@/lib/api/websocket";

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
  { id: "validation-complete", label: "Validation Complete", description: "Ready for engineering review" },
];

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
  
  const wsClientRef = useRef<PipelineWebSocketClient | null>(null);

  // Cleanup WebSocket on unmount
  useEffect(() => {
    return () => {
      if (wsClientRef.current) {
        wsClientRef.current.disconnect();
      }
    };
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

  function handlePipelineMessage(message: PipelineMessage) {
    console.log('Pipeline WebSocket message:', message);

    switch (message.type) {
      case 'progress':
        if ('stage' in message && 'progress' in message) {
          setCurrentStage(message.stage);
          setProgress(message.progress);
          setStatusMessage(message.message);
          
          // Update stage statuses
          setStageStatuses((prev) => {
            const updated = { ...prev };
            // Mark current stage as active
            updated[message.stage] = 'active';
            // Mark previous stages as complete
            PIPELINE_STAGES.forEach((stage) => {
              if (stage.id !== message.stage && !updated[stage.id]) {
                updated[stage.id] = 'pending';
              }
            });
            return updated;
          });
        }
        break;

      case 'stage-complete':
        if ('stage' in message) {
          setStageStatuses((prev) => ({
            ...prev,
            [message.stage]: 'complete',
          }));
          setStatusMessage(`Stage ${message.stage} completed`);
        }
        break;

      case 'error':
        if ('error' in message) {
          setUploadError(`Pipeline error: ${message.error}`);
          setPipelineStatus('failed');
          setUploading(false);
          setDone(false);
          if (wsClientRef.current) {
            wsClientRef.current.disconnect();
          }
        }
        break;

      case 'complete':
        if ('status' in message) {
          setPipelineStatus(message.status as PipelineStatus);
          setProgress(100);
          setStatusMessage('Pipeline processing complete!');
          setDone(true);
          setUploading(false);
          
          // Mark all stages as complete
          const allComplete: Record<string, StageStatus> = {};
          PIPELINE_STAGES.forEach((stage) => {
            allComplete[stage.id] = 'complete';
          });
          setStageStatuses(allComplete);
          
          if (wsClientRef.current) {
            wsClientRef.current.disconnect();
          }
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

      // Connect to WebSocket for real-time status updates
      const wsClient = new PipelineWebSocketClient(
        response.document_id,
        handlePipelineMessage
      );
      wsClient.connect();
      wsClientRef.current = wsClient;

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

    if (wsClientRef.current) {
      wsClientRef.current.disconnect();
      wsClientRef.current = null;
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

        {/* Main content  */}
        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-7xl mx-auto">
            <div className="flex flex-col lg:flex-row gap-6">
              {/* Left: Progress Panel */}
              <div className="lg:w-1/3">
                <Card className="overflow-hidden border-border sticky top-6">
                  <div className="px-6 py-4 border-b border-border bg-muted/40">
                    <h2 className="font-semibold">Pipeline Status</h2>
                  </div>
                  <div className="p-6">
                    <p className="text-sm text-muted-foreground">
                      {uploading 
                        ? "Processing your document..." 
                        : done 
                        ? "Upload complete!" 
                        : "Ready to upload"}
                    </p>
                  </div>
                </Card>
              </div>
              
              {/* Right: Upload Form */}
          <div className="lg:w-2/3 space-y-4">
            {!uploading && !done && !uploadError && (
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
                          Click or drag-and-drop a PDF, DOCX, or Markdown file
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
            )}

            {/* Pipeline progress — shown when uploading */}
            {uploading && (
              <Card className="overflow-hidden border-border">
                <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center justify-between">
                  <div>
                    <h2 className="font-semibold">Ingestion Pipeline</h2>
                    <p className="text-sm text-muted-foreground">
                      {currentStage ? `Current: ${currentStage}` : 'Overall progress'}
                    </p>
                  </div>
                  <div className="text-right">
                    <span className="font-semibold text-lg">{progress}%</span>
                    {done ? (
                      <Badge variant="outline" className="gap-1 text-green-400 bg-green-400/10 border-green-400/30 ml-3">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Complete
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="gap-1 text-amber-400 bg-amber-400/10 border-amber-400/30 ml-3">
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        Processing
                      </Badge>
                    )}
                  </div>
                </div>

                <div className="px-6 py-4 border-b border-border">
                  <div className="flex justify-between text-xs mb-2">
                    <span className="text-muted-foreground">
                      {currentStage ? `Current: ${currentStage}` : 'Overall progress'}
                    </span>
                    <span className="font-semibold">{progress}%</span>
                  </div>
                  <Progress value={totalProgress} className="h-2" />
                  {statusMessage && (
                    <p className="text-xs text-muted-foreground mt-2">{statusMessage}</p>
                  )}
                </div>

                <div className="divide-y divide-border">
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
            )}

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
              <Card className="overflow-hidden border-border">
                <div className="px-6 py-5 border-t border-border bg-green-400/5">
                    <div className="flex items-center gap-3 mb-3">
                      <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
                      <p className="text-sm font-semibold text-green-400">Processing complete</p>
                    </div>
                    <div className="mb-4 rounded-lg border border-border bg-muted/50 p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">Document ID</p>
                      <p className="text-sm font-mono font-bold tracking-wider text-foreground select-all">{documentId}</p>
                      <p className="text-xs text-muted-foreground mt-1">Use this ID to track processing status and audit trail</p>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                      Document validation complete. Ready for engineering review.
                    </p>
                    <div className="flex gap-3">
                      <Button
                        className="flex-1 gap-2 font-semibold"
                        onClick={() => router.push(`/admin/documents/${documentId}/validation`)}
                      >
                        <FileText className="h-4 w-4" />
                        View Document
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
        </div>
      </div>
    </AppLayout>
  );
}
