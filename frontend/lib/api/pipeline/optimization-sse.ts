/**
 * Pipeline API - Optimization Log SSE Event Types and Streaming
 *
 * Provides typed SSE event definitions and streamOptimizationLogs()
 * for real-time LLM optimization run monitoring.
 *
 * SSE Event Contract:
 *   log (INFO|WARNING|ERROR) | done (optimization-complete|failed) | heartbeat (comment, ignored)
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

export type OptimizationSSEEvent = OptimizationLogEvent | OptimizationDoneEvent;

// ============================================================================
// Optimization Log SSE Streaming
// ============================================================================

/**
 * Parse a raw SSE block into a typed OptimizationSSEEvent.
 *
 * Backend format:
 *   event: log\ndata: { "event": "log", "timestamp": "ISO", "level": "INFO|WARNING|ERROR", "message": "..." }
 *   event: done\ndata: { "event": "done", "status": "optimization-complete"|"failed" }
 *   : heartbeat   (SSE comment — ignored)
 */
function parseOptimizationSSEBlock(block: string): OptimizationSSEEvent | null {
  let eventName = '';
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

  let response: Response;
  try {
    response = await fetch(
      `${getFastApiBaseUrl()}/api/v1/documents/${encodeURIComponent(documentId)}/optimization/logs`,
      { headers, signal }
    );
  } catch (err) {
    if (signal?.aborted) return;
    const errMsg = err instanceof Error ? err.message : 'Failed to connect to optimization log stream';
    yield {
      type: 'log',
      timestamp: new Date().toISOString(),
      level: 'ERROR',
      message: `Connection error: ${errMsg}`,
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

      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex !== -1) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        if (block.trim()) {
          const event = parseOptimizationSSEBlock(block);
          if (event) {
            yield event;
            if (event.type === 'done') {
              return;
            }
          }
        }

        separatorIndex = buffer.indexOf('\n\n');
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
