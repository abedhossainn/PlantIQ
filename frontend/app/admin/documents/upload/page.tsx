"use client";

import { useState, useRef } from "react";
import { AppLayout } from "@/components/shared/AppLayout";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Upload, FileText, CheckCircle2, Loader2, ArrowLeft, ArrowRight } from "lucide-react";
import { useRouter } from "next/navigation";

type Stage = {
  id: string;
  label: string;
  description: string;
};

const PIPELINE_STAGES: Stage[] = [
  { id: "upload", label: "File Upload", description: "Transferring document to server" },
  { id: "docling", label: "Docling Conversion", description: "Extracting text, tables, and figures" },
  { id: "vlm", label: "VLM Validation", description: "AI validation of content fidelity" },
  { id: "chunking", label: "Chunking & Embedding", description: "Splitting sections and generating embeddings" },
  { id: "index", label: "RAG Indexing", description: "Indexing into vector database" },
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
  const [stageStatuses, setStageStatuses] = useState<Record<string, StageStatus>>({});
  const [currentStageIdx, setCurrentStageIdx] = useState(-1);
  const [done, setDone] = useState(false);
  const [jobId, setJobId] = useState("");

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    setSelectedFile(f);
    if (f && !title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  }

  async function simulatePipeline() {
    setUploading(true);
    const init: Record<string, StageStatus> = {};
    PIPELINE_STAGES.forEach((s) => (init[s.id] = "pending"));
    setStageStatuses(init);

    for (let i = 0; i < PIPELINE_STAGES.length; i++) {
      setCurrentStageIdx(i);
      setStageStatuses((prev) => ({ ...prev, [PIPELINE_STAGES[i].id]: "active" }));
      await new Promise((r) => setTimeout(r, 1800 + Math.random() * 800));
      setStageStatuses((prev) => ({ ...prev, [PIPELINE_STAGES[i].id]: "complete" }));
    }

    const ts = new Date().toISOString().replace(/[-:T.]/g, "").slice(0, 12);
    const rand = Math.random().toString(36).slice(2, 6).toUpperCase();
    const generatedJobId = `JOB-${ts}-${rand}`;
    setJobId(generatedJobId);

    // Persist upload metadata so the review page can display the real doc title
    if (typeof window !== "undefined") {
      localStorage.setItem(
        "plantiq-upload-preview",
        JSON.stringify({
          title: title.trim(),
          version: version || "1.0",
          system,
          docType,
          uploadedAt: new Date().toISOString(),
          jobId: generatedJobId,
        })
      );
    }

    setDone(true);
  }

  const canSubmit = selectedFile && title.trim() && system && docType;
  const completedCount = Object.values(stageStatuses).filter((s) => s === "complete").length;
  const totalProgress = uploading ? (completedCount / PIPELINE_STAGES.length) * 100 : 0;

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

        <div className="flex-1 overflow-y-auto min-h-0">
          <div className="p-6 max-w-2xl mx-auto">
            {/* Upload form — hidden when processing starts */}
            {!uploading && (
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
                    <Button disabled={!canSubmit} className="w-full gap-2 font-semibold h-11" onClick={simulatePipeline}>
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
                    <p className="text-xs text-muted-foreground mt-0.5">{selectedFile?.name}</p>
                  </div>
                  {done ? (
                    <Badge variant="outline" className="gap-1 text-green-400 bg-green-400/10 border-green-400/30">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Complete
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="gap-1 text-amber-400 bg-amber-400/10 border-amber-400/30">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Processing
                    </Badge>
                  )}
                </div>

                <div className="px-6 py-4 border-b border-border">
                  <div className="flex justify-between text-xs mb-2">
                    <span className="text-muted-foreground">Overall progress</span>
                    <span className="font-semibold">{completedCount} / {PIPELINE_STAGES.length} stages</span>
                  </div>
                  <Progress value={totalProgress} className="h-2" />
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
                          <p className={`font-semibold text-sm ${
                            status === "pending" ? "text-muted-foreground" :
                            status === "active" ? "text-primary" :
                            "text-green-400"
                          }`}>
                            {stage.label}
                          </p>
                          <p className="text-xs text-muted-foreground">{stage.description}</p>
                        </div>
                        <div className="shrink-0 text-xs">
                          {status === "complete" && <span className="text-green-400 font-medium">Done</span>}
                          {status === "active" && <span className="text-primary font-medium">Running…</span>}
                          {status === "pending" && <span className="text-muted-foreground">Pending</span>}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {done && (
                  <div className="px-6 py-5 border-t border-border bg-green-400/5">
                    <div className="flex items-center gap-3 mb-3">
                      <CheckCircle2 className="h-5 w-5 text-green-400 shrink-0" />
                      <p className="text-sm font-semibold text-green-400">Processing complete</p>
                    </div>
                    <div className="mb-4 rounded-lg border border-border bg-muted/50 p-3">
                      <p className="text-xs text-muted-foreground mb-0.5">Job / Queue ID</p>
                      <p className="text-sm font-mono font-bold tracking-wider text-foreground select-all">{jobId}</p>
                      <p className="text-xs text-muted-foreground mt-1">Use this ID to track processing status and audit trail</p>
                    </div>
                    <p className="text-sm text-muted-foreground mb-4">
                      Document has been processed and is ready for engineering review.
                    </p>
                    <Button
                      className="w-full gap-2 font-semibold mb-2"
                      onClick={() => router.push("/admin/documents/doc-3/review")}
                    >
                      Begin Engineering Review
                      <ArrowRight className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="outline"
                      className="w-full gap-2"
                      onClick={() => router.push("/admin/documents")}
                    >
                      View Document Pipeline
                    </Button>
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      </div>
    </AppLayout>
  );
}
