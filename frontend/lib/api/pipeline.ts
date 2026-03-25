/**
 * Pipeline API Client
 * Handles document upload, processing status, artifacts retrieval,
 * and ingestion SSE event streaming.
 *
 * Ingestion SSE contract (matches backend/app/models/sse.py):
 *   event: job.accepted   → IngestionJobAcceptedSSEEvent
 *   event: progress       → IngestionProgressSSEEvent
 *   event: stage.complete → IngestionStageCompleteSSEEvent
 *   event: complete       → IngestionCompleteSSEEvent  (terminal)
 *   event: error          → IngestionErrorSSEEvent     (terminal)
 */

import { fastapiFetch, getAuthToken } from './client';
import type { Document } from '@/types';

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
    `${process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000'}/api/v1/documents/${documentId}/artifacts/${normalizeArtifactType(artifactType)}`,
    { headers }
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

// ============================================================================
// Document from Pipeline Status
// ============================================================================

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

// ============================================================================
// Ingestion SSE Event Types  (match backend/app/models/sse.py)
// ============================================================================

export interface IngestionJobAcceptedSSEEvent {
  type: 'job.accepted';
  document_id: string;
  job_id: string;
  stage: string;
  progress: number;
  message: string;
  timestamp: string;
}

export interface IngestionProgressSSEEvent {
  type: 'progress';
  document_id: string;
  job_id?: string;
  stage: string;
  progress: number;
  message: string;
  timestamp: string;
}

export interface IngestionStageCompleteSSEEvent {
  type: 'stage.complete';
  document_id: string;
  job_id?: string;
  stage: string;
  progress: number;
  message: string;
  artifact_type?: string;
  artifact_path?: string;
  timestamp: string;
}

export interface IngestionCompleteSSEEvent {
  type: 'complete';
  document_id: string;
  job_id?: string;
  stage: string;
  progress: number;
  message: string;
  artifact_type?: string;
  artifact_path?: string;
  timestamp: string;
}

export interface IngestionErrorSSEEvent {
  type: 'error';
  document_id: string;
  job_id?: string;
  stage: string;
  progress: number;
  message: string;
  error: string;
  timestamp: string;
}

export type IngestionSSEEvent =
  | IngestionJobAcceptedSSEEvent
  | IngestionProgressSSEEvent
  | IngestionStageCompleteSSEEvent
  | IngestionCompleteSSEEvent
  | IngestionErrorSSEEvent;

// ============================================================================
// Ingestion SSE Streaming
// ============================================================================

/**
 * Parse a raw SSE block into a typed IngestionSSEEvent.
 *
 * Backend format per block:
 *   event: <name>\ndata: <json>\n
 */
function parseIngestionSSEBlock(
  block: string,
  documentId: string
): IngestionSSEEvent | null {
  let eventName = 'message';
  let dataLine = '';

  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) {
      eventName = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataLine = line.slice(6).trim();
    }
  }

  if (!dataLine) return null;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(dataLine);
  } catch {
    return null;
  }

  const resolved =
    eventName !== 'message' ? eventName : String(parsed.event ?? 'message');

  const common = {
    document_id: String(parsed.document_id ?? documentId),
    stage: String(parsed.stage ?? 'unknown'),
    progress: Number(parsed.progress ?? 0),
    message: String(parsed.message ?? ''),
    timestamp: String(parsed.timestamp ?? new Date().toISOString()),
    ...(parsed.job_id != null ? { job_id: String(parsed.job_id) } : {}),
  };

  switch (resolved) {
    case 'job.accepted':
      return {
        type: 'job.accepted',
        ...common,
        job_id: String(parsed.job_id ?? ''),
      };
    case 'progress':
      return { type: 'progress', ...common };
    case 'stage.complete':
      return {
        type: 'stage.complete',
        ...common,
        ...(parsed.artifact_type != null
          ? { artifact_type: String(parsed.artifact_type) }
          : {}),
        ...(parsed.artifact_path != null
          ? { artifact_path: String(parsed.artifact_path) }
          : {}),
      };
    case 'complete':
      return {
        type: 'complete',
        ...common,
        ...(parsed.artifact_type != null
          ? { artifact_type: String(parsed.artifact_type) }
          : {}),
        ...(parsed.artifact_path != null
          ? { artifact_path: String(parsed.artifact_path) }
          : {}),
      };
    case 'error':
      return {
        type: 'error',
        ...common,
        error: String(parsed.error ?? 'Unknown ingestion error'),
      };
    default:
      return null;
  }
}

/**
 * Stream ingestion progress events for a document via SSE.
 *
 * Connects to GET /api/v1/documents/{documentId}/events and yields typed
 * IngestionSSEEvent objects until `complete` or `error` is received.
 *
 * Pass an AbortSignal to cancel the stream on unmount or reset.
 *
 * @param documentId Document UUID
 * @param signal     Optional AbortSignal to cancel the stream
 */
export async function* streamIngestionEvents(
  documentId: string,
  signal?: AbortSignal
): AsyncGenerator<IngestionSSEEvent, void, unknown> {
  const token = getAuthToken();

  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(
      `${process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000'}/api/v1/documents/${encodeURIComponent(documentId)}/events`,
      { headers, signal }
    );
  } catch (err) {
    if (signal?.aborted) return;
    const errMsg = err instanceof Error ? err.message : 'Failed to connect to ingestion stream';
    yield {
      type: 'error',
      document_id: documentId,
      stage: 'connection',
      progress: 0,
      message: errMsg,
      error: errMsg,
      timestamp: new Date().toISOString(),
    };
    return;
  }

  if (!response.ok) {
    const errMsg = `Ingestion SSE failed: ${response.statusText}`;
    yield {
      type: 'error',
      document_id: documentId,
      stage: 'connection',
      progress: 0,
      message: errMsg,
      error: errMsg,
      timestamp: new Date().toISOString(),
    };
    return;
  }

  if (!response.body) {
    const errMsg = 'Response body is null';
    yield {
      type: 'error',
      document_id: documentId,
      stage: 'connection',
      progress: 0,
      message: errMsg,
      error: errMsg,
      timestamp: new Date().toISOString(),
    };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      if (signal?.aborted) break;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex !== -1) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        if (block.trim()) {
          const event = parseIngestionSSEBlock(block, documentId);
          if (event) {
            yield event;
            if (event.type === 'complete' || event.type === 'error') {
              return;
            }
          }
        }

        separatorIndex = buffer.indexOf('\n\n');
      }
    }

    // Drain remaining buffer.
    if (buffer.trim() && !signal?.aborted) {
      const event = parseIngestionSSEBlock(buffer.trim(), documentId);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
