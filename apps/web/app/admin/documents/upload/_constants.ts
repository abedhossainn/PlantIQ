/**
 * Upload page constants and stage mapping helpers.
 * Pure data and utility — no React, no side-effects.
 */

// ---------------------------------------------------------------------------
// Pipeline stage definitions (displayed in UI progress tracker)
// ---------------------------------------------------------------------------

export type Stage = {
  id: string;
  label: string;
  description: string;
};

export const PIPELINE_STAGES: Stage[] = [
  { id: "uploading",           label: "File Upload",          description: "Transferring document to server" },
  { id: "extracting",          label: "Document Extraction",  description: "Extracting text, tables, and figures with Docling" },
  { id: "vlm-validating",      label: "VLM Validation",       description: "AI validation of content fidelity" },
  { id: "validation-complete", label: "Validation Complete",  description: "Ready for fidelity review" },
];

// ---------------------------------------------------------------------------
// Backend stage → UI stage mapping
//
// Backend emits granular stage strings (queued, extraction, docling, etc.).
// We map these to the simplified PIPELINE_STAGES ids for visual progress.
// Unknown stages fall back to the raw value (forward-compatible).
// ---------------------------------------------------------------------------

export const BACKEND_TO_UI_STAGE: Record<string, string> = {
  queued:     "uploading",
  upload:     "uploading",
  extraction: "extracting",
  docling:    "extracting",
  manifest:   "extracting",
  validation: "vlm-validating",
  tables:     "vlm-validating",
  review:     "vlm-validating",
  version:    "vlm-validating",
  qa:         "vlm-validating",
  audit:      "vlm-validating",
  completed:  "validation-complete",
  startup:    "uploading",
  monitoring: "vlm-validating",
};

/** Resolve a backend stage string to a PIPELINE_STAGES id, falling back to the raw value. */
export function toUIStage(backendStage: string): string {
  return BACKEND_TO_UI_STAGE[backendStage] ?? backendStage;
}

// ---------------------------------------------------------------------------
// Upload validation limits
// ---------------------------------------------------------------------------

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100 MB
export const ALLOWED_UPLOAD_EXTENSION = ".pdf";
