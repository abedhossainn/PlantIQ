"use client";

/**
 * Three-step upload form: file selection, metadata entry, and pipeline submission.
 * Pure presentational component — all state lives in the parent UploadPage.
 */

import { useState } from "react";
import { FileText, Upload } from "lucide-react";

import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { PIPELINE_STAGES, ALLOWED_UPLOAD_ACCEPT } from "../_constants";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UploadFormProps {
  fileRef: React.RefObject<HTMLInputElement | null>;
  selectedFile: File | null;
  title: string;
  version: string;
  system: string;
  canSubmit: boolean;
  submitHint?: string;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onFileDrop: (file: File) => void;
  onTitleChange: (v: string) => void;
  onVersionChange: (v: string) => void;
  onSystemChange: (v: string) => void;
  onSubmit: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function UploadForm({
  fileRef, selectedFile, title, version, system, canSubmit,
  submitHint,
  onFileChange, onFileDrop, onTitleChange, onVersionChange, onSystemChange, onSubmit,
}: UploadFormProps) {
  const [isDragging, setIsDragging] = useState(false);

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    if (!isDragging) setIsDragging(true);
  }

  function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    // Only clear when leaving the drop zone itself, not a child element
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  }

  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const file = e.dataTransfer.files?.[0];
    if (file) onFileDrop(file);
  }

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <Card className="overflow-hidden border-border">

        {/* Step 1 — File */}
        <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center gap-3">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-bold shrink-0">1</span>
          <span className="font-semibold text-sm">Select File</span>
        </div>
        <div className="p-6">
          <div
            className={`flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-8 cursor-pointer transition-colors ${
              isDragging
                ? "border-primary bg-primary/10"
                : "border-border hover:border-primary/60 hover:bg-primary/5"
            }`}
            onClick={() => fileRef.current?.click()}
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {selectedFile ? (
              <>
                <FileText className="h-10 w-10 text-primary" />
                <p className="font-medium">{selectedFile.name}</p>
                <p className="text-xs text-muted-foreground">{(selectedFile.size / 1024 / 1024).toFixed(2)} MB · Click to change</p>
              </>
            ) : (
              <>
                <Upload className="h-10 w-10 text-muted-foreground/40" />
                <p className="text-sm text-muted-foreground">Click or drag-and-drop a PDF or XLSX document</p>
              </>
            )}
          </div>
          <input ref={fileRef} type="file" accept={ALLOWED_UPLOAD_ACCEPT} className="hidden" onChange={onFileChange} />
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
              <Input id="title" value={title} onChange={(e) => onTitleChange(e.target.value)} placeholder="e.g., Gas Turbine Maintenance Guide" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label htmlFor="version" className="mb-1.5 block">Version</Label>
                <Input id="version" value={version} onChange={(e) => onVersionChange(e.target.value)} placeholder="e.g., Rev 3.0" />
              </div>
              <div>
                <Label className="mb-1.5 block">System / Area</Label>
                <Select onValueChange={onSystemChange}>
                  <SelectTrigger><SelectValue placeholder="Select system" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="Power Block">Power Block</SelectItem>
                    <SelectItem value="Pre Treatment">Pre Treatment</SelectItem>
                    <SelectItem value="Liquefaction">Liquefaction</SelectItem>
                    <SelectItem value="OSBL (Outside Battery Limits)">OSBL (Outside Battery Limits)</SelectItem>
                    <SelectItem value="Maintenance">Maintenance</SelectItem>
                    <SelectItem value="Instrumentation">Instrumentation</SelectItem>
                    <SelectItem value="DCS (Distributed Control System)">DCS (Distributed Control System)</SelectItem>
                    <SelectItem value="Electrical">Electrical</SelectItem>
                    <SelectItem value="Mechanical">Mechanical</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </div>

        {/* Step 3 — Submit */}
        <div className="border-t border-border">
          <div className="px-6 py-4 border-b border-border bg-muted/40 flex items-center gap-3">
            <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold shrink-0 ${canSubmit ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground border border-border"}`}>3</span>
            <span className="font-semibold text-sm">Start Pipeline</span>
          </div>
          <div className="p-6">
            <div className="rounded-lg border border-border bg-muted/20 p-4 mb-4">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Pipeline Stages</p>
              <div className="space-y-2">
                {PIPELINE_STAGES.map((stage, idx) => (
                  <div key={stage.id} className="flex items-center gap-3 text-sm">
                    <span className="flex h-5 w-5 items-center justify-center rounded-full border border-border text-xs text-muted-foreground shrink-0 font-medium">{idx + 1}</span>
                    <span className="font-medium">{stage.label}</span>
                    <span className="text-muted-foreground text-xs">— {stage.description}</span>
                  </div>
                ))}
              </div>
            </div>
            <Button disabled={!canSubmit} className="w-full gap-2 font-semibold h-11" onClick={onSubmit}>
              <Upload className="h-4 w-4" />
              Start Ingestion Pipeline
            </Button>
            {!canSubmit && (
              <p className="text-xs text-muted-foreground text-center mt-2">
                {submitHint ?? "Complete steps 1 and 2 to continue"}
              </p>
            )}
          </div>
        </div>

      </Card>
    </div>
  );
}
