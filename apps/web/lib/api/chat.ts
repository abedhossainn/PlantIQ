/**
 * Chat API client for RAG-powered conversations.
 * 
 * Streaming Architecture:
 * - submitChatQuery(): Synchronous request (small payloads, non-critical queries)
 * - streamChatQuery(): Server-Sent Events (SSE) streaming of token-by-token generation
 * - Falls back to polling if SSE unsupported or fails
 * 
 * Event Types:
 * - MessageSSEEvent: LLM-generated text tokens (role=assistant)
 * - CitationSSEEvent: Document citations with source metadata
 * - StatusSSEEvent: Lifecycle updates (e.g., "generating", "done")
 * - ErrorSSEEvent: Backend errors during generation
 * 
 * Citation System:
 * - Emitted as separate events during/after generation
 * - Contains document_id, source, page_number, chunk_text
 * - Frontend renders as hover-able badges with source detail drawer
 * 
 * Token Accumulation:
 * - Text tokens accumulated into complete message before UI update
 * - Prevents excessive re-renders and layout thrashing
 * - Batched updates every 50ms or on citation/terminal event
 * 
 * SSE contract (matches backend/app/models/sse.py):
 *   event: token   → ChatTokenSSEEvent
 *   event: citation → ChatCitationSSEEvent
 *   event: complete → ChatCompleteSSEEvent  (terminal)
 *   event: error    → ChatErrorSSEEvent     (terminal)
 */

import {
  ApiError,
  buildQuery,
  fastapiFetch,
  formatScopeDeniedMessage,
  getAuthToken,
  getFastApiBaseUrl,
  parseScopeAccessDeniedPayload,
} from './client';

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
  workspace?: string;
  system?: string;
  document_type?: string;
  excerpt: string;
  relevance_score: number;
}

export interface ChatQueryRequest {
  query: string;
  conversation_id?: string;
  workspace?: string;
  document_filters?: string[];
  system_filters?: string[];
  include_shared_documents?: boolean;
  stream?: boolean;
}

export interface ChatQueryResponse {
  message_id: string;
  conversation_id: string;
  content: string;
  citations: Citation[];
  timestamp: string;
}

export type FeedbackSentiment = 'up' | 'down';

export interface ChatFeedbackSubmitRequest {
  answer_message_id: string;
  conversation_id?: string;
  source_message_id?: string;
  sentiment: FeedbackSentiment;
  reason_code?: string;
  comment?: string;
  system_scope?: string;
  area_scope?: string;
}

export interface ChatQualitySnapshot {
  answer_message_id: string;
  conversation_id: string;
  feedback_count: number;
  positive_count: number;
  negative_count: number;
  negative_streak: number;
  quality_score: number;
  is_flagged: boolean;
  last_feedback_at: string;
}

export interface ChatFeedbackSubmitResponse {
  event_id: string;
  answer_message_id: string;
  conversation_id: string;
  timestamp: string;
  snapshot: ChatQualitySnapshot;
}

export interface ChatFeedbackReasonMetric {
  reason_code: string;
  count: number;
}

export interface ChatQualityMetricsResponse {
  window_days: number;
  total_feedback_events: number;
  positive_feedback_events: number;
  negative_feedback_events: number;
  flagged_answers: number;
  reason_breakdown: ChatFeedbackReasonMetric[];
}

export interface ChatQualityMetricsRequest {
  window_days?: number;
  system_scope?: string;
  area_scope?: string;
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
  code?: string;
  reason_code?: string;
  requested_scope?: Record<string, unknown>;
  message_id?: string;
  conversation_id?: string;
}

export type ChatStreamEvent =
  | ChatTokenSSEEvent
  | ChatCitationSSEEvent
  | ChatCompleteSSEEvent
  | ChatErrorSSEEvent;

const METRICS_AUTHORIZED_ROLES = new Set([
  'admin',
  'reviewer',
  'plantig_admin',
  'plantig_reviewer',
]);

interface ApiDetailMessage {
  code?: string;
  message?: string;
}

function parseApiDetailMessage(data: unknown): ApiDetailMessage | null {
  if (!data || typeof data !== 'object') {
    return null;
  }

  const payload = data as Record<string, unknown>;
  const detail = payload.detail;
  if (detail && typeof detail === 'object') {
    const detailRecord = detail as Record<string, unknown>;
    return {
      code: typeof detailRecord.code === 'string' ? detailRecord.code : undefined,
      message: typeof detailRecord.message === 'string' ? detailRecord.message : undefined,
    };
  }

  return {
    code: typeof payload.code === 'string' ? payload.code : undefined,
    message: typeof payload.message === 'string' ? payload.message : undefined,
  };
}

function normalizeApiError(error: unknown, fallbackMessage: string): ApiError {
  if (error instanceof ApiError) {
    const detail = parseApiDetailMessage(error.data);
    if (detail?.message) {
      return new ApiError(detail.message, error.status, {
        ...(typeof error.data === 'object' && error.data ? error.data as Record<string, unknown> : {}),
        code: detail.code,
      });
    }
    return error;
  }

  return new ApiError(
    error instanceof Error ? error.message : fallbackMessage,
    0,
  );
}

export function canAccessFeedbackMetrics(role?: string | null): boolean {
  if (!role) {
    return false;
  }

  return METRICS_AUTHORIZED_ROLES.has(role.toLowerCase());
}

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

export async function submitChatFeedback(
  request: ChatFeedbackSubmitRequest
): Promise<ChatFeedbackSubmitResponse> {
  try {
    return await fastapiFetch<ChatFeedbackSubmitResponse>('/api/v1/chat/feedback', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  } catch (error) {
    throw normalizeApiError(error, 'Failed to submit answer feedback.');
  }
}

export async function getChatFeedbackMetrics(
  request: ChatQualityMetricsRequest = {}
): Promise<ChatQualityMetricsResponse> {
  const query = buildQuery({
    window_days: request.window_days ?? 30,
    system_scope: request.system_scope,
    area_scope: request.area_scope,
  });

  try {
    return await fastapiFetch<ChatQualityMetricsResponse>(`/api/v1/chat/feedback/metrics${query}`);
  } catch (error) {
    throw normalizeApiError(error, 'Failed to load answer-quality metrics.');
  }
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
      {
      const scopeDenied = parseScopeAccessDeniedPayload(parsed);
      return {
        type: 'error',
        error: scopeDenied ? formatScopeDeniedMessage(scopeDenied) : String(parsed.error ?? 'Unknown streaming error'),
        code: scopeDenied?.code,
        reason_code: scopeDenied?.reason_code,
        requested_scope: scopeDenied?.requested_scope,
        message_id: parsed.message_id != null ? String(parsed.message_id) : undefined,
        conversation_id: parsed.conversation_id != null ? String(parsed.conversation_id) : undefined,
      };
      }
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
    `${getFastApiBaseUrl()}/api/v1/chat/stream`,
    {
      method: 'POST',
      headers,
      body: JSON.stringify({ ...request, stream: true }),
    }
  );

  if (!response.ok) {
    const contentType = response.headers.get('content-type');
    const isJson = contentType?.includes('application/json');
    const errorData = isJson ? await response.json() : await response.text();
    const scopeDenied = parseScopeAccessDeniedPayload(errorData);

    if (scopeDenied) {
      throw new ApiError(
        formatScopeDeniedMessage(scopeDenied),
        response.status,
        errorData
      );
    }

    throw new ApiError(
      `Chat streaming failed: ${response.statusText}`,
      response.status,
      errorData
    );
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
      if (event.code === 'SCOPE_ACCESS_DENIED') {
        throw new ApiError(
          event.error,
          403,
          {
            code: event.code,
            reason_code: event.reason_code,
            requested_scope: event.requested_scope,
            message: event.error,
          }
        );
      }
      throw new Error(event.error);
    }
    // 'complete' — stream ended cleanly; nothing to do.
  }

  return fullContent;
}
