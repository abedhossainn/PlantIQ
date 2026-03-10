/**
 * Pipeline API Client
 * Handles document upload, processing status, artifacts retrieval
 */

import { fastapiFetch, getAuthToken } from './client';

// ============================================================================
// Type Definitions
// ============================================================================

export type PipelineStatus =
  | 'pending'
  | 'uploading'
  | 'extracting'
  | 'vlm-validating'
  | 'validation-complete'
  | 'in-review'
  | 'review-complete'
  | 'approved'
  | 'rejected'
  | 'failed';

export type ArtifactType =
  | 'validation'
  | 'manifest'
  | 'qa-report'
  | 'qa_report'
  | 'review'
  | 'table_figure'
  | 'audit';

function normalizeArtifactType(artifactType: ArtifactType): string {
  if (artifactType === 'qa-report') {
    return 'qa_report';
  }

  return artifactType;
}

export interface DocumentUploadRequest {
  file: File;
  title: string;
  version?: string;
  system?: string;
  documentType?: string;
  notes?: string;
}

export interface DocumentUploadResponse {
  document_id: string;
  status: PipelineStatus;
  file_path: string;
  message: string;
}

export interface PipelineStatusResponse {
  document_id: string;
  status: PipelineStatus;
  current_stage?: string;
  progress: number; // 0-100
  message?: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
}

export interface ReprocessRequest {
  document_id: string;
  reason?: string;
}

export interface ReprocessResponse {
  job_id: string;
  document_id: string;
  status: PipelineStatus;
  message: string;
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Upload a new PDF document and trigger processing pipeline
 * 
 * @param request Upload request with file and metadata
 * @returns Upload response with document ID and initial status
 */
export async function uploadDocument(
  request: DocumentUploadRequest
): Promise<DocumentUploadResponse> {
  const formData = new FormData();
  formData.append('file', request.file);
  formData.append('title', request.title);
  
  if (request.version) {
    formData.append('version', request.version);
  }
  if (request.system) {
    formData.append('system', request.system);
  }
  if (request.documentType) {
    formData.append('document_type', request.documentType);
  }
  if (request.notes) {
    formData.append('notes', request.notes);
  }

  return fastapiFetch<DocumentUploadResponse>('/api/v1/documents/upload', {
    method: 'POST',
    body: formData,
    headers: {
      // Let browser set Content-Type with boundary for multipart/form-data
      // Do not set Content-Type manually
    },
  });
}

/**
 * Get current pipeline processing status for a document
 * 
 * @param documentId Document UUID
 * @returns Current status with progress percentage
 */
export async function getPipelineStatus(
  documentId: string
): Promise<PipelineStatusResponse> {
  return fastapiFetch<PipelineStatusResponse>(
    `/api/v1/documents/${documentId}/status`
  );
}

/**
 * Trigger reprocessing of a document through the pipeline
 * 
 * @param request Reprocess request with document ID and optional reason
 * @returns Job ID and new status
 */
export async function reprocessDocument(
  request: ReprocessRequest
): Promise<ReprocessResponse> {
  return fastapiFetch<ReprocessResponse>(
    `/api/v1/documents/${request.document_id}/reprocess`,
    {
      method: 'POST',
      body: JSON.stringify({ reason: request.reason }),
    }
  );
}

/**
 * Download pipeline artifacts (validation reports, manifests, QA reports)
 * 
 * @param documentId Document UUID
 * @param artifactType Type of artifact to download
 * @returns Blob for file download
 */
export async function downloadArtifact(
  documentId: string,
  artifactType: ArtifactType
): Promise<Blob> {
  const token = getAuthToken();

  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000'}/api/v1/documents/${documentId}/artifacts/${normalizeArtifactType(artifactType)}`,
    { headers }
  );

  if (!response.ok) {
    throw new Error(`Failed to download artifact: ${response.statusText}`);
  }

  return response.blob();
}

/**
 * Helper to trigger file download in browser
 * 
 * @param blob File blob
 * @param filename Suggested filename
 */
export function triggerBrowserDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
