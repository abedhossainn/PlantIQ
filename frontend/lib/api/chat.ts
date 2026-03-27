/**
 * Chat API Client
 * Handles RAG chat queries with streaming and citation support.
 *
 * SSE contract (matches backend/app/models/sse.py):
 *   event: token   → ChatTokenSSEEvent
 *   event: citation → ChatCitationSSEEvent
 *   event: complete → ChatCompleteSSEEvent  (terminal)
 *   event: error    → ChatErrorSSEEvent     (terminal)
 */

import { fastapiFetch, getAuthToken } from './client';

// ============================================================================
// Type Definitions
// ============================================================================

/** Citation as returned by the backend (snake_case). */
export interface Citation {
  id: string;
  document_id: string;
  document_title: string;
  section_heading?: string;
  page_number?: number;
  excerpt: string;
  relevance_score: number;
}

export interface ChatQueryRequest {
  query: string;
  conversation_id?: string;
  document_filters?: string[];
  system_filters?: string[];
  stream?: boolean;
}

export interface ChatQueryResponse {
  message_id: string;
  conversation_id: string;
  content: string;
  citations: Citation[];
  timestamp: string;
}

// ============================================================================
// SSE Event Types  (match backend/app/models/sse.py)
// ============================================================================

export interface ChatTokenSSEEvent {
  type: 'token';
  token: string;
  content: string;
  message_id: string;
  conversation_id: string;
}

export interface ChatCitationSSEEvent {
  type: 'citation';
  citation: Citation;
  message_id: string;
  conversation_id: string;
}

export interface ChatCompleteSSEEvent {
  type: 'complete';
  message_id: string;
  conversation_id: string;
}

export interface ChatErrorSSEEvent {
  type: 'error';
  error: string;
  message_id?: string;
  conversation_id?: string;
}

export type ChatStreamEvent =
  | ChatTokenSSEEvent
  | ChatCitationSSEEvent
  | ChatCompleteSSEEvent
  | ChatErrorSSEEvent;

// ============================================================================
// API Functions
// ============================================================================

/**
 * Submit a RAG chat query (non-streaming).
 */
export async function submitChatQuery(
  request: ChatQueryRequest
): Promise<ChatQueryResponse> {
  return fastapiFetch<ChatQueryResponse>('/api/v1/chat/query', {
    method: 'POST',
    body: JSON.stringify({
      ...request,
      stream: false,
    }),
  });
}

/**
 * Parse a raw SSE block (text between two \n\n delimiters) into a typed
 * ChatStreamEvent.
 *
 * Backend format per block:
 *   event: <name>\ndata: <json>\n
 *
 * The JSON payload also contains an "event" field that mirrors the SSE event
 * name — we prefer the SSE event: line but fall back to the payload field.
 */
function parseSSEBlock(block: string): ChatStreamEvent | null {
  let eventName = 'message';
  let dataLine = '';

  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) {
      eventName = line.slice(7).trim();
    } else if (line.startsWith('data: ')) {
      dataLine = line.slice(6).trim();
    }
  }

  if (!dataLine || dataLine === '[DONE]') return null;

  let parsed: Record<string, unknown>;
  try {
    parsed = JSON.parse(dataLine);
  } catch {
    return null;
  }

  // Resolve event name: SSE event: line takes priority over payload field.
  const resolved = eventName !== 'message' ? eventName : String(parsed.event ?? 'message');

  switch (resolved) {
    case 'token':
      return {
        type: 'token',
        token: String(parsed.token ?? parsed.content ?? ''),
        content: String(parsed.content ?? parsed.token ?? ''),
        message_id: String(parsed.message_id ?? ''),
        conversation_id: String(parsed.conversation_id ?? ''),
      };
    case 'citation':
      return {
        type: 'citation',
        citation: parsed.citation as Citation,
        message_id: String(parsed.message_id ?? ''),
        conversation_id: String(parsed.conversation_id ?? ''),
      };
    case 'complete':
      return {
        type: 'complete',
        message_id: String(parsed.message_id ?? ''),
        conversation_id: String(parsed.conversation_id ?? ''),
      };
    case 'error':
      return {
        type: 'error',
        error: String(parsed.error ?? 'Unknown streaming error'),
        message_id: parsed.message_id != null ? String(parsed.message_id) : undefined,
        conversation_id: parsed.conversation_id != null ? String(parsed.conversation_id) : undefined,
      };
    default:
      return null;
  }
}

/**
 * Submit a RAG chat query with streaming response (SSE).
 *
 * Yields typed ChatStreamEvent objects:
 *   - token:    incremental text chunk
 *   - citation: source reference (emitted after tokens, before complete)
 *   - complete: terminal — stream finished successfully
 *   - error:    terminal — stream failed
 *
 * Callers should stop iterating after receiving complete or error.
 */
export async function* streamChatQuery(
  request: ChatQueryRequest
): AsyncGenerator<ChatStreamEvent, void, unknown> {
  const token = getAuthToken();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(
    `${process.env.NEXT_PUBLIC_FASTAPI_URL || 'http://localhost:8000'}/api/v1/chat/stream`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ ...request, stream: true }),
    }
  );

  if (!response.ok) {
    yield { type: 'error', error: `Chat streaming failed: ${response.statusText}` };
    return;
  }

  if (!response.body) {
    yield { type: 'error', error: 'Response body is null' };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      let separatorIndex = buffer.indexOf('\n\n');
      while (separatorIndex !== -1) {
        const block = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);

        if (block.trim()) {
          const event = parseSSEBlock(block);
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

    // Drain any remaining data in the buffer.
    if (buffer.trim()) {
      const event = parseSSEBlock(buffer.trim());
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Helper to consume a streaming chat response into a complete string.
 *
 * @param request    Chat query request
 * @param onToken    Called with each streamed token string
 * @param onCitation Called with each citation received from the stream
 * @returns Complete accumulated text content
 */
// ============================================================================
// LLM Status
// ============================================================================

export interface LlmStatus {
  backend: string;
  model: string;
  host: string;
  port: number;
  container_reachable: boolean;
  active_requests: number;
  unload_after_request: boolean;
  startup_wait_seconds: number;
  last_demand_utc: string | null;
  idle_seconds: number | null;
}

/**
 * Fetch the current LLM lifecycle state from the backend.
 * Returns null if the request fails (treated as unreachable).
 */
export async function getLlmStatus(): Promise<LlmStatus | null> {
  try {
    return await fastapiFetch<LlmStatus>('/api/v1/llm/status');
  } catch {
    return null;
  }
}

export async function consumeStreamingResponse(
  request: ChatQueryRequest,
  onToken?: (token: string) => void,
  onCitation?: (citation: Citation) => void
): Promise<string> {
  let fullContent = '';

  for await (const event of streamChatQuery(request)) {
    if (event.type === 'token') {
      fullContent += event.content;
      onToken?.(event.content);
    } else if (event.type === 'citation') {
      onCitation?.(event.citation);
    } else if (event.type === 'error') {
      throw new Error(event.error);
    }
    // 'complete' — stream ended cleanly; nothing to do.
  }

  return fullContent;
}
