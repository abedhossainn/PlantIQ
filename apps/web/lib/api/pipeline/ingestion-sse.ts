/**
 * Pipeline API - Ingestion SSE Event Types and Streaming
 *
 * Provides typed SSE event definitions and streamIngestionEvents()
 * for real-time document ingestion progress monitoring.
 *
 * SSE Event Contract (backend/app/models/sse.py):
 *   job.accepted | progress | stage.complete | complete | error
 */

import { getAuthToken, getFastApiBaseUrl } from '../client';
import { isAbortLikeError } from './_internal';

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
      `${getFastApiBaseUrl()}/api/v1/documents/${encodeURIComponent(documentId)}/events`,
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

      let chunk;
      try {
        chunk = await reader.read();
      } catch (err) {
        if (signal?.aborted || isAbortLikeError(err)) {
          return;
        }
        throw err;
      }

      const { done, value } = chunk;
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
