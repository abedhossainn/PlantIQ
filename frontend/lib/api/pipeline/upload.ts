/**
 * Pipeline API - Upload, Status, Artifact, and Document Functions
 *
 * Handles document upload, status polling, artifact retrieval,
 * and building Document objects from pipeline state.
 */

import { fastapiFetch, getAuthToken, getFastApiBaseUrl } from '../client';
import type { Document } from '@/types';
import type {
  PipelineStatus,
  ArtifactType,
  DocumentUploadRequest,
  DocumentUploadResponse,
  PipelineStatusResponse,
  ReprocessRequest,
  ReprocessResponse,
} from './types';

// Artifact naming notes:
// - `qa-report` is accepted for backward compatibility with older clients.
// - Backend canonical key currently uses `qa_report`.
// - normalizeArtifactType bridges both forms.
function normalizeArtifactType(artifactType: ArtifactType): string {
  if (artifactType === 'qa-report') {
    return 'qa_report';
  }
  return artifactType;
}

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
    `${getFastApiBaseUrl()}/api/v1/documents/${documentId}/artifacts/${normalizeArtifactType(artifactType)}`,
    { headers }
  );

  if (!response.ok) {
    throw new Error(`Failed to download artifact: ${response.statusText}`);
  }

  return response.blob();
}

/**
 * Fetch a pipeline artifact as parsed JSON
 *
 * @param documentId Document UUID
 * @param artifactType Type of artifact to fetch
 * @returns Parsed JSON response
 */
export async function fetchArtifactJson<T>(
  documentId: string,
  artifactType: ArtifactType
): Promise<T> {
  const token = getAuthToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${getFastApiBaseUrl()}/api/v1/documents/${documentId}/artifacts/${normalizeArtifactType(artifactType)}`,
    {
      headers,
      cache: 'no-store',
    }
  );

  if (!response.ok) {
    throw new Error(`Failed to fetch artifact: ${response.statusText}`);
  }

  return response.json() as Promise<T>;
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

interface UploadPreviewData {
  title: string;
  version: string;
  system: string;
  docType: string;
}

/**
 * Build a Document object from FastAPI pipeline status + upload preview.
 *
 * Use this in place of getDocumentById (PostgREST) when the local core stack
 * does not include PostgREST. The upload page saves form metadata under
 * `plantiq-upload-preview-{id}` so that document detail pages can recover
 * the human-readable title, version, system, and type.
 *
 * @param id Document UUID
 * @returns Document or null if the document was not found / request failed
 */
export async function getDocumentFromPipeline(id: string): Promise<Document | null> {
  let preview: UploadPreviewData | null = null;
  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem(`plantiq-upload-preview-${id}`);
    if (stored) {
      try {
        preview = JSON.parse(stored) as UploadPreviewData;
      } catch { /* noop */ }
    }
  }

  try {
    const status = await fastapiFetch<PipelineStatusResponse>(
      `/api/v1/documents/${id}/status`
    );
    return {
      id: String(status.document_id),
      title: preview?.title ?? `Document ${String(status.document_id).slice(0, 8)}…`,
      version: preview?.version || '1.0',
      system: preview?.system || '—',
      documentType: preview?.docType || 'PDF',
      status: status.status as Document['status'],
      totalPages: 0,
      totalSections: 0,
      reviewProgress: status.progress,
      uploadedBy: '—',
      uploadedAt: status.started_at ?? new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

// Re-export types consumed by callers who import from this sub-module
export type {
  PipelineStatus,
  ArtifactType,
  DocumentUploadRequest,
  DocumentUploadResponse,
  PipelineStatusResponse,
  ReprocessRequest,
  ReprocessResponse,
};
