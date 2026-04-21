/**
 * Pipeline API - Optimization Log SSE Event Types and Streaming
 *
 * Provides typed SSE event definitions and streamOptimizationLogs()
 * for real-time LLM optimization run monitoring.
 *
 * SSE Event Contract:
 *   log (INFO|WARNING|ERROR)
 *   progress (structured segment-generation snapshot)
 *   done (optimization-complete|failed)
 *   heartbeat (comment, ignored)
 */

import { getAuthToken, getFastApiBaseUrl } from '../client';
import { isAbortLikeError } from './_internal';

// ============================================================================
// Optimization Log SSE Event Types
// ============================================================================

export interface OptimizationLogEvent {
  type: 'log';
  timestamp: string;
  level: 'INFO' | 'WARNING' | 'ERROR';
  message: string;
}

export interface OptimizationDoneEvent {
  type: 'done';
  status: 'optimization-complete' | 'failed';
}

export interface OptimizationProgressEvent {
  type: 'progress';
  timestamp: string;
  document_id: string;
  phase: 'segment-generation';
  current_segment: number | null;
  total_segments: number | null;
  segment_progress_percent: number;
  overall_progress_percent: number;
  tokens_generated: number | null;
  tokens_target: number | null;
  elapsed_seconds: number | null;
  label: string;
}

export type OptimizationSSEEvent =
  | OptimizationLogEvent
  | OptimizationProgressEvent
  | OptimizationDoneEvent;

// ============================================================================
// Optimization Log SSE Streaming
// ============================================================================

/**
 * Parse a raw SSE block into a typed OptimizationSSEEvent.
 *
 * Backend format:
 *   event: log\ndata: { "event": "log", "timestamp": "ISO", "level": "INFO|WARNING|ERROR", "message": "..." }
 *   event: progress\ndata: { "event": "progress", "phase": "segment-generation", ... }
 *   event: done\ndata: { "event": "done", "status": "optimization-complete"|"failed" }
 *   : heartbeat   (SSE comment — ignored)
 */
function parseOptimizationSSEBlock(block: string): OptimizationSSEEvent | null {
  let eventName = '';
  let dataLine = '';

  for (const line of block.split(/\r?\n/)) {
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

  // SSE event: field takes priority; fall back to parsed.event in case of
  // single-field format (e.g. no explicit event: line).
  const resolvedEvent = eventName || String(parsed.event ?? '');

  if (resolvedEvent === 'log') {
    return {
      type: 'log',
      timestamp: String(parsed.timestamp ?? new Date().toISOString()),
      level: (parsed.level as 'INFO' | 'WARNING' | 'ERROR') ?? 'INFO',
      message: String(parsed.message ?? ''),
    };
  }

  if (resolvedEvent === 'done') {
    const st = String(parsed.status ?? 'failed');
    return {
      type: 'done',
      status: st === 'optimization-complete' ? 'optimization-complete' : 'failed',
    };
  }

  if (resolvedEvent === 'progress') {
    const segmentPercent = Number(parsed.segment_progress_percent ?? 0);
    const overallPercent = Number(parsed.overall_progress_percent ?? 0);
    const toNullableNumber = (value: unknown): number | null => {
      if (value === null || value === undefined) return null;
      const n = Number(value);
      return Number.isFinite(n) ? n : null;
    };

    return {
      type: 'progress',
      timestamp: String(parsed.timestamp ?? new Date().toISOString()),
      document_id: String(parsed.document_id ?? ''),
      phase: 'segment-generation',
      current_segment: toNullableNumber(parsed.current_segment),
      total_segments: toNullableNumber(parsed.total_segments),
      segment_progress_percent: Number.isFinite(segmentPercent)
        ? Math.max(0, Math.min(100, Math.round(segmentPercent)))
        : 0,
      overall_progress_percent: Number.isFinite(overallPercent)
        ? Math.max(0, Math.min(100, Math.round(overallPercent)))
        : 0,
      tokens_generated: toNullableNumber(parsed.tokens_generated),
      tokens_target: toNullableNumber(parsed.tokens_target),
      elapsed_seconds: toNullableNumber(parsed.elapsed_seconds),
      label: String(parsed.label ?? 'Segment generation'),
    };
  }

  return null;
}

/**
 * Stream live optimization log events for a document via SSE.
 *
 * Connects to GET /api/v1/documents/{documentId}/optimization/logs and yields
 * typed OptimizationSSEEvent objects. Connecting late replays the full
 * in-memory buffer from the backend, then continues live.
 *
 * Terminal event: OptimizationDoneEvent (type === 'done').
 *
 * Pass an AbortSignal to cancel the stream on unmount or retry.
 *
 * @param documentId Document UUID
 * @param signal     Optional AbortSignal to cancel the stream
 */
export async function* streamOptimizationLogs(
  documentId: string,
  signal?: AbortSignal
): AsyncGenerator<OptimizationSSEEvent, void, unknown> {
  const token = getAuthToken();

  const headers: Record<string, string> = {
    Accept: 'text/event-stream',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const streamUrl = `${getFastApiBaseUrl()}/api/v1/documents/${encodeURIComponent(documentId)}/optimization/logs/`;

  let response: Response;
  try {
    response = await fetch(streamUrl, { headers, signal });
  } catch (err) {
    if (signal?.aborted) return;
    const errMsg = err instanceof Error ? err.message : 'Failed to connect to optimization log stream';
    yield {
      type: 'log',
      timestamp: new Date().toISOString(),
      level: 'ERROR',
      message: `Connection error: ${errMsg} (stream: ${streamUrl})`,
    };
    return;
  }

  if (!response.ok) {
    const errMsg = `Optimization SSE failed: ${response.statusText}`;
    yield { type: 'log', timestamp: new Date().toISOString(), level: 'ERROR', message: errMsg };
    yield { type: 'done', status: 'failed' };
    return;
  }

  if (!response.body) {
    yield { type: 'log', timestamp: new Date().toISOString(), level: 'ERROR', message: 'Response body is null' };
    yield { type: 'done', status: 'failed' };
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

      let separatorMatch = buffer.match(/\r?\n\r?\n/);
      while (separatorMatch && separatorMatch.index !== undefined) {
        const separatorIndex = separatorMatch.index;
        const separatorLength = separatorMatch[0].length;
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + separatorLength);

        if (block.trim()) {
          const event = parseOptimizationSSEBlock(block);
          if (event) {
            yield event;
            if (event.type === 'done') {
              return;
            }
          }
        }

        separatorMatch = buffer.match(/\r?\n\r?\n/);
      }
    }

    // Drain remaining buffer.
    if (buffer.trim() && !signal?.aborted) {
      const event = parseOptimizationSSEBlock(buffer.trim());
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
